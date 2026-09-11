#!/usr/bin/env python3
"""
bars.py  --  Intraday OHLCV bars and exchange session handling. stdlib only.

Everything intraday hinges on knowing where a session starts. VWAP anchors there, pivots and
CPR are computed from the PREVIOUS session's range, and a scalping signal that straddles two
sessions is meaningless. So sessions are handled explicitly, in the exchange's own timezone,
via stdlib `zoneinfo`.

Session membership is keyed on the bar's LOCAL CALENDAR DATE, not on a rolling window. Neither
NSE nor the US regular session crosses local midnight, so the local date is an exact session
identifier, and it stays correct across weekends, holidays and DST without a holiday calendar.
"""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Session:
    """Regular trading hours for one exchange, in its own timezone."""
    name: str
    tz_name: str
    open_hm: tuple      # (hour, minute) local
    close_hm: tuple

    @property
    def tz(self):
        return ZoneInfo(self.tz_name)

    def local(self, ts):
        """Convert an aware UTC timestamp into exchange-local time."""
        return ts.astimezone(self.tz)

    def key(self, ts):
        """
        Session identity for a timestamp: the exchange-local calendar date.

        This is what VWAP resets on and what groups bars into 'today' vs 'yesterday'.
        """
        return self.local(ts).date()

    def is_regular(self, ts):
        """
        True if the timestamp falls inside regular trading hours.

        Vendors happily return pre/post-market bars. Letting those into a VWAP corrupts it --
        thin extended-hours prints carry real volume weight and drag the anchor -- so they are
        filtered out rather than blended in.
        """
        t = self.local(ts).time()
        return dt.time(*self.open_hm) <= t < dt.time(*self.close_hm)

    def open_utc(self, day):
        """UTC instant of the session open on a given exchange-local date."""
        return dt.datetime.combine(day, dt.time(*self.open_hm), self.tz).astimezone(dt.timezone.utc)

    def close_utc(self, day):
        return dt.datetime.combine(day, dt.time(*self.close_hm), self.tz).astimezone(dt.timezone.utc)

    def minutes_into(self, ts):
        """Minutes elapsed since this session's open; negative before it."""
        return (ts - self.open_utc(self.key(ts))).total_seconds() / 60.0

    def minutes_left(self, ts):
        return (self.close_utc(self.key(ts)) - ts).total_seconds() / 60.0


#: Exchanges the desk knows. Add one here and it works everywhere.
SESSIONS = {
    "NSE": Session("NSE", "Asia/Kolkata", (9, 15), (15, 30)),
    "BSE": Session("BSE", "Asia/Kolkata", (9, 15), (15, 30)),
    "US": Session("US", "America/New_York", (9, 30), (16, 0)),
}
DEFAULT_EXCHANGE = "US"


def get_session(name):
    s = SESSIONS.get((name or DEFAULT_EXCHANGE).strip().upper())
    if s is None:
        raise SystemExit(f"[bars] unknown exchange {name!r}; known: {', '.join(sorted(SESSIONS))}")
    return s


@dataclass
class Bar:
    """One OHLCV bar. `ts` is the aware-UTC START of the bar's interval."""
    ts: dt.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def typical(self):
        """(H+L+C)/3 -- the price VWAP and pivots are both built on."""
        return (self.high + self.low + self.close) / 3.0

    @property
    def range(self):
        return self.high - self.low

    @property
    def body(self):
        return abs(self.close - self.open)

    @property
    def is_up(self):
        return self.close >= self.open

    def upper_wick(self):
        return self.high - max(self.open, self.close)

    def lower_wick(self):
        return min(self.open, self.close) - self.low

    def to_dict(self):
        return {"ts": self.ts.isoformat(), "o": self.open, "h": self.high,
                "l": self.low, "c": self.close, "v": self.volume}

    @staticmethod
    def from_dict(d):
        return Bar(dt.datetime.fromisoformat(d["ts"]), d["o"], d["h"], d["l"], d["c"],
                   d.get("v", 0.0))


class BarSeries:
    """An ordered list of bars with the slicing helpers the rules need."""

    def __init__(self, bars=(), session=None):
        self.bars = sorted(bars, key=lambda b: b.ts)
        self.session = session or SESSIONS[DEFAULT_EXCHANGE]

    def __len__(self):
        return len(self.bars)

    def __iter__(self):
        return iter(self.bars)

    @property
    def last(self):
        return self.bars[-1] if self.bars else None

    def regular_only(self):
        """Drop pre/post-market bars -- see Session.is_regular."""
        return BarSeries([b for b in self.bars if self.session.is_regular(b.ts)], self.session)

    def by_session(self):
        """{local_date: [bars]}, in order."""
        out = {}
        for b in self.bars:
            out.setdefault(self.session.key(b.ts), []).append(b)
        return out

    def session_dates(self):
        return sorted(self.by_session())

    def session_bars(self, day=None):
        """Bars for one session; defaults to the most recent one present."""
        groups = self.by_session()
        if not groups:
            return []
        return groups[day or max(groups)]

    def previous_session_bars(self):
        days = self.session_dates()
        return self.by_session()[days[-2]] if len(days) >= 2 else []

    def tail(self, n):
        return self.bars[-n:] if n else list(self.bars)

    @staticmethod
    def ohlc(bars):
        """Aggregate a list of bars into one (open, high, low, close, volume) tuple."""
        if not bars:
            return None
        return (bars[0].open, max(b.high for b in bars), min(b.low for b in bars),
                bars[-1].close, sum(b.volume for b in bars))
