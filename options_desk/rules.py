#!/usr/bin/env python3
"""
rules.py  --  Signal rules evaluated against every chain snapshot. stdlib only.

Each rule is a small, independently testable object: given a ChainSnapshot and the rolling
History, return zero or more Signals. Rules never place orders and never mutate state -- the
engine owns cooldowns and dispatch, so the exact same rule objects can be replayed over
recorded data by the backtester and produce identical output.

Rules are declared as data (see DEFAULT_RULES / rules.json) so a strategy change is a config
edit, not a code change:

    {"type": "iv_spike", "window_s": 300, "threshold": 0.02, "severity": "alert"}
"""

import datetime as dt
from dataclasses import dataclass, field

from .history import nearest_delta, skew_25d

SEVERITIES = ("info", "warn", "alert")


@dataclass
class Signal:
    """One fired rule. `key` is the dedupe identity the engine applies cooldowns against."""
    rule: str
    underlying: str
    severity: str
    message: str
    ts: dt.datetime
    key: str = ""
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.key:
            self.key = f"{self.rule}:{self.underlying}"

    def line(self):
        return f"[{self.ts:%H:%M:%S}] {self.severity.upper():5s} {self.underlying:6s} {self.message}"

    def to_dict(self):
        d = dict(self.__dict__)
        d["ts"] = self.ts.isoformat()
        return d


class Rule:
    """Base class. Subclasses set `type` and implement evaluate()."""
    type = "base"
    default_severity = "info"
    default_cooldown_s = 300

    def __init__(self, **params):
        self.params = params
        self.name = params.get("name") or self.type
        self.severity = params.get("severity", self.default_severity)
        if self.severity not in SEVERITIES:
            raise SystemExit(f"[rules] {self.name}: severity must be one of {SEVERITIES}")
        self.cooldown_s = float(params.get("cooldown_s", self.default_cooldown_s))
        self.symbols = [s.upper() for s in params.get("symbols", [])]   # empty = all

    def applies_to(self, underlying):
        return not self.symbols or underlying.upper() in self.symbols

    def evaluate(self, snap, hist):
        raise NotImplementedError

    def _signal(self, snap, message, key_extra="", **data):
        return Signal(self.name, snap.underlying, self.severity, message, snap.ts,
                      key=f"{self.name}:{snap.underlying}:{key_extra}" if key_extra else "",
                      data=data)

    def describe(self):
        return f"{self.name} ({self.type}) {self.params}"


class SpotMoveRule(Rule):
    """Underlying moved more than `threshold` (fraction) over `window_s`."""
    type = "spot_move"
    default_severity = "warn"

    def evaluate(self, snap, hist):
        w = float(self.params.get("window_s", 300))
        thr = float(self.params.get("threshold", 0.005))
        pct = hist.series(snap.underlying, "spot").pct_change(w)
        if pct is None or abs(pct) < thr:
            return []
        direction = "up" if pct > 0 else "down"
        # Bucket the key by direction so an up-move and a later down-move both get through.
        return [self._signal(
            snap, f"spot {direction} {pct*100:+.2f}% in {int(w)}s -> {snap.spot:.2f}",
            key_extra=direction, pct=pct, spot=snap.spot, window_s=w)]


class IVSpikeRule(Rule):
    """ATM implied vol moved more than `threshold` VOL POINTS (0.02 == 2 pts) over `window_s`."""
    type = "iv_spike"
    default_severity = "alert"

    def evaluate(self, snap, hist):
        w = float(self.params.get("window_s", 300))
        thr = float(self.params.get("threshold", 0.02))
        chg = hist.series(snap.underlying, "atm_iv").change(w)
        iv = snap.atm_iv()
        if chg is None or iv is None or abs(chg) < thr:
            return []
        direction = "spike" if chg > 0 else "crush"
        return [self._signal(
            snap, f"ATM IV {direction} {chg*100:+.2f} pts in {int(w)}s -> {iv*100:.2f}%",
            key_extra=direction, change=chg, atm_iv=iv, window_s=w)]


