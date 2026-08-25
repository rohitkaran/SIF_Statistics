#!/usr/bin/env python3
"""
test_options_desk.py  --  Unit tests for the options desk. stdlib unittest, no network.

The vendor adapters are tested against captured payload shapes with _http.get_json patched
out, so the parsing logic is covered in CI where there is neither a key nor egress.

    python -m unittest discover -s tests -v
"""

import datetime as dt
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options_desk import alerts, config, greeks as bs, rules as rules_mod, store  # noqa: E402
from options_desk.engine import Engine  # noqa: E402
from options_desk.history import History, Series, skew_25d, nearest_delta  # noqa: E402
from options_desk.models import ChainSnapshot, Contract, Quote, expiry_utc  # noqa: E402
from options_desk.providers import get as get_provider, ProviderError  # noqa: E402
from options_desk.providers.synthetic import SyntheticProvider  # noqa: E402

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 8, 25, 14, 0, tzinfo=UTC)


def cfg(**kw):
    return config.load(env_path="/nonexistent", overrides=kw)


class TestGreeks(unittest.TestCase):
    def test_put_call_parity(self):
        import math
        s, k, t, v, r, q = 100, 100, 0.5, 0.25, 0.04, 0.01
        lhs = bs.price(s, k, t, v, "C", r, q) - bs.price(s, k, t, v, "P", r, q)
        rhs = s * math.exp(-q * t) - k * math.exp(-r * t)
        self.assertAlmostEqual(lhs, rhs, places=10)

    def test_iv_roundtrip(self):
        for vol in (0.08, 0.2, 0.75, 2.0):
            px = bs.price(640, 645, 0.05, vol, "C", 0.04)
            self.assertAlmostEqual(bs.implied_vol(px, 640, 645, 0.05, "C", 0.04), vol, places=5)

    def test_deep_itm_put_below_undiscounted_intrinsic_still_solves(self):
        """Regression: the solver used to reject European puts priced under (K - S)."""
        s, k, t, r, vol = 641.13, 655.0, 3 / 365, 0.04, 0.117
        px = bs.price(s, k, t, vol, "P", r)
        self.assertLess(px, max(0.0, k - s))          # genuinely below undiscounted intrinsic
        self.assertAlmostEqual(bs.implied_vol(px, s, k, t, "P", r), vol, places=5)

    def test_iv_rejects_unsolvable(self):
        self.assertIsNone(bs.implied_vol(0.0001, 641, 655, 3 / 365, "P", 0.04))
        self.assertIsNone(bs.implied_vol(9999.0, 641, 655, 3 / 365, "P", 0.04))
        self.assertIsNone(bs.implied_vol(None, 641, 655, 3 / 365, "P"))

    def test_expired_is_intrinsic_and_step_delta(self):
        self.assertEqual(bs.price(110, 100, 0, 0.2, "C"), 10)
        self.assertEqual(bs.greeks(110, 100, 0, 0.2, "C")["delta"], 1.0)
        self.assertEqual(bs.greeks(90, 100, 0, 0.2, "C")["delta"], 0.0)
        self.assertEqual(bs.greeks(90, 100, 0, 0.2, "P")["delta"], -1.0)

    def test_greek_signs(self):
        g = bs.greeks(100, 100, 0.5, 0.25, "C", 0.04)
        self.assertGreater(g["delta"], 0)
        self.assertGreater(g["gamma"], 0)
        self.assertGreater(g["vega"], 0)
        self.assertLess(g["theta"], 0)               # long options decay
        self.assertLess(bs.greeks(100, 100, 0.5, 0.25, "P", 0.04)["delta"], 0)

    def test_year_fraction_never_negative(self):
        self.assertEqual(bs.year_fraction(T0, T0 - dt.timedelta(days=5)), 0.0)


