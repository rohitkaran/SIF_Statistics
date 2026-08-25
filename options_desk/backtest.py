#!/usr/bin/env python3
"""
backtest.py  --  Replay recorded chains through the live rules and score them. stdlib only.

Scoring is deliberately modest and honest. It does NOT simulate fills, slippage, assignment
or margin, so it must never be read as a P&L. What it measures is whether a signal carried
information: after each signal fired, which way did the underlying and the ATM vol actually
go, over fixed horizons?

That is enough to answer the question that matters when tuning thresholds -- 'is this rule
picking up anything, or is it firing on noise?' -- without pretending to be a fill engine.
"""

import statistics
from collections import defaultdict

from .engine import Engine
from .history import History


class Backtest:
    """Runs an Engine over recorded snapshots, then scores each signal's forward outcome."""

    def __init__(self, rules, horizons_s=(60, 300, 900)):
        self.rules = rules
        self.horizons = tuple(sorted(horizons_s))
        self.timeline = defaultdict(list)      # underlying -> [(ts, mark_price, vol_metric)]
        self.signals = []
        # Labels come from the snapshots themselves, so an options recording reports IV points
        # and a scalping recording reports VWAP z-scores, through one code path.
        self.vol_label = "vol"
        self.vol_scale = 1.0

    def run(self, snapshots, dispatcher=None):
        from .alerts import Dispatcher
        engine = Engine(provider=None, rules=self.rules,
                        dispatcher=dispatcher or Dispatcher(), history=History())

        def _on_tick(snap, fired):
            self.vol_label, self.vol_scale = snap.VOL_LABEL, snap.VOL_SCALE
            self.timeline[snap.underlying].append((snap.ts, snap.mark_price, snap.vol_metric))
            self.signals.extend(fired)

        stats = engine.replay(snapshots, on_tick=_on_tick)
        self.stats = stats
        return stats

    # -- scoring --------------------------------------------------------------------

    def _forward(self, underlying, ts, horizon_s):
        """(price_return, vol_change) `horizon_s` after ts, or None if the recording ends."""
        series = self.timeline.get(underlying) or []
        base = next(((s, v) for t, s, v in series if t >= ts), None)
        if base is None:
            return None
        target_ts = ts.timestamp() + horizon_s
        fwd = next(((s, v) for t, s, v in series if t.timestamp() >= target_ts), None)
        if fwd is None:
            return None                        # not enough recording left to score honestly
        spot_ret = (fwd[0] - base[0]) / base[0] if base[0] else None
        iv_chg = (fwd[1] - base[1]) if (fwd[1] is not None and base[1] is not None) else None
        return spot_ret, iv_chg

    def score(self):
        """Per-rule forward statistics across every horizon."""
        by_rule = defaultdict(lambda: {"n": 0, "horizons": defaultdict(list)})
        for sig in self.signals:
            entry = by_rule[sig.rule]
            entry["n"] += 1
            for h in self.horizons:
                fwd = self._forward(sig.underlying, sig.ts, h)
                if fwd and fwd[0] is not None:
                    entry["horizons"][h].append(fwd)

        out = {}
        for rule, e in by_rule.items():
            hs = {}
            for h, pairs in e["horizons"].items():
                rets = [p[0] for p in pairs]
                ivs = [p[1] for p in pairs if p[1] is not None]
                if not rets:
                    continue
                hs[h] = {
                    "scored": len(rets),
                    "mean_spot_bp": statistics.fmean(rets) * 10_000,
                    "mean_abs_spot_bp": statistics.fmean(abs(r) for r in rets) * 10_000,
                    "median_spot_bp": statistics.median(rets) * 10_000,
                    "up_rate": sum(1 for r in rets if r > 0) / len(rets),
                    "mean_vol": (statistics.fmean(ivs) * self.vol_scale) if ivs else None,
                }
            out[rule] = {"fired": e["n"], "horizons": hs}
        return out

    def report(self):
        lines = ["", "=" * 78,
                 "BACKTEST -- forward behaviour after each signal",
                 "  Not a P&L. No fills, slippage, assignment or margin are modelled.",
                 "  'spot bp' = basis points the instrument moved after the signal.",
                 "=" * 78]
        scored = self.score()
        if not scored:
            lines.append("  No signals fired over this recording.")
            lines.append("  Either the thresholds are too wide, or the recording is too short")
            lines.append("  to cover the rules' windows (see 'covers' in history.py).")
            return "\n".join(lines)

        for rule, e in sorted(scored.items(), key=lambda kv: -kv[1]["fired"]):
            lines.append(f"\n  {rule}  --  fired {e['fired']}x")
            if not e["horizons"]:
                lines.append("      (no horizon had enough recording left to score)")
            for h in sorted(e["horizons"]):
                s = e["horizons"][h]
                iv = (f"  {self.vol_label} {s['mean_vol']:+.2f}"
                      if s["mean_vol"] is not None else "")
                lines.append(
                    f"      +{h:>4}s  n={s['scored']:<4d} "
                    f"mean {s['mean_spot_bp']:+7.2f}bp  "
                    f"median {s['median_spot_bp']:+7.2f}bp  "
                    f"|move| {s['mean_abs_spot_bp']:6.2f}bp  "
                    f"up {s['up_rate']*100:5.1f}%{iv}")
        lines.append("")
        return "\n".join(lines)
