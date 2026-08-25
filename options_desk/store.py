#!/usr/bin/env python3
"""
store.py  --  Snapshot recorder + replay source. stdlib only.

Every live tick can be appended to a gzipped JSONL file, partitioned by underlying and UTC
date. That recording is what makes the backtester honest: it replays the exact chains the
live engine saw, through the exact same rules, rather than a reconstruction.

Layout:  <record_dir>/<UNDERLYING>/<YYYY-MM-DD>.jsonl.gz   (one ChainSnapshot per line)

Chains are large and repetitive, so gzip is not optional -- it is roughly a 10x saving on
this data and keeps a multi-day recording practical on disk.
"""

import datetime as dt
import glob
import gzip
import json
import os
import sys

from .models import ChainSnapshot


class Recorder:
    """Append-only writer. Holds one open handle per (symbol, date) and rolls at UTC midnight."""

    def __init__(self, root, enabled=True):
        self.root = root
        self.enabled = enabled
        self._open = {}
        self.written = 0

    def _handle(self, underlying, day):
        key = (underlying, day)
        if key not in self._open:
            d = os.path.join(self.root, underlying)
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"{day.isoformat()}.jsonl.gz")
            # Roll to a new day => close yesterday's handles so nothing is left dangling.
            for k in [k for k in self._open if k[0] == underlying and k[1] != day]:
                self._open.pop(k).close()
            self._open[key] = gzip.open(path, "at", encoding="utf-8")
        return self._open[key]

    def write(self, snap):
        if not self.enabled:
            return
        fh = self._handle(snap.underlying, snap.ts.date())
        fh.write(json.dumps(snap.to_dict(), ensure_ascii=False) + "\n")
        self.written += 1
        # Flush periodically rather than per tick: chains are big and a live desk writes often.
        if self.written % 20 == 0:
            fh.flush()

    def close(self):
        for fh in self._open.values():
            try:
                fh.flush()
                fh.close()
            except OSError:
                pass
        self._open.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def files_for(root, underlying=None, start=None, end=None):
    """Recorded files matching a symbol and inclusive UTC date range, in chronological order."""
    pattern = os.path.join(root, underlying.upper() if underlying else "*", "*.jsonl.gz")
    out = []
    for path in glob.glob(pattern):
        try:
            day = dt.date.fromisoformat(os.path.basename(path).split(".")[0])
        except ValueError:
            continue                       # not one of ours; ignore
        if (start and day < start) or (end and day > end):
            continue
        out.append((day, path))
    return [p for _, p in sorted(out)]


def replay(root, underlying=None, start=None, end=None, limit=None):
    """
    Yield ChainSnapshots from disk in time order.

    A corrupt trailing line is normal -- a recording that was killed mid-write -- so a bad
    line is skipped with a warning instead of aborting a whole backtest.
    """
    n = 0
    for path in files_for(root, underlying, start, end):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield ChainSnapshot.from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                    sys.stderr.write(f"[store] skipping {os.path.basename(path)}:{lineno}: {e}\n")
                    continue
                n += 1
                if limit and n >= limit:
                    return


def summary(root):
    """What has been recorded so far -- ticks and date span per underlying."""
    out = {}
    for path in files_for(root):
        sym = os.path.basename(os.path.dirname(path))
        day = os.path.basename(path).split(".")[0]
        e = out.setdefault(sym, {"days": 0, "ticks": 0, "first": day, "last": day})
        e["days"] += 1
        e["first"], e["last"] = min(e["first"], day), max(e["last"], day)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            e["ticks"] += sum(1 for line in fh if line.strip())
    return out
