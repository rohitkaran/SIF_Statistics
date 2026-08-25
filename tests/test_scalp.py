#!/usr/bin/env python3
"""
test_scalp.py  --  Unit tests for the intraday scalping side: sessions, pivots, CPR, VWAP,
and every scalping rule. stdlib unittest, no network, no credentials.

Each rule is tested twice: once on data engineered to trigger it, once on data that must NOT.
A signal rule that only ever fires is as useless as one that never does.

    python -m unittest discover -s tests -v
"""

import datetime as dt
import io
import json
import os
import statistics
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options_desk import config, rules as rules_mod  # noqa: E402
from options_desk.bars import Bar, BarSeries, get_session, SESSIONS  # noqa: E402
from options_desk.history import History  # noqa: E402
from options_desk.levels import (Levels, Vwap, central_pivot_range,  # noqa: E402
                                 classic_pivots, running_vwap)
from options_desk.models import BarSnapshot, snapshot_from_dict  # noqa: E402
from options_desk.providers import ProviderError  # noqa: E402
from options_desk.providers.synthetic import SyntheticProvider  # noqa: E402

UTC = dt.timezone.utc
DAY = dt.date(2026, 8, 25)          # a Tuesday
PREV = (105.0, 95.0, 104.0)         # prev H/L/C -> P 101.333, BC 100.0, TC 102.667


def cfg(**kw):
    return config.load(env_path="/nonexistent", overrides=kw)


def make_snap(bars_spec, prev=PREV, exchange="NSE", price=None, day=DAY):
    """
    Build a BarSnapshot from [(o, h, l, c, v), ...] laid on the session's 5-minute grid.

    Timestamps start at the session open so every bar survives the regular-hours filter.
    """
    session = get_session(exchange)
    start = session.open_utc(day)
    bars = [Bar(start + dt.timedelta(minutes=5 * i), *spec)
            for i, spec in enumerate(bars_spec)]
    series = BarSeries(bars, session)
    vwap = Vwap(session).feed(series)
    last = bars[-1]
    return BarSnapshot(underlying="TEST", price=price if price is not None else last.close,
                       ts=last.ts, bars=series,
                       levels=Levels.from_previous(*prev) if prev else None,
                       vwap=vwap, provider="test", exchange=exchange, interval="5m")


def flat(n, px=101.0, vol=1000.0):
    return [(px, px + 0.05, px - 0.05, px, vol)] * n


def rule(type_, **params):
    return rules_mod.build([{"type": type_, **params}])[0]


class TestSessions(unittest.TestCase):
    def test_known_session_bounds(self):
        nse, us = get_session("NSE"), get_session("US")
        self.assertEqual(nse.open_utc(DAY).strftime("%H:%M"), "03:45")   # 09:15 IST
        self.assertEqual(nse.close_utc(DAY).strftime("%H:%M"), "10:00")  # 15:30 IST
        self.assertEqual(us.open_utc(DAY).strftime("%H:%M"), "13:30")    # 09:30 ET
        self.assertEqual(us.close_utc(DAY).strftime("%H:%M"), "20:00")   # 16:00 ET

    def test_regular_hours_filter(self):
        s = get_session("US")
        self.assertFalse(s.is_regular(s.open_utc(DAY) - dt.timedelta(hours=1)))
        self.assertTrue(s.is_regular(s.open_utc(DAY) + dt.timedelta(minutes=1)))
        self.assertFalse(s.is_regular(s.close_utc(DAY) + dt.timedelta(minutes=1)))

    def test_session_key_is_local_date(self):
        nse = get_session("NSE")
        # 04:00 UTC is 09:30 IST the same day -- NSE never crosses local midnight.
        self.assertEqual(nse.key(dt.datetime(2026, 8, 25, 4, 0, tzinfo=UTC)), DAY)

    def test_unknown_exchange(self):
        with self.assertRaises(SystemExit):
            get_session("LSE")

    def test_series_groups_and_slices(self):
        s = get_session("NSE")
        b1 = [Bar(s.open_utc(DAY) + dt.timedelta(minutes=5 * i), 1, 2, 0.5, 1.5, 10)
              for i in range(3)]
        d2 = dt.date(2026, 8, 26)
        b2 = [Bar(s.open_utc(d2) + dt.timedelta(minutes=5 * i), 2, 3, 1.5, 2.5, 10)
              for i in range(2)]
        series = BarSeries(b1 + b2, s)
        self.assertEqual(series.session_dates(), [DAY, d2])
        self.assertEqual(len(series.session_bars()), 2)
        self.assertEqual(len(series.previous_session_bars()), 3)
        o, h, l, c, v = BarSeries.ohlc(b1)
        self.assertEqual((o, h, l, c, v), (1, 2, 0.5, 1.5, 30))


