#!/usr/bin/env python3
"""
history.py  --  Rolling time-series state the rules evaluate against. stdlib only.

A single snapshot cannot tell you that IV *spiked* or that spot *moved* -- those are
statements about a window. This holds the small number of scalars worth tracking per
underlying (spot, ATM IV, skew) in bounded deques so a desk can run for days without
growing without limit.

Retention is time-based, not tick-based, so the same window means the same thing whether
the provider pushes 10/sec or polls every 5s.
"""

import bisect
import datetime as dt
from collections import deque

DEFAULT_RETENTION_S = 6 * 3600      # a US options session plus slack


class Series:
    """An append-only (timestamp, value) series pruned to a fixed time horizon."""

    def __init__(self, retention_s=DEFAULT_RETENTION_S, maxlen=50_000):
        self.retention_s = retention_s
        self._pts = deque(maxlen=maxlen)     # maxlen is a hard memory backstop

    def __len__(self):
        return len(self._pts)

    def append(self, ts, value):
        if value is None:
            return                            # never store gaps as zeros
        self._pts.append((ts, float(value)))
        self._prune(ts)

    def _prune(self, now):
        cutoff = now - dt.timedelta(seconds=self.retention_s)
        while self._pts and self._pts[0][0] < cutoff:
            self._pts.popleft()

    @property
    def last(self):
        return self._pts[-1][1] if self._pts else None

    @property
    def last_ts(self):
        return self._pts[-1][0] if self._pts else None

    def window(self, seconds):
        """Points within the last `seconds`."""
        if not self._pts:
            return []
        cutoff = self._pts[-1][0] - dt.timedelta(seconds=seconds)
        return [(t, v) for t, v in self._pts if t >= cutoff]

    def value_at_or_before(self, seconds_ago):
        """
        The value as of `seconds_ago`, for change calculations.

        Returns the newest point at-or-before the cutoff -- not an interpolation. With a
        gappy feed, interpolating invents prices that never traded.
        """
        if not self._pts:
            return None
        cutoff = self._pts[-1][0] - dt.timedelta(seconds=seconds_ago)
        idx = bisect.bisect_right([t for t, _ in self._pts], cutoff) - 1
        return self._pts[idx][1] if idx >= 0 else None

    def change(self, seconds):
        """Absolute change over the window; None until the window is actually covered."""
        base, now = self.value_at_or_before(seconds), self.last
        if base is None or now is None or not self.covers(seconds):
            return None
        return now - base

    def pct_change(self, seconds):
        base, now = self.value_at_or_before(seconds), self.last
        if base is None or now is None or base == 0 or not self.covers(seconds):
            return None
        return (now - base) / abs(base)

    def covers(self, seconds):
        """
        True once the series actually spans `seconds`.

        Without this a rule fires on its second tick, comparing a 5-second window against a
        threshold meant for 5 minutes -- the classic false-positive-at-startup bug.
        """
        if len(self._pts) < 2:
            return False
        return (self._pts[-1][0] - self._pts[0][0]).total_seconds() >= seconds

    def rank(self, value=None):
        """
        Percentile rank (0..1) of `value` within the retained window -- the 'IV rank' idea.

        Note this ranks against the session so far, not a 52-week history. Treat it as
        'where in today's range', and do not read it as a true IV rank until the recorder
        has enough days behind it.
        """
        if len(self._pts) < 2:
            return None
        v = self.last if value is None else value
        if v is None:
            return None
        vals = sorted(x for _, x in self._pts)
        return bisect.bisect_right(vals, v) / len(vals)

    def high_low(self):
        if not self._pts:
            return (None, None)
        vals = [v for _, v in self._pts]
        return (max(vals), min(vals))


class History:
    """Per-underlying bundle of the series the built-in rules need."""

    TRACKED = ("spot", "atm_iv", "skew")

    def __init__(self, retention_s=DEFAULT_RETENTION_S):
        self.retention_s = retention_s
        self._by_symbol = {}

    def series(self, underlying, field):
        d = self._by_symbol.setdefault(underlying, {})
        if field not in d:
            d[field] = Series(self.retention_s)
        return d[field]

    def update(self, snap):
        """Fold one snapshot into the tracked series. Called once per tick by the engine."""
        self.series(snap.underlying, "spot").append(snap.ts, snap.spot)
        self.series(snap.underlying, "atm_iv").append(snap.ts, snap.atm_iv())
        self.series(snap.underlying, "skew").append(snap.ts, skew_25d(snap))

    def symbols(self):
        return sorted(self._by_symbol)


def nearest_delta(snap, expiry, right, target):
    """Contract whose |delta| sits closest to `target` -- how option desks name strikes."""
    pool = [q for q in snap.by_expiry(expiry)
            if q.contract.right == right and q.delta is not None]
    return min(pool, key=lambda q: abs(abs(q.delta) - target)) if pool else None


def skew_25d(snap, expiry=None):
    """
    25-delta put IV minus 25-delta call IV, in vol points.

    Positive = puts bid over calls (normal equity fear skew). A sharp rise is the classic
    'someone is paying up for downside' tell, which is why it is tracked every tick.
    """
    e = expiry or snap.nearest_expiry()
    if e is None:
        return None
    p, c = nearest_delta(snap, e, "P", 0.25), nearest_delta(snap, e, "C", 0.25)
    if not p or not c or p.iv is None or c.iv is None:
        return None
    return p.iv - c.iv
