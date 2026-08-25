#!/usr/bin/env python3
"""
engine.py  --  The real-time loop: snapshot -> history -> rules -> cooldown -> alerts. stdlib only.

One class does live and replay alike. That is the whole point: `tick()` is pure with respect
to wall-clock time (it keys everything off the snapshot's own timestamp), so the backtester
feeds it recorded snapshots and gets exactly what the live desk would have produced. If this
ever starts calling datetime.now(), live and backtest have silently diverged.
"""

import datetime as dt
import signal as _signal
import sys
import threading

from .history import History


class Engine:
    def __init__(self, provider, rules, dispatcher, recorder=None,
                 history=None, retention_s=None):
        self.provider = provider
        self.rules = list(rules)
        self.dispatcher = dispatcher
        self.recorder = recorder
        self.history = history or History(retention_s or 6 * 3600)
        self._last_fired = {}                 # signal.key -> snapshot ts of last emission
        self.stats = {"ticks": 0, "signals": 0, "suppressed": 0, "errors": 0,
                      "by_rule": {}, "first_ts": None, "last_ts": None}

    # -- one unit of work ----------------------------------------------------------

    def tick(self, snap):
        """
        Fold one snapshot in and return the signals that survived cooldown.

        Order matters: history is updated BEFORE rules run, so a rule always sees the current
        tick included in its own window.
        """
        self.history.update(snap)
        if self.recorder:
            self.recorder.write(snap)

        self.stats["ticks"] += 1
        self.stats["first_ts"] = self.stats["first_ts"] or snap.ts
        self.stats["last_ts"] = snap.ts

        fired = []
        for rule in self.rules:
            if not rule.applies_to(snap.underlying):
                continue
            try:
                produced = rule.evaluate(snap, self.history) or []
            except Exception as e:            # noqa: BLE001 - a broken rule must not stop the desk
                self.stats["errors"] += 1
                sys.stderr.write(f"[engine] rule {rule.name} raised "
                                 f"{type(e).__name__}: {e}\n")
                continue
            for sig in produced:
                if self._cooled(sig, rule.cooldown_s):
                    fired.append(sig)
                    self.stats["signals"] += 1
                    self.stats["by_rule"][sig.rule] = self.stats["by_rule"].get(sig.rule, 0) + 1
                else:
                    self.stats["suppressed"] += 1

        self.dispatcher.emit_all(fired)
        return fired

    def _cooled(self, sig, cooldown_s):
        """
        True if this signal key is outside its cooldown.

        Keyed on snapshot time, not wall clock, so replaying a recording applies the identical
        suppression the live run did.
        """
        prev = self._last_fired.get(sig.key)
        if prev is not None and (sig.ts - prev).total_seconds() < cooldown_s:
            return False
        self._last_fired[sig.key] = sig.ts
        return True

    # -- live -----------------------------------------------------------------------

    def run(self, underlyings, interval=5.0, stop=None, on_tick=None, max_ticks=None):
        """Drive the provider stream until stopped. Returns the stats dict."""
        stop = stop or threading.Event()
        try:
            for _sym, snap in self.provider.stream(underlyings, interval, stop):
                fired = self.tick(snap)
                if on_tick:
                    on_tick(snap, fired)
                if max_ticks and self.stats["ticks"] >= max_ticks:
                    break
                if stop.is_set():
                    break
        except KeyboardInterrupt:
            sys.stderr.write("\n[engine] interrupted\n")
        finally:
            if self.recorder:
                self.recorder.close()
            self.dispatcher.close()
        return self.stats

    def replay(self, snapshots, on_tick=None):
        """Feed recorded snapshots through the identical path. Returns the stats dict."""
        for snap in snapshots:
            fired = self.tick(snap)
            if on_tick:
                on_tick(snap, fired)
        return self.stats

    def report(self):
        s = self.stats
        span = ""
        if s["first_ts"] and s["last_ts"]:
            mins = (s["last_ts"] - s["first_ts"]).total_seconds() / 60
            span = f" over {mins:.1f} min ({s['first_ts']:%H:%M:%S}-{s['last_ts']:%H:%M:%S} UTC)"
        lines = [f"[engine] {s['ticks']} ticks{span}",
                 f"[engine] {s['signals']} signals fired, {s['suppressed']} suppressed by cooldown"]
        for rule, n in sorted(s["by_rule"].items(), key=lambda kv: -kv[1]):
            lines.append(f"           {n:5d}  {rule}")
        if s["errors"]:
            lines.append(f"[engine] {s['errors']} rule errors (see above)")
        return "\n".join(lines)


def install_sigint(stop_event):
    """Ctrl-C sets the stop event so the desk shuts down cleanly and flushes its recording."""
    def _handler(_sig, _frm):
        if stop_event.is_set():
            raise KeyboardInterrupt        # second Ctrl-C = give up immediately
        sys.stderr.write("\n[engine] stopping (Ctrl-C again to force)...\n")
        stop_event.set()
    try:
        _signal.signal(_signal.SIGINT, _handler)
    except ValueError:
        pass                               # not on the main thread; caller drives stop itself
    return stop_event
