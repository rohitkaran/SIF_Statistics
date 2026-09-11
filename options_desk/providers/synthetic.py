#!/usr/bin/env python3
"""
synthetic.py  --  A self-contained fake market. No credentials, no network. stdlib only.

This exists so the whole desk -- rules, engine, alerts, recorder, dashboard, backtester --
is runnable and testable on day one, before any vendor key is in place, and in CI where
there is no market data and no egress. It is the default provider for exactly that reason.

The prices are NOT a market simulation and must never be traded off. They are a plausible
surface (GBM spot, smile-shaped vol, widening wings) whose only job is to exercise the code.
"""

import datetime as dt
import math
import random

from .base import Provider, ProviderError
from ..bars import Bar, get_session
from ..models import ChainSnapshot, Contract, Quote


class SyntheticProvider(Provider):
    name = "synthetic"

    # Rough starting marks so the demo chain looks familiar.
    SPOTS = {"SPY": 640.0, "QQQ": 585.0, "IWM": 240.0, "AAPL": 255.0, "NVDA": 190.0}

    def __init__(self, cfg, seed=None):
        super().__init__(cfg)
        # Seeded by default => deterministic tests. Pass seed=None explicitly for variety.
        self._rng = random.Random(7 if seed is None else seed)
        self._spot = {}
        self._base_vol = {}
        # Virtual clock. With OPTIONS_SYNTH_STEP_S=60 each snapshot is stamped 60s after the
        # last, so a few hundred ticks cover a whole session instantly. Without it the rules'
        # multi-minute windows can never be covered in a test run, and nothing ever fires.
        self.step_s = cfg.float("OPTIONS_SYNTH_STEP_S", 0.0)
        self._clock = None
        self._bar_state = {}          # (symbol, interval) -> accumulated bar history

    def _now(self):
        if self.step_s <= 0:
            return dt.datetime.now(dt.timezone.utc)
        if self._clock is None:
            self._clock = dt.datetime.now(dt.timezone.utc)
        else:
            self._clock += dt.timedelta(seconds=self.step_s)
        return self._clock

    def _walk(self, underlying):
        """
        Advance this underlying one GBM step per call.

        Per-tick vol scales with sqrt(elapsed) so a 60s virtual step moves about as much as
        60 one-second ticks would -- otherwise accelerated runs look implausibly calm.
        """
        s = self._spot.get(underlying)
        if s is None:
            s = self.SPOTS.get(underlying, 100.0)
            self._base_vol[underlying] = self._rng.uniform(0.14, 0.28)
        # 8bp per second annualises to roughly 20% vol over a 6.5h session, which is about
        # where SPY actually sits. Scaled by sqrt(elapsed) so accelerated and real-time runs
        # move at the same rate per unit of simulated time.
        sigma = 0.00008 * math.sqrt(max(self.step_s, 1.0))
        s *= math.exp(-0.5 * sigma ** 2 + sigma * self._rng.gauss(0, 1))
        self._spot[underlying] = s
        return s

    def _drift_vol(self, underlying):
        """Mean-reverting wander in the base vol level, so IV rules have real signal to find."""
        v = self._base_vol.get(underlying, 0.20)
        pull = 0.02 * (0.20 - v)
        # ~0.15 vol points per simulated minute: enough for the IV rules to have something
        # real to find, without the implausible 3-points-a-minute a larger shock produces.
        shock = 0.0002 * math.sqrt(max(self.step_s, 1.0)) * self._rng.gauss(0, 1)
        self._base_vol[underlying] = max(0.05, min(1.0, v + pull + shock))

    def _smile(self, underlying, strike, spot, t):
        """Downward-sloping skew: puts bid over calls, wings over ATM, flattening with time."""
        base = self._base_vol.get(underlying, 0.20)
        m = math.log(strike / spot) if spot > 0 and strike > 0 else 0.0
        damp = 1.0 / math.sqrt(max(t, 1 / 365))
        return max(0.05, base - 0.35 * m * damp + 1.4 * m * m * damp)

    def snapshot(self, underlying, expiry_limit=3, strike_window=10):
        from .. import greeks as bs

        now = self._now()
        # Round BEFORE pricing, not after. The snapshot stores a 2dp spot, so pricing the
        # chain off the unrounded value left deep-ITM contracts marked fractionally under the
        # floor implied by the stored spot -- and their IV then came back unsolvable.
        spot = round(self._walk(underlying), 2)
        self._drift_vol(underlying)
        step = 5.0 if spot > 300 else 2.5 if spot > 100 else 1.0
        atm = round(spot / step) * step
        window = strike_window or 12

        quotes = []
        for exp in _weekly_expiries(now.date(), expiry_limit):
            t = max((dt.datetime(exp.year, exp.month, exp.day, 20, tzinfo=dt.timezone.utc)
                     - now).total_seconds() / (365 * 24 * 3600), 1 / (365 * 24))
            for i in range(-window, window + 1):
                k = round(atm + i * step, 2)
                if k <= 0:
                    continue
                vol = self._smile(underlying, k, spot, t)
                for right in ("C", "P"):
                    theo = bs.price(spot, k, t, vol, right, self.rate, self.dividend)
                    # Spread widens away from ATM and on cheap contracts, as in a real book.
                    moneyness = abs(k - spot) / spot
                    half = max(0.01, theo * (0.01 + 1.2 * moneyness)) / 2
                    # Quote in penny increments rounded OUTWARD (bid down, ask up), as an
                    # exchange does. Rounding both to nearest could drag a deep-ITM mid below
                    # the model's own floor, which then makes the IV unsolvable -- a generator
                    # artifact that looked like a solver bug.
                    bid = math.floor(max(0.0, theo - half) * 100) / 100
                    ask = math.ceil((theo + half) * 100) / 100
                    depth = math.exp(-((k - spot) / (0.06 * spot)) ** 2)   # OI/vol taper
                    quotes.append(Quote(
                        contract=Contract(underlying, exp, k, right,
                                          Contract(underlying, exp, k, right).occ()),
                        bid=bid, ask=ask, last=round(theo, 2),
                        volume=int(depth * self._rng.uniform(200, 4000)),
                        open_interest=int(depth * self._rng.uniform(500, 20000)),
                        vendor_iv=round(vol, 4),
                    ))

        snap = ChainSnapshot(underlying, spot, now, quotes, self.name,
                             self.rate, self.dividend)
        return snap.enrich()


