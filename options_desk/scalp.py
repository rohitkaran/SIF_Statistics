#!/usr/bin/env python3
"""
scalp.py  --  Intraday scalping rules over pivots, the Central Pivot Range, and VWAP.

These evaluate a BarSnapshot (see models.BarSnapshot) and are registered into the same rule
registry as the options rules, so they are configured, cooled down, alerted, recorded and
backtested by exactly the same machinery.

Every rule here is a *location and context* signal -- price is at a level that matters, with
or without volume behind it. None of them is an instruction to trade, none sizes a position,
and none accounts for spread or slippage, all of which dominate scalping economics.
"""

from .levels import running_vwap
from .rules import Rule


class ScalpRule(Rule):
    """
    Base for bar-driven rules.

    Guards on snapshot kind so that pointing a mixed rule set at an option chain is a no-op
    rather than an AttributeError storm -- the engine catches those, but silently degrading is
    better than a stderr flood every tick.
    """
    default_severity = "info"
    min_bars = 2

    def applies_to_snapshot(self, snap):
        if getattr(snap, "kind", None) != "bars":
            return False
        if snap.levels is None or len(snap.bars or []) < self.min_bars:
            return False
        return True

    def evaluate(self, snap, hist):
        if not self.applies_to_snapshot(snap):
            return []
        return self.check(snap, hist) or []

    def check(self, snap, hist):
        raise NotImplementedError

    def _tol(self, snap, key="tolerance_pct", default=0.001):
        """Tolerance as a price distance, from a fraction-of-price setting."""
        return float(self.params.get(key, default)) * snap.price


class VwapCrossRule(ScalpRule):
    """
    Price crossed session VWAP -- the reclaim/lose trigger most intraday scalps hang off.

    The previous bar is compared against the VWAP *as it stood then*, so this fires once on
    the actual crossing rather than every bar that price happens to sit on the far side.
    """
    type = "vwap_cross"
    default_severity = "warn"
    default_cooldown_s = 300
    min_bars = 3

    def check(self, snap, hist):
        track = running_vwap(snap.bars.session, list(snap.bars))
        usable = [(b, v) for b, v in track if v is not None]
        if len(usable) < 2:
            return []
        (_pb, pv), (cb, cv) = usable[-2], usable[-1]
        prev_above, now_above = _pb.close > pv, cb.close > cv
        if prev_above == now_above:
            return []

        rvol = snap.relative_volume()
        min_rvol = float(self.params.get("min_rvol", 0.0))
        if min_rvol and (rvol is None or rvol < min_rvol):
            return []                       # a cross on no volume is noise

        way = "reclaimed" if now_above else "lost"
        extra = f" rvol {rvol:.2f}x" if rvol else ""
        return [self._signal(
            snap, f"{way} VWAP {cv:.2f} @ {snap.price:.2f} "
                  f"({snap.cpr_position} CPR){extra}",
            key_extra=way, vwap=cv, price=snap.price, rvol=rvol,
            cpr_position=snap.cpr_position)]


class VwapBandRule(ScalpRule):
    """
    Price is stretched `threshold` standard deviations from VWAP -- a mean-reversion fade.

    Requires a minimum number of bars: early in a session the VWAP standard deviation is
    computed from a handful of prints and a 2-sigma excursion means nothing.
    """
    type = "vwap_band"
    default_severity = "info"
    default_cooldown_s = 300
    min_bars = 6

    def check(self, snap, hist):
        thr = float(self.params.get("threshold", 2.0))
        z = snap.vwap_z
        if z is None or abs(z) < thr or snap.vwap.bars < int(self.params.get("min_samples", 10)):
            return []
        side = "extended above" if z > 0 else "extended below"
        lo, hi = snap.vwap.band(thr)
        band = hi if z > 0 else lo
        return [self._signal(
            snap, f"{side} VWAP {z:+.2f}σ @ {snap.price:.2f} "
                  f"(vwap {snap.vwap_value:.2f}, {thr:g}σ band {band:.2f})",
            key_extra="hi" if z > 0 else "lo",
            z=z, vwap=snap.vwap_value, price=snap.price)]


class CprBreakoutRule(ScalpRule):
    """
    Price broke out of the Central Pivot Range: closed above TC, or below BC, having been
    inside on the previous bar.

    Breaking out of the CPR is the classic start-of-trend tell, and it is far more meaningful
    on a narrow CPR -- `max_width_pct` optionally restricts firing to those days.
    """
    type = "cpr_breakout"
    default_severity = "alert"
    default_cooldown_s = 600

    def check(self, snap, hist):
        cpr = snap.levels.cpr
        tc, bc = cpr["tc"], cpr["bc"]
        bars = list(snap.bars)
        prev, cur = bars[-2], bars[-1]

        max_w = self.params.get("max_width_pct")
        if max_w is not None and (snap.levels.width_pct or 0) > float(max_w):
            return []

        was_inside = bc <= prev.close <= tc
        if not was_inside:
            return []

        rvol = snap.relative_volume()
        min_rvol = float(self.params.get("min_rvol", 0.0))
        if min_rvol and (rvol is None or rvol < min_rvol):
            return []

        if cur.close > tc:
            way, lvl = "broke above TC", tc
        elif cur.close < bc:
            way, lvl = "broke below BC", bc
        else:
            return []

        extra = f" rvol {rvol:.2f}x" if rvol else ""
        return [self._signal(
            snap, f"{way} {lvl:.2f} @ {snap.price:.2f} "
                  f"(CPR width {(snap.levels.width_pct or 0)*100:.2f}%){extra}",
            key_extra=way, level=lvl, price=snap.price, rvol=rvol,
            width_pct=snap.levels.width_pct)]


