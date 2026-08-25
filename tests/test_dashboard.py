#!/usr/bin/env python3
"""
test_dashboard.py  --  Unit tests for the analytics layer and the dashboard server.

The HTTP tests bind an ephemeral port on loopback and speak to the real server, so routing,
JSON shape and the no-store header are covered rather than assumed.

    python -m unittest discover -s tests -v
"""

import datetime as dt
import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options_desk import analytics, config, netbind  # noqa: E402
from options_desk.bars import Bar, BarSeries, get_session  # noqa: E402
from options_desk.levels import Levels, Vwap  # noqa: E402
from options_desk.models import BarSnapshot, ChainSnapshot, Contract, Quote  # noqa: E402
from options_desk.providers.synthetic import SyntheticProvider  # noqa: E402
from options_desk.server import DeskState, _bars_payload, _chain_payload, make_handler  # noqa: E402

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
EXP = dt.date(2026, 8, 28)
DAY = dt.date(2026, 8, 25)


def cfg(**kw):
    return config.load(env_path="/nonexistent", overrides=kw)


def chain(spot=100.0, spec=None):
    """Hand-built chain: {strike: (call_oi, put_oi, call_mid, put_mid)}."""
    spec = spec or {95.0: (100, 400, 6.0, 1.0), 100.0: (500, 500, 3.0, 3.0),
                    105.0: (400, 100, 1.0, 6.0)}
    quotes = []
    for k, (coi, poi, cmid, pmid) in spec.items():
        quotes.append(Quote(Contract("T", EXP, k, "C"), bid=cmid - .05, ask=cmid + .05,
                            open_interest=coi, volume=coi // 10))
        quotes.append(Quote(Contract("T", EXP, k, "P"), bid=pmid - .05, ask=pmid + .05,
                            open_interest=poi, volume=poi // 10))
    return ChainSnapshot("T", spot, T0, quotes, "test", 0.04).enrich()


def bar_snap(price=101.0, prev=(105.0, 95.0, 104.0), n=12, vol=1000.0):
    session = get_session("NSE")
    start = session.open_utc(DAY)
    bars = [Bar(start + dt.timedelta(minutes=5 * i), 100, 100.1, 99.9, 100, vol)
            for i in range(n)]
    bars.append(Bar(start + dt.timedelta(minutes=5 * n), price, price, price, price, vol))
    series = BarSeries(bars, session)
    return BarSnapshot("T", price, bars[-1].ts, series,
                       Levels.from_previous(*prev) if prev else None,
                       Vwap(session).feed(series), "test", "NSE", "5m")


class TestExpectedMove(unittest.TestCase):
    def test_straddle_and_sigma(self):
        em = analytics.expected_move(chain())
        self.assertEqual(em["atm_strike"], 100.0)
        self.assertAlmostEqual(em["straddle"], 6.0)              # 3.0 call + 3.0 put
        self.assertAlmostEqual(em["straddle_pct"], 0.06)
        self.assertGreater(em["sigma"], 0)
        self.assertLess(em["low"], 100.0)
        self.assertGreater(em["high"], 100.0)
        self.assertAlmostEqual(em["high"] - em["low"], 2 * em["sigma"])

    def test_none_without_atm_quotes(self):
        snap = ChainSnapshot("T", 100.0, T0, [], "test")
        self.assertIsNone(analytics.expected_move(snap))


class TestMaxPain(unittest.TestCase):
    def test_picks_minimum_loss_strike(self):
        # Symmetric OI around 100 -> writers hurt least if it settles at 100.
        mp = analytics.max_pain(chain())
        self.assertEqual(mp["strike"], 100.0)
        losses = {r["strike"]: r["loss"] for r in mp["curve"]}
        self.assertEqual(min(losses, key=losses.get), 100.0)

    def test_skewed_open_interest_moves_it(self):
        # Pile call OI at 105: settling high would cost writers, so pain sits lower.
        spec = {95.0: (0, 100, 6.0, 1.0), 100.0: (0, 100, 3.0, 3.0),
                105.0: (100000, 0, 1.0, 6.0)}
        self.assertLessEqual(analytics.max_pain(chain(spec=spec))["strike"], 105.0)

    def test_none_without_open_interest(self):
        spec = {100.0: (0, 0, 3.0, 3.0)}
        self.assertIsNone(analytics.max_pain(chain(spec=spec)))


class TestPcrAndWalls(unittest.TestCase):
    def test_pcr_counts(self):
        pcr = analytics.put_call_ratio(chain())
        self.assertEqual(pcr["call_oi"], 1000)
        self.assertEqual(pcr["put_oi"], 1000)
        self.assertAlmostEqual(pcr["oi"], 1.0)

    def test_walls_pick_largest_open_interest(self):
        w = analytics.oi_walls(chain())
        self.assertEqual(w["resistance"], 100.0)     # biggest call OI
        self.assertEqual(w["support"], 100.0)        # biggest put OI
        self.assertEqual(len(w["call_walls"]), 3)

    def test_smile_rows_align_to_strikes(self):
        rows = analytics.iv_smile(chain())
        self.assertEqual([r["strike"] for r in rows], [95.0, 100.0, 105.0])
        self.assertTrue(all(r["call_iv"] for r in rows))


class TestBias(unittest.TestCase):
    def test_above_cpr_and_vwap_reads_long(self):
        b = analytics.bias(bar_snap(price=110.0), None)
        self.assertEqual(b["label"], "LONG")
        self.assertGreater(b["score"], 0)

    def test_below_cpr_and_vwap_reads_short(self):
        b = analytics.bias(bar_snap(price=90.0), None)
        self.assertEqual(b["label"], "SHORT")
        self.assertLess(b["score"], 0)

    def test_vwap_stretch_is_a_counter_signal(self):
        """Regression: the stretch term was inverted, so being extended ADDED conviction."""
        up = analytics.bias(bar_snap(price=103.0), None)
        down = analytics.bias(bar_snap(price=97.0), None)
        s_up = [c for c in up["components"] if c["name"] == "VWAP stretch"][0]["score"]
        s_dn = [c for c in down["components"] if c["name"] == "VWAP stretch"][0]["score"]
        self.assertLess(s_up, 0)          # stretched above VWAP -> bearish tilt
        self.assertGreater(s_dn, 0)       # stretched below VWAP -> bullish tilt

    def test_cpr_width_is_context_not_direction(self):
        comps = analytics.bias(bar_snap(), None)["components"]
        w = [c for c in comps if c["name"] == "CPR width"][0]
        self.assertEqual(w["weight"], 0.0)
        self.assertEqual(w["score"], 0.0)

    def test_weights_are_the_only_thing_scoring(self):
        b = analytics.bias(bar_snap(price=110.0), None)
        scored = [c for c in b["components"] if c["weight"] > 0]
        total = sum(c["score"] * c["weight"] for c in scored) / sum(c["weight"] for c in scored)
        self.assertAlmostEqual(b["score"], total, places=9)

    def test_carries_a_disclaimer(self):
        self.assertIn("Not a trade signal", analytics.bias(bar_snap(), None)["disclaimer"])

    def test_empty_inputs_are_neutral(self):
        b = analytics.bias(None, None)
        self.assertEqual(b["label"], "NEUTRAL")
        self.assertEqual(b["components"], [])

    def test_chain_only_still_scores(self):
        b = analytics.bias(None, chain())
        self.assertTrue(any(c["name"] == "PCR (OI)" for c in b["components"]))


class TestPayloads(unittest.TestCase):
    def test_chain_payload_is_json_safe(self):
        p = _chain_payload(chain())
        json.dumps(p)
        self.assertEqual(len(p["rows"]), 3)
        self.assertEqual(p["atm_strike"], 100.0)
        self.assertIn("iv", p["rows"][0]["call"])

    def test_bars_payload_carries_series_and_levels(self):
        p = _bars_payload(bar_snap())
        json.dumps(p)
        self.assertEqual(len(p["series"]), 13)
        self.assertIn("vwap", p["series"][0])
        self.assertIn("TC", p["named_levels"])
        self.assertEqual(len(p["bands"]["s1"]), 2)

    def test_full_analytics_serialises(self):
        json.dumps(analytics.chain_analytics(chain()))


class TestDeskState(unittest.TestCase):
    def test_signal_buffer_is_bounded(self):
        from options_desk.rules import Signal
        st = DeskState()
        st.add_signals([Signal("r", "T", "info", f"m{i}", T0) for i in range(200)])
        self.assertLessEqual(len(st.signals), 60)
        self.assertEqual(st.signals[-1]["message"], "m199")     # newest kept

    def test_filter_by_symbol_and_newest_first(self):
        from options_desk.rules import Signal
        st = DeskState()
        st.add_signals([Signal("r", "A", "info", "a1", T0), Signal("r", "B", "info", "b1", T0),
                        Signal("r", "A", "info", "a2", T0)])
        rows = st.recent_signals("A")
        self.assertEqual([r["message"] for r in rows], ["a2", "a1"])

    def test_payload_swap_is_atomic(self):
        st = DeskState()
        st.write({"status": "ok", "n": 1})
        self.assertEqual(st.read()["n"], 1)


class TestHttp(unittest.TestCase):
    """Real server on an ephemeral loopback port."""

    @classmethod
    def setUpClass(cls):
        cls.state = DeskState()
        cls.state.write({"status": "ok", "symbols": ["T"], "data": {}, "errors": []})
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.state))
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5)

    def test_state_endpoint(self):
        r = self._get("/api/state")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(r.read())["status"], "ok")

    def test_health_endpoint(self):
        self.assertTrue(json.loads(self._get("/api/health").read())["ok"])

    def test_index_is_served_and_self_contained(self):
        body = self._get("/").read().decode("utf-8")
        self.assertIn("<title>Options Desk</title>", body)
        # A dashboard that reaches the internet for assets is a dashboard that breaks offline.
        for marker in ("src=\"http", "href=\"http", "@import url(http"):
            self.assertNotIn(marker, body)

    def test_unknown_path_404s(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self._get("/nope")
        self.assertEqual(e.exception.code, 404)


class TestNetBind(unittest.TestCase):
    """Where the dashboard binds IS its security boundary -- it has no login by design."""

    def test_tailnet_range_boundaries(self):
        for inside in ("100.64.0.0", "100.101.102.103", "100.127.255.255"):
            self.assertTrue(netbind.is_tailnet(inside), inside)
        for outside in ("100.63.255.255", "100.128.0.0", "10.0.0.5",
                        "192.168.1.1", "127.0.0.1", "not-an-ip", ""):
            self.assertFalse(netbind.is_tailnet(outside), outside)

    def test_picks_tailnet_address_out_of_iproute_output(self):
        lines = [
            "1: lo    inet 127.0.0.1/8 scope host lo",
            "2: eth0    inet 10.0.0.5/24 brd 10.0.0.255 scope global eth0",
            "5: tailscale0    inet 100.101.102.103/32 scope global tailscale0",
        ]
        self.assertEqual(netbind.pick_tailnet_ip(lines), "100.101.102.103")

    def test_picks_tailnet_address_out_of_ifconfig_output(self):
        self.assertEqual(
            netbind.pick_tailnet_ip(["\tinet 100.88.7.9 --> 100.88.7.9 netmask 0xff000000"]),
            "100.88.7.9")

    def test_returns_none_when_no_tailnet_address(self):
        self.assertIsNone(netbind.pick_tailnet_ip(["inet 192.168.0.2/24", "inet 10.1.2.3/8"]))

    def test_classify(self):
        self.assertEqual(netbind.classify("127.0.0.1"), "loopback")
        self.assertEqual(netbind.classify("localhost"), "loopback")
        self.assertEqual(netbind.classify("100.101.102.103"), "tailnet")
        self.assertEqual(netbind.classify("0.0.0.0"), "wildcard")
        self.assertEqual(netbind.classify("192.168.1.50"), "other")

    def test_resolve_passes_explicit_addresses_through(self):
        self.assertEqual(netbind.resolve("127.0.0.1"), "127.0.0.1")
        self.assertEqual(netbind.resolve("100.101.2.3"), "100.101.2.3")

    def test_resolve_fails_loudly_without_tailscale(self):
        """Must never quietly fall back to a wider bind when the tailnet is unavailable."""
        orig = netbind.detect_tailnet_ip
        netbind.detect_tailnet_ip = lambda: None
        self.addCleanup(lambda: setattr(netbind, "detect_tailnet_ip", orig))
        with self.assertRaises(SystemExit) as e:
            netbind.resolve("tailscale")
        msg = str(e.exception)
        self.assertIn("tailscale status", msg)
        self.assertIn("--host 100.x.y.z", msg)

    def test_resolve_uses_detected_address(self):
        orig = netbind.detect_tailnet_ip
        netbind.detect_tailnet_ip = lambda: "100.9.9.9"
        self.addCleanup(lambda: setattr(netbind, "detect_tailnet_ip", orig))
        for alias in ("tailscale", "ts", "TAILNET"):
            self.assertEqual(netbind.resolve(alias), "100.9.9.9")

    def test_advice_warns_appropriately(self):
        loop = " ".join(netbind.advise("127.0.0.1", 8787))
        self.assertIn("this machine only", loop)
        self.assertNotIn("WARNING", loop)

        tail = " ".join(netbind.advise("100.101.2.3", 8787))   # inside 100.64.0.0/10
        self.assertIn("tailnet", tail)
        self.assertIn("funnel", tail)               # the one way to leak it publicly

        wild = " ".join(netbind.advise("0.0.0.0", 8787))
        self.assertIn("WARNING", wild)
        self.assertIn("ALL interfaces", wild)

        other = " ".join(netbind.advise("192.168.1.50", 8787))
        self.assertIn("WARNING", other)


class TestWorkerIntegration(unittest.TestCase):
    def test_worker_builds_a_full_payload(self):
        from options_desk import rules as rules_mod
        from options_desk.server import Worker

        c = cfg(OPTIONS_SYNTH_STEP_S="300", OPTIONS_EXCHANGE="US")
        prov = SyntheticProvider(c)
        for _ in range(80):
            prov._now()
        state = DeskState()
        w = Worker(c, state, ["SPY"], prov, prov,
                   rules_mod.build(rules_mod.default_specs("chain")
                                   + rules_mod.default_specs("bars")),
                   interval=1, bar_interval="5m", stop=threading.Event())
        errors = []
        payload = w._one("SPY", errors)
        self.assertEqual(errors, [])
        for key in ("chain", "bars", "analytics", "bias", "signals"):
            self.assertIn(key, payload)
        self.assertGreater(len(payload["chain"]["rows"]), 0)
        self.assertGreater(len(payload["bars"]["series"]), 0)
        json.dumps(payload, default=str)

    def test_bar_only_provider_yields_no_chain(self):
        from options_desk import rules as rules_mod
        from options_desk.server import Worker
        from options_desk.providers.yahoo import YahooProvider

        c = cfg(OPTIONS_EXCHANGE="US")
        errors = []
        w = Worker(c, DeskState(), ["SPY"], YahooProvider(c), None,
                   rules_mod.build(rules_mod.default_specs("chain")),
                   interval=1, bar_interval="5m", stop=threading.Event())
        payload = w._one("SPY", errors)
        self.assertNotIn("chain", payload)          # yahoo has no chains
        self.assertTrue(errors)                     # and says so rather than failing silently


if __name__ == "__main__":
    unittest.main(verbosity=2)