class IVRankRule(Rule):
    """ATM IV sits in the top/bottom `threshold` of its retained range -- a rich/cheap read."""
    type = "iv_rank"
    default_severity = "info"
    default_cooldown_s = 900

    def evaluate(self, snap, hist):
        thr = float(self.params.get("threshold", 0.9))
        side = self.params.get("side", "high")      # "high" | "low" | "both"
        s = hist.series(snap.underlying, "atm_iv")
        rank, iv = s.rank(), snap.atm_iv()
        # Demand a real sample before calling anything a percentile extreme.
        if rank is None or iv is None or len(s) < int(self.params.get("min_samples", 30)):
            return []
        hi, lo = s.high_low()
        if side in ("high", "both") and rank >= thr:
            return [self._signal(snap, f"ATM IV {iv*100:.2f}% is rich -- {rank*100:.0f}th pct of "
                                       f"session range ({lo*100:.1f}-{hi*100:.1f}%)",
                                 key_extra="high", rank=rank, atm_iv=iv)]
        if side in ("low", "both") and rank <= 1 - thr:
            return [self._signal(snap, f"ATM IV {iv*100:.2f}% is cheap -- {rank*100:.0f}th pct of "
                                       f"session range ({lo*100:.1f}-{hi*100:.1f}%)",
                                 key_extra="low", rank=rank, atm_iv=iv)]
        return []


class SkewShiftRule(Rule):
    """25-delta put/call skew moved more than `threshold` vol points over `window_s`."""
    type = "skew_shift"
    default_severity = "warn"

    def evaluate(self, snap, hist):
        w = float(self.params.get("window_s", 600))
        thr = float(self.params.get("threshold", 0.015))
        chg = hist.series(snap.underlying, "skew").change(w)
        cur = skew_25d(snap)
        if chg is None or cur is None or abs(chg) < thr:
            return []
        way = "steepening (downside bid)" if chg > 0 else "flattening"
        return [self._signal(snap, f"25d skew {way} {chg*100:+.2f} pts in {int(w)}s "
                                   f"-> {cur*100:.2f} pts",
                             key_extra="steep" if chg > 0 else "flat", change=chg, skew=cur)]


class CreditTargetRule(Rule):
    """
    A premium-selling screen: at the target delta, is there at least `min_credit` on offer
    in a contract that is actually liquid enough to exit?

    This is the rule that turns 'watch the chain' into 'here is the contract' -- it names the
    strike, so it deliberately keys on the contract and not just the underlying.
    """
    type = "credit_target"
    default_severity = "info"
    default_cooldown_s = 600

    def evaluate(self, snap, hist):
        target = float(self.params.get("delta", 0.20))
        min_credit = float(self.params.get("min_credit", 1.0))
        right = self.params.get("right", "P").upper()[0]
        min_dte = int(self.params.get("min_dte", 1))
        max_spread_pct = float(self.params.get("max_spread_pct", 0.10))
        min_oi = int(self.params.get("min_oi", 250))

        exp = snap.nearest_expiry(min_dte)
        if exp is None:
            return []
        q = nearest_delta(snap, exp, right, target)
        if q is None or q.mid is None or q.mid < min_credit:
            return []
        if not q.is_tradeable(max_spread_pct, min_oi):
            return []                              # illiquid: a credit you cannot close is not a credit
        dte = (exp - snap.ts.date()).days
        return [self._signal(
            snap,
            f"{q.contract.label()} ~{abs(q.delta):.2f}d {dte}dte "
            f"credit {q.mid:.2f} (bid {q.bid} ask {q.ask}, oi {q.open_interest}, iv {(q.iv or 0)*100:.1f}%)",
            key_extra=q.contract.occ(),
            strike=q.contract.strike, right=right, expiry=exp.isoformat(),
            credit=q.mid, delta=q.delta, iv=q.iv, open_interest=q.open_interest)]


_TYPES = {c.type: c for c in (SpotMoveRule, IVSpikeRule, IVRankRule, SkewShiftRule, CreditTargetRule)}

#: A sane starting desk. Override with --rules rules.json.
DEFAULT_RULES = [
    {"type": "spot_move", "window_s": 300, "threshold": 0.004},
    {"type": "iv_spike", "window_s": 300, "threshold": 0.02},
    {"type": "iv_rank", "threshold": 0.9, "side": "both"},
    {"type": "skew_shift", "window_s": 600, "threshold": 0.015},
    {"type": "credit_target", "delta": 0.20, "right": "P", "min_credit": 0.80, "min_dte": 1},
]


def build(specs):
    """Turn a list of rule dicts into Rule objects, failing loudly on a bad spec."""
    out = []
    for i, spec in enumerate(specs):
        if not isinstance(spec, dict) or "type" not in spec:
            raise SystemExit(f"[rules] entry {i}: each rule needs a 'type' key, got {spec!r}")
        cls = _TYPES.get(spec["type"])
        if cls is None:
            raise SystemExit(f"[rules] entry {i}: unknown rule type {spec['type']!r}; "
                             f"available: {', '.join(sorted(_TYPES))}")
        out.append(cls(**{k: v for k, v in spec.items() if k != "type"}))
    return out


def available():
    return sorted(_TYPES)