class TestPivotsAndCpr(unittest.TestCase):
    def test_classic_pivot_formulas(self):
        h, l, c = PREV
        p = classic_pivots(h, l, c)
        self.assertAlmostEqual(p["P"], (h + l + c) / 3)
        self.assertAlmostEqual(p["R1"], 2 * p["P"] - l)
        self.assertAlmostEqual(p["S1"], 2 * p["P"] - h)
        self.assertAlmostEqual(p["R2"], p["P"] + (h - l))
        self.assertAlmostEqual(p["S2"], p["P"] - (h - l))
        self.assertAlmostEqual(p["R3"], h + 2 * (p["P"] - l))
        self.assertAlmostEqual(p["S3"], l - 2 * (h - p["P"]))

    def test_cpr_formula(self):
        h, l, c = PREV
        cpr = central_pivot_range(h, l, c)
        self.assertAlmostEqual(cpr["pivot"], (h + l + c) / 3)
        self.assertAlmostEqual(cpr["bc"], (h + l) / 2)
        self.assertAlmostEqual(cpr["tc"], 2 * cpr["pivot"] - cpr["bc"])
        self.assertAlmostEqual(cpr["width"], cpr["tc"] - cpr["bc"])

    def test_tc_bc_swapped_when_close_below_range_mid(self):
        """Close under the range midpoint computes TC below BC; they must be relabelled."""
        cpr = central_pivot_range(105.0, 95.0, 96.0)
        self.assertGreaterEqual(cpr["tc"], cpr["bc"])
        self.assertAlmostEqual(cpr["bc"], 2 * cpr["pivot"] - 100.0)   # the raw TC value
        self.assertAlmostEqual(cpr["width"], cpr["tc"] - cpr["bc"])

    def test_position_and_nearest(self):
        lv = Levels.from_previous(*PREV)
        self.assertEqual(lv.position(110), "above")
        self.assertEqual(lv.position(101), "inside")
        self.assertEqual(lv.position(90), "below")
        name, val, dist = lv.nearest(102.6)
        self.assertEqual(name, "TC")
        self.assertLess(dist, 0.1)

    def test_width_pct_is_scale_free(self):
        small = Levels.from_previous(105, 95, 104)
        big = Levels.from_previous(10500, 9500, 10400)
        self.assertAlmostEqual(small.width_pct, big.width_pct, places=9)

    def test_named_includes_prev_session(self):
        named = Levels.from_previous(*PREV).named()
        for k in ("PDH", "PDL", "PDC", "TC", "BC", "P", "R1", "S3"):
            self.assertIn(k, named)


