#!/usr/bin/env python3
"""
fetch_sif_portfolios.py  --  Download & normalise fund-house PORTFOLIO disclosures for SIFs.

SIFs (Specialized Investment Funds) disclose their holdings BI-MONTHLY (every alternate
month -- a SEBI rule), NOT monthly. AMFI does not host the holdings: its "Portfolio
Disclosure" page, like the mutual-fund one, only links out to each AMC's own website. So --
unlike NAVs (see fetch_amfi_sif.py, which hits real AMFI JSON APIs) -- portfolios must be
pulled per-AMC, from heterogeneous Excel/PDF files.

This script is registry-driven (portfolios/registry.json). Each AMC has an *adapter* that
knows how to (1) discover the disclosure file for a period on that AMC's site, (2) download
it verbatim into portfolios/raw/, and (3) parse it into a normalised holdings JSON under
portfolios/data/. An index.json maps every dashboard scheme code to the periods available.

Adding an AMC = one registry entry + (only if the file layout is new) one adapter here.

Requires: openpyxl (xlsx), pdfplumber (pdf).  Install: pip install -r requirements.txt

Examples:
  python fetch_sif_portfolios.py                       # all AMCs, latest disclosed period
  python fetch_sif_portfolios.py --amc apex --period 2026-05
  python fetch_sif_portfolios.py --file mine.xlsx --amc apex   # normalise a hand-downloaded file
  python fetch_sif_portfolios.py --list                # show what's already stored
"""

import argparse
import datetime as dt
import io
import json
import os
import re
import ssl
import statistics
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_SSL_UNVERIFIED = ssl.create_default_context()
_SSL_UNVERIFIED.check_hostname = False
_SSL_UNVERIFIED.verify_mode = ssl.CERT_NONE

ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")


# --------------------------------------------------------------------------- #
# HTTP  (mirrors the NAV fetcher: browser UA, retries, SSL fallback)
# --------------------------------------------------------------------------- #

