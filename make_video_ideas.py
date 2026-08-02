#!/usr/bin/env python3
"""
make_video_ideas.py  --  Turn SIFintel's live data into ready-to-shoot short-form video ideas.

Reads nav_data.json + benchmark_data.json + portfolios/ and emits a dated brief under
content/video/ideas/<asof>.md with 6-9 data-driven video concepts: each has a hook, three
talking points (with real numbers), suggested Higgsfield scenes, and a post caption + hashtags.
This is the "source" step of the content engine — run it weekly, pick 2-3, shoot in Higgsfield.

stdlib only. Usage:  python make_video_ideas.py   [--min-obs 30]  [--window-days 30]
"""

import argparse
import datetime as dt
import json
import math
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    p = os.path.join(HERE, path)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def iso_add(iso, days):
    p = [int(x) for x in iso.split("-")]
    return (dt.date(*p) + dt.timedelta(days=days)).isoformat()


def on_or_before(series, target):
    k = -1
    for i, (d, _) in enumerate(series):
        if d <= target:
            k = i
        else:
            break
    return k


def metrics(series, bench_by_date, D=252, Rf=6.5):
    """series sorted [[iso,nav]]; bench_by_date {iso:close}. Returns a dict of stats."""
    if len(series) < 3:
        return None
    navs = [float(n) for _, n in series]
    dates = [d for d, _ in series]
    r = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    n = len(r)
    mean = sum(r) / n
    sd = st.pstdev(r) if n > 1 else 0
    ann_ret = mean * D * 100
    ann_std = sd * math.sqrt(D) * 100
    sharpe = (ann_ret - Rf) / ann_std if ann_std else None
    # max drawdown
    peak = navs[0]
    maxdd = 0
    for v in navs:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1)
    total = (navs[-1] / navs[0] - 1) * 100
    # up/down capture vs benchmark
    un = ud = dn = dd = 0.0
    for i in range(1, len(series)):
        b0 = bench_by_date.get(dates[i - 1])
        b1 = bench_by_date.get(dates[i])
        if b0 is None or b1 is None:
            continue
        fr = navs[i] / navs[i - 1] - 1
        br = b1 / b0 - 1
        if br > 0:
            un += fr
            ud += br
        elif br < 0:
            dn += fr
            dd += br
    up_cap = (un / ud * 100) if ud else None
    dn_cap = (dn / dd * 100) if dd else None

    def ret_since(target):
        k = on_or_before(series, target)
        return (navs[-1] / navs[k] - 1) * 100 if 0 <= k < len(navs) - 1 else None

    as_of = dates[-1]
    r1m = ret_since(iso_add(as_of, -30))
    # WTD: since last close of previous week
    wd = dt.date(*[int(x) for x in as_of.split("-")])
    monday = wd - dt.timedelta(days=(wd.weekday()))
    wtd = ret_since((monday - dt.timedelta(days=1)).isoformat())
    return {"total": total, "ann_ret": ann_ret, "ann_std": ann_std, "sharpe": sharpe,
            "maxdd": -maxdd * 100, "up_cap": up_cap, "dn_cap": dn_cap, "r1m": r1m, "wtd": wtd,
            "obs": len(navs), "as_of": as_of, "first": dates[0]}


STRAT = [("hybrid", "Hybrid Long-Short"), ("ex-top", "Ex-Top-100 Long-Short"),
         ("allocator", "Active Asset Allocator"), ("sector", "Sector Rotation"),
         ("long", "Equity Long-Short")]


def short_name(name):
    return name.split(" - ")[0].split("-Direct")[0].split("-Regular")[0].strip()


def flabel(r):
    """Clean fund label — the base name already carries the brand; avoid 'qsif SIF qsif ...'."""
    base, sif = r["base"], (r["sif"] or "").replace(" SIF", "").strip()
    return base if (not sif or sif.lower() in base.lower()) else f"{sif} {base}"


def slabel(r):
    """Shortened label for inline lists."""
    return flabel(r).replace(" Long-Short Fund", "").replace(" Long-Short", "").replace(" Fund", "").strip()