class TestVwap(unittest.TestCase):
    def test_equal_volume_equals_mean_typical(self):
        s = get_session("NSE")
        bars = [Bar(s.open_utc(DAY) + dt.timedelta(minutes=5 * i),
                    100 + i, 101 + i, 99 + i, 100.5 + i, 1000) for i in range(6)]
        v = Vwap(s).feed(bars)
        tps = [b.typical for b in bars]
        self.assertAlmostEqual(v.value, statistics.fmean(tps))
        self.assertAlmostEqual(v.stdev, statistics.pstdev(tps))

    def test_volume_actually_weights(self):
        s = get_session("NSE")
        o = s.open_utc(DAY)
        bars = [Bar(o, 100, 100, 100, 100, 1),
                Bar(o + dt.timedelta(minutes=5), 200, 200, 200, 200, 999)]
        self.assertGreater(Vwap(s).feed(bars).value, 199.0)

    def test_zero_volume_is_undefined_not_zero(self):
        s = get_session("NSE")
        v = Vwap(s).feed([Bar(s.open_utc(DAY), 100, 101, 99, 100, 0)])
        self.assertIsNone(v.value)
        self.assertIsNone(v.stdev)
        self.assertEqual(v.band(2), (None, None))
        self.assertIsNone(v.z(100))

    def test_resets_on_new_session(self):
        s = get_session("NSE")
        v = Vwap(s).feed([Bar(s.open_utc(DAY), 100, 100, 100, 100, 500)])
        self.assertAlmostEqual(v.value, 100.0)
        v.update(Bar(s.open_utc(dt.date(2026, 8, 26)), 200, 200, 200, 200, 500))
        self.assertEqual(v.anchor, dt.date(2026, 8, 26))
        self.assertAlmostEqual(v.value, 200.0)      # yesterday must not leak in
        self.assertEqual(v.bars, 1)

    def test_variance_never_negative_on_flat_prices(self):
        s = get_session("NSE")
        bars = [Bar(s.open_utc(DAY) + dt.timedelta(minutes=5 * i), 100, 100, 100, 100, 1e9)
                for i in range(50)]
        v = Vwap(s).feed(bars)
        self.assertGreaterEqual(v.variance, 0.0)
        self.assertEqual(v.stdev, 0.0)
        self.assertIsNone(v.z(101))                 # zero stdev -> z is undefined, not inf

    def test_running_vwap_uses_contemporaneous_value(self):
        s = get_session("NSE")
        bars = [Bar(s.open_utc(DAY) + dt.timedelta(minutes=5 * i), 100, 100, 100, 100, 100)
                for i in range(3)]
        bars.append(Bar(s.open_utc(DAY) + dt.timedelta(minutes=15), 200, 200, 200, 200, 100))
        track = running_vwap(s, bars)
        self.assertEqual(len(track), 4)
        self.assertAlmostEqual(track[0][1], 100.0)
        self.assertLess(track[2][1], track[3][1])   # vwap rises only once the 200 print lands


class TestBarSnapshot(unittest.TestCase):
    def test_relative_volume_uses_median(self):
        spec = flat(10, vol=1000.0)
        spec[0] = (101, 101.05, 100.95, 101, 100000.0)      # huge opening bar
        spec[-1] = (101, 101.05, 100.95, 101, 2000.0)
        snap = make_snap(spec)
        # A mean would be dragged over 10000 by the opening print and hide the 2x surge.
        self.assertAlmostEqual(snap.relative_volume(), 2.0, places=6)

    def test_roundtrip_rebuilds_vwap_and_levels(self):
        snap = make_snap(flat(8))
        again = snapshot_from_dict(json.loads(json.dumps(snap.to_dict())))
        self.assertEqual(again.kind, "bars")
        self.assertAlmostEqual(again.vwap_value, snap.vwap_value)
        self.assertEqual(again.levels.cpr, snap.levels.cpr)
        self.assertEqual(again.exchange, snap.exchange)

    def test_history_tracks_bar_fields(self):
        h = History()
        h.update(make_snap(flat(5)))
        self.assertIsNotNone(h.series("TEST", "price").last)
        self.assertIsNotNone(h.series("TEST", "vwap").last)

    def test_backtest_hooks(self):
        snap = make_snap(flat(5))
        self.assertEqual(snap.mark_price, snap.price)
        self.assertEqual(snap.VOL_LABEL, "z")