def http_get(url, timeout=60, retries=3, backoff=1.6):
    """GET raw bytes with a browser UA and retry on transient failures."""
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "identity"}
    last = None
    for attempt in range(retries):
        for ctx in (ssl.create_default_context(), _SSL_UNVERIFIED):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500:
                    raise
                last = e
            except (ssl.SSLError,) as e:
                last = e
                continue
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
        import time
        time.sleep(backoff ** attempt)
    raise last if last else RuntimeError("unreachable")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def norm(s):
    """Lower-case, keep only alphanumerics -- for fuzzy name matching."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s in ("-", "NA", "N.A.", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_registry():
    with open(os.path.join(HERE, "portfolios", "registry.json"), encoding="utf-8") as f:
        return json.load(f)


def load_nav_schemes():
    """code -> {name, sif} from nav_data.json, so disclosed funds map to dashboard codes."""
    path = os.path.join(HERE, "nav_data.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return [{"code": s["code"], "name": s.get("name", ""), "sif": s.get("sif", "")}
            for s in d.get("schemes", [])]


def match_codes(fund_name, amc_schemes):
    """Dashboard scheme codes whose name belongs to this disclosed fund.

    A portfolio is per FUND, but the dashboard tracks per PLAN VARIANT (Direct/Regular x
    Growth/IDCW). So one disclosed fund maps to several scheme codes.
    """
    fn = norm(fund_name)
    if not fn:
        return []
    out = []
    for s in amc_schemes:
        sn = norm(s["name"])
        # scheme name usually starts with the fund name, then " - Direct Plan - Growth"
        if sn.startswith(fn) or fn in sn:
            out.append(s["code"])
    return out


# --------------------------------------------------------------------------- #
# ABSL adapter  (Apex SIF -- Aditya Birla Sun Life AMC)
#   File: /uploads/DDMMYYYY_ABSLMF_Monthly_SIF_<hash>.xlsx
#   Layout: an "Index" sheet (fund code -> name) + one sheet per fund, each with a header
#   row "Name of the Instrument | ISIN | Industry | Quantity | Market Value (Rs.Lacs) |
#   % to Net Assets", cash-market holdings, then futures/options long-short sections.
# --------------------------------------------------------------------------- #

TOP_CATEGORIES = {
    "equity & equity related": "equity",
    "debt instruments": "debt",
    "money market instruments": "money_market",
    "others": "others",
    "net receivables / (payables)": "net_receivables",
    "net receivables/(payables)": "net_receivables",
}


def absl_discover(amc_cfg):
    """Return [{period, as_of, url, filename}] for every ABSLMF Monthly SIF file listed."""
    pat = re.compile(amc_cfg["file_pattern"])
    fmt = amc_cfg.get("date_format", "%d%m%Y")
    site = amc_cfg["site"].rstrip("/")
    found = {}
    for listing in amc_cfg.get("listing_urls", [amc_cfg["site"]]):
        try:
            html = http_get(listing).decode("utf-8", "replace")
        except Exception as e:
            sys.stderr.write(f"  ! {listing}: {e}\n")
            continue
        for m in pat.finditer(html):
            path = m.group(0)
            try:
                d = dt.datetime.strptime(m.group("date"), fmt).date()
            except ValueError:
                continue
            url = path if path.startswith("http") else site + path
            found[url] = {"period": f"{d.year}-{d.month:02d}", "as_of": d.isoformat(),
                          "url": url, "filename": os.path.basename(path)}
    return sorted(found.values(), key=lambda x: x["as_of"])


def _find_header(rows):
    """Locate the holdings header row and its column indices, by header NAME (not index)."""
    for i, row in enumerate(rows):
        cells = [str(c).lower() if c is not None else "" for c in row]
        joined = " | ".join(cells)
        if "name of the instrument" in joined and "% to net asset" in joined:
            def col(*keys):
                for k in keys:
                    for j, c in enumerate(cells):
                        if k in c:
                            return j
                return -1
            return i, {
                "name": col("name of the instrument"),
                "isin": col("isin"),
                "industry": col("industry", "rating"),
                "qty": col("quantity"),
                "mv": col("market", "fair value"),
                "pct": col("% to net asset"),
            }
    return -1, None


def absl_parse_workbook(xlsx_bytes, source_url, meta):
    """Parse an ABSL Monthly SIF workbook -> list of normalised per-fund portfolio dicts."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)

    # fund sheets = every sheet except a leading "Index" map
    fund_sheets = [s for s in wb.sheetnames if s.lower() != "index"]
    funds = []
    for sn in fund_sheets:
        ws = wb[sn]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        hi, cols = _find_header(rows)
        if hi < 0:
            continue
        c = cols
        fund_name = str(rows[0][1] if len(rows[0]) > 1 and rows[0][1] else sn).strip()

        holdings, sectors, allocation, derivatives = [], {}, {}, []
        cur_cat = None
        for r in rows[hi + 1:]:
            def cell(k):
                j = c[k]
                return r[j] if 0 <= j < len(r) else None
            name = (str(cell("name")).strip() if cell("name") is not None else "")
            isin = (str(cell("isin")).strip() if cell("isin") is not None else "")
            pct = to_float(cell("pct"))
            low = name.lower()

            if low in TOP_CATEGORIES:
                cur_cat = TOP_CATEGORIES[low]
                if cur_cat in ("net_receivables",) and pct is not None:
                    allocation[cur_cat] = round(pct * 100, 4)
                continue
            if low == "grand total":
                allocation["grand_total"] = round((pct or 1) * 100, 4)
                break                       # cash-market book ends here
            if low in ("total", "sub total", "subtotal"):
                if low == "total" and cur_cat and pct is not None:
                    allocation[cur_cat] = round(pct * 100, 4)   # last "Total" per category wins
                continue

            if ISIN_RE.match(isin) and pct is not None:
                mv = to_float(cell("mv"))
                h = {
                    "name": name,
                    "isin": isin,
                    "sector": (str(cell("industry")).strip() if cell("industry") else ""),
                    "qty": to_float(cell("qty")),
                    "mv_cr": round(mv / 100, 4) if mv is not None else None,  # Rs.Lacs -> Cr
                    "weight": round(pct * 100, 4),
                    "category": cur_cat or "equity",
                    "position": "Long",
                }
                holdings.append(h)
                if h["category"] == "equity" and h["sector"]:
                    sectors[h["sector"]] = round(sectors.get(h["sector"], 0) + h["weight"], 4)

        # derivative (futures/options) long-short exposure, below GRAND TOTAL
        derivatives = _absl_derivatives(rows)

        # net assets: derive from any liquid holding's mv / weight (Rs.Cr)
        net = None
        ratios = [h["mv_cr"] / (h["weight"] / 100) for h in holdings
                  if h.get("mv_cr") and h["weight"] and h["weight"] > 0.05]
        if ratios:
            net = round(statistics.median(ratios), 2)

        holdings.sort(key=lambda h: -(h["weight"] or 0))
        top = holdings[:10]
        sector_list = sorted(({"sector": k, "weight": v} for k, v in sectors.items()),
                             key=lambda x: -x["weight"])
        funds.append({
            "amc": meta["amc"],
            "fund_code": sn,
            "fund_name": fund_name,
            "period": meta["period"],
            "as_of": meta["as_of"],
            "source_url": source_url,
            "raw": meta["raw"],
            "fetched": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "net_assets_cr": net,
            "n_holdings": len(holdings),
            "allocation": allocation,
            "sectors": sector_list,
            "derivatives": derivatives,
            "top": top,
            "holdings": holdings,
        })
    return funds


