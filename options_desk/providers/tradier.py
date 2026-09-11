#!/usr/bin/env python3
"""
tradier.py  --  Tradier Market Data adapter. stdlib only.

Two calls per snapshot: /markets/options/expirations to find the ladder, then
/markets/options/chains?greeks=true per expiry. Tradier returns vendor greeks (ORATS-derived)
which we keep in `vendor_iv` for comparison, but the engine still uses locally solved IV so
every provider is measured the same way.

Sandbox keys return DELAYED data on a 15-minute lag. That is fine for wiring things up and
useless for a live desk -- set TRADIER_ENV=production once you have a brokerage token.

Credentials (.env):  TRADIER_ACCESS_TOKEN=...   TRADIER_ENV=sandbox|production
"""

import datetime as dt
import sys

from . import _http
from .base import Provider, ProviderError
from ..bars import Bar
from ..models import ChainSnapshot, Contract, Quote

HOSTS = {"production": "https://api.tradier.com", "sandbox": "https://sandbox.tradier.com"}


class TradierProvider(Provider):
    name = "tradier"

    def __init__(self, cfg):
        super().__init__(cfg)
        (self.token,) = cfg.require("TRADIER_ACCESS_TOKEN")
        env = (cfg.str("TRADIER_ENV", "sandbox") or "sandbox").lower()
        if env not in HOSTS:
            raise SystemExit(f"[tradier] TRADIER_ENV must be one of {sorted(HOSTS)}, got {env!r}")
        self.env, self.base = env, HOSTS[env]
        if env == "sandbox":
            sys.stderr.write("[tradier] sandbox: quotes are ~15 min DELAYED, not live.\n")

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def snapshot(self, underlying, expiry_limit=3, strike_window=10):
        underlying = underlying.upper()
        spot = self._spot(underlying)
        quotes = []
        for exp in self._expirations(underlying)[:expiry_limit]:
            quotes.extend(self._chain(underlying, exp))
        if not quotes:
            raise ProviderError(f"no option chain returned for {underlying}")

        snap = ChainSnapshot(underlying, spot, dt.datetime.now(dt.timezone.utc),
                             self._window(quotes, spot, strike_window), self.name,
                             self.rate, self.dividend)
        return snap.enrich()

    # -- wire -> model -------------------------------------------------------------

    def _spot(self, underlying):
        j = _http.get_json(f"{self.base}/v1/markets/quotes",
                           {"symbols": underlying}, self._headers)
        q = _one((j.get("quotes") or {}).get("quote"))
        px = (q or {}).get("last") or (q or {}).get("close")
        if not px:
            raise ProviderError(f"no quote for underlying {underlying}")
        return float(px)

    def _expirations(self, underlying):
        j = _http.get_json(f"{self.base}/v1/markets/options/expirations",
                           {"symbol": underlying, "includeAllRoots": "true"}, self._headers)
        dates = (j.get("expirations") or {}).get("date") or []
        if isinstance(dates, str):
            dates = [dates]
        out = []
        for d in dates:
            try:
                out.append(dt.date.fromisoformat(d))
            except (TypeError, ValueError):
                continue
        return sorted(out)

    def _chain(self, underlying, expiry):
        j = _http.get_json(f"{self.base}/v1/markets/options/chains",
                           {"symbol": underlying, "expiration": expiry.isoformat(),
                            "greeks": "true"}, self._headers)
        raw = (j.get("options") or {}).get("option") or []
        if isinstance(raw, dict):
            raw = [raw]
        out = []
        for o in raw:
            try:
                strike = float(o["strike"])
                right = "C" if str(o.get("option_type", "")).lower().startswith("c") else "P"
            except (KeyError, TypeError, ValueError):
                continue
            g = o.get("greeks") or {}
            out.append(Quote(
                contract=Contract(underlying, expiry, strike, right, o.get("symbol", "")),
                bid=_f(o.get("bid")), ask=_f(o.get("ask")), last=_f(o.get("last")),
                volume=_i(o.get("volume")), open_interest=_i(o.get("open_interest")),
                vendor_iv=_f(g.get("mid_iv") or g.get("smv_vol")),
            ))
        return out


class _TradierBars:
    """Bar half of the Tradier adapter (mixed into TradierProvider below)."""

    #: Tradier names its intraday intervals differently from everyone else.
    _IV = {"1m": "1min", "5m": "5min", "15m": "15min"}

    def bars(self, symbol, interval="5m", lookback_days=5):
        iv = self._IV.get(str(interval).strip().lower())
        if iv is None:
            raise ProviderError(f"tradier serves only {', '.join(self._IV)}; got {interval!r}")
        start = dt.date.today() - dt.timedelta(days=max(1, lookback_days))
        j = _http.get_json(f"{self.base}/v1/markets/timesales",
                           {"symbol": symbol.upper(), "interval": iv,
                            "start": start.isoformat(),
                            "end": dt.date.today().isoformat(),
                            "session_filter": "open"}, self._headers)
        rows = (j.get("series") or {}).get("data") or []
        if isinstance(rows, dict):
            rows = [rows]
        out = []
        for r in rows:
            try:
                # `timestamp` is epoch seconds; the `time` field is exchange-local and naive,
                # so it is deliberately ignored.
                out.append(Bar(dt.datetime.fromtimestamp(float(r["timestamp"]), dt.timezone.utc),
                               float(r["open"]), float(r["high"]), float(r["low"]),
                               float(r["close"]), float(r.get("volume") or 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
        if not out:
            raise ProviderError(f"no {interval} bars for {symbol}")
        return out

    def daily_bars(self, symbol, days=10):
        start = dt.date.today() - dt.timedelta(days=days * 2 + 5)
        j = _http.get_json(f"{self.base}/v1/markets/history",
                           {"symbol": symbol.upper(), "interval": "daily",
                            "start": start.isoformat(),
                            "end": dt.date.today().isoformat()}, self._headers)
        rows = (j.get("history") or {}).get("day") or []
        if isinstance(rows, dict):
            rows = [rows]
        out = []
        for r in rows:
            try:
                day = dt.date.fromisoformat(r["date"])
                out.append(Bar(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc),
                               float(r["open"]), float(r["high"]), float(r["low"]),
                               float(r["close"]), float(r.get("volume") or 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
        if not out:
            raise ProviderError(f"no daily bars for {symbol}")
        return out[-days:]


TradierProvider.__bases__ = (_TradierBars,) + TradierProvider.__bases__


def _one(v):
    """Tradier collapses single-element arrays to a bare object; normalise both shapes."""
    return v[0] if isinstance(v, list) and v else (v if isinstance(v, dict) else None)


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
