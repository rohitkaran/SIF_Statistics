#!/usr/bin/env python3
"""
models.py  --  The vendor-neutral shapes every provider normalises into. stdlib only.

Everything downstream (rules, engine, dashboard, backtest) is written against these types
and never against a vendor payload, so swapping Polygon for Tradier changes one adapter and
nothing else. Providers are responsible for mapping their JSON into these; if a provider
cannot fill a field it leaves it None rather than inventing a value.
"""

import datetime as dt
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

from . import greeks as bs


@dataclass(frozen=True)
class Contract:
    """Static identity of one option. Never carries a price."""
    underlying: str
    expiry: dt.date
    strike: float
    right: str            # "C" | "P"
    symbol: str = ""      # vendor/OCC symbol, informational only

    def occ(self):
        """OCC 21-char symbol: ROOT(6) YYMMDD C/P STRIKE*1000(8)."""
        return "%-6s%s%s%08d" % (self.underlying[:6], self.expiry.strftime("%y%m%d"),
                                 self.right, round(self.strike * 1000))

    def label(self):
        return f"{self.underlying} {self.expiry:%d%b%y} {self.strike:g}{self.right}".upper()


@dataclass
class Quote:
    """One contract's live market state at a point in time."""
    contract: Contract
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    # Computed locally by ChainSnapshot.enrich(); vendor greeks are kept separately.
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None
    rho: Optional[float] = None
    vendor_iv: Optional[float] = None

    @property
    def mid(self):
        """Mid price, or whichever single side exists, or last. None if the quote is empty."""
        if self.bid is not None and self.ask is not None and self.ask >= self.bid:
            return (self.bid + self.ask) / 2.0
        return self.last if self.last is not None else (self.bid or self.ask)

    @property
    def spread(self):
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    @property
    def spread_pct(self):
        """Spread as a fraction of mid -- the liquidity gate most rules key off."""
        m, s = self.mid, self.spread
        if m is None or s is None or m <= 0:
            return None
        return s / m

    def is_tradeable(self, max_spread_pct=0.10, min_oi=0):
        """Cheap liquidity screen so rules never fire on a contract you cannot get out of."""
        if self.mid is None or self.mid <= 0:
            return False
        if self.spread_pct is not None and self.spread_pct > max_spread_pct:
            return False
        if min_oi and (self.open_interest or 0) < min_oi:
            return False
        return True