def _absl_derivatives(rows):
    """Scan futures/options sections (a 'Long/Short' + '% to Net Assets' table) below the book."""
    out = []
    i = 0
    while i < len(rows):
        cells = [str(x).lower() if x is not None else "" for x in rows[i]]
        joined = " | ".join(cells)
        if "long/short" in joined and "% to net asset" in joined:
            ls_col = next((j for j, x in enumerate(cells) if "long/short" in x), -1)
            pct_col = next((j for j, x in enumerate(cells) if "% to net asset" in x), -1)
            nm_col = next((j for j, x in enumerate(cells) if "underlying" in x), 1)
            for r in rows[i + 1:]:
                pos = str(r[ls_col]).strip() if 0 <= ls_col < len(r) and r[ls_col] else ""
                if pos.lower() not in ("long", "short"):
                    break                       # end of this derivative table
                pct = to_float(r[pct_col]) if 0 <= pct_col < len(r) else None
                nm = str(r[nm_col]).strip() if 0 <= nm_col < len(r) and r[nm_col] else ""
                if nm and pct is not None:
                    out.append({"underlying": nm, "position": pos.title(),
                                "weight": round(pct * 100, 4)})
        i += 1
    return out


# --------------------------------------------------------------------------- #
# generic xlsx adapter  (for --file: any AMC's hand-downloaded sheet)
# --------------------------------------------------------------------------- #