class TestScalpRules(unittest.TestCase):
    """Every rule: one case that must fire, one that must not."""

    def test_vwap_cross_fires_on_reclaim(self):
        spec = flat(5, px=100.0) + [(100, 110.1, 100, 110, 1000.0)]
        sigs = rule("vwap_cross", min_rvol=0).evaluate(make_snap(spec), History())
        self.assertEqual(len(sigs), 1)
        self.assertIn("reclaimed VWAP", sigs[0].message)

    def test_vwap_cross_silent_without_cross(self):
        sigs = rule("vwap_cross", min_rvol=0).evaluate(make_snap(flat(8)), History())
        self.assertEqual(sigs, [])

    def test_vwap_cross_volume_gate(self):
        spec = flat(5, px=100.0) + [(100, 110.1, 100, 110, 1.0)]   # cross on no volume
        self.assertEqual(rule("vwap_cross", min_rvol=5.0).evaluate(make_snap(spec), History()), [])

    def test_vwap_band_fires_when_stretched(self):
        spec = flat(12, px=100.0) + [(100, 106, 100, 105.9, 1000.0)]
        snap = make_snap(spec)
        self.assertGreater(abs(snap.vwap_z), 2.0)
        sigs = rule("vwap_band", threshold=2.0, min_samples=5).evaluate(snap, History())
        self.assertEqual(len(sigs), 1)
        self.assertIn("extended above", sigs[0].message)

    def test_vwap_band_silent_when_close_to_anchor(self):
        self.assertEqual(rule("vwap_band", threshold=2.0, min_samples=5)
                         .evaluate(make_snap(flat(12)), History()), [])

    def test_cpr_breakout_fires_from_inside(self):
        # prev bar closes inside [BC 100, TC 102.667]; next closes above TC.
        spec = flat(4, px=101.0) + [(101, 103.2, 101, 103.0, 1000.0)]
        sigs = rule("cpr_breakout", min_rvol=0).evaluate(make_snap(spec), History())
        self.assertEqual(len(sigs), 1)
        self.assertIn("broke above TC", sigs[0].message)

    def test_cpr_breakout_requires_prior_bar_inside(self):
        spec = flat(4, px=103.5) + [(103.5, 104, 103.4, 103.9, 1000.0)]   # already outside
        self.assertEqual(rule("cpr_breakout", min_rvol=0)
                         .evaluate(make_snap(spec), History()), [])

    def test_cpr_breakout_width_filter(self):
        spec = flat(4, px=101.0) + [(101, 103.2, 101, 103.0, 1000.0)]
        self.assertEqual(rule("cpr_breakout", min_rvol=0, max_width_pct=0.0001)
                         .evaluate(make_snap(spec), History()), [])

    def test_cpr_reject_fires_on_wick(self):
        spec = flat(4, px=101.0) + [(101, 104.0, 100.5, 101.2, 1000.0)]
        sigs = rule("cpr_reject", min_wick_frac=0.4).evaluate(make_snap(spec), History())
        self.assertEqual(len(sigs), 1)
        self.assertIn("rejected at TC", sigs[0].message)

    def test_cpr_reject_silent_without_wick(self):
        spec = flat(4, px=101.0) + [(101, 103.0, 100.5, 102.9, 1000.0)]   # closed at the high
        self.assertEqual(rule("cpr_reject", min_wick_frac=0.4)
                         .evaluate(make_snap(spec), History()), [])

    def test_narrow_cpr_fires_and_keys_per_session(self):
        snap = make_snap(flat(4), prev=(101.0, 99.0, 100.0))     # width 0 -> narrowest
        sigs = rule("narrow_cpr", threshold_pct=0.0025).evaluate(snap, History())
        self.assertEqual(len(sigs), 1)
        self.assertIn("NARROW CPR", sigs[0].message)
        self.assertIn(str(DAY), sigs[0].key)                     # once per session

    def test_narrow_cpr_silent_when_wide(self):
        snap = make_snap(flat(4), prev=(120.0, 80.0, 119.0))
        self.assertEqual(rule("narrow_cpr", threshold_pct=0.0025).evaluate(snap, History()), [])

    def test_level_test_fires_at_level(self):
        lv = Levels.from_previous(*PREV)
        tc = lv.cpr["tc"]
        snap = make_snap(flat(4), price=tc)
        sigs = rule("level_test", tolerance_pct=0.0005, levels=["TC"]).evaluate(snap, History())
        self.assertEqual(len(sigs), 1)
        self.assertIn("testing TC", sigs[0].message)

    def test_level_test_silent_when_far(self):
        snap = make_snap(flat(4), price=150.0)
        self.assertEqual(rule("level_test", tolerance_pct=0.0005).evaluate(snap, History()), [])

    def test_confluence_requires_level_vwap_and_price_together(self):
        tc = Levels.from_previous(*PREV).cpr["tc"]
        # Every bar prints at TC, so VWAP converges on it and price sits there too.
        snap = make_snap([(tc, tc, tc, tc, 1000.0)] * 6, price=tc)
        sigs = rule("confluence", tolerance_pct=0.002).evaluate(snap, History())
        names = {s.data["level_name"] for s in sigs}
        self.assertIn("TC", names)
        self.assertIn("CONFLUENCE", sigs[0].message)

    def test_confluence_silent_when_vwap_is_elsewhere(self):
        tc = Levels.from_previous(*PREV).cpr["tc"]
        snap = make_snap(flat(6, px=90.0), price=tc)      # vwap ~90, level ~102.7
        self.assertEqual(rule("confluence", tolerance_pct=0.002).evaluate(snap, History()), [])

    def test_rules_ignore_option_chains(self):
        """Pointing scalp rules at an option chain must be a silent no-op, not a crash."""
        chain = SyntheticProvider(cfg()).snapshot("SPY", 1, 3)
        for t in ("vwap_cross", "vwap_band", "cpr_breakout", "cpr_reject",
                  "narrow_cpr", "level_test", "confluence"):
            self.assertEqual(rule(t).evaluate(chain, History()), [], t)

    def test_rules_survive_missing_levels(self):
        snap = make_snap(flat(6), prev=None)
        for t in ("cpr_breakout", "narrow_cpr", "confluence"):
            self.assertEqual(rule(t).evaluate(snap, History()), [], t)

    def test_all_scalp_types_registered(self):
        available = rules_mod.available()
        for t in ("vwap_cross", "vwap_band", "cpr_breakout", "cpr_reject",
                  "narrow_cpr", "level_test", "confluence"):
            self.assertIn(t, available)
        self.assertEqual(len(rules_mod.build(rules_mod.default_specs("bars"))), 7)