class CprRejectRule(ScalpRule):
    """
    Price tested a CPR edge and was rejected -- traded through TC/BC intrabar but closed back
    inside, leaving a wick. The fade counterpart to cpr_breakout.
    """
    type = "cpr_reject"
    default_severity = "warn"
    default_cooldown_s = 600

    def check(self, snap, hist):
        cpr = snap.levels.cpr
        tc, bc = cpr["tc"], cpr["bc"]
        cur = list(snap.bars)[-1]
        min_wick = float(self.params.get("min_wick_frac", 0.4))
        rng = cur.range
        if rng <= 0:
            return []

        if cur.high > tc >= cur.close and cur.upper_wick() / rng >= min_wick:
            return [self._signal(
                snap, f"rejected at TC {tc:.2f} (high {cur.high:.2f}, close {cur.close:.2f}, "
                      f"upper wick {cur.upper_wick()/rng*100:.0f}% of range)",
                key_extra="tc", level=tc, price=snap.price)]
        if cur.low < bc <= cur.close and cur.lower_wick() / rng >= min_wick:
            return [self._signal(
                snap, f"rejected at BC {bc:.2f} (low {cur.low:.2f}, close {cur.close:.2f}, "
                      f"lower wick {cur.lower_wick()/rng*100:.0f}% of range)",
                key_extra="bc", level=bc, price=snap.price)]
        return []


class NarrowCprRule(ScalpRule):
    """
    Today's CPR is unusually narrow -- the widely used precondition for a trending day.

    Fires once per session (keyed on the session date), as a heads-up before the open rather
    than a trade trigger.
    """
    type = "narrow_cpr"
    default_severity = "info"
    default_cooldown_s = 6 * 3600
    min_bars = 1

    def check(self, snap, hist):
        thr = float(self.params.get("threshold_pct", 0.0025))
        w = snap.levels.width_pct
        if w is None or w > thr:
            return []
        cpr = snap.levels.cpr
        return [self._signal(
            snap, f"NARROW CPR {w*100:.3f}% (TC {cpr['tc']:.2f} / BC {cpr['bc']:.2f}) "
                  f"-- trending day setup; price {snap.cpr_position} the range",
            key_extra=str(snap.bars.session.key(snap.ts)),
            width_pct=w, tc=cpr["tc"], bc=cpr["bc"], position=snap.cpr_position)]


class LevelTestRule(ScalpRule):
    """
    Price reached one of the static levels -- any pivot (P, R1-R3, S1-S3), a CPR edge, or the
    previous session's high/low/close.

    Keyed per level name, so each level announces itself once per cooldown instead of the
    whole set re-firing while price loiters.
    """
    type = "level_test"
    default_severity = "info"
    default_cooldown_s = 900

    def check(self, snap, hist):
        tol = self._tol(snap, default=0.0015)
        watch = [w.upper() for w in self.params.get("levels", [])]
        out = []
        for name, value in snap.levels.named().items():
            if watch and name not in watch:
                continue
            if value is None or abs(snap.price - value) > tol:
                continue
            out.append(self._signal(
                snap, f"testing {name} {value:.2f} @ {snap.price:.2f} "
                      f"({(snap.price - value):+.2f})",
                key_extra=name, level_name=name, level=value, price=snap.price))
        return out


class ConfluenceRule(ScalpRule):
    """
    A static level and VWAP have converged, and price is there.

    This is the setup worth waiting for: when a pivot or CPR edge sits on top of VWAP, two
    independent reference prices agree, and the reaction at that zone tends to be the cleanest
    of the session. Fires only when the level, VWAP and price are all inside one tolerance.
    """
    type = "confluence"
    default_severity = "alert"
    default_cooldown_s = 900
    min_bars = 4

    def check(self, snap, hist):
        vwap = snap.vwap_value
        if vwap is None:
            return []
        tol = self._tol(snap, default=0.002)
        watch = [w.upper() for w in self.params.get("levels", [])]

        out = []
        for name, value in snap.levels.named().items():
            if watch and name not in watch:
                continue
            if value is None:
                continue
            if abs(value - vwap) > tol or abs(snap.price - value) > tol:
                continue
            out.append(self._signal(
                snap, f"CONFLUENCE {name} {value:.2f} + VWAP {vwap:.2f} @ {snap.price:.2f} "
                      f"(spread {abs(value - vwap):.2f}, {snap.cpr_position} CPR)",
                key_extra=name, level_name=name, level=value, vwap=vwap,
                price=snap.price, position=snap.cpr_position))
        return out


#: Registered into the shared rule registry by rules.build().
TYPES = {c.type: c for c in (VwapCrossRule, VwapBandRule, CprBreakoutRule, CprRejectRule,
                             NarrowCprRule, LevelTestRule, ConfluenceRule)}

#: A reasonable scalping desk to start from.
DEFAULT_SCALP_RULES = [
    {"type": "narrow_cpr", "threshold_pct": 0.0025},
    {"type": "cpr_breakout", "min_rvol": 1.2},
    {"type": "cpr_reject", "min_wick_frac": 0.4},
    {"type": "vwap_cross", "min_rvol": 1.0},
    {"type": "vwap_band", "threshold": 2.0},
    {"type": "confluence", "tolerance_pct": 0.002},
    {"type": "level_test", "tolerance_pct": 0.0015},
]