def generic_parse_xlsx(xlsx_bytes, source_url, meta):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    funds = []
    for sn in wb.sheetnames:
        ws = wb[sn]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        hi, cols = _find_header(rows)
        if hi < 0:
            continue
        holdings, sectors = [], {}
        for r in rows[hi + 1:]:
            def cell(k):
                j = cols[k]
                return r[j] if 0 <= j < len(r) else None
            isin = (str(cell("isin")).strip() if cell("isin") else "")
            pct = to_float(cell("pct"))
            if ISIN_RE.match(isin) and pct is not None:
                mv = to_float(cell("mv"))
                sec = (str(cell("industry")).strip() if cell("industry") else "")
                w = round(pct * 100, 4)
                holdings.append({"name": str(cell("name")).strip(), "isin": isin,
                                 "sector": sec, "qty": to_float(cell("qty")),
                                 "mv_cr": round(mv / 100, 4) if mv else None,
                                 "weight": w, "category": "equity", "position": "Long"})
                if sec:
                    sectors[sec] = round(sectors.get(sec, 0) + w, 4)
        if not holdings:
            continue
        holdings.sort(key=lambda h: -(h["weight"] or 0))
        funds.append({
            "amc": meta["amc"], "fund_code": sn, "fund_name": sn,
            "period": meta["period"], "as_of": meta["as_of"], "source_url": source_url,
            "raw": meta["raw"],
            "fetched": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "net_assets_cr": None, "n_holdings": len(holdings), "allocation": {},
            "sectors": sorted(({"sector": k, "weight": v} for k, v in sectors.items()),
                              key=lambda x: -x["weight"]),
            "derivatives": [], "top": holdings[:10], "holdings": holdings})
    return funds


ADAPTERS = {"absl": absl_parse_workbook, "generic_xlsx": generic_parse_xlsx}
DISCOVERERS = {"absl": absl_discover}


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #

def out_dir():
    return os.path.join(HERE, "portfolios")


def save_raw(amc, period, filename, data):
    d = os.path.join(out_dir(), "raw", amc, period)
    os.makedirs(d, exist_ok=True)
    rel = os.path.join("portfolios", "raw", amc, period, filename).replace("\\", "/")
    with open(os.path.join(HERE, rel), "wb") as f:
        f.write(data)
    return rel


def save_fund(fund):
    d = os.path.join(out_dir(), "data", fund["period"])
    os.makedirs(d, exist_ok=True)
    fname = f'{fund["amc"]}__{fund["fund_code"]}.json'
    rel = os.path.join("portfolios", "data", fund["period"], fname).replace("\\", "/")
    with open(os.path.join(HERE, rel), "w", encoding="utf-8") as f:
        json.dump(fund, f, ensure_ascii=False, indent=1)
    return rel