class TestBarProviders(unittest.TestCase):
    def test_synthetic_bar_snapshot_assembles(self):
        p = SyntheticProvider(cfg(OPTIONS_SYNTH_STEP_S="300", OPTIONS_EXCHANGE="NSE"))
        for _ in range(70):
            p._now()
        snap = p.bar_snapshot("RELIANCE", "5m", 4)
        self.assertEqual(snap.exchange, "NSE")
        self.assertIsNotNone(snap.levels)
        self.assertIsNotNone(snap.vwap_value)
        self.assertGreater(len(snap.bars), 0)
        session = get_session("NSE")
        self.assertTrue(all(session.is_regular(b.ts) for b in snap.bars))
        self.assertEqual(len({session.key(b.ts) for b in snap.bars}), 1)   # one session only

    def test_levels_fall_back_to_intraday_without_daily_feed(self):
        """An adapter with no daily feed must still produce pivots from intraday sessions."""
        from options_desk.providers.base import Provider

        session = get_session("NSE")

        class NoDaily(Provider):
            name = "nodaily"

            def bars(self, symbol, interval="5m", lookback_days=5):
                out = []
                for day, base in ((dt.date(2026, 8, 24), 100.0), (DAY, 110.0)):
                    for i in range(4):
                        out.append(Bar(session.open_utc(day) + dt.timedelta(minutes=5 * i),
                                       base, base + 2, base - 2, base + 1, 500))
                return out

        snap = NoDaily(cfg(OPTIONS_EXCHANGE="NSE")).bar_snapshot("X", "5m", 5)
        self.assertAlmostEqual(snap.levels.prev_high, 102.0)
        self.assertAlmostEqual(snap.levels.prev_low, 98.0)
        self.assertAlmostEqual(snap.levels.prev_close, 101.0)

    def test_provider_without_bars_raises(self):
        from options_desk.providers.base import Provider
        with self.assertRaises(ProviderError):
            Provider(cfg()).bars("X")

    def test_yahoo_parses_chart(self):
        from options_desk.providers import yahoo as y
        session = get_session("US")
        t0 = int(session.open_utc(DAY).timestamp())
        payload = {"chart": {"result": [{
            "meta": {"symbol": "SPY", "exchangeTimezoneName": "America/New_York"},
            "timestamp": [t0, t0 + 300, t0 + 600],
            "indicators": {"quote": [{
                "open": [100.0, 101.0, None],       # third bar is a null-padded gap
                "high": [101.0, 102.0, None],
                "low": [99.5, 100.5, None],
                "close": [100.8, 101.5, None],
                "volume": [1000, 1200, None]}]}}]}}
        orig = y._http.get_json
        y._http.get_json = lambda url, params=None, headers=None, **kw: payload
        self.addCleanup(lambda: setattr(y._http, "get_json", orig))

        bars = y.YahooProvider(cfg(OPTIONS_EXCHANGE="US")).bars("SPY", "5m", 2)
        self.assertEqual(len(bars), 2)                       # null row dropped, not zero-filled
        self.assertAlmostEqual(bars[0].close, 100.8)
        self.assertAlmostEqual(bars[1].volume, 1200)

    def test_yahoo_reports_errors(self):
        from options_desk.providers import yahoo as y
        orig = y._http.get_json
        y._http.get_json = lambda *a, **k: {"chart": {"result": None,
                                                      "error": {"description": "No data found"}}}
        self.addCleanup(lambda: setattr(y._http, "get_json", orig))
        with self.assertRaises(ProviderError) as e:
            y.YahooProvider(cfg()).bars("NOPE")
        self.assertIn("No data found", str(e.exception))

    def test_yahoo_rejects_bad_interval(self):
        from options_desk.providers import yahoo as y
        with self.assertRaises(ProviderError):
            y.YahooProvider(cfg()).bars("SPY", "3m")

    def test_polygon_parses_aggregates(self):
        from options_desk.providers import polygon as poly
        t0 = int(get_session("US").open_utc(DAY).timestamp() * 1000)
        payload = {"results": [
            {"t": t0, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 5000},
            {"t": t0 + 300_000, "o": 100.5, "h": 102, "l": 100, "c": 101.5, "v": 6000}]}
        orig = poly._http.get_json
        poly._http.get_json = lambda url, params=None, headers=None, **kw: payload
        self.addCleanup(lambda: setattr(poly._http, "get_json", orig))
        bars = poly.PolygonProvider(cfg(POLYGON_API_KEY="x")).bars("SPY", "5m", 2)
        self.assertEqual(len(bars), 2)
        self.assertAlmostEqual(bars[1].close, 101.5)

    def test_tradier_parses_timesales(self):
        from options_desk.providers import tradier as tr
        t0 = get_session("US").open_utc(DAY).timestamp()
        payload = {"series": {"data": [
            {"timestamp": t0, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 900}]}}
        orig = tr._http.get_json
        tr._http.get_json = lambda url, params=None, headers=None, **kw: payload
        self.addCleanup(lambda: setattr(tr._http, "get_json", orig))
        bars = tr.TradierProvider(cfg(TRADIER_ACCESS_TOKEN="x",
                                      TRADIER_ENV="production")).bars("SPY", "5m", 2)
        self.assertEqual(len(bars), 1)
        self.assertAlmostEqual(bars[0].volume, 900)


