#!/usr/bin/env python3
"""
monitor.py  --  Daily change-watch for the SIF universe.

Compares today's data against the last snapshot (monitor/state.json) and reports:
  • NEW schemes / fund launches   (a new SIF's first NAV appears)
  • NEW portfolio disclosures      (a new bi-monthly period for a fund)
  • FUND-MANAGER changes           (managers on a fund differ from last run)
  • NAV freshness                  (latest NAV date; how many schemes updated)
  • BROKEN links                   (presentation / disclosure pages that went from OK -> failing)
  • MISSING presentation links     (AMCs without an official presentation URL to fix)

Writes monitor/state.json (new snapshot) + prepends a dated section to monitor/CHANGELOG.md when
anything changed, and drops monitor/changed.flag so CI can alert. stdlib only.

Run in CI daily after the NAV/portfolio fetch. Local:  python monitor.py [--no-net]
"""

import argparse
import datetime as dt
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MON = os.path.join(HERE, "monitor")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def load(path, default=None):
    p = os.path.join(HERE, path)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def link_ok(url, timeout=20):
    if not url or not url.startswith("http"):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return 200 <= r.status < 400
    except urllib.error.HTTPError as e:
        return 200 <= e.code < 400
    except Exception:
        return False


def snapshot(check_net=True):
    nav = load("nav_data.json", {"schemes": []})
    idx = load("portfolios/index.json", {"schemes": {}, "amcs": {}, "periods": []})

    schemes = {}
    for s in nav["schemes"]:
        ds = [d for d, _ in s["series"]]
        schemes[s["code"]] = {"name": s.get("name", ""), "sif": s.get("sif", ""),
                              "first": min(ds) if ds else None, "last": max(ds) if ds else None}

    # managers per code (from each fund's latest disclosed data file)
    managers, periods, file_cache = {}, {}, {}
    for code, e in idx.get("schemes", {}).items():
        pers = sorted(e.get("periods", {}).keys())
        periods[code] = pers
        if pers:
            rel = e["periods"][pers[-1]]
            if rel not in file_cache:
                file_cache[rel] = load(rel, {})
            managers[code] = file_cache[rel].get("managers", "")

    # links to watch: each AMC's presentation + disclosure page
    links = {}
    missing_pres = []
    for amc, a in idx.get("amcs", {}).items():
        if a.get("presentation"):
            links[a["presentation"]] = None
        else:
            missing_pres.append(f"{a.get('brand', amc)} ({a.get('parent', '')})")
        if a.get("disclosure_page"):
            links.setdefault(a["disclosure_page"], None)
    health = {}
    if check_net:
        for u in list(links):
            health[u] = link_ok(u)

    return {
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "latest_nav": max((v["last"] for v in schemes.values() if v["last"]), default=None),
        "schemes": schemes, "periods": periods, "managers": managers,
        "link_health": health, "missing_presentations": sorted(set(missing_pres)),
    }


def diff(prev, cur):
    ch = {"new_schemes": [], "new_periods": [], "manager_changes": [], "broken_links": [],
          "nav_updated": 0}
    ps, cs = prev.get("schemes", {}), cur["schemes"]
    for code, v in cs.items():
        if code not in ps:
            ch["new_schemes"].append(f"{v['sif']} · {v['name']} (first NAV {v['first'] or '—'})")
        elif ps[code].get("last") and v["last"] and v["last"] > ps[code]["last"]:
            ch["nav_updated"] += 1
    pp, cp = prev.get("periods", {}), cur["periods"]
    for code, pers in cp.items():
        new = [p for p in pers if p not in pp.get(code, [])]
        if new and code in cs:
            ch["new_periods"].append(f"{cs[code]['sif']} · {cs[code]['name']} → {', '.join(new)}")
    pm, cm = prev.get("managers", {}), cur["managers"]
    for code, m in cm.items():
        if code in pm and pm[code] and m and pm[code] != m:
            nm = cs.get(code, {}).get("name", code)
            ch["manager_changes"].append(f"{nm}: '{pm[code]}' → '{m}'")
    ph, cur_h = prev.get("link_health", {}), cur["link_health"]
    for u, ok in cur_h.items():
        if ph.get(u) is True and ok is False:
            ch["broken_links"].append(u)
    return ch


def has_changes(ch):
    return any(ch[k] for k in ("new_schemes", "new_periods", "manager_changes", "broken_links"))


def write_changelog(ch, cur):
    day = (cur["latest_nav"] or cur["generated"][:10])
    lines = [f"## {cur['generated'][:10]} (data as of {day})", ""]
    if ch["new_schemes"]:
        lines.append("**🆕 New schemes / launches:**")
        lines += [f"- {x}" for x in ch["new_schemes"]] + [""]
    if ch["new_periods"]:
        lines.append("**📄 New portfolio disclosures:**")
        lines += [f"- {x}" for x in ch["new_periods"]] + [""]
    if ch["manager_changes"]:
        lines.append("**👤 Fund-manager changes:**")
        lines += [f"- {x}" for x in ch["manager_changes"]] + [""]
    if ch["broken_links"]:
        lines.append("**🔗 Links that went broken (check the AMC site):**")
        lines += [f"- {x}" for x in ch["broken_links"]] + [""]
    lines.append(f"_NAV updated on {ch['nav_updated']} scheme(s)._")
    if cur.get("missing_presentations"):
        lines.append(f"_AMCs still missing a presentation link: {', '.join(cur['missing_presentations'])}._")
    lines.append("")
    block = "\n".join(lines)
    path = os.path.join(MON, "CHANGELOG.md")
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    header = "# SIFintel — change log\n\nAuto-generated by `monitor.py` (daily). Newest first.\n\n"
    body = old[len(header):] if old.startswith(header) else old
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + block + body)
    return block


def main(argv=None):
    p = argparse.ArgumentParser(description="Daily SIF change monitor.")
    p.add_argument("--no-net", action="store_true", help="skip link-health HTTP checks")
    a = p.parse_args(argv)
    os.makedirs(MON, exist_ok=True)
    prev = load("monitor/state.json", {})
    cur = snapshot(check_net=not a.no_net)
    # carry forward prior health for links we didn't check this run
    if a.no_net:
        cur["link_health"] = prev.get("link_health", {})
    if not prev.get("schemes"):   # first run: establish baseline, don't report the whole universe as "new"
        with open(os.path.join(MON, "state.json"), "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)
        sys.stderr.write(f"[monitor] baseline established: {len(cur['schemes'])} schemes, "
                         f"NAV as of {cur['latest_nav']}.\n")
        return 0
    ch = diff(prev, cur)
    with open(os.path.join(MON, "state.json"), "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    flag = os.path.join(MON, "changed.flag")
    if has_changes(ch):
        block = write_changelog(ch, cur)
        with open(flag, "w", encoding="utf-8") as f:
            f.write(block)
        sys.stderr.write("[monitor] CHANGES detected:\n" + block + "\n")
    else:
        if os.path.exists(flag):
            os.remove(flag)
        sys.stderr.write(f"[monitor] no material changes. NAV as of {cur['latest_nav']}; "
                         f"{ch['nav_updated']} scheme(s) updated.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
