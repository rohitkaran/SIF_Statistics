#!/usr/bin/env python3
"""Fetch AMFI's official SIF Monthly Report for every month since the category launched.

THIS is the authoritative industry dataset — and it is what /aum should be built on. Earlier the
AUM page was derived from fund houses' portfolio disclosures, which are staggered and bi-monthly, so
a "total" mixed June figures with October ones and understated the industry badly (₹6,009 cr from
disclosures vs ₹23,177 cr actual for July 2026). AMFI's report is a clean point-in-time snapshot:
every scheme, same month-end, every month.

Source: https://www.amfiindia.com/sif/sif-monthly  ->  portal.amfiindia.com/spages/sif_am{mon}{yyyy}repo.xls
Legacy OLE2 .xls, so it needs xlrd (openpyxl cannot read these).

Two sheets per file:
  SIF MCR — per SEBI category: schemes, folios, funds mobilized, redemptions, net flow,
            closing AUM and average AUM (all INR crore)
  NSR     — new schemes whose allotment completed that month, with amount mobilised. This is real,
            dated NFO data with rupee amounts, unlike AMFI's dateless open-NFO API.

Coverage is monthly from 2025-10 (the category's first month) to the latest published month, so
month-on-month growth IS computable here — unlike the portfolio-derived figures.

    python fetch_amfi_monthly.py --out industry_data.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.request

try:
    import xlrd
except ImportError:                                              # pragma: no cover
    print("xlrd is required to read AMFI's legacy .xls files:  pip install xlrd", file=sys.stderr)
    raise

URL = "https://portal.amfiindia.com/spages/sif_am{mon}{year}repo.xls"
FIRST = (2025, 10)          # SIF category launch — first monthly report
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Rows that are totals rather than categories — kept separately, never mixed into the category list.
SUBTOTAL = re.compile(r"^\s*(sub\s*total|grand\s*total)", re.I)
GROUPS = {"a": "Equity Oriented", "b": "Debt Oriented", "c": "Hybrid"}


def months_since(y0: int, m0: int):
    today = dt.date.today()
    y, m = y0, m0
    while (y, m) <= (today.year, today.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def fetch(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            blob = r.read()
    except Exception:                                            # noqa: BLE001 - month not published yet
        return None
    return blob if blob[:4] == b"\xd0\xcf\x11\xe0" else None     # must be a real OLE2 .xls


def num(v):
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip().replace(",", "")
    if not s or s in {"-", "NA", "N.A."}:
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


# AMFI renames the sheets EVERY MONTH — observed: "SIF MCR", "SIF_MCR_Report", "SIFMCR_Report",
# "SIF_MCR_MonthlyReport", "AMFI MONTHLY", "OCT 2025", and "NSR"/"NSR_Report". Never match by name;
# identify both the sheet and its columns by their content instead.
COLUMNS = [
    ("schemes",       r"no\.?\s*of\s*schemes"),
    ("folios",        r"no\.?\s*of\s*folios"),
    ("inflow_cr",     r"funds?\s*mobili[sz]ed"),
    ("redemption_cr", r"repurchase|redemption"),
    ("net_flow_cr",   r"net\s*inflow|net\s*outflow"),
    ("avg_aum_cr",    r"average\s*net\s*assets"),          # must be tested before plain AUM
    ("aum_cr",        r"net\s*assets\s*under\s*management"),
]


def _cells(sheet, r):
    return [str(sheet.cell_value(r, c)) for c in range(sheet.ncols)]


def find_header(sheet):
    """Row index + {field: column} mapped from header text, not fixed positions."""
    for r in range(min(sheet.nrows, 12)):
        joined = " ".join(_cells(sheet, r)).lower()
        if "no. of schemes" not in joined and "no of schemes" not in joined:
            continue
        cols, taken = {}, set()
        for c, text in enumerate(_cells(sheet, r)):
            t = re.sub(r"\s+", " ", text).strip().lower()
            if not t or "segregated" in t:                 # segregated-portfolio columns are not AUM
                continue
            for field, pat in COLUMNS:
                if field in cols or c in taken:
                    continue
                if re.search(pat, t):
                    cols[field], _ = c, taken.add(c)
                    break
        if "aum_cr" in cols or "schemes" in cols:
            return r, cols
    return None, {}


def parse_mcr(sheet, period: str) -> tuple[list[dict], dict | None]:
    header_row, cols = find_header(sheet)
    if header_row is None:
        return [], None

    # The category label is the last text column before the first numeric column.
    name_col = min(cols.values()) - 1 if cols else 1
    name_col = max(name_col, 0)

    rows, total, group = [], None, None
    for r in range(header_row + 1, sheet.nrows):
        cells = _cells(sheet, r)
        name = cells[name_col].strip() if name_col < len(cells) else ""
        if not name:
            continue
        values = {f: num(sheet.cell_value(r, c)) for f, c in cols.items() if c < sheet.ncols}

        if not any(v is not None for v in values.values()) and not SUBTOTAL.match(name):
            # Group header row ("A | Equity Oriented Investment Strategies") — carries no numbers.
            key = (cells[0] if cells else "").strip().lower().strip(". ")
            if key in GROUPS:
                group = GROUPS[key]
            elif re.search(r"equity\s*oriented", name, re.I):
                group = GROUPS["a"]
            elif re.search(r"debt\s*oriented", name, re.I):
                group = GROUPS["b"]
            elif re.search(r"hybrid", name, re.I):
                group = GROUPS["c"]
            continue

        if re.match(r"^\s*grand\s*total", name, re.I):
            total = {"period": period, **values}
        elif SUBTOTAL.match(name):
            continue                                             # sub-totals are re-derivable
        else:
            rows.append({"category": name, "group": group, **values})
    return rows, total


def parse_nsr(sheet, period: str) -> list[dict]:
    """New-schemes sheet. Column count varies between months, so every access is bounds-checked."""
    def cell(r, c):
        return str(sheet.cell_value(r, c)).strip() if c < sheet.ncols else ""

    out, group = [], None
    for r in range(sheet.nrows):
        cat, names = cell(r, 0), cell(r, 1)
        if not cat:
            continue
        if re.match(r"^[A-C]\s*\.", cat) and not names:
            group = re.sub(r"^[A-C]\s*\.\s*", "", cat).strip()
            continue
        if re.match(r"^(sub\s*total|total)", cat, re.I):
            continue
        n = num(cell(r, 2))
        if not n or not names:
            continue
        # One row can list several schemes, with a single combined amount for the row.
        schemes = [s.strip() for s in names.split(",") if s.strip()]
        raised = num(cell(r, 3))
        for scheme in schemes:
            out.append({"period": period, "group": group, "category": cat, "scheme": scheme,
                        "schemes_in_row": n,
                        "funds_mobilized_cr": raised,
                        "amount_is_row_total": len(schemes) > 1})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch AMFI's official monthly SIF industry reports.")
    ap.add_argument("--out", default="industry_data.json")
    ap.add_argument("--from-year", type=int, default=FIRST[0])
    ap.add_argument("--from-month", type=int, default=FIRST[1])
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    out_path = args.out if os.path.isabs(args.out) else os.path.join(root, args.out)
    raw_dir = os.path.join(root, "portfolios", "raw", "amfi_monthly")
    os.makedirs(raw_dir, exist_ok=True)

    months, categories, totals, new_schemes, missing = [], [], [], [], []

    for y, m in months_since(args.from_year, args.from_month):
        period = f"{y}-{m:02d}"
        mon = dt.date(y, m, 1).strftime("%b").lower()
        url = URL.format(mon=mon, year=y)
        blob = fetch(url)
        if blob is None:
            missing.append(period)
            continue

        # Keep the source file: AMFI has no archive guarantee, and this is the primary record.
        with open(os.path.join(raw_dir, f"sif_am{mon}{y}repo.xls"), "wb") as f:
            f.write(blob)

        book = xlrd.open_workbook(file_contents=blob)

        # Pick sheets by what they contain, not what they are called.
        mcr_sheet = nsr_sheet = None
        for name in book.sheet_names():
            sh = book.sheet_by_name(name)
            blob_text = " ".join(" ".join(_cells(sh, r)) for r in range(min(sh.nrows, 8))).lower()
            if "new schemes report" in blob_text or re.search(r"\bnsr\b", name, re.I):
                nsr_sheet = nsr_sheet or sh
            elif find_header(sh)[0] is not None:
                mcr_sheet = mcr_sheet or sh

        if mcr_sheet is None:
            print(f"  {period}: no recognisable MCR sheet ({book.sheet_names()})", file=sys.stderr)
            missing.append(period)
            continue

        cats, total = parse_mcr(mcr_sheet, period)
        for c in cats:
            c["period"] = period
        categories.extend(cats)
        if total:
            totals.append(total)
        if nsr_sheet is not None:
            new_schemes.extend(parse_nsr(nsr_sheet, period))
        months.append(period)
        print(f"  {period}  {len(cats)} categories"
              + (f"  AUM Rs {total['aum_cr']:,.0f} cr  {total['folios']:,.0f} folios" if total else ""))

    if not months:
        print("No AMFI monthly reports could be fetched — keeping the existing file.", file=sys.stderr)
        return 1

    # Month-on-month deltas: valid here because every month covers the whole industry on the same date.
    by_cat: dict[str, list[dict]] = {}
    for c in categories:
        by_cat.setdefault(c["category"], []).append(c)
    for rows in by_cat.values():
        rows.sort(key=lambda r: r["period"])
        for prev, cur in zip(rows, rows[1:]):
            if prev.get("aum_cr") is not None and cur.get("aum_cr") is not None:
                cur["aum_change_cr"] = round(cur["aum_cr"] - prev["aum_cr"], 2)
                cur["aum_change_pct"] = (round(100 * cur["aum_change_cr"] / prev["aum_cr"], 2)
                                         if prev["aum_cr"] else None)

    latest = months[-1]
    latest_total = next((t for t in totals if t["period"] == latest), None)
    latest_cats = sorted([c for c in categories if c["period"] == latest and c.get("aum_cr")],
                         key=lambda c: -c["aum_cr"])
    tot = (latest_total or {}).get("aum_cr") or sum(c["aum_cr"] for c in latest_cats) or 1
    for c in latest_cats:
        c["share_pct"] = round(100 * c["aum_cr"] / tot, 2)

    body = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "AMFI SIF Monthly Report — https://www.amfiindia.com/sif/sif-monthly",
        "basis": ("Official AMFI industry figures. Every month is a whole-industry snapshot at the "
                  "same month-end, so month-on-month comparisons are valid."),
        "units": "INR crore",
        "months": months,
        "months_missing": missing,
        "latest": latest,
        "latest_total": latest_total,
        "latest_categories": latest_cats,
        "totals": totals,
        "categories": categories,
        "new_schemes": new_schemes,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)

    print(f"\nwrote {os.path.basename(out_path)}: {len(months)} month(s) "
          f"({months[0]} to {months[-1]}), {len(categories)} category-months, "
          f"{len(new_schemes)} new scheme record(s)")
    if missing:
        print(f"  not published / unavailable: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