@dataclass
class ChainSnapshot:
    """The full option chain for one underlying at one instant -- the engine's unit of work."""
    kind = "chain"
    underlying: str
    spot: float
    ts: dt.datetime                      # timezone-aware UTC
    quotes: list = field(default_factory=list)
    provider: str = ""
    rate: float = 0.0                    # risk-free used for greeks
    dividend: float = 0.0

    # ---- derivation -------------------------------------------------------------

    def enrich(self, rate=None, dividend=None):
        """
        Fill iv + greeks on every quote from its mid price. Idempotent; safe to re-run.

        Done here rather than in each provider so that all providers -- including replayed
        backtest data -- get identical greeks from identical inputs.
        """
        r = self.rate if rate is None else rate
        q = self.dividend if dividend is None else dividend
        self.rate, self.dividend = r, q

        # Pass 1 -- solve each contract's own IV from its own mid.
        tenor = {}
        for qt in self.quotes:
            t = tenor.setdefault(qt.contract.expiry,
                                 bs.year_fraction(self.ts, expiry_utc(qt.contract.expiry)))
            qt.iv = bs.implied_vol(qt.mid, self.spot, qt.contract.strike, t,
                                   qt.contract.right, r, q)

        # Pass 2 -- borrow vol from the other side of the same strike where pass 1 failed.
        #
        # A deep-ITM option is nearly all intrinsic, so its premium carries almost no vol
        # information and a penny of quote noise can put it under the model floor, leaving it
        # unsolvable. Its counterpart at the same strike is correspondingly deep OTM, all
        # time value, and solves cleanly -- and by put-call parity the two share one vol.
        # Taking vol from the OTM wing is what an options desk does for exactly this reason.
        pair = {}
        for qt in self.quotes:
            c = qt.contract
            pair.setdefault((c.expiry, c.strike), {})[c.right] = qt
        for (expiry, _strike), sides in pair.items():
            for right, other in (("C", "P"), ("P", "C")):
                this, that = sides.get(right), sides.get(other)
                if this is not None and this.iv is None and that is not None and that.iv:
                    this.iv = that.iv

        # Pass 3 -- greeks, from whatever vol we ended up with.
        for qt in self.quotes:
            t = tenor[qt.contract.expiry]
            g = bs.greeks(self.spot, qt.contract.strike, t, qt.iv or 0.0,
                          qt.contract.right, r, q)
            qt.delta, qt.gamma = g["delta"], g["gamma"]
            qt.vega, qt.theta, qt.rho = g["vega"], g["theta"], g["rho"]
        return self

    # ---- selection --------------------------------------------------------------

    def expiries(self):
        return sorted({q.contract.expiry for q in self.quotes})

    def by_expiry(self, expiry):
        return [q for q in self.quotes if q.contract.expiry == expiry]

    def strikes(self, expiry=None):
        pool = self.quotes if expiry is None else self.by_expiry(expiry)
        return sorted({q.contract.strike for q in pool})

    def get(self, expiry, strike, right):
        for q in self.quotes:
            c = q.contract
            if c.expiry == expiry and c.right == right and math.isclose(c.strike, strike):
                return q
        return None

    def atm_strike(self, expiry=None):
        ks = self.strikes(expiry)
        return min(ks, key=lambda k: abs(k - self.spot)) if ks else None

    def nearest_expiry(self, min_dte=0):
        """First expiry at least `min_dte` calendar days out -- skips same-day gamma traps."""
        today = self.ts.date()
        for e in self.expiries():
            if (e - today).days >= min_dte:
                return e
        return None

    def atm_iv(self, expiry=None):
        """Average of the ATM call and put IV -- the standard single-number vol read."""
        e = expiry or self.nearest_expiry()
        k = self.atm_strike(e)
        if e is None or k is None:
            return None
        ivs = [q.iv for q in (self.get(e, k, "C"), self.get(e, k, "P")) if q and q.iv]
        return sum(ivs) / len(ivs) if ivs else None

    #: How the backtester reads this snapshot: the price forward returns are measured on,
    #: plus a secondary metric with a label and display scale.
    VOL_LABEL = "iv"
    VOL_SCALE = 100.0            # fractions -> vol points

    @property
    def mark_price(self):
        return self.spot

    @property
    def vol_metric(self):
        return self.atm_iv()

    def series_values(self):
        """
        The scalars History tracks for this snapshot type.

        Declared by the snapshot rather than hard-coded in History, so an options chain and an
        intraday bar snapshot can share one engine, one recorder and one backtester.
        """
        return {"spot": self.spot, "atm_iv": self.atm_iv(), "skew": _skew(self)}

    # ---- serialisation (JSONL for the recorder / backtester) ---------------------

    def to_dict(self):
        return {
            "kind": self.kind,
            "underlying": self.underlying, "spot": self.spot,
            "ts": self.ts.isoformat(), "provider": self.provider,
            "rate": self.rate, "dividend": self.dividend,
            "quotes": [_quote_dict(q) for q in self.quotes],
        }

    @staticmethod
    def from_dict(d):
        snap = ChainSnapshot(
            underlying=d["underlying"], spot=d["spot"],
            ts=dt.datetime.fromisoformat(d["ts"]), provider=d.get("provider", ""),
            rate=d.get("rate", 0.0), dividend=d.get("dividend", 0.0),
            quotes=[_quote_obj(x) for x in d["quotes"]],
        )
        return snap


def _quote_dict(q):
    d = asdict(q)
    c = d.pop("contract")
    c["expiry"] = q.contract.expiry.isoformat()
    d["contract"] = c
    return d


def _quote_obj(d):
    c = dict(d["contract"])
    c["expiry"] = dt.date.fromisoformat(c["expiry"])
    rest = {k: v for k, v in d.items() if k != "contract"}
    return Quote(contract=Contract(**c), **rest)


def expiry_utc(day):
    """
    US equity options stop trading 16:00 America/New_York on the expiry date.

    Hardcoded as 20:00Z (EDT). During EST that is an hour off, which moves theta by well
    under a tenth of a day -- immaterial next to the bid/ask noise the IV is solved from,
    and it avoids a tzdata dependency in a stdlib-only tree.
    """
    return dt.datetime(day.year, day.month, day.day, 20, 0, tzinfo=dt.timezone.utc)


