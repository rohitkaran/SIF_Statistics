#!/usr/bin/env python3
"""
polygon.py  --  Polygon.io options adapter (real-time OPRA chains). stdlib only.

Endpoint: GET /v3/snapshot/options/{underlying} -- one call returns the chain with quotes,
open interest and the underlying's own price, which is why it is preferred over assembling
/v3/reference/options/contracts + per-contract quotes.

Entitlement note: the snapshot endpoint is on every tier, but the `last_quote` NBBO inside it
requires an options data plan. On a free key the quote block comes back absent and only
`day.close` is populated -- the adapter degrades to close-based marks and says so once, rather
than silently producing greeks off stale end-of-day prices.

Credentials (.env):  POLYGON_API_KEY=...
"""

import datetime as dt
import sys

from . import _http
from .base import Provider, ProviderError
from ..bars import Bar
from ..models import ChainSnapshot, Contract, Quote

BASE = "https://api.polygon.io"
PAGE_LIMIT = 250          # vendor maximum per page
MAX_PAGES = 20            # hard stop so a runaway next_url cannot spin forever


class PolygonProvider(Provider):
    name = "polygon"

    def __init__(self, cfg):
        super().__init__(cfg)
        (self.api_key,) = cfg.require("POLYGON_API_KEY")
        self._warned_no_quotes = False

    def snapshot(self, underlying, expiry_limit=3, strike_window=10):
        underlying = underlying.upper()
        rows = self._fetch_all(underlying, expiry_limit)
        if not rows:
            raise ProviderError(f"no contracts returned for {underlying} "
                                "(unknown symbol, or key not entitled to options data)")

        spot = self._spot(rows, underlying)
        quotes, missing_quotes = [], 0
        for r in rows:
            q = self._to_quote(r, underlying)
            if q is None:
                continue
            if q.bid is None and q.ask is None:
                missing_quotes += 1
            quotes.append(q)

        if missing_quotes == len(quotes) and not self._warned_no_quotes:
            self._warned_no_quotes = True
            sys.stderr.write(
                "[polygon] no NBBO in snapshot -- falling back to daily close for marks. "
                "Real-time greeks need an options data plan on this key.\n")

        # Keep only the nearest `expiry_limit` expiries, then trim strikes around spot.
        keep = set(sorted({q.contract.expiry for q in quotes})[:expiry_limit])
        quotes = self._window([q for q in quotes if q.contract.expiry in keep],
                              spot, strike_window)

        snap = ChainSnapshot(underlying, spot, dt.datetime.now(dt.timezone.utc),
                             quotes, self.name, self.rate, self.dividend)
        return snap.enrich()

    # -- wire -> model -------------------------------------------------------------

    def _fetch_all(self, underlying, expiry_limit):
        """Page through the snapshot endpoint, stopping once we have enough expiries."""
        url = f"{BASE}/v3/snapshot/options/{underlying}"
        params = {
            "limit": PAGE_LIMIT,
            "expiration_date.gte": dt.date.today().isoformat(),
            "sort": "expiration_date",
            "order": "asc",
            "apiKey": self.api_key,
        }
        rows, seen_expiries = [], set()
        for _ in range(MAX_PAGES):
            j = _http.get_json(url, params)
            if j.get("status") == "ERROR":
                raise ProviderError(j.get("error") or j.get("message") or "polygon error")
            batch = j.get("results") or []
            rows.extend(batch)
            for r in batch:
                exp = (r.get("details") or {}).get("expiration_date")
                if exp:
                    seen_expiries.add(exp)
            nxt = j.get("next_url")
            # Stop as soon as a later expiry than we need has appeared -- the feed is sorted,
            # so anything past that boundary is contracts we would only discard.
            if not nxt or len(seen_expiries) > expiry_limit:
                break
            url, params = nxt, {"apiKey": self.api_key}
        return rows

    def _spot(self, rows, underlying):
        for r in rows:
            ua = r.get("underlying_asset") or {}
            px = ua.get("price") or ua.get("last_updated_price")
            if px:
                return float(px)
        # Snapshot omits the underlying price on some tiers; fall back to the equity endpoint.
        j = _http.get_json(f"{BASE}/v2/aggs/ticker/{underlying}/prev", {"apiKey": self.api_key})
        res = (j.get("results") or [{}])[0]
        if not res.get("c"):
            raise ProviderError(f"could not determine spot price for {underlying}")
        return float(res["c"])

    def _to_quote(self, r, underlying):
        d = r.get("details") or {}
        try:
            expiry = dt.date.fromisoformat(d["expiration_date"])
            strike = float(d["strike_price"])
            right = "C" if str(d.get("contract_type", "")).lower().startswith("c") else "P"
        except (KeyError, TypeError, ValueError):
            return None                                   # malformed row; skip, don't crash

        lq, day, trade = r.get("last_quote") or {}, r.get("day") or {}, r.get("last_trade") or {}
        bid, ask = _f(lq.get("bid")), _f(lq.get("ask"))
        last = _f(trade.get("price")) or _f(day.get("close"))
        g = r.get("greeks") or {}

        return Quote(
            contract=Contract(underlying, expiry, strike, right, d.get("ticker", "")),
            bid=bid, ask=ask, last=last,
            volume=_i(day.get("volume")),
            open_interest=_i(r.get("open_interest")),
            vendor_iv=_f(r.get("implied_volatility")),
        ) if (bid or ask or last) else Quote(
            contract=Contract(underlying, expiry, strike, right, d.get("ticker", "")),
            open_interest=_i(r.get("open_interest")),
            vendor_iv=_f(r.get("implied_volatility")),
        )


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


class _PolygonBars:
    """Bar half of the Polygon adapter (mixed into PolygonProvider below)."""

    def bars(self, symbol, interval="5m", lookback_days=5):
        mult, span = _timespan(interval)
        return self._aggs(symbol, mult, span, lookback_days)

    def daily_bars(self, symbol, days=10):
        # Calendar days, widened for weekends and holidays so `days` sessions actually land.
        return self._aggs(symbol, 1, "day", days * 2 + 5)[-days:]

    def _aggs(self, symbol, mult, span, lookback_days):
        end = dt.date.today()
        start = end - dt.timedelta(days=max(1, lookback_days))
        url = (f"{BASE}/v2/aggs/ticker/{symbol.upper()}/range/{mult}/{span}"
               f"/{start.isoformat()}/{end.isoformat()}")
        j = _http.get_json(url, {"adjusted": "true", "sort": "asc",
                                 "limit": 50_000, "apiKey": self.api_key})
        if j.get("status") == "ERROR":
            raise ProviderError(j.get("error") or j.get("message") or "polygon error")
        rows = j.get("results") or []
        if not rows:
            raise ProviderError(f"no {mult}{span} bars for {symbol}")
        out = []
        for r in rows:
            try:
                out.append(Bar(dt.datetime.fromtimestamp(r["t"] / 1000.0, dt.timezone.utc),
                               float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]),
                               float(r.get("v") or 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
        return out


PolygonProvider.__bases__ = (_PolygonBars,) + PolygonProvider.__bases__


def _timespan(interval):
    """'5m' -> (5, 'minute'); '1h' -> (1, 'hour')."""
    txt = str(interval).strip().lower()
    try:
        if txt.endswith("m"):
            return max(1, int(txt[:-1])), "minute"
        if txt.endswith("h"):
            return max(1, int(txt[:-1])), "hour"
        if txt.endswith("d"):
            return max(1, int(txt[:-1])), "day"
    except ValueError:
        pass
    raise ProviderError(f"unrecognised bar interval {interval!r} (use 1m, 5m, 15m, 1h)")