class TestModels(unittest.TestCase):
    def test_occ_symbol(self):
        c = Contract("SPY", dt.date(2026, 9, 18), 640.0, "C")
        self.assertEqual(c.occ(), "SPY   260918C00640000")
        self.assertEqual(len(c.occ()), 21)

    def test_mid_and_spread(self):
        q = Quote(Contract("SPY", dt.date(2026, 9, 18), 640.0, "C"), bid=5.0, ask=5.4)
        self.assertAlmostEqual(q.mid, 5.2)
        self.assertAlmostEqual(q.spread, 0.4)
        self.assertAlmostEqual(q.spread_pct, 0.4 / 5.2)

    def test_mid_falls_back(self):
        c = Contract("SPY", dt.date(2026, 9, 18), 640.0, "C")
        self.assertEqual(Quote(c, last=3.3).mid, 3.3)
        self.assertEqual(Quote(c, bid=2.0).mid, 2.0)
        self.assertIsNone(Quote(c).mid)

    def test_tradeable_gates(self):
        c = Contract("SPY", dt.date(2026, 9, 18), 640.0, "C")
        self.assertTrue(Quote(c, bid=5.0, ask=5.2, open_interest=500).is_tradeable(0.1, 100))
        self.assertFalse(Quote(c, bid=1.0, ask=3.0, open_interest=500).is_tradeable(0.1, 100))
        self.assertFalse(Quote(c, bid=5.0, ask=5.2, open_interest=10).is_tradeable(0.1, 100))

    def test_snapshot_roundtrip_preserves_greeks(self):
        snap = _snap()
        again = ChainSnapshot.from_dict(json.loads(json.dumps(snap.to_dict())))
        self.assertEqual(again.to_dict(), snap.to_dict())
        self.assertAlmostEqual(again.quotes[0].iv, snap.quotes[0].iv)

    def test_selection_helpers(self):
        snap = _snap()
        self.assertEqual(snap.atm_strike(), 640.0)
        self.assertIsNotNone(snap.atm_iv())
        self.assertEqual(snap.nearest_expiry(), dt.date(2026, 8, 28))
        self.assertIsNone(snap.nearest_expiry(min_dte=999))
        self.assertIsNotNone(snap.get(dt.date(2026, 8, 28), 640.0, "C"))

    def test_parity_vol_fallback_fills_deep_itm(self):
        """Deep-ITM contracts borrow vol from the OTM side of the same strike."""
        exp = dt.date(2026, 8, 28)
        quotes = [
            # Deep ITM put: all intrinsic, quoted a hair under the model floor -> unsolvable.
            Quote(Contract("SPY", exp, 700.0, "P"), bid=59.60, ask=59.70),
            # Its counterpart: deep OTM call, all time value, solves cleanly.
            Quote(Contract("SPY", exp, 700.0, "C"), bid=0.20, ask=0.24),
        ]
        snap = ChainSnapshot("SPY", 640.0, T0, quotes, "test", 0.04).enrich()
        put, call = snap.get(exp, 700.0, "P"), snap.get(exp, 700.0, "C")
        self.assertIsNotNone(call.iv)
        self.assertIsNotNone(put.iv)
        self.assertAlmostEqual(put.iv, call.iv)
        self.assertLess(put.delta, -0.9)
        self.assertGreater(put.gamma, 0.0)      # continuous, not the expiry step function

    def test_every_synthetic_contract_solves(self):
        """Regression: rounding order and the floor bracket used to blank deep-ITM IVs."""
        p = SyntheticProvider(cfg())
        unsolved = 0
        for _ in range(20):
            snap = p.snapshot("SPY", 3, 12)
            unsolved += sum(1 for q in snap.quotes if q.iv is None)
        self.assertEqual(unsolved, 0)

    def test_expiry_utc_is_aware(self):
        self.assertIsNotNone(expiry_utc(dt.date(2026, 8, 28)).tzinfo)


class TestHistory(unittest.TestCase):
    def test_covers_guard_blocks_early_fire(self):
        s = Series()
        s.append(T0, 100)
        self.assertFalse(s.covers(60))
        self.assertIsNone(s.change(60))
        s.append(T0 + dt.timedelta(seconds=90), 101)
        self.assertTrue(s.covers(60))
        self.assertAlmostEqual(s.change(60), 1.0)

    def test_none_values_are_not_stored(self):
        s = Series()
        s.append(T0, None)
        self.assertEqual(len(s), 0)

    def test_time_based_pruning(self):
        s = Series(retention_s=100)
        for i in range(0, 301, 10):
            s.append(T0 + dt.timedelta(seconds=i), i)
        self.assertEqual(len(s), 11)

    def test_rank_and_high_low(self):
        s = Series()
        for i, v in enumerate([1, 2, 3, 4, 5]):
            s.append(T0 + dt.timedelta(seconds=i), v)
        self.assertEqual(s.rank(5), 1.0)
        self.assertEqual(s.high_low(), (5, 1))

    def test_history_tracks_snapshot(self):
        h = History()
        h.update(_snap())
        self.assertEqual(h.symbols(), ["SPY"])
        self.assertIsNotNone(h.series("SPY", "spot").last)

    def test_nearest_delta_and_skew(self):
        snap = SyntheticProvider(cfg()).snapshot("SPY", 1, 10)
        e = snap.nearest_expiry()
        self.assertIsNotNone(nearest_delta(snap, e, "P", 0.25))
        self.assertIsNotNone(skew_25d(snap))