class TestYahooOptionChain(unittest.TestCase):
    """
    Parser coverage for /v7/finance/options against the documented payload shape.

    NOTE: this was NOT verified against the live endpoint -- Yahoo is blocked by the egress
    policy of the environment this was written in. The GitHub Actions run is the first thing
    that talks to the real API, and it reports parse failures rather than hiding them.
    """

    EXP1 = int(dt.datetime(2026, 8, 28, 20, 0, tzinfo=UTC).timestamp())
    EXP2 = int(dt.datetime(2026, 9, 4, 20, 0, tzinfo=UTC).timestamp())

    def _contract(self, k, right, bid, ask, oi, vol, iv, expiration):
        return {"contractSymbol": f"SPY_{right}_{int(k)}", "strike": k,
                "lastPrice": (bid + ask) / 2, "bid": bid, "ask": ask,
                "volume": vol, "openInterest": oi, "impliedVolatility": iv,
                "expiration": expiration, "inTheMoney": False}

    def _payload(self, expiration):
        c = self._contract
        return {"optionChain": {"error": None, "result": [{
            "underlyingSymbol": "SPY",
            "expirationDates": [self.EXP1, self.EXP2],
            "quote": {"symbol": "SPY", "regularMarketPrice": 640.35},
            "options": [{
                "expirationDate": expiration,
                "calls": [c(635.0, "C", 7.10, 7.20, 5000, 900, 0.21, expiration),
                          c(640.0, "C", 4.10, 4.20, 12000, 3100, 0.19, expiration)],
                "puts": [c(635.0, "P", 2.00, 2.10, 9000, 1200, 0.22, expiration),
                         c(640.0, "P", 3.95, 4.05, 15000, 2800, 0.19, expiration)],
            }]}]}}

    def _patch(self, fn):
        from options_desk.providers import yahoo as y
        orig = y._http.get_json
        y._http.get_json = fn
        self.addCleanup(lambda: setattr(y._http, "get_json", orig))
        return y

    def test_parses_two_expiries(self):
        seen = []

        def fake(url, params=None, headers=None, **kw):
            epoch = (params or {}).get("date")
            seen.append(epoch)
            return self._payload(epoch or self.EXP1)

        y = self._patch(fake)
        snap = y.YahooProvider(cfg()).snapshot("SPY", expiry_limit=2, strike_window=0)
        self.assertEqual(len(seen), 2)                      # 1 default + 1 explicit expiry
        self.assertEqual(len(snap.expiries()), 2)
        self.assertEqual(snap.spot, 640.35)
        self.assertEqual(len(snap.quotes), 8)

    def test_greeks_are_solved_locally_not_copied(self):
        y = self._patch(lambda url, params=None, headers=None, **kw:
                        self._payload((params or {}).get("date") or self.EXP1))
        snap = y.YahooProvider(cfg()).snapshot("SPY", expiry_limit=1, strike_window=0)
        q = snap.get(snap.nearest_expiry(), 640.0, "C")
        self.assertAlmostEqual(q.vendor_iv, 0.19)           # kept for comparison
        self.assertIsNotNone(q.iv)
        self.assertIsNotNone(q.delta)
        self.assertGreater(q.delta, 0)

    def test_zero_quotes_are_absent_not_zero(self):
        """Yahoo writes 0 for 'no quote'; treating that as a price fabricates a mid."""
        from options_desk.providers.yahoo import _f
        self.assertIsNone(_f(0))
        self.assertIsNone(_f(0.0))
        self.assertIsNone(_f(None))
        self.assertEqual(_f(1.5), 1.5)

    def test_reports_api_error(self):
        y = self._patch(lambda *a, **k: {"optionChain": {
            "error": {"description": "Not Found"}, "result": None}})
        with self.assertRaises(ProviderError) as e:
            y.YahooProvider(cfg()).snapshot("NOPE")
        self.assertIn("Not Found", str(e.exception))

    def test_reports_symbol_without_options(self):
        y = self._patch(lambda *a, **k: {"optionChain": {"error": None, "result": []}})
        with self.assertRaises(ProviderError) as e:
            y.YahooProvider(cfg()).snapshot("RELIANCE.NS")
        self.assertIn("listed options", str(e.exception))

    def test_missing_spot_is_an_error_not_a_guess(self):
        payload = self._payload(self.EXP1)
        payload["optionChain"]["result"][0]["quote"] = {}
        y = self._patch(lambda *a, **k: payload)
        with self.assertRaises(ProviderError):
            y.YahooProvider(cfg()).snapshot("SPY")

    def test_malformed_rows_are_skipped(self):
        payload = self._payload(self.EXP1)
        payload["optionChain"]["result"][0]["options"][0]["calls"].append(
            {"strike": "not-a-number", "expiration": self.EXP1})
        y = self._patch(lambda *a, **k: payload)
        snap = y.YahooProvider(cfg()).snapshot("SPY", expiry_limit=1, strike_window=0)
        self.assertEqual(len(snap.quotes), 4)


class TestScalpEngineIntegration(unittest.TestCase):
    def test_engine_replays_bar_snapshots_deterministically(self):
        from options_desk.alerts import Dispatcher
        from options_desk.engine import Engine

        snaps = []
        session = get_session("NSE")
        for i in range(12):
            spec = flat(4 + i, px=100.0 + i * 0.4)
            s = make_snap(spec)
            s.ts = session.open_utc(DAY) + dt.timedelta(minutes=5 * (i + 4))
            snaps.append(s)

        runs = []
        for _ in range(2):
            eng = Engine(None, rules_mod.build(rules_mod.default_specs("bars")), Dispatcher())
            eng.replay([snapshot_from_dict(s.to_dict()) for s in snaps])
            runs.append(eng.stats["by_rule"])
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(sum(runs[0].values()), eng.stats["signals"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
