#!/usr/bin/env python3
"""Return attribution for every SIF with enough history — attribution_data.json.

WHAT THIS DOES (and, just as importantly, what it does not)

Returns-based attribution. For each scheme we regress its daily return on the NIFTY 50's daily
return and split the period return into the part explained by market exposure and the part that is
not:

    r_fund,t = alpha + beta * r_nifty,t + e_t

    market contribution   ~=  beta x (cumulative benchmark return)
    manager contribution  ~=  total fund return - market contribution

That second line is the residual, so it carries everything the market term does not explain: stock
selection, the short book, timing, cash drag, fees and luck. It is honest to call it "not explained
by market exposure"; it is NOT honest to call it pure stock-picking skill, and the page says so.

This is deliberately NOT a Brinson allocation/selection attribution. Brinson needs benchmark weights
per sector at each date, which nobody publishes for this category, and the holdings we hold are
staggered and bi-monthly. Producing a Brinson table from this data would look precise and be wrong.

Long-short funds also break the usual assumption that beta is stable and positive — several of these
run deliberately low or variable net exposure. Beta is still the right summary of realised market
sensitivity over the window, but R-squared is reported next to it so a low-explanatory-power fit is
visible rather than hidden.

MINIMUM HISTORY: 60 overlapping trading days. Most of this category launched recently; anything
shorter produces a beta that is mostly noise, so those schemes are listed as insufficient history
rather than given a number.

    python build_attribution.py
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
MIN_OBS = 60
TRADING_DAYS = 252


def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def parse_series(series):
    """Accept [[date, value], ...] or ["date value", ...] — benchmark and NAV files differ."""
    out = {}
    for row in series or []:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            d, v = row[0], row[1]
        else:
            parts = str(row).split()
            if len(parts) < 2:
                continue
            d, v = parts[0], parts[1]
        try:
            out[str(d)[:10]] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def daily_returns(points: dict, dates: list) -> list:
    out = []
    for prev, cur in zip(dates, dates[1:]):
        p0, p1 = points.get(prev), points.get(cur)
        if p0 and p1 and p0 > 0:
            out.append((cur, p1 / p0 - 1.0))
    return out


def max_drawdown(points: dict, dates: list) -> float | None:
    peak, worst = None, 0.0
    for d in dates:
        v = points.get(d)
        if not v:
            continue
        peak = v if peak is None else max(peak, v)
        if peak:
            worst = min(worst, v / peak - 1.0)
    return round(100 * worst, 2) if peak else None


def stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def analyse(fund_pts, bench_pts):
    common = sorted(set(fund_pts) & set(bench_pts))
    if len(common) < MIN_OBS + 1:
        return None

    fr = daily_returns(fund_pts, common)
    br = daily_returns(bench_pts, common)
    bmap = dict(br)
    pairs = [(f, bmap[d]) for d, f in fr if d in bmap]
    if len(pairs) < MIN_OBS:
        return None

    fs = [p[0] for p in pairs]
    bs = [p[1] for p in pairs]
    n = len(pairs)
    mf, mb = sum(fs) / n, sum(bs) / n

    var_b = sum((b - mb) ** 2 for b in bs) / (n - 1)
    cov = sum((f - mf) * (b - mb) for f, b in pairs) / (n - 1)
    beta = cov / var_b if var_b else 0.0
    alpha_daily = mf - beta * mb

    sf, sb = stdev(fs), stdev(bs)
    corr = cov / (sf * sb) if sf and sb else 0.0

    # Cumulative (geometric) returns over the window.
    tot_f = 1.0
    for f in fs:
        tot_f *= (1 + f)
    tot_f -= 1
    tot_b = 1.0
    for b in bs:
        tot_b *= (1 + b)
    tot_b -= 1

    market_contrib = beta * tot_b
    manager_contrib = tot_f - market_contrib

    up = [(f, b) for f, b in pairs if b > 0]
    down = [(f, b) for f, b in pairs if b < 0]

    def capture(rows):
        if not rows:
            return None
        mb_ = sum(r[1] for r in rows) / len(rows)
        mf_ = sum(r[0] for r in rows) / len(rows)
        return round(100 * mf_ / mb_, 1) if mb_ else None

    diffs = [f - b for f, b in pairs]
    te = stdev(diffs) * math.sqrt(TRADING_DAYS)
    years = n / TRADING_DAYS
    ann_f = (1 + tot_f) ** (1 / years) - 1 if years > 0 and tot_f > -1 else None
    ann_b = (1 + tot_b) ** (1 / years) - 1 if years > 0 and tot_b > -1 else None

    return {
        "observations": n,
        "from": common[0],
        "to": common[-1],
        "total_return_pct": round(100 * tot_f, 2),
        "benchmark_return_pct": round(100 * tot_b, 2),
        "market_contribution_pct": round(100 * market_contrib, 2),
        "manager_contribution_pct": round(100 * manager_contrib, 2),
        "market_share_of_return_pct": (round(100 * market_contrib / tot_f, 1)
                                       if abs(tot_f) > 1e-9 else None),
        "beta": round(beta, 3),
        "r_squared": round(corr ** 2, 3),
        "alpha_annual_pct": round(100 * ((1 + alpha_daily) ** TRADING_DAYS - 1), 2),
        "volatility_annual_pct": round(100 * sf * math.sqrt(TRADING_DAYS), 2),
        "benchmark_volatility_annual_pct": round(100 * sb * math.sqrt(TRADING_DAYS), 2),
        "tracking_error_pct": round(100 * te, 2),
        "information_ratio": (round((ann_f - ann_b) / te, 2)
                              if ann_f is not None and ann_b is not None and te else None),
        "up_capture_pct": capture(up),
        "down_capture_pct": capture(down),
        "up_days": len(up),
        "down_days": len(down),
        "max_drawdown_pct": max_drawdown(fund_pts, common),
        "annualised_return_pct": round(100 * ann_f, 2) if ann_f is not None else None,
    }


def holdings_changes():
    """What actually changed in the portfolio between a fund's consecutive disclosures.

    Labelled as portfolio CHANGE, not attribution: without daily holdings we cannot say what each
    position contributed to return, only how the book was repositioned between two snapshots.
    """
    index_path = os.path.join(ROOT, "portfolios", "index.json")
    if not os.path.exists(index_path):
        return []
    index = load(os.path.join("portfolios", "index.json"))

    by_file = {}
    for entry in (index.get("schemes") or {}).values():
        for period, path in (entry.get("periods") or {}).items():
            by_file[path] = period

    funds = defaultdict(list)
    for path, period in by_file.items():
        full = os.path.join(ROOT, path.replace("/", os.sep))
        if not os.path.exists(full):
            continue
        with open(full, encoding="utf-8") as f:
            p = json.load(f)
        funds[p.get("fund_name") or p.get("fund_code")].append((period, p))

    out = []
    for fund, snaps in funds.items():
        snaps.sort(key=lambda s: s[0])
        for (p0, a), (p1, b) in zip(snaps, snaps[1:]):
            sec0 = {s.get("sector"): s.get("weight") for s in (a.get("sectors") or [])
                    if isinstance(s, dict)}
            sec1 = {s.get("sector"): s.get("weight") for s in (b.get("sectors") or [])
                    if isinstance(s, dict)}
            shifts = []
            for name in set(sec0) | set(sec1):
                if not name:
                    continue
                w0, w1 = sec0.get(name) or 0.0, sec1.get(name) or 0.0
                if abs(w1 - w0) >= 0.5:
                    shifts.append({"sector": name, "from_pct": round(w0, 2),
                                   "to_pct": round(w1, 2), "change_pct": round(w1 - w0, 2)})
            shifts.sort(key=lambda s: -abs(s["change_pct"]))

            alloc0, alloc1 = a.get("allocation") or {}, b.get("allocation") or {}
            out.append({
                "fund": fund,
                "amc": b.get("amc"),
                "from_period": p0, "to_period": p1,
                "net_assets_from_cr": a.get("net_assets_cr"),
                "net_assets_to_cr": b.get("net_assets_cr"),
                "holdings_from": a.get("n_holdings"), "holdings_to": b.get("n_holdings"),
                "allocation_from": alloc0, "allocation_to": alloc1,
                "allocation_shift": {k: round((alloc1.get(k) or 0) - (alloc0.get(k) or 0), 2)
                                     for k in set(alloc0) | set(alloc1)},
                "sector_shifts": shifts[:8],
            })
    out.sort(key=lambda r: (r["to_period"], r["fund"]))
    return out


def main() -> int:
    nav = load("nav_data.json")
    bench = load("benchmark_data.json")
    bench_pts = parse_series(bench.get("series"))
    if not bench_pts:
        print("benchmark_data.json has no usable series", flush=True)
        return 1

    funds, skipped = [], []
    for s in nav.get("schemes", []):
        pts = parse_series(s.get("series"))
        res = analyse(pts, bench_pts) if pts else None
        base = {"code": s.get("code"), "name": s.get("name"), "category": s.get("cat"),
                "fund_house": s.get("sif"), "isin": s.get("isin")}
        if res is None:
            skipped.append({**base, "observations": len(pts)})
        else:
            funds.append({**base, **res})

    funds.sort(key=lambda f: -(f.get("manager_contribution_pct") or 0))

    # One row per actual fund. Direct/Regular x Growth/IDCW are four rows of the same portfolio and
    # would otherwise dominate any ranking; keep the Direct Growth variant as representative and
    # record how many variants it stands for.
    def strategy_key(f):
        base = re.split(r"\s+-\s+(direct|regular)\s+plan", f["name"], flags=re.I)[0]
        base = re.sub(r"\s+-\s+(growth|idcw|income distribution).*$", "", base, flags=re.I)
        return (f.get("fund_house") or "", re.sub(r"[^a-z0-9]", "", base.lower()))

    def variant_rank(f):
        name = f["name"].lower()
        return (0 if "direct" in name else 1, 0 if "growth" in name else 1)

    groups = defaultdict(list)
    for f in funds:
        groups[strategy_key(f)].append(f)
    primary = []
    for rows in groups.values():
        rows.sort(key=variant_rank)
        head = dict(rows[0])
        head["variants"] = len(rows)
        head["variant_codes"] = [r["code"] for r in rows]
        primary.append(head)

    # Second pass: AMFI's scheme names contain typos (e.g. "Actice Asset Allocator" alongside
    # "Active Asset Allocator"), which name-based grouping cannot merge. Two entries from the same
    # house, in the same category, with an identical return series are the same portfolio — no two
    # distinct funds produce byte-identical daily returns over 100+ days.
    merged: dict[tuple, dict] = {}
    for f in primary:
        sig = (f.get("fund_house"), f.get("category"), f["observations"],
               f["total_return_pct"], f["beta"], f["volatility_annual_pct"])
        keep = merged.get(sig)
        if keep is None:
            merged[sig] = f
        else:
            keep["variants"] += f["variants"]
            keep["variant_codes"] = sorted(set(keep["variant_codes"]) | set(f["variant_codes"]))
            if variant_rank(f) < variant_rank(keep):
                f["variants"], f["variant_codes"] = keep["variants"], keep["variant_codes"]
                merged[sig] = f
    primary = sorted(merged.values(), key=lambda f: -(f.get("manager_contribution_pct") or 0))

    # Category averages, so a fund can be read against its own strategy rather than the whole market.
    cats = defaultdict(list)
    for f in funds:
        cats[f["category"]].append(f)
    by_category = sorted(
        [{"category": c,
          "funds": len(rows),
          "avg_beta": round(sum(r["beta"] for r in rows) / len(rows), 3),
          "avg_r_squared": round(sum(r["r_squared"] for r in rows) / len(rows), 3),
          "avg_total_return_pct": round(sum(r["total_return_pct"] for r in rows) / len(rows), 2),
          "avg_market_contribution_pct": round(
              sum(r["market_contribution_pct"] for r in rows) / len(rows), 2),
          "avg_manager_contribution_pct": round(
              sum(r["manager_contribution_pct"] for r in rows) / len(rows), 2),
          "avg_volatility_pct": round(sum(r["volatility_annual_pct"] for r in rows) / len(rows), 2)}
         for c, rows in cats.items()],
        key=lambda c: -c["funds"])

    body = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "benchmark": bench.get("index", "NIFTY 50"),
        "method": ("Daily fund returns regressed on daily NIFTY 50 returns. Market contribution = "
                   "beta x cumulative benchmark return; manager contribution is the residual, i.e. "
                   "everything not explained by market exposure — selection, the short book, timing, "
                   "cash and fees together."),
        "not_brinson": ("This is returns-based, not a Brinson allocation/selection attribution. "
                        "Brinson requires benchmark sector weights at each date, which are not "
                        "published for this category."),
        "min_observations": MIN_OBS,
        "analysed": len(funds),
        "distinct_funds": len(primary),
        "insufficient_history": len(skipped),
        "by_category": by_category,
        "funds_primary": primary,
        "funds": funds,
        "skipped": sorted(skipped, key=lambda s: -s["observations"]),
        "portfolio_changes": holdings_changes(),
    }

    with open(os.path.join(ROOT, "attribution_data.json"), "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)

    print(f"wrote attribution_data.json — {len(primary)} distinct funds "
          f"({len(funds)} plan variants), {len(skipped)} with under {MIN_OBS} overlapping days")
    print(f"   {len(body['portfolio_changes'])} portfolio-change pair(s)")
    for f in primary[:8]:
        print(f"   {f['name'][:52]:<52} beta {f['beta']:>6.2f}  R2 {f['r_squared']:.2f}  "
              f"total {f['total_return_pct']:>7.2f}%  market {f['market_contribution_pct']:>7.2f}%  "
              f"manager {f['manager_contribution_pct']:>7.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
