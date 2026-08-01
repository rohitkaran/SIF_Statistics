#!/usr/bin/env python3
"""
fetch_benchmark.py  --  Download a daily benchmark index series (NIFTY 50) for up/down capture.

The dashboard's up-/down-capture columns compare each fund's daily returns against the market
on days the market rose vs fell. That needs a daily index series aligned to fund NAV dates.

Source: Yahoo Finance chart API for ^NSEI (NIFTY 50) -> benchmark_data.json. stdlib only.

  python fetch_benchmark.py --from 2025-09-25            # default from 2025-09-25 to today
"""

import argparse
import datetime as dt
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

SYMBOL = "^NSEI"           # NIFTY 50
NAME = "NIFTY 50"


def epoch(d):
    return int(dt.datetime(d.year, d.month, d.day).timestamp())


def fetch(frm, to):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(SYMBOL)
           + f"?period1={epoch(frm)}&period2={epoch(to)}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45, context=_CTX) as r:
        j = json.loads(r.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(ts, close):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")
        out.append([d, round(float(c), 2)])
    # dedupe by date (last wins), sorted
    by = {}
    for d, c in out:
        by[d] = c
    return sorted(by.items())


def main(argv=None):
    p = argparse.ArgumentParser(description="Download NIFTY 50 daily closes for capture ratios.")
    p.add_argument("--from", dest="frm", default="2025-09-25")
    p.add_argument("--to", dest="to", default=dt.date.today().isoformat())
    p.add_argument("--out", default="benchmark_data.json")
    a = p.parse_args(argv)
    frm = dt.date(*[int(x) for x in a.frm.split("-")])
    to = dt.date(*[int(x) for x in a.to.split("-")]) + dt.timedelta(days=1)
    series = fetch(frm, to)
    data = {
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "index": NAME, "symbol": SYMBOL, "source": "Yahoo Finance chart API",
        "series": [[d, c] for d, c in series],
    }
    with open(os.path.join(HERE, a.out), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    lo = series[0][0] if series else "-"
    hi = series[-1][0] if series else "-"
    sys.stderr.write(f"[benchmark] {NAME}: {len(series)} closes, {lo} .. {hi} -> {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
