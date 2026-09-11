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


class ScalpDashboard:
    """
    Intraday levels view: price against VWAP, the CPR, and the pivot ladder.

    Levels are drawn as a single price-sorted ladder with a marker on the row price is
    nearest, because what matters when scalping is not any one level's value but which one you
    are standing on and what is directly above and below.
    """

    def __init__(self, stream=None, max_signals=8):
        self.stream = stream or sys.stderr
        self.tty = self.stream.isatty()
        self.max_signals = max_signals
        self.recent = []
        self.frames = 0

    def _c(self, text, colour):
        return f"{colour}{text}{RESET}" if self.tty else text

    def update(self, snap, hist, signals=()):
        self.recent.extend(signals)
        self.recent = self.recent[-self.max_signals:]
        self.frames += 1
        if self.tty:
            self.stream.write(HOME_CLEAR)
        self.stream.write(self.render(snap, hist) + "\n")
        self.stream.flush()

    def render(self, snap, hist):
        width = min(shutil.get_terminal_size((100, 30)).columns, 96)
        out = [self._header(snap, hist, width)]
        if snap.levels is None:
            out.append("  (no previous session in the data yet -- pivots/CPR unavailable)")
        else:
            out.append(self._ladder(snap, width))
        out.append(self._footer(snap, width))
        return "\n".join(out)

    def _header(self, snap, hist, width):
        chg = hist.series(snap.underlying, "price").pct_change(300)
        chg_s = "  n/a" if chg is None else f"{chg*100:+.2f}%"
        col = GREEN if (chg or 0) > 0 else RED if (chg or 0) < 0 else DIM

        vwap, z = snap.vwap_value, snap.vwap_z
        vwap_s = f"VWAP {vwap:.2f}" if vwap is not None else "VWAP    n/a"
        z_s = f"{z:+.2f}σ" if z is not None else "  n/a"
        rvol = snap.relative_volume()
        session = snap.bars.session
        left = session.minutes_left(snap.ts)

        title = f"{BOLD}{snap.underlying}{RESET}" if self.tty else snap.underlying
        line1 = (f"  {title}  {snap.price:>10,.2f}  " + self._c(f"{chg_s} (5m)", col) +
                 f"   {vwap_s}  {z_s}" +
                 (f"   rvol {rvol:.2f}x" if rvol else ""))
        pos = snap.cpr_position
        pos_col = GREEN if pos == "above" else RED if pos == "below" else YELLOW
        line2 = (f"  {snap.provider} · {snap.exchange} · {snap.interval} · "
                 f"{len(snap.bars)} bars · {left:.0f}m to close · " +
                 self._c(f"{pos} CPR" if pos else "no CPR", pos_col))
        if not self.tty:
            line2 = line2.replace(RESET, "")
        return "\n".join(["=" * width, line1,
                          self._c(line2, DIM) if self.tty else line2, "=" * width])

    def _ladder(self, snap, width):
        rows = ["", f"  {'LEVEL':<8}{'PRICE':>12}   {'DIST':>9}  {'':<4}"]
        rows.append("  " + "-" * (width - 4))
        levels = dict(snap.levels.named())
        if snap.vwap_value is not None:
            levels["VWAP"] = snap.vwap_value

        nearest = min(levels.items(), key=lambda kv: abs(kv[1] - snap.price))[0]
        cpr_names = {"TC", "BC"}
        placed = False
        for name, value in sorted(levels.items(), key=lambda kv: -kv[1]):
            # Drop a marker row the moment we cross below the live price.
            if not placed and value < snap.price:
                rows.append(self._c(f"  {'>>>':<8}{snap.price:>12,.2f}   "
                                    f"{'  spot':>9}", BOLD if self.tty else ""))
                placed = True
            dist = value - snap.price
            tag = "  <<" if name == nearest else ""
            colour = (CYAN if name == "VWAP" else
                      YELLOW if name in cpr_names else
                      GREEN if dist > 0 else RED)
            row = f"  {name:<8}{value:>12,.2f}   {dist:>+9,.2f}{tag}"
            rows.append(self._c(row, colour))
        if not placed:
            rows.append(self._c(f"  {'>>>':<8}{snap.price:>12,.2f}   {'  spot':>9}",
                                BOLD if self.tty else ""))
        return "\n".join(rows)

    def _footer(self, snap, width):
        rows = ["  " + "-" * (width - 4)]
        if snap.levels:
            cpr = snap.levels.cpr
            w = snap.levels.width_pct or 0
            kind = "NARROW (trend day)" if w <= 0.0025 else "wide (range day)" if w >= 0.006 else "normal"
            rows.append(f"  CPR width {cpr['width']:.2f} ({w*100:.3f}% of pivot) -- {kind}")
            rows.append(f"  prev session  H {snap.levels.prev_high:,.2f}  "
                        f"L {snap.levels.prev_low:,.2f}  C {snap.levels.prev_close:,.2f}")
        if snap.vwap_value is not None and snap.vwap.stdev:
            lo1, hi1 = snap.vwap.band(1)
            lo2, hi2 = snap.vwap.band(2)
            rows.append(f"  VWAP bands    1σ {lo1:,.2f} / {hi1:,.2f}    2σ {lo2:,.2f} / {hi2:,.2f}")
        rows.append("")
        rows.append(f"  SIGNALS " + (f"(last {len(self.recent)})" if self.recent else "(none yet)"))
        for s in self.recent:
            rows.append("  " + self._c(s.line(), _SEV.get(s.severity, "")))
        rows.append("")
        rows.append(self._c("  Ctrl-C to stop.  Levels and signals only -- no orders are placed.",
                            DIM))
        return "\n".join(rows)