class TestRules(unittest.TestCase):
    def test_build_validation(self):
        self.assertEqual(len(rules_mod.build(rules_mod.DEFAULT_RULES)), 5)
        for bad in ([{"type": "nope"}], [{"nope": 1}], [{"type": "iv_spike", "severity": "x"}]):
            with self.assertRaises(SystemExit):
                rules_mod.build(bad)

    def test_spot_move_fires_only_past_threshold(self):
        rule = rules_mod.build([{"type": "spot_move", "window_s": 60, "threshold": 0.01}])[0]
        h = History()
        a, b = _snap(spot=640.0), _snap(spot=640.5, ts=T0 + dt.timedelta(seconds=90))
        h.update(a)
        h.update(b)
        self.assertEqual(rule.evaluate(b, h), [])                 # +0.08% < 1%
        c = _snap(spot=660.0, ts=T0 + dt.timedelta(seconds=180))
        h.update(c)
        sigs = rule.evaluate(c, h)
        self.assertEqual(len(sigs), 1)
        self.assertIn("up", sigs[0].message)

    def test_symbol_scoping(self):
        rule = rules_mod.build([{"type": "spot_move", "symbols": ["QQQ"]}])[0]
        self.assertFalse(rule.applies_to("SPY"))
        self.assertTrue(rule.applies_to("QQQ"))

    def test_credit_target_rejects_illiquid(self):
        rule = rules_mod.build([{"type": "credit_target", "delta": 0.5, "right": "C",
                                 "min_credit": 0.01, "min_dte": 0,
                                 "max_spread_pct": 0.001, "min_oi": 10 ** 9}])[0]
        snap = SyntheticProvider(cfg()).snapshot("SPY", 1, 6)
        self.assertEqual(rule.evaluate(snap, History()), [])

    def test_credit_target_fires_when_liquid(self):
        rule = rules_mod.build([{"type": "credit_target", "delta": 0.5, "right": "P",
                                 "min_credit": 0.01, "min_dte": 0,
                                 "max_spread_pct": 0.99, "min_oi": 0}])[0]
        snap = SyntheticProvider(cfg()).snapshot("SPY", 1, 6)
        sigs = rule.evaluate(snap, History())
        self.assertEqual(len(sigs), 1)
        self.assertIn("credit", sigs[0].message)

    def test_signal_serialises(self):
        sig = rules_mod.Signal("r", "SPY", "info", "hi", T0)
        self.assertEqual(sig.key, "r:SPY")
        self.assertEqual(json.loads(json.dumps(sig.to_dict()))["ts"], T0.isoformat())


class TestEngine(unittest.TestCase):
    def test_cooldown_uses_snapshot_time(self):
        """Determinism guarantee: replay must suppress exactly as the live run did."""
        rule = rules_mod.build([{"type": "spot_move", "window_s": 60,
                                 "threshold": 0.001, "cooldown_s": 600}])[0]
        eng = Engine(None, [rule], alerts.Dispatcher())
        eng.tick(_snap(spot=640.0))
        fired1 = eng.tick(_snap(spot=660.0, ts=T0 + dt.timedelta(seconds=90)))
        fired2 = eng.tick(_snap(spot=680.0, ts=T0 + dt.timedelta(seconds=150)))
        self.assertEqual(len(fired1), 1)
        self.assertEqual(fired2, [])                      # inside the 600s cooldown
        fired3 = eng.tick(_snap(spot=700.0, ts=T0 + dt.timedelta(seconds=900)))
        self.assertEqual(len(fired3), 1)
        self.assertEqual(eng.stats["suppressed"], 1)

    def test_broken_rule_does_not_stop_engine(self):
        class Boom(rules_mod.Rule):
            type = "boom"

            def evaluate(self, snap, hist):
                raise ValueError("boom")

        eng = Engine(None, [Boom()], alerts.Dispatcher())
        err = io.StringIO()
        stderr, sys.stderr = sys.stderr, err
        try:
            eng.tick(_snap())
        finally:
            sys.stderr = stderr
        self.assertEqual(eng.stats["errors"], 1)
        self.assertEqual(eng.stats["ticks"], 1)
        self.assertIn("boom", err.getvalue())

    def test_replay_is_deterministic(self):
        snaps = [_snap(spot=640 + i, ts=T0 + dt.timedelta(seconds=60 * i)) for i in range(10)]
        runs = []
        for _ in range(2):
            eng = Engine(None, rules_mod.build(rules_mod.DEFAULT_RULES), alerts.Dispatcher())
            eng.replay([ChainSnapshot.from_dict(s.to_dict()) for s in snaps])
            runs.append(eng.stats["by_rule"])
        self.assertEqual(runs[0], runs[1])