def build(min_obs, window_days):
    nav = load("nav_data.json")
    bench = load("benchmark_data.json")
    idx = load("portfolios/index.json")
    if not nav:
        print("no nav_data.json"); return
    bench_map = {d: c for d, c in (bench or {}).get("series", [])}
    bench_name = (bench or {}).get("index", "NIFTY 50")

    # one row per fund (prefer Direct + Growth to dedupe plan variants)
    rows = []
    seen = set()
    for s in sorted(nav["schemes"], key=lambda x: (0 if "direct" in x["name"].lower() and "growth" in x["name"].lower() else 1)):
        base = short_name(s["name"])
        key = (s.get("sif", ""), base)
        if key in seen:
            continue
        m = metrics(s["series"], bench_map)
        if not m or m["obs"] < min_obs:
            continue
        seen.add(key)
        rows.append({"code": s["code"], "sif": s.get("sif", ""), "base": base, "m": m})
    if not rows:
        print("no rows with enough obs"); return
    asof = max(r["m"]["as_of"] for r in rows)

    def top(key, rev=True, need=1, filt=lambda r: True):
        vs = [r for r in rows if filt(r) and r["m"].get(key) is not None and math.isfinite(r["m"][key])]
        return sorted(vs, key=lambda r: r["m"][key], reverse=rev)[:need]

    ideas = []

    def add(title, hook, bullets, scenes, tags):
        ideas.append({"title": title, "hook": hook, "bullets": bullets, "scenes": scenes, "tags": tags})

    # 1. Biggest 1-month mover
    t = top("r1m", need=3)
    if t:
        b = t[0]["m"]
        add("Biggest SIF mover this month",
            f"One SIF is up {b['r1m']:.1f}% in a month — here's which, and why it matters.",
            [f"{flabel(t[0])} leads on 1-month return: {b['r1m']:+.1f}%.",
             "Top 3 movers: " + "; ".join(f"{slabel(x)} ({x['m']['r1m']:+.1f}%)" for x in t),
             "Remember: one-month spikes aren't skill — check Sharpe and drawdown before getting excited."],
            "Countdown reveal of the top-3 movers as glowing bars; push-in on the #1 fund's rising line.",
            "#SIF #InvestingIndia #LongShort #SIFintel")

    # 2. Best down-capture (rose/fell least when Nifty fell)
    t = top("dn_cap", rev=False, need=3, filt=lambda r: r["m"]["obs"] >= 40)
    if t:
        b = t[0]["m"]
        verb = "ROSE while the market fell" if (b["dn_cap"] or 0) < 0 else "fell far less than the market"
        add("The SIF that beats a falling market",
            f"When {bench_name} dropped, this fund {verb}. That's the whole point of a SIF.",
            [f"{flabel(t[0])} down-capture: {b['dn_cap']:.0f}% (below 0 = it rose when the index fell).",
             "This is 'down capture' — how much of the market's fall a fund takes. Lower is better.",
             f"Steadiest on down days: " + "; ".join(f"{slabel(x)} ({x['m']['dn_cap']:.0f})" for x in t)],
            "Split screen: red Nifty line crashing vs the fund line holding/rising; gauge swings into the green.",
            "#Hedging #DownsideProtection #SIF #StockMarketIndia #SIFintel")

    # 3. Best risk-adjusted (Sharpe)
    t = top("sharpe", need=3, filt=lambda r: r["m"]["obs"] >= 40)
    if t:
        add("Highest reward-for-risk SIF",
            "Forget headline returns — this is the fund giving the most return per unit of risk.",
            [f"{flabel(t[0])} tops Sharpe at {t[0]['m']['sharpe']:.2f}.",
             "Sharpe = extra return above a safe deposit, per unit of ups-and-downs. Higher is better.",
             "Top 3 by Sharpe: " + "; ".join(f"{slabel(x)} ({x['m']['sharpe']:.2f})" for x in t)],
            "A speedometer/dial filling to the Sharpe value; clean NAV line with low wobble.",
            "#Sharpe #RiskAdjusted #SIF #FinanceIndia #SIFintel")

    # 4. Steadiest (smallest drawdown)
    t = top("maxdd", rev=False, need=1, filt=lambda r: r["m"]["obs"] >= 40)
    if t:
        b = t[0]["m"]
        add("The calmest SIF ride",
            f"This SIF's worst fall was just {b['maxdd']:.1f}%. For nervous investors, that's the story.",
            [f"{flabel(t[0])} max drawdown: only {b['maxdd']:.1f}%.",
             "Max drawdown = the worst peak-to-trough drop. Smaller = a smoother ride.",
             "Low drawdown is what hedging buys you — the trade-off is usually lower upside."],
            "A near-flat underwater (drawdown) curve vs a jagged equity one; calm vs choppy water metaphor.",
            "#LowVolatility #SIF #InvestingBasics #SIFintel")

    # 5. New disclosure / strategy spotlight (from latest portfolio period)
    if idx and idx.get("periods"):
        latest = idx["periods"][-1]
        cand = [c for c, e in idx["schemes"].items() if latest in e.get("periods", {})]
        if cand:
            code = cand[0]
            rel = idx["schemes"][code]["periods"][latest]
            fund = load(rel)
            if fund and fund.get("top"):
                top3 = ", ".join(h["name"] for h in fund["top"][:3])
                alloc = fund.get("allocation", {})
                a = " · ".join(f"{k.replace('_',' ')} {v:.0f}%" for k, v in alloc.items() if isinstance(v, (int, float)) and v > 1)
                add(f"Inside {fund['fund_name']} — what it actually holds",
                    f"We opened {fund['fund_name']}'s latest disclosed portfolio. Here's how it really makes money.",
                    [f"As of {fund.get('as_of', latest)}: {fund.get('n_holdings','?')} holdings, ~₹{fund.get('net_assets_cr','?')} Cr.",
                     f"Top holdings: {top3}. Allocation: {a or 'mixed'}.",
                     "Strategy: " + (fund.get("strategy") or "long-short with hedging — returns from the spread between longs and shorts.")],
                    "Reveal a portfolio 'X-ray': top holdings as bars, an allocation donut, a long/short split.",
                    "#PortfolioDisclosure #SIF #HowItWorks #SIFintel")

    # 6. Market context
    if bench_map and len(bench_map) > 2:
        bd = sorted(bench_map.items())
        b_last = bd[-1][0]
        k = on_or_before(bd, iso_add(b_last, -30))
        if 0 <= k < len(bd) - 1:
            nifty_1m = (bd[-1][1] / bd[k][1] - 1) * 100
            sif_1m = [r["m"]["r1m"] for r in rows if r["m"].get("r1m") is not None]
            avg = sum(sif_1m) / len(sif_1m) if sif_1m else 0
            add("SIFs vs the Nifty this month",
                f"{bench_name} did {nifty_1m:+.1f}% this month. Here's how the average SIF compared.",
                [f"{bench_name} 1-month: {nifty_1m:+.1f}%.",
                 f"Average SIF 1-month: {avg:+.1f}% across {len(sif_1m)} funds.",
                 "SIFs aim to smooth the ride, not always beat the index — the value shows up on the down days."],
                "Two lines racing over the month: Nifty vs an 'average SIF'; end on the gap.",
                "#NIFTY #SIF #MarketUpdate #SIFintel")

    # 7. Evergreen explainer (always include one)
    add("What is a SIF? (in 30 seconds)",
        "There's a new way to invest in India your mutual fund can't do — meet the SIF.",
        ["A Specialized Investment Fund = your mutual fund's 'advanced mode': it can short and hedge.",
         "₹10 lakh minimum, higher risk, for informed investors; sits between mutual funds and PMS.",
         f"India already has {len({r['sif'] for r in rows})}+ SIF houses live — compare them all on SIFintel."],
        "Follow the reusable 'What is a SIF?' storyboard in content/video/intro-sif-scripts.md.",
        "#SIF #SpecializedInvestmentFund #InvestingIndia #SIFintel")

    # ---- write the brief (INTERNAL, git-ignored — names specific funds/returns) ----
    out_dir = os.path.join(HERE, "content", "video", "ideas", "_analytical")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{asof}.md")
    L = [f"# INTERNAL analytical briefs — data as of {asof}", "",
         "> ⚠️ **COMPLIANCE:** these name **specific funds and their returns/rankings**. Do **NOT** use "
         "them in public videos/posts/ads — that is fund promotion and needs a SEBI licence "
         "(RA/RIA/ARN). See `content/COMPLIANCE.md`. Public content must be **fund-agnostic & "
         "educational** — use `content/video/educational-series.md`. Use these only for internal "
         "analysis / the neutral data tool.", "",
         f"_Auto-generated from live data ({len(rows)} funds)._", ""]
    for i, v in enumerate(ideas, 1):
        L.append(f"## {i}. {v['title']}")
        L.append(f"**Hook (0-3s):** {v['hook']}")
        L.append("**Talking points:**")
        L += [f"- {b}" for b in v["bullets"]]
        L.append(f"**Higgsfield visual:** {v['scenes']}")
        L.append(f"**Caption tags:** {v['tags']}")
        L.append("**End card:** SIFintel · *Decode the strategy behind the returns · sifintel.com* · "
                 "_Educational, not investment advice._")
        L.append("")
    open(path, "w", encoding="utf-8").write("\n".join(L))
    print(f"[ideas] wrote {len(ideas)} INTERNAL briefs -> {os.path.relpath(path, HERE)} (git-ignored; do NOT publish)")


def main():
    p = argparse.ArgumentParser(description="SIF video ideas. Public content must be fund-agnostic & educational.")
    p.add_argument("--min-obs", type=int, default=30)
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--analytical", action="store_true",
                   help="generate INTERNAL data-driven briefs that name specific funds/returns. "
                        "NOT for public publishing without a SEBI licence — see content/COMPLIANCE.md.")
    a = p.parse_args()
    if not a.analytical:
        print("For PUBLIC content, use the fund-agnostic educational series:")
        print("  content/video/educational-series.md   (what SIFs are, the 5 categories, concepts)")
        print("  content/COMPLIANCE.md                 (no promoting/ranking specific funds without a licence)")
        print("\nTo generate INTERNAL analytical briefs (fund-specific; do NOT publish), run: --analytical")
        return
    build(a.min_obs, a.window_days)


if __name__ == "__main__":
    main()