def rebuild_index():
    """Scan portfolios/data/** and (re)write portfolios/index.json mapping code -> periods."""
    reg = load_registry()
    schemes = {}
    periods = set()
    amcs = {k: {"name": v["name"], "site": v["site"],
                "disclosure_page": v.get("disclosure_page", v["site"])}
            for k, v in reg["amcs"].items()}
    data_root = os.path.join(out_dir(), "data")
    if os.path.isdir(data_root):
        for period in sorted(os.listdir(data_root)):
            pdir = os.path.join(data_root, period)
            if not os.path.isdir(pdir):
                continue
            for fn in sorted(os.listdir(pdir)):
                if not fn.endswith(".json"):
                    continue
                rel = f"portfolios/data/{period}/{fn}"
                with open(os.path.join(pdir, fn), encoding="utf-8") as f:
                    fund = json.load(f)
                periods.add(period)
                for code in fund.get("_codes", []):
                    e = schemes.setdefault(code, {"name": fund["fund_name"],
                                                  "amc": fund["amc"],
                                                  "fund": fund["fund_name"], "periods": {}})
                    e["periods"][period] = rel
    idx = {
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "note": "SIFs disclose portfolios bi-monthly. Source: each AMC's own website (see registry.json).",
        "periods": sorted(periods),
        "amcs": amcs,
        "schemes": schemes,
    }
    with open(os.path.join(out_dir(), "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    return idx


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def process_amc(amc, amc_cfg, period, nav_schemes):
    adapter = amc_cfg["adapter"]
    discover = DISCOVERERS.get(adapter)
    parse = ADAPTERS.get(adapter)
    if not discover or not parse:
        sys.stderr.write(f"  ! {amc}: no discoverer/adapter '{adapter}'\n")
        return 0
    files = discover(amc_cfg)
    if not files:
        sys.stderr.write(f"  ! {amc}: no disclosure files found on {amc_cfg['site']}\n")
        return 0
    if period:
        files = [f for f in files if f["period"] == period]
    else:
        files = [files[-1]]                  # latest disclosed period
    if not files:
        sys.stderr.write(f"  ! {amc}: no file for period {period}\n")
        return 0

    amc_schemes = [s for s in nav_schemes if norm(s["sif"]) == norm(amc_cfg.get("nav_sif", ""))]
    written = 0
    for fmeta in files:
        try:
            blob = http_get(fmeta["url"])
        except Exception as e:
            sys.stderr.write(f"  ! {amc} {fmeta['url']}: {e}\n")
            continue
        rel_raw = save_raw(amc, fmeta["period"], fmeta["filename"], blob)
        meta = {"amc": amc, "period": fmeta["period"], "as_of": fmeta["as_of"], "raw": rel_raw}
        funds = parse(blob, fmeta["url"], meta)
        for fund in funds:
            fund["_codes"] = match_codes(fund["fund_name"], amc_schemes)
            rel = save_fund(fund)
            written += 1
            sys.stderr.write(
                f"[{amc}] {fmeta['period']} {fund['fund_name']}: "
                f"{fund['n_holdings']} holdings -> {len(fund['_codes'])} scheme code(s) -> {rel}\n")
    return written


def process_file(path, amc, period, nav_schemes):
    with open(path, "rb") as f:
        blob = f.read()
    filename = os.path.basename(path)
    as_of = (f"{period}-01" if period else dt.date.today().isoformat())
    per = period or dt.date.today().strftime("%Y-%m")
    rel_raw = save_raw(amc, per, filename, blob)
    meta = {"amc": amc, "period": per, "as_of": as_of, "raw": rel_raw}
    reg = load_registry()
    adapter = reg["amcs"].get(amc, {}).get("adapter", "generic_xlsx")
    parse = ADAPTERS.get(adapter, generic_parse_xlsx)
    amc_schemes = [s for s in nav_schemes
                   if norm(s["sif"]) == norm(reg["amcs"].get(amc, {}).get("nav_sif", ""))]
    funds = parse(blob, "file://" + filename, meta)
    for fund in funds:
        fund["_codes"] = match_codes(fund["fund_name"], amc_schemes)
        rel = save_fund(fund)
        sys.stderr.write(f"[{amc}] {per} {fund['fund_name']}: {fund['n_holdings']} holdings -> {rel}\n")
    return len(funds)


def main(argv=None):
    p = argparse.ArgumentParser(description="Fetch & normalise SIF portfolio disclosures.")
    p.add_argument("--amc", help="AMC key from registry.json (default: all)")
    p.add_argument("--period", help="YYYY-MM to fetch (default: latest disclosed)")
    p.add_argument("--file", help="normalise a hand-downloaded xlsx instead of fetching")
    p.add_argument("--list", action="store_true", help="list stored portfolios and exit")
    args = p.parse_args(argv)

    if args.list:
        idx = rebuild_index()
        print(f"periods: {', '.join(idx['periods']) or '(none)'}")
        print(f"schemes with disclosures: {len(idx['schemes'])}")
        return 0

    nav_schemes = load_nav_schemes()

    if args.file:
        if not args.amc:
            p.error("--file requires --amc (which AMC's layout)")
        process_file(args.file, args.amc, args.period, nav_schemes)
        rebuild_index()
        return 0

    reg = load_registry()
    amcs = [args.amc] if args.amc else list(reg["amcs"].keys())
    total = 0
    for amc in amcs:
        cfg = reg["amcs"].get(amc)
        if not cfg:
            sys.stderr.write(f"  ! unknown AMC '{amc}'\n")
            continue
        total += process_amc(amc, cfg, args.period, nav_schemes)
    idx = rebuild_index()
    sys.stderr.write(f"[done] {total} fund portfolio(s) written; "
                     f"{len(idx['schemes'])} scheme code(s) now have disclosures.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
