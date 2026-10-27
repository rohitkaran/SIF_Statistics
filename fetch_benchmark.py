#!/usr/bin/env python3
"""
fetch_benchmark.py  --  Download daily benchmark index series for the dashboard.

Two uses:
  * up/down capture ratios (vs NIFTY 50) on the main terminal, and
  * the Monthly view, which compares fund monthly returns against NIFTY 50 and
    NIFTY Midcap 100.

Source: Yahoo Finance chart API -> benchmark_data.json. stdlib only.

Output keeps NIFTY 50 at the top level (index/symbol/series) for backward
compatibility with the capture-ratio code, and adds an `indices` list with every
index fetched:

  {"generated", "source",
   "index": "NIFTY 50", "symbol": "^NSEI", "series": [[date, close], ...],
   "indices": [{"index","symbol","series"}, ...]}

  python fetch_benchmark.py --from 2025-09-25
"""

import argparse
import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# (display name, Yahoo symbol). The first entry is the primary benchmark and is
# also written at the top level for the capture-ratio code.
INDICES = [
    ("NIFTY 50", "^NSEI"),
    ("NIFTY Midcap 50", "^NSEMDCP50"),   # Midcap 100 has no history on Yahoo; 50 does
]


def epoch(d):
    return int(dt.datetime(d.year, d.month, d.day).timestamp())


def fetch(symbol, frm, to, retries=4):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(symbol)
           + f"?period1={epoch(frm)}&period2={epoch(to)}&interval=1d")
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45, context=_CTX) as r:
                j = json.loads(r.read())
            res = j["chart"]["result"][0]
            ts = res["timestamp"]
            close = res["indicators"]["quote"][0]["close"]
            by = {}
            for t, c in zip(ts, close):
                if c is None:
                    continue
                d = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")
                by[d] = round(float(c), 2)
            return sorted(by.items())
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError("unreachable")


def main(argv=None):
    p = argparse.ArgumentParser(description="Download NIFTY 50 + Midcap daily closes.")
    p.add_argument("--from", dest="frm", default="2025-09-25")
    p.add_argument("--to", dest="to", default=dt.date.today().isoformat())
    p.add_argument("--out", default="benchmark_data.json")
    a = p.parse_args(argv)
    frm = dt.date(*[int(x) for x in a.frm.split("-")])
    to = dt.date(*[int(x) for x in a.to.split("-")]) + dt.timedelta(days=1)

    indices = []
    for name, sym in INDICES:
        try:
            series = fetch(sym, frm, to)
        except Exception as e:
            sys.stderr.write(f"::warning::benchmark {name} ({sym}) failed: {e}\n")
            continue
        indices.append({"index": name, "symbol": sym,
                        "series": [[d, c] for d, c in series]})
        lo = series[0][0] if series else "-"
        hi = series[-1][0] if series else "-"
        sys.stderr.write(f"[benchmark] {name}: {len(series)} closes, {lo} .. {hi}\n")
        time.sleep(0.4)

    if not indices:
        sys.stderr.write("::error::no benchmark indices fetched\n")
        return 1

    primary = indices[0]
    data = {
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source": "Yahoo Finance chart API",
        "index": primary["index"], "symbol": primary["symbol"],
        "series": primary["series"],      # backward compat (capture ratios vs NIFTY 50)
        "indices": indices,               # all indices for the Monthly view
    }
    with open(os.path.join(HERE, a.out), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    sys.stderr.write(f"[benchmark] wrote {len(indices)} index series -> {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
