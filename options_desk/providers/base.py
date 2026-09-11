#!/usr/bin/env python3
"""
base.py  --  The contract every market-data adapter implements. stdlib only.

A provider's only job is to turn a vendor's wire format into ChainSnapshot objects. It does
NOT compute greeks (models.ChainSnapshot.enrich does, identically for all providers) and it
does NOT place orders -- this desk is data + signals only, by design.

To add a vendor: subclass Provider, implement snapshot(), register it in providers/__init__.py.
`stream()` has a working default that polls snapshot(), so a new adapter is one method.
"""

import sys
import time


class ProviderError(RuntimeError):
    """Vendor-side failure (auth, rate limit, malformed payload) worth surfacing to the user."""


class Provider:
    name = "base"
    #: True when the vendor pushes updates; False when stream() is really a poll loop.
    realtime_push = False

    def __init__(self, cfg):
        self.cfg = cfg
        self.rate = cfg.float("OPTIONS_RISK_FREE", 0.04)
        self.dividend = cfg.float("OPTIONS_DIVIDEND", 0.0)
        self.exchange = cfg.str("OPTIONS_EXCHANGE", "US")

    def snapshot(self, underlying, expiry_limit=3, strike_window=10):
        """
        Return one enriched ChainSnapshot.

        expiry_limit  -- how many near expiries to pull (chains are huge; most rules use 1-3).
        strike_window -- strikes to keep either side of ATM (0 = keep the whole chain).

        Adapters that only carry equities (see yahoo) leave this raising and implement bars().
        """
        raise ProviderError(f"{self.name} provides no option chains")

    # -- intraday bars (scalping side) ---------------------------------------------

    def bars(self, symbol, interval="5m", lookback_days=5):
        """Intraday OHLCV bars, oldest first. Adapters that have no bar feed raise."""
        raise ProviderError(f"{self.name} provides no intraday bars")

    def daily_bars(self, symbol, days=10):
        """Daily OHLCV bars, oldest first. Used for pivots/CPR from the previous session."""
        raise ProviderError(f"{self.name} provides no daily bars")

    def bar_snapshot(self, symbol, interval="5m", lookback_days=5):
        """
        Assemble a BarSnapshot: current-session bars, VWAP anchored to this session, and
        pivots/CPR from the previous session.

        Shared here so every adapter derives levels identically -- an adapter only has to
        return raw bars.
        """
        from ..bars import BarSeries, get_session
        from ..levels import Levels, Vwap
        from ..models import BarSnapshot

        session = get_session(self.exchange)
        raw = self.bars(symbol, interval, lookback_days)
        if not raw:
            raise ProviderError(f"no intraday bars for {symbol}")

        # Extended-hours prints would corrupt a VWAP, so they are dropped before anything else.
        series = BarSeries(raw, session).regular_only()
        if not len(series):
            raise ProviderError(
                f"{symbol}: no regular-hours bars returned "
                f"(is {symbol!r} listed on {session.name}? check OPTIONS_EXCHANGE)")

        today = series.session_bars()
        current = BarSeries(today, session)
        levels = self._levels_for(symbol, series, session)
        vwap = Vwap(session).feed(current)
        last = current.last

        return BarSnapshot(
            underlying=symbol.upper(), price=last.close, ts=last.ts,
            bars=current, levels=levels, vwap=vwap, provider=self.name,
            exchange=session.name, interval=interval)

    def _levels_for(self, symbol, series, session):
        """
        Previous-session OHLC for pivots/CPR.

        Daily bars are the authority -- that is what the pivot convention is defined on, and
        an intraday lookback can easily start mid-session and understate yesterday's range.
        Intraday is only the fallback when the adapter has no daily feed.
        """
        from ..bars import BarSeries
        from ..levels import Levels

        today = session.key(series.last.ts)
        try:
            daily = self.daily_bars(symbol, days=10)
            prior = [b for b in daily if session.key(b.ts) < today]
            if prior:
                b = prior[-1]
                return Levels.from_previous(b.high, b.low, b.close)
        except ProviderError:
            pass                                  # no daily feed; fall through to intraday

        prev = series.previous_session_bars()
        agg = BarSeries.ohlc(prev)
        if not agg:
            return None                           # first recorded session: no levels yet
        _o, h, l, c, _v = agg
        return Levels.from_previous(h, l, c)

    def stream_bars(self, symbols, interval="5m", poll_s=5.0, stop=None):
        """Yield (symbol, BarSnapshot) on a poll loop, same failure isolation as stream()."""
        while not (stop and stop.is_set()):
            cycle = time.monotonic()
            for sym in symbols:
                if stop and stop.is_set():
                    break
                try:
                    yield sym, self.bar_snapshot(sym, interval)
                except ProviderError as e:
                    sys.stderr.write(f"[{self.name}] {sym}: {e}\n")
                except Exception as e:                   # noqa: BLE001 - keep the desk alive
                    sys.stderr.write(f"[{self.name}] {sym}: unexpected "
                                     f"{type(e).__name__}: {e}\n")
            if (delay := poll_s - (time.monotonic() - cycle)) > 0:
                if stop:
                    stop.wait(delay)
                else:
                    time.sleep(delay)

    def stream(self, underlyings, interval=5.0, stop=None):
        """
        Yield (underlying, ChainSnapshot) continuously.

        Default implementation polls snapshot() on `interval`. Vendors with a real push feed
        override this. A failed poll is logged and skipped rather than killing the loop --
        a dropped tick must never take down a running desk.
        """
        while not (stop and stop.is_set()):
            cycle = time.monotonic()
            for sym in underlyings:
                if stop and stop.is_set():
                    break
                try:
                    yield sym, self.snapshot(sym)
                except ProviderError as e:
                    sys.stderr.write(f"[{self.name}] {sym}: {e}\n")
                except Exception as e:                       # noqa: BLE001 - keep the desk alive
                    sys.stderr.write(f"[{self.name}] {sym}: unexpected {type(e).__name__}: {e}\n")
            slept = time.monotonic() - cycle
            if (delay := interval - slept) > 0:
                if stop:
                    stop.wait(delay)      # interruptible, so Ctrl-C is instant
                else:
                    time.sleep(delay)

    # -- helpers shared by concrete adapters ---------------------------------------

    def _window(self, quotes, spot, strike_window):
        """Trim a chain to `strike_window` strikes either side of spot, per expiry."""
        if not strike_window:
            return quotes
        keep, by_exp = [], {}
        for q in quotes:
            by_exp.setdefault(q.contract.expiry, []).append(q)
        for exp, group in by_exp.items():
            ks = sorted({q.contract.strike for q in group})
            if not ks:
                continue
            atm = min(range(len(ks)), key=lambda i: abs(ks[i] - spot))
            lo, hi = max(0, atm - strike_window), min(len(ks), atm + strike_window + 1)
            allowed = set(ks[lo:hi])
            keep.extend(q for q in group if q.contract.strike in allowed)
        return keep