def _skew(snap):
    """Deferred import: history imports models, so this cannot be a module-level import."""
    from .history import skew_25d
    return skew_25d(snap)


@dataclass
class BarSnapshot:
    """
    One intraday moment for a stock: latest price, the session's bars so far, the static
    levels derived from yesterday, and the live VWAP.

    Same shape of contract as ChainSnapshot -- `underlying`, `ts`, `series_values()`,
    `to_dict()` -- so the engine, recorder, alerting and backtester take either without
    knowing which it has.
    """
    kind = "bars"

    underlying: str
    price: float
    ts: dt.datetime
    bars: object = None                 # BarSeries for the CURRENT session (regular hours)
    levels: object = None               # Levels, from the previous session
    vwap: object = None                 # Vwap, anchored to this session
    provider: str = ""
    exchange: str = "US"
    interval: str = "5m"

    @property
    def symbol(self):
        return self.underlying

    # ---- derived reads the rules use ---------------------------------------------

    @property
    def vwap_value(self):
        return self.vwap.value if self.vwap else None

    @property
    def vwap_z(self):
        return self.vwap.z(self.price) if self.vwap else None

    @property
    def cpr_position(self):
        return self.levels.position(self.price) if self.levels else None

    def session_volume(self):
        return sum(b.volume for b in self.bars) if self.bars else 0.0

    def relative_volume(self, lookback=20):
        """
        Latest bar's volume against the median of the preceding `lookback` bars.

        Median, not mean: one opening bar routinely carries 10x a midday bar, and a mean is
        dragged so far by it that nothing ever looks like a volume surge afterwards.
        """
        bars = list(self.bars or [])
        if len(bars) < 3:
            return None
        prior = [b.volume for b in bars[-(lookback + 1):-1] if b.volume > 0]
        if not prior:
            return None
        import statistics
        med = statistics.median(prior)
        return (bars[-1].volume / med) if med > 0 else None

    #: For scalping the useful secondary is the VWAP z-score: after a stretch signal, did
    #: price actually revert toward the anchor or keep going?
    VOL_LABEL = "z"
    VOL_SCALE = 1.0

    @property
    def mark_price(self):
        return self.price

    @property
    def vol_metric(self):
        return self.vwap_z

    def series_values(self):
        return {"price": self.price, "vwap": self.vwap_value, "vwap_z": self.vwap_z}

    # ---- serialisation ------------------------------------------------------------

    def to_dict(self):
        return {
            "kind": self.kind,
            "underlying": self.underlying, "price": self.price, "ts": self.ts.isoformat(),
            "provider": self.provider, "exchange": self.exchange, "interval": self.interval,
            "levels": self.levels.to_dict() if self.levels else None,
            "bars": [b.to_dict() for b in (self.bars or [])],
        }

    @staticmethod
    def from_dict(d):
        from .bars import Bar, BarSeries, get_session
        from .levels import Levels, Vwap
        session = get_session(d.get("exchange", "US"))
        series = BarSeries([Bar.from_dict(b) for b in d.get("bars", [])], session)
        # VWAP is rebuilt from the bars rather than serialised. Replaying the accumulation is
        # what guarantees a backtest sees the identical anchor the live desk had.
        vwap = Vwap(session).feed(series)
        return BarSnapshot(
            underlying=d["underlying"], price=d["price"],
            ts=dt.datetime.fromisoformat(d["ts"]),
            bars=series, levels=Levels.from_dict(d["levels"]) if d.get("levels") else None,
            vwap=vwap, provider=d.get("provider", ""),
            exchange=d.get("exchange", "US"), interval=d.get("interval", "5m"))


#: Snapshot kinds the recorder can replay.
_KINDS = {"chain": ChainSnapshot, "bars": BarSnapshot}


def snapshot_from_dict(d):
    """Rebuild whichever snapshot type a recorded line holds."""
    cls = _KINDS.get(d.get("kind", "chain"))   # untagged lines predate BarSnapshot
    if cls is None:
        raise ValueError(f"unknown snapshot kind {d.get('kind')!r}")
    return cls.from_dict(d)
