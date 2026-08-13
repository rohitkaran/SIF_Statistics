#!/usr/bin/env python3
"""Aggregate SIF AUM, market share and month-on-month movement into aum_data.json.

WHERE THE AUM COMES FROM: AMFI publishes no AUM API for SIFs (every /api/sif-*aum* variant 404s,
verified 2026-08-13). But each fund house's portfolio disclosure states the scheme's net assets, and
fetch_sif_portfolios.py already normalises that into `net_assets_cr` on every file under
portfolios/data/<period>/. So AUM here is *disclosed net assets*, straight from the fund houses.

COUNTING RULE: 111 NAV variants map to far fewer distinct funds (Direct/Regular × Growth/IDCW all
share one portfolio). Portfolio files are per fund, so each FILE is counted exactly once — never
once per scheme code, which would multiply AUM several-fold.

HONESTY RULE: a period only shows what actually disclosed. Every figure is emitted alongside the
number of funds behind it, and the page states coverage, because SIF disclosure is staggered and a
period with 10 of 40 funds is not an industry total.

    python build_aum.py
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


def months_between(a: str, b: str) -> int:
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def main() -> int:
    index = load("portfolios/index.json")
    nav = load("nav_data.json")

    # scheme code -> (category, fund house) from the NAV universe
    meta = {s["code"]: (s.get("cat") or "Uncategorised", s.get("sif") or "Unknown")
            for s in nav.get("schemes", [])}

    # Join through index.json: file path is the unit of truth, so a fund counts once.
    # file -> {period, category, house, amc}
    file_meta: dict[str, dict] = {}
    for code, entry in (index.get("schemes") or {}).items():
        cat, house = meta.get(code, (None, None))
        for period, path in (entry.get("periods") or {}).items():
            fm = file_meta.setdefault(path, {"period": period, "amc": entry.get("amc"),
                                             "categories": set(), "houses": set()})
            if cat:
                fm["categories"].add(cat)
            if house:
                fm["houses"].add(house)

    # Read each file once for its disclosed net assets.
    records = []
    for path, fm in sorted(file_meta.items()):
        full = os.path.join(ROOT, path.replace("/", os.sep))
        if not os.path.exists(full):
            continue
        with open(full, encoding="utf-8") as f:
            p = json.load(f)
        aum = p.get("net_assets_cr")
        if not aum:
            continue
        records.append({
            "period": fm["period"],
            "fund": p.get("fund_name") or p.get("fund_code"),
            "amc": p.get("amc") or fm["amc"],
            "house": sorted(fm["houses"])[0] if fm["houses"] else (p.get("amc") or "Unknown"),
            "category": sorted(fm["categories"])[0] if fm["categories"] else "Uncategorised",
            "as_of": p.get("as_of"),
            "aum_cr": round(float(aum), 2),
            "n_holdings": p.get("n_holdings"),
            "allocation": p.get("allocation"),
        })

    periods = sorted({r["period"] for r in records})
    total_funds_in_universe = len({s.get("sif", "") + "|" + s.get("cat", "") for s in nav["schemes"]})

    def group(period, key):
        agg = defaultdict(lambda: {"aum_cr": 0.0, "funds": 0})
        for r in records:
            if r["period"] != period:
                continue
            g = agg[r[key]]
            g["aum_cr"] += r["aum_cr"]
            g["funds"] += 1
        total = sum(g["aum_cr"] for g in agg.values()) or 1.0
        return sorted(
            [{"name": k, "aum_cr": round(v["aum_cr"], 2), "funds": v["funds"],
              "share_pct": round(100 * v["aum_cr"] / total, 2)} for k, v in agg.items()],
            key=lambda x: -x["aum_cr"])

    by_category = {p: group(p, "category") for p in periods}
    by_house = {p: group(p, "house") for p in periods}

    totals = []
    for p in periods:
        rows = [r for r in records if r["period"] == p]
        totals.append({
            "period": p,
            "aum_cr": round(sum(r["aum_cr"] for r in rows), 2),
            "funds": len(rows),
            "amcs": len({r["amc"] for r in rows}),
        })

    # WHY THERE IS NO MONTH-ON-MONTH TABLE:
    # SIF houses disclose on a staggered, roughly bi-monthly cycle — verified in the data itself:
    # 2026-05 and 2026-06 share ZERO funds (May = DynaSIF/Apex/WSIF/quant/…, June = iSIF/RedHex/…).
    # So "who gained this month" cannot be computed by differencing two periods; that would compare
    # different fund houses and report composition change as growth. A fund can only be compared to
    # its OWN previous disclosure, whenever that fell. That is what this does, and it labels the gap.
    per_fund = defaultdict(list)
    for r in records:
        per_fund[r["fund"]].append(r)

    movers = []
    for fund, rows in per_fund.items():
        rows.sort(key=lambda r: r["period"])
        for p, c in zip(rows, rows[1:]):
            chg = round(c["aum_cr"] - p["aum_cr"], 2)
            movers.append({
                "fund": fund, "house": c["house"], "category": c["category"],
                "from_period": p["period"], "to_period": c["period"],
                "gap_months": months_between(p["period"], c["period"]),
                "from_cr": p["aum_cr"], "to_cr": c["aum_cr"], "change_cr": chg,
                "change_pct": round(100 * chg / p["aum_cr"], 2) if p["aum_cr"] else None,
            })
    movers.sort(key=lambda m: -abs(m["change_cr"]))

    # The only defensible "current picture": every fund at its own most recent disclosure, each
    # carrying the date it actually applies to. This is how staggered industry data is normally
    # rolled up, and it is what the market-share view uses.
    latest_rows = [max(rows, key=lambda r: r["period"]) for rows in per_fund.values()]
    latest_total = sum(r["aum_cr"] for r in latest_rows) or 1.0

    def latest_group(key):
        agg = defaultdict(lambda: {"aum_cr": 0.0, "funds": 0, "periods": set()})
        for r in latest_rows:
            g = agg[r[key]]
            g["aum_cr"] += r["aum_cr"]
            g["funds"] += 1
            g["periods"].add(r["period"])
        return sorted(
            [{"name": k, "aum_cr": round(v["aum_cr"], 2), "funds": v["funds"],
              "share_pct": round(100 * v["aum_cr"] / latest_total, 2),
              "as_of_periods": sorted(v["periods"])} for k, v in agg.items()],
            key=lambda x: -x["aum_cr"])

    latest = {
        "aum_cr": round(sum(r["aum_cr"] for r in latest_rows), 2),
        "funds": len(latest_rows),
        "periods_spanned": sorted({r["period"] for r in latest_rows}),
        "by_house": latest_group("house"),
        "by_category": latest_group("category"),
        "funds_detail": sorted(latest_rows, key=lambda r: -r["aum_cr"]),
    }

    body = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "basis": ("Disclosed net assets from each fund house's own portfolio disclosure. AMFI "
                  "publishes no AUM API for SIFs."),
        "counting": "One portfolio file = one fund. Plan variants are never counted separately.",
        "caveat": ("SIF portfolio disclosure is staggered and roughly bi-monthly: consecutive periods "
                   "contain different fund houses (2026-05 and 2026-06 share no funds at all). Period "
                   "totals are therefore NOT comparable to each other and NOT industry totals. Use "
                   "`latest` for the current picture and `fund_movers` for genuine growth."),
        "periods": periods,
        "universe": {"nav_schemes": len(nav["schemes"]), "distinct_strategies": total_funds_in_universe},
        "totals": totals,
        "by_category": by_category,
        "by_house": by_house,
        "latest": latest,
        "fund_movers": movers,
        "funds": sorted(records, key=lambda r: (r["period"], -r["aum_cr"])),
    }

    out = os.path.join(ROOT, "aum_data.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)

    print(f"wrote aum_data.json — {len(periods)} period(s), {len(records)} fund-period records")
    for t in totals:
        print(f"   {t['period']}  Rs {t['aum_cr']:>12,.2f} cr   {t['funds']:>3} funds  {t['amcs']} AMCs")
    print(f"   latest roll-forward: Rs {latest['aum_cr']:,.2f} cr across {latest['funds']} funds "
          f"(periods {', '.join(latest['periods_spanned'])})")
    print(f"   {len(movers)} genuine fund-to-fund movement(s)"
          + ("" if movers else " — no fund has disclosed twice yet, so no growth is computable"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
