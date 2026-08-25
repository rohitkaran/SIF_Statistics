#!/usr/bin/env python3
"""
dashboard.py  --  Terminal render of a live chain. stdlib only, no curses.

Redraws a full frame on each tick using ANSI home+erase rather than curses, so it works
unchanged over SSH, inside CI logs and when piped to a file (colour and cursor control are
dropped automatically when stderr is not a TTY).

Layout is the conventional option-desk ladder: calls on the left, strikes down the middle,
puts on the right, ATM row highlighted.
"""

import datetime as dt
import shutil
import sys

from .history import skew_25d, nearest_delta

HOME_CLEAR = "\033[H\033[J"
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
GREEN, RED, YELLOW, CYAN = "\033[32m", "\033[31m", "\033[33m", "\033[36m"
_SEV = {"info": CYAN, "warn": YELLOW, "alert": RED}


class Dashboard:
    """Stateful renderer -- keeps the recent-signal tail between frames."""

    def __init__(self, stream=None, rows=9, max_signals=6):
        self.stream = stream or sys.stderr
        self.tty = self.stream.isatty()
        self.rows = rows                    # strikes shown either side of ATM
        self.max_signals = max_signals
        self.recent = []
        self.frames = 0

    def _c(self, text, colour):
        return f"{colour}{text}{RESET}" if self.tty else text

    def update(self, snap, hist, signals=()):
        self.recent.extend(signals)
        self.recent = self.recent[-self.max_signals:]
        self.frames += 1
        frame = self.render(snap, hist)
        if self.tty:
            self.stream.write(HOME_CLEAR)
        self.stream.write(frame + "\n")
        self.stream.flush()

    def render(self, snap, hist):
        width = min(shutil.get_terminal_size((100, 30)).columns, 110)
        out = [self._header(snap, hist, width)]
        exp = snap.nearest_expiry()
        if exp is None:
            out.append("  (no expiries in snapshot)")
            return "\n".join(out)
        out.append(self._ladder(snap, exp))
        out.append(self._footer(snap, exp, width))
        return "\n".join(out)

    # -- sections -------------------------------------------------------------------

    def _header(self, snap, hist, width):
        spot_s = hist.series(snap.underlying, "spot")
        chg = spot_s.pct_change(300)
        chg_s = "   n/a" if chg is None else f"{chg*100:+.2f}%"
        chg_col = GREEN if (chg or 0) > 0 else RED if (chg or 0) < 0 else DIM

        iv = snap.atm_iv()
        iv_chg = hist.series(snap.underlying, "atm_iv").change(300)
        sk = skew_25d(snap)

        title = (f"{BOLD}{snap.underlying}{RESET}  {snap.spot:>10,.2f}  "
                 if self.tty else f"{snap.underlying}  {snap.spot:>10,.2f}  ")
        bits = [
            title + self._c(f"{chg_s} (5m)", chg_col),
            f"ATM IV {iv*100:6.2f}%" if iv else "ATM IV    n/a",
            f"Δ5m {iv_chg*100:+.2f}pts" if iv_chg is not None else "Δ5m   n/a",
            f"25d skew {sk*100:+.2f}pts" if sk is not None else "25d skew  n/a",
        ]
        line1 = "  " + "   ".join(bits)
        line2 = (f"  {DIM}{snap.provider} · {snap.ts:%Y-%m-%d %H:%M:%S} UTC · "
                 f"{len(snap.quotes)} contracts · frame {self.frames}{RESET}"
                 if self.tty else
                 f"  {snap.provider} · {snap.ts:%Y-%m-%d %H:%M:%S} UTC · "
                 f"{len(snap.quotes)} contracts · frame {self.frames}")
        return "\n".join(["=" * width, line1, line2, "=" * width])

    def _ladder(self, snap, exp):
        dte = (exp - snap.ts.date()).days
        head = (f"\n  {exp:%d %b %Y} ({dte}dte)\n"
                f"  {'CALLS':^46}   {'':^9}   {'PUTS':^46}\n"
                f"  {'bid':>7} {'ask':>7} {'iv':>7} {'delta':>7} {'oi':>7} {'vol':>7}"
                f"   {'STRIKE':^9}   "
                f"{'bid':>7} {'ask':>7} {'iv':>7} {'delta':>7} {'oi':>7} {'vol':>7}")
        rows = [head, "  " + "-" * 108]

        strikes = snap.strikes(exp)
        if not strikes:
            return "\n".join(rows + ["  (no strikes)"])
        atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - snap.spot))
        lo, hi = max(0, atm - self.rows), min(len(strikes), atm + self.rows + 1)

        for i in range(lo, hi):
            k = strikes[i]
            c, p = snap.get(exp, k, "C"), snap.get(exp, k, "P")
            is_atm = (i == atm)
            mid = f"{k:>9,.2f}"
            if is_atm:
                mid = self._c(f"{BOLD}{k:>9,.2f}{RESET}" if self.tty else f"{k:>9,.2f}", YELLOW)
            rows.append(f"  {self._side(c)}   {mid}   {self._side(p)}")
        return "\n".join(rows)

    def _side(self, q):
        if q is None:
            return " " * 46
        f = lambda v, w, p=2: (f"{v:>{w}.{p}f}" if isinstance(v, (int, float)) else f"{'-':>{w}}")
        iv = f"{q.iv*100:>7.2f}" if q.iv else f"{'-':>7}"
        dl = f"{q.delta:>7.3f}" if q.delta is not None else f"{'-':>7}"
        oi = f"{q.open_interest:>7,}" if q.open_interest is not None else f"{'-':>7}"
        vol = f"{q.volume:>7,}" if q.volume is not None else f"{'-':>7}"
        return f"{f(q.bid,7)} {f(q.ask,7)} {iv} {dl} {oi} {vol}"

    def _footer(self, snap, exp, width):
        rows = ["  " + "-" * 108]
        # Name the strikes a desk actually quotes, so the ladder has an anchor.
        for tag, right, target in (("25d put", "P", 0.25), ("25d call", "C", 0.25)):
            q = nearest_delta(snap, exp, right, target)
            if q:
                rows.append(f"  {tag:>9}: {q.contract.strike:>9,.2f} "
                            f"mid {q.mid if q.mid is not None else float('nan'):>7.2f} "
                            f"iv {(q.iv or 0)*100:>6.2f}%  oi {q.open_interest or 0:>8,}")
        rows.append("")
        rows.append(f"  {'SIGNALS':<12}" + (f"(last {len(self.recent)})" if self.recent else "(none yet)"))
        for s in self.recent:
            rows.append("  " + self._c(s.line(), _SEV.get(s.severity, "")))
        rows.append("")
        rows.append(self._c("  Ctrl-C to stop.  Data is informational only -- no orders are placed.",
                            DIM))
        return "\n".join(rows)
