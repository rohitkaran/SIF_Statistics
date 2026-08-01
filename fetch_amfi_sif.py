#!/usr/bin/env python3
"""
fetch_amfi_sif.py  --  Download REAL Specialized Investment Fund (SIF) NAVs from AMFI.

Endpoints discovered from the AMFI Next.js bundles (see README.md for the trail):

  ENUMERATE  https://www.amfiindia.com/api/sif-latest-nav
             -> every live SIF scheme variant with its Sd_Id, plan name, category.

  HISTORY    https://www.amfiindia.com/api/sif-nav-history
                 ?query_type=historical_period&sd_id={sd}&from_date={frm}&to_date={to}
             -> full daily NAV series for one Sd_Id (one plan variant).

Both return JSON. sd_id -> exactly one plan variant (1:1), so there is no cross-scheme
duplication. Dates accept either dd-Mmm-yyyy or yyyy-MM-dd; we send dd-Mmm-yyyy (AMFI's
canonical form). AMFI sends NO CORS headers, which is why --serve exists: a file:// page
cannot fetch these directly.

stdlib only. No API key.

Examples:
  python fetch_amfi_sif.py --from 2025-10-01 --to 2026-08-01
  python fetch_amfi_sif.py --latest
  python fetch_amfi_sif.py --serve          # http://127.0.0.1:8765  (+ /refresh?from=&to=)
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import gzip
import io
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------- #
# Endpoints / constants
# --------------------------------------------------------------------------- #

LIST_URL = "https://www.amfiindia.com/api/sif-latest-nav"

# {sd} {frm} {to} placeholders. Overridable with --url.
HIST_URL = (
    "https://www.amfiindia.com/api/sif-nav-history"
    "?query_type=historical_period&sd_id={sd}&from_date={frm}&to_date={to}"
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

DEFAULT_FILTER = r"long[- ]?short|allocator|sector rotation"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# AMFI's chain validates fine on most machines, but some minimal Windows Python
# builds ship without the needed root CA; we fall back to an unverified context so
# a fresh machine still works (public NAV data, no secrets in transit).
_SSL_UNVERIFIED = ssl.create_default_context()
_SSL_UNVERIFIED.check_hostname = False
_SSL_UNVERIFIED.verify_mode = ssl.CERT_NONE


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def http_get(url, timeout=45, retries=4, backoff=1.6):
    """GET with gzip, a browser UA, and retry on transient failures.

    Returns decoded text. Raises the last error on permanent failure.
    """
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.amfiindia.com/sif/latest-nav",
    }
    last = None
    for attempt in range(retries):
        for ctx in (ssl.create_default_context(), _SSL_UNVERIFIED):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                    raw = r.read()
                    if "gzip" in r.headers.get("Content-Encoding", ""):
                        raw = gzip.decompress(raw)
                    elif "deflate" in r.headers.get("Content-Encoding", ""):
                        import zlib
                        raw = zlib.decompress(raw)
                    return raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                # 4xx are permanent (bad params); don't waste retries.
                if 400 <= e.code < 500:
                    raise
                last = e
            except ssl.SSLError as e:
                last = e
                continue  # try the unverified context
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
        time.sleep(backoff ** attempt)
    raise last if last else RuntimeError("unreachable")


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #

def parse_ymd(s):
    return dt.date(*[int(x) for x in s.split("-")])


def amfi_date(d):
    """date -> '01-Oct-2025'."""
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def iso_from_any(s):
    """Normalise an AMFI date string to 'YYYY-MM-DD'.

    Handles '2026-07-31', '2026-07-31T00:00:00.000Z', '31-Jul-2026'.
    """
    s = s.strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T", 1)[0]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$", s)
    if m:
        day, mon, yr = m.groups()
        mi = MONTHS.index(mon.title()) + 1
        return f"{yr}-{mi:02d}-{int(day):02d}"
    return None


def chunk_ranges(frm, to, days):
    """Yield (start, end) date pairs covering [frm, to] in <= `days` windows."""
    cur = frm
    step = dt.timedelta(days=days - 1)
    while cur <= to:
        end = min(cur + step, to)
        yield cur, end
        cur = end + dt.timedelta(days=1)


# --------------------------------------------------------------------------- #
# Parsing AMFI JSON
# --------------------------------------------------------------------------- #

def enumerate_schemes():
    """Return list of dicts: {code, name, cat, sif, isin} for every SIF variant."""
    txt = http_get(LIST_URL)
    j = json.loads(txt)
    out = []
    for top in j.get("data", []):
        for cat in top.get("categories", []):
            for grp in cat.get("groups", []):
                for sc in grp.get("schemes", []):
                    code = sc.get("Sd_Id")
                    if not code:
                        continue
                    out.append({
                        "code": code,
                        "name": sc.get("NavName", "").strip(),
                        "cat": sc.get("category") or cat.get("category", ""),
                        "sif": grp.get("SIFName", ""),
                        "isin": sc.get("ISINPO", ""),
                        "latest_nav": sc.get("NetAssetValue"),
                        "latest_date": iso_from_any(sc.get("Date", "")),
                    })
    return out


def parse_history(txt):
    """historical_period JSON -> list of (iso_date, nav_float)."""
    j = json.loads(txt)
    data = j.get("data")
    if not isinstance(data, dict):
        return []
    pairs = []
    for grp in data.get("nav_groups", []):
        for rec in grp.get("historical_records", []):
            iso = iso_from_any(str(rec.get("date", "")))
            nav = rec.get("nav")
            if iso is None or nav in (None, "", "N.A."):
                continue
            try:
                pairs.append((iso, float(nav)))
            except (TypeError, ValueError):
                continue
    return pairs


def fetch_one_history(code, frm, to, url_tmpl, chunk_days):
    """Full de-duplicated series for one Sd_Id across [frm, to]."""
    by_date = {}
    for a, b in chunk_ranges(frm, to, chunk_days):
        url = url_tmpl.format(sd=urllib.parse.quote(code),
                              frm=amfi_date(a), to=amfi_date(b))
        try:
            txt = http_get(url)
        except Exception as e:
            sys.stderr.write(f"  ! {code} {a}..{b}: {e}\n")
            continue
        for iso, nav in parse_history(txt):
            by_date[iso] = nav  # dedupe by (code, date); last wins
    return sorted(by_date.items())


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def build_dataset(frm, to, filt, url_tmpl, chunk_days, latest_only, workers,
                  progress=True):
    schemes = enumerate_schemes()
    rx = re.compile(filt, re.I) if filt else None
    if rx:
        schemes = [s for s in schemes if rx.search(s["name"]) or rx.search(s["cat"])]

    if progress:
        sys.stderr.write(f"[enumerate] {len(schemes)} schemes match filter\n")

    result = []

    if latest_only:
        for s in schemes:
            series = []
            if s["latest_date"] and s["latest_nav"] is not None:
                series = [[s["latest_date"], float(s["latest_nav"])]]
            result.append(_row(s, series))
        return _package(result)

    def work(s):
        series = fetch_one_history(s["code"], frm, to, url_tmpl, chunk_days)
        return _row(s, [[d, n] for d, n in series])

    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, s): s for s in schemes}
        for fut in cf.as_completed(futs):
            row = fut.result()
            result.append(row)
            done += 1
            if progress and (done % 10 == 0 or done == len(schemes)):
                sys.stderr.write(f"[history] {done}/{len(schemes)}\n")

    # stable order: by category then name
    result.sort(key=lambda r: (r["cat"], r["name"]))
    return _package(result)


def _row(s, series):
    return {
        "code": s["code"],
        "name": s["name"],
        "cat": s["cat"],
        "sif": s.get("sif", ""),
        "isin": s.get("isin", ""),
        "series": series,
    }


def _package(rows):
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    return {
        "generated": now.isoformat(),
        "source": "AMFI api/sif-nav-history (historical_period) + api/sif-latest-nav",
        "schemes": rows,
    }


# --------------------------------------------------------------------------- #
# Serve mode
# --------------------------------------------------------------------------- #

def serve(directory, host, port, default_url, chunk_days, workers):
    import http.server
    import functools

    class Handler(http.server.SimpleHTTPRequestHandler):
        # HTTP/1.1 keep-alive + Content-Length. HTTP/1.0 (the stdlib default)
        # closes the socket after each reply; Chrome, which pipelines the favicon
        # and preconnect requests, then sees ERR_CONNECTION_RESET on the larger
        # in-flight nav_data.json. HTTP/1.1 keeps the connection alive cleanly.
        protocol_version = "HTTP/1.1"

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.end_headers()

        def log_message(self, fmt, *args):
            sys.stderr.write("  " + (fmt % args) + "\n")

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.rstrip("/") == "/refresh":
                return self._refresh(urllib.parse.parse_qs(parsed.query))
            return super().do_GET()

        def _refresh(self, q):
            try:
                today = dt.date.today()
                frm = parse_ymd(q.get("from", ["2025-10-01"])[0])
                to = parse_ymd(q.get("to", [today.isoformat()])[0])
                filt = q.get("filter", [DEFAULT_FILTER])[0]
                latest = q.get("latest", ["0"])[0] in ("1", "true", "yes")
                sys.stderr.write(f"[refresh] {frm}..{to} latest={latest}\n")
                data = build_dataset(frm, to, filt, default_url, chunk_days,
                                     latest, workers, progress=True)
                # persist so a plain page load picks it up too
                with open(f"{directory}/nav_data.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                body = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    handler = functools.partial(Handler, directory=directory)
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    print(f"Serving {directory} at http://{host}:{port}")
    print(f"  dashboard : http://{host}:{port}/sif_dashboard.html")
    print(f"  refresh   : http://{host}:{port}/refresh?from=2025-10-01&to={dt.date.today()}")
    print("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None):
    p = argparse.ArgumentParser(description="Download real AMFI SIF NAVs.")
    p.add_argument("--from", dest="frm", default="2025-10-01",
                   help="start date YYYY-MM-DD (default 2025-10-01)")
    p.add_argument("--to", dest="to", default=dt.date.today().isoformat(),
                   help="end date YYYY-MM-DD (default today)")
    p.add_argument("--filter", default=DEFAULT_FILTER,
                   help="scheme name/category regex (default: long-short|allocator|sector rotation)")
    p.add_argument("--out", default="nav_data.json", help="output file")
    p.add_argument("--url", default=HIST_URL,
                   help="history URL template with {sd} {frm} {to} placeholders")
    p.add_argument("--chunk-days", type=int, default=365,
                   help="split long ranges into windows this many days wide")
    p.add_argument("--workers", type=int, default=8, help="parallel fetch workers")
    p.add_argument("--latest", action="store_true",
                   help="today's snapshot only (uses api/sif-latest-nav)")
    p.add_argument("--serve", action="store_true",
                   help="serve this folder on 127.0.0.1:8765 with CORS + /refresh")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--dir", default=".", help="folder to serve (default: cwd)")
    args = p.parse_args(argv)

    if args.serve:
        serve(args.dir, args.host, args.port, args.url, args.chunk_days, args.workers)
        return 0

    frm = parse_ymd(args.frm)
    to = parse_ymd(args.to)
    if frm > to:
        p.error("--from is after --to")

    data = build_dataset(frm, to, args.filter, args.url, args.chunk_days,
                         args.latest, args.workers)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    n_pts = sum(len(s["series"]) for s in data["schemes"])
    dated = [d for s in data["schemes"] for d, _ in s["series"]]
    lo = min(dated) if dated else "-"
    hi = max(dated) if dated else "-"
    sys.stderr.write(
        f"[done] wrote {args.out}: {len(data['schemes'])} schemes, "
        f"{n_pts} NAV points, {lo} .. {hi}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
