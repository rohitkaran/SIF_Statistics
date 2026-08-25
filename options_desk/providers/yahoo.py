#!/usr/bin/env python3
"""
yahoo.py  --  Yahoo Finance chart adapter: intraday + daily bars, no credentials. stdlib only.

This is the zero-setup path for the scalping side, and the only bundled adapter that covers
NSE/BSE symbols (suffix `.NS` / `.BO`, e.g. RELIANCE.NS) as well as US tickers. The same
endpoint is already used by fetch_benchmark.py elsewhere in this repo.

Covers BOTH sides: `/v8/finance/chart` for intraday bars and `/v7/finance/options` for option
chains, so the whole desk runs with no credentials at all.

Caveats worth knowing before trading off it:
  * Quotes are delayed for many exchanges (commonly ~15 min on NSE) and Yahoo publishes no SLA.
  * 1m bars are only retained for about 7 days.
  * It is an undocumented endpoint that can change without notice.
For anything that has to be dependable, use polygon or tradier and keep this for convenience.
"""

import datetime as dt
import sys

from . import _http
from .base import Provider, ProviderError
from ..bars import Bar

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
OPTIONS = "https://query1.finance.yahoo.com/v7/finance/options/"

# Yahoo's accepted interval strings, and the widest range each one supports.
_INTERVALS = {"1m": "7d", "2m": "60d", "5m": "60d", "15m": "60d",
              "30m": "60d", "60m": "730d", "1h": "730d", "1d": "1y"}


class YahooProvider(Provider):
    name = "yahoo"

    def bars(self, symbol, interval="5m", lookback_days=5):
        iv = self._interval(interval)
        return self._fetch(symbol, iv, self._range(iv, lookback_days))

    def daily_bars(self, symbol, days=10):
        return self._fetch(symbol, "1d", f"{max(days * 2, 10)}d")[-days:]

    # -- wire -> model -------------------------------------------------------------

    def _interval(self, interval):
        iv = str(interval).strip().lower()
        if iv == "1h":
            iv = "60m"
        if iv not in _INTERVALS:
            raise ProviderError(f"yahoo does not serve {interval!r}; "
                                f"use one of {', '.join(sorted(_INTERVALS))}")
        return iv

    def _range(self, iv, lookback_days):
        """Clamp the requested lookback to what Yahoo actually retains for that interval."""
        cap = int(_INTERVALS[iv].rstrip("dy") or 60)
        return f"{max(1, min(int(lookback_days), cap))}d"

    def _fetch(self, symbol, interval, rng):
        j = _http.get_json(BASE + symbol.upper(), {"interval": interval, "range": rng,
                                                   "includePrePost": "false"})
        chart = j.get("chart") or {}
        if chart.get("error"):
            err = chart["error"]
            raise ProviderError(f"{symbol}: {err.get('description') or err.get('code')}")
        results = chart.get("result") or []
        if not results:
            raise ProviderError(f"{symbol}: no chart data (unknown ticker? "
                                "NSE symbols need a .NS suffix, e.g. RELIANCE.NS)")

        res = results[0]
        stamps = res.get("timestamp") or []
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        o, h, l, c = (quote.get(k) or [] for k in ("open", "high", "low", "close"))
        v = quote.get("volume") or []

        out = []
        for i, ts in enumerate(stamps):
            # Yahoo pads every array to the same length and fills gaps with null. A bar with
            # any missing leg is unusable -- dropped, not zero-filled, which would fabricate
            # a print at 0.00 and wreck both the range and the VWAP.
            try:
                bar = Bar(dt.datetime.fromtimestamp(ts, dt.timezone.utc),
                          float(o[i]), float(h[i]), float(l[i]), float(c[i]),
                          float(v[i]) if i < len(v) and v[i] is not None else 0.0)
            except (IndexError, TypeError, ValueError):
                continue
            out.append(bar)

        if not out:
            raise ProviderError(f"{symbol}: chart returned no usable bars for {interval}/{rng}")
        return out


    # -- option chains -------------------------------------------------------------

    def snapshot(self, underlying, expiry_limit=3, strike_window=10):
        """
        Build a ChainSnapshot from /v7/finance/options.

        Yahoo returns one expiry per call plus the full list of expiration dates, so this is
        1 + (expiry_limit - 1) requests. The first response also carries the underlying quote,
        which saves a separate lookup for spot.
        """
        from ..models import ChainSnapshot, Contract, Quote

        underlying = underlying.upper()
        first = self._chain_call(underlying)
        spot = self._spot_from(first, underlying)

        expiries = [e for e in (first.get("expirationDates") or [])]
        quotes = list(self._contracts(first, underlying))

        # The first payload already contains the nearest expiry; fetch any others we still want.
        for epoch in expiries[1:max(1, expiry_limit)]:
            try:
                more = self._chain_call(underlying, epoch)
            except ProviderError as e:
                sys.stderr.write(f"[yahoo] {underlying}: skipping one expiry: {e}\n")
                continue
            quotes.extend(self._contracts(more, underlying))

        if not quotes:
            raise ProviderError(f"{underlying}: option chain came back empty")

        snap = ChainSnapshot(underlying, spot, dt.datetime.now(dt.timezone.utc),
                             self._window(quotes, spot, strike_window), self.name,
                             self.rate, self.dividend)
        return snap.enrich()

    def _chain_call(self, underlying, epoch=None):
        j = _http.get_json(OPTIONS + underlying, {"date": epoch} if epoch else None)
        chain = j.get("optionChain") or {}
        if chain.get("error"):
            err = chain["error"]
            raise ProviderError(f"{underlying}: {err.get('description') or err.get('code')}")
        results = chain.get("result") or []
        if not results:
            raise ProviderError(f"{underlying}: no option chain "
                                "(does this symbol have listed options?)")
        return results[0]

    def _spot_from(self, result, underlying):
        q = result.get("quote") or {}
        for key in ("regularMarketPrice", "postMarketPrice", "preMarketPrice",
                    "regularMarketPreviousClose"):
            px = q.get(key)
            if px:
                return float(px)
        raise ProviderError(f"{underlying}: no underlying price in the option chain payload")

    def _contracts(self, result, underlying):
        from ..models import Contract, Quote

        for block in (result.get("options") or []):
            for side, right in (("calls", "C"), ("puts", "P")):
                for o in (block.get(side) or []):
                    try:
                        strike = float(o["strike"])
                        expiry = dt.datetime.fromtimestamp(
                            float(o["expiration"]), dt.timezone.utc).date()
                    except (KeyError, TypeError, ValueError, OSError):
                        continue                     # malformed row; skip, never guess
                    yield Quote(
                        contract=Contract(underlying, expiry, strike, right,
                                          o.get("contractSymbol", "")),
                        bid=_f(o.get("bid")), ask=_f(o.get("ask")),
                        last=_f(o.get("lastPrice")),
                        volume=_i(o.get("volume")),
                        open_interest=_i(o.get("openInterest")),
                        vendor_iv=_f(o.get("impliedVolatility")))


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # Yahoo uses 0 for "no quote" on illiquid contracts; a real bid of exactly 0.00 and an
    # absent one are indistinguishable here, and treating absent as 0 would fabricate a mid.
    return f if f else None


def _i(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