class TestAlerts(unittest.TestCase):
    def test_jsonl_sink_writes(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "a.jsonl")
            sink = alerts.JsonlSink(path)
            sink.emit(rules_mod.Signal("r", "SPY", "info", "hello", T0))
            sink.close()
            with open(path) as f:
                self.assertEqual(json.loads(f.read())["message"], "hello")
        finally:
            shutil.rmtree(d)

    def test_failing_sink_is_isolated(self):
        class Bad(alerts.Sink):
            name = "bad"

            def emit(self, signal):
                raise RuntimeError("nope")

        good = io.StringIO()
        d = alerts.Dispatcher([Bad(), alerts.ConsoleSink(stream=good, color=False)])
        err = io.StringIO()
        stderr, sys.stderr = sys.stderr, err
        try:
            d.emit(rules_mod.Signal("r", "SPY", "info", "still delivered", T0))
        finally:
            sys.stderr = stderr
        self.assertIn("still delivered", good.getvalue())
        self.assertIn("sink bad failed", err.getvalue())


class TestStore(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_record_replay_roundtrip(self):
        with store.Recorder(self.d) as rec:
            for i in range(3):
                rec.write(_snap(spot=640 + i, ts=T0 + dt.timedelta(seconds=i)))
        got = list(store.replay(self.d, "SPY"))
        self.assertEqual([round(s.spot) for s in got], [640, 641, 642])
        self.assertEqual(store.summary(self.d)["SPY"]["ticks"], 3)

    def test_corrupt_line_is_skipped(self):
        with store.Recorder(self.d) as rec:
            rec.write(_snap())
        path = store.files_for(self.d, "SPY")[0]
        with gzip.open(path, "at", encoding="utf-8") as f:
            f.write("{ this is not json\n")
        err = io.StringIO()
        stderr, sys.stderr = sys.stderr, err
        try:
            got = list(store.replay(self.d, "SPY"))
        finally:
            sys.stderr = stderr
        self.assertEqual(len(got), 1)
        self.assertIn("skipping", err.getvalue())


class TestConfig(unittest.TestCase):
    def test_env_parsing(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, ".env")
            with open(p, "w") as f:
                f.write('# comment\nexport A="1 #2"\nB=plain # trailing\nC=\nbad line\n')
            got = config.parse_env_file(p)
            self.assertEqual(got, {"A": "1 #2", "B": "plain", "C": ""})
        finally:
            shutil.rmtree(d)

    def test_secrets_are_redacted(self):
        c = cfg(POLYGON_API_KEY="abcdef123456")
        self.assertNotIn("abcdef123456", json.dumps(c.describe()))
        self.assertIn("chars", c.describe()["POLYGON_API_KEY"])

    def test_require_names_missing_keys(self):
        with self.assertRaises(SystemExit) as e:
            cfg().require("MISSING_ONE", "MISSING_TWO")
        self.assertIn("MISSING_ONE", str(e.exception))

    def test_typed_accessors(self):
        c = cfg(OPTIONS_UNDERLYINGS="spy, qqq;iwm")
        self.assertEqual(c.list("OPTIONS_UNDERLYINGS"), ["SPY", "QQQ", "IWM"])
        self.assertEqual(c.int("OPTIONS_EXPIRY_LIMIT"), 3)
        self.assertEqual(c.float("NOPE", 1.5), 1.5)


class TestProviderRegistry(unittest.TestCase):
    def test_unknown_provider(self):
        with self.assertRaises(SystemExit):
            get_provider("nope", cfg())

    def test_missing_credentials_are_named(self):
        with self.assertRaises(SystemExit) as e:
            get_provider("polygon", cfg())
        self.assertIn("POLYGON_API_KEY", str(e.exception))

    def test_synthetic_is_deterministic(self):
        a = SyntheticProvider(cfg()).snapshot("SPY", 1, 3)
        b = SyntheticProvider(cfg()).snapshot("SPY", 1, 3)
        self.assertEqual(a.spot, b.spot)
        self.assertEqual(len(a.quotes), len(b.quotes))

    def test_synthetic_chain_is_well_formed(self):
        snap = SyntheticProvider(cfg()).snapshot("SPY", 2, 4)
        self.assertEqual(len(snap.expiries()), 2)
        self.assertTrue(all(q.iv is not None for q in snap.quotes))
        self.assertTrue(all(q.bid <= q.ask for q in snap.quotes))
        e = snap.nearest_expiry()
        k = snap.atm_strike(e)
        self.assertGreater(snap.get(e, k, "C").delta, 0)
        self.assertLess(snap.get(e, k, "P").delta, 0)

    def test_virtual_clock_advances(self):
        p = SyntheticProvider(cfg(OPTIONS_SYNTH_STEP_S="60"))
        a = p.snapshot("SPY", 1, 2)
        b = p.snapshot("SPY", 1, 2)
        self.assertAlmostEqual((b.ts - a.ts).total_seconds(), 60, places=3)


class TestVendorParsing(unittest.TestCase):
    """Adapter parsing against captured payload shapes -- no network, no credentials."""

    def _patch(self, module, fn):
        from options_desk.providers import _http
        orig = _http.get_json
        module._http.get_json = fn
        self.addCleanup(lambda: setattr(module._http, "get_json", orig))

    def test_polygon_parses_snapshot(self):
        from options_desk.providers import polygon as poly
        payload = {"status": "OK", "results": [{
            "details": {"expiration_date": "2026-09-18", "strike_price": 640,
                        "contract_type": "call", "ticker": "O:SPY260918C00640000"},
            "last_quote": {"bid": 5.0, "ask": 5.4}, "last_trade": {"price": 5.2},
            "day": {"volume": 1234, "close": 5.1}, "open_interest": 4321,
            "implied_volatility": 0.19,
            "underlying_asset": {"price": 640.0, "ticker": "SPY"}}]}
        self._patch(poly, lambda url, params=None, headers=None, **kw: payload)
        snap = poly.PolygonProvider(cfg(POLYGON_API_KEY="x")).snapshot("SPY", 1, 0)
        self.assertEqual(snap.spot, 640.0)
        self.assertEqual(len(snap.quotes), 1)
        q = snap.quotes[0]
        self.assertEqual((q.contract.strike, q.contract.right), (640.0, "C"))
        self.assertAlmostEqual(q.mid, 5.2)
        self.assertEqual(q.open_interest, 4321)
        self.assertAlmostEqual(q.vendor_iv, 0.19)
        self.assertIsNotNone(q.iv)                    # solved locally, not copied

    def test_polygon_empty_chain_raises(self):
        from options_desk.providers import polygon as poly
        self._patch(poly, lambda url, params=None, headers=None, **kw: {"results": []})
        with self.assertRaises(ProviderError):
            poly.PolygonProvider(cfg(POLYGON_API_KEY="x")).snapshot("NOPE")

    def test_polygon_skips_malformed_rows(self):
        from options_desk.providers import polygon as poly
        payload = {"results": [
            {"details": {"expiration_date": "bad-date", "strike_price": 1, "contract_type": "call"}},
            {"details": {"expiration_date": "2026-09-18", "strike_price": 640,
                         "contract_type": "put"}, "last_quote": {"bid": 1.0, "ask": 1.2},
             "underlying_asset": {"price": 640.0}}]}
        self._patch(poly, lambda url, params=None, headers=None, **kw: payload)
        snap = poly.PolygonProvider(cfg(POLYGON_API_KEY="x")).snapshot("SPY", 1, 0)
        self.assertEqual(len(snap.quotes), 1)

    def test_tradier_parses_chain(self):
        from options_desk.providers import tradier as tr

        def fake(url, params=None, headers=None, **kw):
            if "quotes" in url:
                return {"quotes": {"quote": {"last": 640.0}}}
            if "expirations" in url:
                return {"expirations": {"date": ["2026-09-18", "2026-09-25"]}}
            return {"options": {"option": [
                {"strike": 640, "option_type": "put", "bid": 4.0, "ask": 4.4,
                 "last": 4.2, "volume": 10, "open_interest": 99,
                 "symbol": "SPY260918P00640000", "greeks": {"mid_iv": 0.21}}]}}

        self._patch(tr, fake)
        err = io.StringIO()
        stderr, sys.stderr = sys.stderr, err
        try:
            snap = tr.TradierProvider(cfg(TRADIER_ACCESS_TOKEN="x", TRADIER_ENV="sandbox")) \
                .snapshot("SPY", 1, 0)
        finally:
            sys.stderr = stderr
        self.assertIn("DELAYED", err.getvalue())      # sandbox must warn
        self.assertEqual(snap.spot, 640.0)
        self.assertEqual(len(snap.quotes), 1)
        self.assertAlmostEqual(snap.quotes[0].mid, 4.2)
        self.assertAlmostEqual(snap.quotes[0].vendor_iv, 0.21)

    def test_tradier_handles_single_object_collapse(self):
        """Tradier returns a bare object, not a list, when there is exactly one element."""
        from options_desk.providers import tradier as tr

        def fake(url, params=None, headers=None, **kw):
            if "quotes" in url:
                return {"quotes": {"quote": [{"last": 640.0}]}}
            if "expirations" in url:
                return {"expirations": {"date": "2026-09-18"}}
            return {"options": {"option": {"strike": 640, "option_type": "call",
                                           "bid": 5.0, "ask": 5.2}}}

        self._patch(tr, fake)
        snap = tr.TradierProvider(cfg(TRADIER_ACCESS_TOKEN="x", TRADIER_ENV="production")) \
            .snapshot("SPY", 1, 0)
        self.assertEqual(len(snap.quotes), 1)

    def test_tradier_rejects_bad_env(self):
        with self.assertRaises(SystemExit):
            from options_desk.providers import tradier as tr
            tr.TradierProvider(cfg(TRADIER_ACCESS_TOKEN="x", TRADIER_ENV="live"))


class TestBacktest(unittest.TestCase):
    def test_scores_forward_moves(self):
        from options_desk.backtest import Backtest
        snaps = [_snap(spot=640 + i * 0.5, ts=T0 + dt.timedelta(seconds=60 * i))
                 for i in range(40)]
        bt = Backtest(rules_mod.build([{"type": "spot_move", "window_s": 60,
                                        "threshold": 0.0001, "cooldown_s": 0}]),
                      horizons_s=(60, 300))
        stats = bt.run(snaps)
        self.assertEqual(stats["ticks"], 40)
        scored = bt.score()
        self.assertIn("spot_move", scored)
        self.assertGreater(scored["spot_move"]["horizons"][60]["mean_spot_bp"], 0)
        self.assertIn("BACKTEST", bt.report())

    def test_empty_recording_reports_cleanly(self):
        from options_desk.backtest import Backtest
        bt = Backtest(rules_mod.build(rules_mod.DEFAULT_RULES))
        bt.run([])
        self.assertIn("No signals fired", bt.report())


class TestCLI(unittest.TestCase):
    def test_commands_run(self):
        from options_desk.cli import main
        err = io.StringIO()
        stderr, sys.stderr = sys.stderr, err
        try:
            for argv in (["providers"], ["rules"], ["config"]):
                self.assertEqual(main(argv), 0)
        finally:
            sys.stderr = stderr
        self.assertIn("synthetic", err.getvalue())


# -- fixtures ----------------------------------------------------------------------

def _snap(spot=640.0, ts=T0):
    """A tiny two-strike chain, enriched, good enough for rule/engine tests."""
    exp = dt.date(2026, 8, 28)
    quotes = []
    for k in (635.0, 640.0, 645.0):
        for right, bid, ask in (("C", 5.0, 5.4), ("P", 4.0, 4.4)):
            quotes.append(Quote(Contract("SPY", exp, k, right), bid=bid, ask=ask,
                                open_interest=1000, volume=100))
    return ChainSnapshot("SPY", spot, ts, quotes, "test", 0.04).enrich()


if __name__ == "__main__":
    unittest.main(verbosity=2)