def _weekly_expiries(today, count):
    """Next `count` Fridays, which is close enough to a real weekly expiry ladder."""
    out, d = [], today
    while len(out) < count:
        d += dt.timedelta(days=1)
        if d.weekday() == 4:
            out.append(d)
    return out


# --- intraday bars ------------------------------------------------------------------

def parse_interval(interval):
    """'1m' / '5m' / '15m' / '1h' -> minutes."""
    txt = str(interval).strip().lower()
    try:
        if txt.endswith("m"):
            return max(1, int(txt[:-1]))
        if txt.endswith("h"):
            return max(1, int(txt[:-1]) * 60)
        return max(1, int(txt))
    except ValueError:
        raise ProviderError(f"unrecognised bar interval {interval!r} (use 1m, 5m, 15m, 1h)")


def next_trading_day(day):
    """Next weekday. No holiday calendar -- synthetic data does not need one."""
    d = day + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def prev_trading_day(day):
    d = day - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _intraday_volume_shape(frac):
    """
    Classic U-shape: heavy at the open, thin midday, heavy into the close.

    Without this every bar carries the same volume, VWAP degenerates into a plain average of
    typical prices, and the relative-volume rule has nothing to detect.
    """
    return 0.4 + 2.2 * math.exp(-((frac - 0.02) / 0.10) ** 2) + 1.3 * math.exp(-((frac - 1.0) / 0.12) ** 2)


class _SyntheticBars:
    """Mixin holding the bar-generation half of SyntheticProvider."""

    def bars(self, symbol, interval="5m", lookback_days=5):
        symbol = symbol.upper()
        session = get_session(self.exchange)
        step = parse_interval(interval)
        now = self._now()
        key = (symbol, interval)

        st = self._bar_state.get(key)
        if st is None:
            day = session.key(now)
            for _ in range(max(1, lookback_days) - 1):
                day = prev_trading_day(day)
            st = {"bars": [], "cursor": session.open_utc(day),
                  "px": self.SPOTS.get(symbol, 100.0)}
            self._bar_state[key] = st

        # Extend the history up to `now`, one bar at a time, rolling into the next session
        # when the cursor passes the close. Bars accumulate rather than being regenerated, so
        # a streaming caller sees a VWAP that builds through the session exactly as a real
        # feed would.
        guard = 0
        while st["cursor"] + dt.timedelta(minutes=step) <= now and guard < 20_000:
            guard += 1
            day = session.key(st["cursor"])
            if st["cursor"] >= session.close_utc(day):
                nxt = next_trading_day(day)
                st["cursor"] = session.open_utc(nxt)
                st["px"] *= math.exp(0.004 * self._rng.gauss(0, 1))     # overnight gap
                continue
            st["bars"].append(self._make_bar(st, session, day, step))

        if not st["bars"]:
            raise ProviderError(f"{symbol}: no bars generated (virtual clock has not advanced "
                                "past one bar interval yet)")
        return list(st["bars"])

    def _make_bar(self, st, session, day, step):
        o = st["px"]
        sigma = 0.0009 * math.sqrt(step)
        c = o * math.exp(-0.5 * sigma ** 2 + sigma * self._rng.gauss(0, 1))
        wick = abs(o) * sigma * abs(self._rng.gauss(0, 1)) * 0.8
        hi, lo = max(o, c) + wick, min(o, c) - wick
        opened = session.open_utc(day)
        span = (session.close_utc(day) - opened).total_seconds() / 60.0
        frac = max(0.0, min(1.0, (st["cursor"] - opened).total_seconds() / 60.0 / span))
        vol = _intraday_volume_shape(frac) * self._rng.uniform(6_000, 14_000) * step
        bar = Bar(st["cursor"], round(o, 2), round(hi, 2), round(lo, 2), round(c, 2), round(vol))
        st["px"] = c
        st["cursor"] += dt.timedelta(minutes=step)
        return bar

    def daily_bars(self, symbol, days=10):
        """Aggregate completed synthetic sessions into daily bars."""
        from ..bars import BarSeries
        session = get_session(self.exchange)
        series = BarSeries(self.bars(symbol, "5m", max(days, 3)), session)
        out = []
        for day in series.session_dates():
            agg = BarSeries.ohlc(series.session_bars(day))
            if agg:
                o, h, l, c, v = agg
                out.append(Bar(session.open_utc(day), o, h, l, c, v))
        return out[-days:]


# Fold the bar half into the provider.
SyntheticProvider.__bases__ = (_SyntheticBars,) + SyntheticProvider.__bases__
