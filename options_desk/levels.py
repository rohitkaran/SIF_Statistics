#!/usr/bin/env python3
"""
levels.py  --  Floor-trader pivots, Central Pivot Range, and session-anchored VWAP. stdlib only.

All three are computed here rather than taken from a vendor, for the same reason greeks are:
vendors disagree on anchoring and on whether extended-hours prints are included, and a level
you cannot reproduce is a level you cannot trust.

Pivots and CPR come from the PREVIOUS session's high/low/close. VWAP is anchored to the
CURRENT session's open and resets when the exchange-local date changes.
"""

import math
from dataclasses import dataclass, field


# --- pivots and CPR ---------------------------------------------------------------

def classic_pivots(high, low, close):
    """
    Standard floor-trader pivots from the previous session's range.

        P  = (H + L + C) / 3
        R1 = 2P - L        S1 = 2P - H
        R2 = P + (H - L)   S2 = P - (H - L)
        R3 = H + 2(P - L)  S3 = L - 2(H - P)
    """
    p = (high + low + close) / 3.0
    rng = high - low
    return {
        "P": p,
        "R1": 2 * p - low, "S1": 2 * p - high,
        "R2": p + rng, "S2": p - rng,
        "R3": high + 2 * (p - low), "S3": low - 2 * (high - p),
    }


def central_pivot_range(high, low, close):
    """
    Central Pivot Range from the previous session's range.

        Pivot = (H + L + C) / 3
        BC    = (H + L) / 2
        TC    = (Pivot - BC) + Pivot        [equivalently 2*Pivot - BC]

    TC as computed can land BELOW BC -- that happens whenever the close sits under the mid of
    the range. The two are then relabelled so TC is always the top of the band and BC the
    bottom; the band itself is identical either way, and every downstream comparison
    ('above the CPR', 'inside the CPR') depends on that ordering holding.
    """
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = 2 * pivot - bc
    if tc < bc:
        tc, bc = bc, tc
    return {"pivot": pivot, "tc": tc, "bc": bc, "width": tc - bc}


@dataclass
class Levels:
    """Every static level for one session, derived from the previous session."""
    prev_high: float
    prev_low: float
    prev_close: float
    pivots: dict = field(default_factory=dict)
    cpr: dict = field(default_factory=dict)

    @staticmethod
    def from_previous(high, low, close):
        return Levels(high, low, close,
                      classic_pivots(high, low, close),
                      central_pivot_range(high, low, close))

    @property
    def width_pct(self):
        """
        CPR width as a fraction of the pivot -- the scale-free 'narrow vs wide' measure.

        Raw width cannot be compared across symbols (a 20-point CPR is tight on a 25,000 index
        and enormous on a 300 stock), so every narrowness test uses this.
        """
        p = self.cpr.get("pivot")
        return (self.cpr["width"] / p) if p else None

    def named(self):
        """All levels as {name: price}, including previous-session high/low/close."""
        out = {"PDH": self.prev_high, "PDL": self.prev_low, "PDC": self.prev_close,
               "TC": self.cpr["tc"], "BC": self.cpr["bc"]}
        out.update(self.pivots)          # P, R1-R3, S1-S3
        return out

    def nearest(self, price, exclude=()):
        """(name, level, distance) for the level closest to `price`."""
        cands = [(n, v) for n, v in self.named().items() if n not in exclude and v is not None]
        if not cands:
            return None
        name, val = min(cands, key=lambda kv: abs(kv[1] - price))
        return name, val, abs(val - price)

    def position(self, price):
        """Where price sits relative to the CPR band: 'above' | 'inside' | 'below'."""
        if price > self.cpr["tc"]:
            return "above"
        if price < self.cpr["bc"]:
            return "below"
        return "inside"

    def to_dict(self):
        return {"prev_high": self.prev_high, "prev_low": self.prev_low,
                "prev_close": self.prev_close, "pivots": self.pivots, "cpr": self.cpr}

    @staticmethod
    def from_dict(d):
        return Levels(d["prev_high"], d["prev_low"], d["prev_close"],
                      d.get("pivots", {}), d.get("cpr", {}))


# --- VWAP -------------------------------------------------------------------------

class Vwap:
    """
    Session-anchored VWAP with volume-weighted standard-deviation bands.

    Maintained as running sums so each bar is O(1):

        vwap = sum(tp*v) / sum(v)
        var  = sum(tp^2*v) / sum(v) - vwap^2

    Zero-volume bars are skipped rather than counted with weight zero or promoted to equal
    weight. A symbol that reports no volume at all (cash indices, typically) therefore has a
    VWAP of None, which is the truthful answer -- there is no traded value to weight by.
    """

    def __init__(self, session):
        self.session = session
        self.anchor = None            # exchange-local date this accumulation belongs to
        self._reset()

    def _reset(self):
        self._v = self._pv = self._p2v = 0.0
        self.bars = 0

    def update(self, bar):
        """Fold one bar in, resetting first if it belongs to a new session."""
        key = self.session.key(bar.ts)
        if key != self.anchor:
            self.anchor = key
            self._reset()
        v = bar.volume or 0.0
        if v <= 0:
            return self
        tp = bar.typical
        self._v += v
        self._pv += tp * v
        self._p2v += tp * tp * v
        self.bars += 1
        return self

    def feed(self, bars):
        for b in bars:
            self.update(b)
        return self

    @property
    def value(self):
        return (self._pv / self._v) if self._v > 0 else None

    @property
    def variance(self):
        v = self.value
        if v is None:
            return None
        # Floating-point cancellation can drive this fractionally negative when every bar
        # printed at nearly the same price; clamp rather than hand back a NaN stdev.
        return max(0.0, self._p2v / self._v - v * v)

    @property
    def stdev(self):
        var = self.variance
        return math.sqrt(var) if var is not None else None

    def band(self, n):
        """(lower, upper) at n standard deviations."""
        v, sd = self.value, self.stdev
        if v is None or sd is None:
            return (None, None)
        return (v - n * sd, v + n * sd)

    def z(self, price):
        """How many standard deviations `price` sits from VWAP. None if undefined or flat."""
        v, sd = self.value, self.stdev
        if v is None or not sd:
            return None
        return (price - v) / sd

    def to_dict(self):
        return {"value": self.value, "stdev": self.stdev, "bars": self.bars,
                "anchor": self.anchor.isoformat() if self.anchor else None}


def running_vwap(session, bars):
    """
    [(bar, vwap_after_that_bar)] for a sequence of bars.

    Cross detection needs the VWAP *as it stood* on the previous bar, not the current one --
    comparing an earlier close against today's latest VWAP invents crossings that never
    happened. One pass, so it is cheap enough to redo every tick.
    """
    acc = Vwap(session)
    out = []
    for b in bars:
        acc.update(b)
        out.append((b, acc.value))
    return out
