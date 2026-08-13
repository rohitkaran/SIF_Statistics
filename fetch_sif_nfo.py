#!/usr/bin/env python3
"""Track SIF New Fund Offers from AMFI and build their history.

AMFI publishes the currently-open SIF NFOs at

    https://www.amfiindia.com/api/sif-nfo

but that endpoint is a *snapshot*: fund house, strategy name, Scheme_Id, sifId — and nothing else.
It carries **no open or close dates**, and every query parameter is ignored (verified 2026-08-13:
type/status/scheme_id all return the identical 513-byte summary). There is no AMFI NFO archive.

So the history is ours to build. Each run:

  * records any NFO seen for the first time with `first_seen`
  * refreshes `last_seen` for NFOs still on the list
  * marks an NFO `closed` once it drops off AMFI's list, keeping the dates it was observed
  * cross-references nav_data.json — once the scheme starts publishing a NAV we know it launched,
    and we store `launched_on` (its first NAV date), which is the closest thing to a hard fact
    AMFI gives us about when the offer actually ended

Run it daily (it is wired into the GitHub Action). Missing a few days only widens the observed
window for one NFO; it never corrupts history.

Python standard library only.

    python fetch_sif_nfo.py --out nfo_data.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

NFO_API = "https://www.amfiindia.com/api/sif-nfo"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def fetch_json(url: str):
    # AMFI rejects requests without a browser UA + gzip (see the amfi-sif-nav-endpoints notes).
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def load_previous(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
        return {n["key"]: n for n in prev.get("nfos", [])}
    except Exception:                                            # noqa: BLE001 - never lose a run to a bad file
        return {}


def nav_launch_dates(root: str) -> dict:
    """strategy-name-slug -> first NAV date, so a closed NFO can be tied to its actual launch."""
    path = os.path.join(root, "nav_data.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        nav = json.load(f)
    out = {}
    for s in nav.get("schemes", []):
        series = s.get("series") or []
        if not series:
            continue
        first = min(p[0] for p in series)
        # Match on the strategy name, ignoring plan/option suffixes ("- Direct Plan - Growth").
        base = slug(re.split(r"\s+-\s+(direct|regular)\s+plan", s["name"], flags=re.I)[0])
        if base and (base not in out or first < out[base]):
            out[base] = first
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Track AMFI SIF new fund offers and their history.")
    ap.add_argument("--out", default="nfo_data.json")
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    out_path = args.out if os.path.isabs(args.out) else os.path.join(root, args.out)

    today = datetime.now(timezone.utc).date().isoformat()
    known = load_previous(out_path)
    launches = nav_launch_dates(root)

    try:
        payload = fetch_json(NFO_API)
    except Exception as e:                                       # noqa: BLE001
        print(f"AMFI NFO fetch failed ({e}) — keeping the existing file.", file=sys.stderr)
        return 1

    open_keys = set()
    for house in payload.get("NewFundOffer", []) or []:
        fund_house = (house.get("MutualFund") or "").strip()
        for item in house.get("items", []) or []:
            strategy = (item.get("Investment_Strategy") or "").strip()
            if not strategy:
                continue
            key = f"{slug(fund_house)}__{slug(strategy)}"
            open_keys.add(key)
            rec = known.get(key)
            if rec:
                rec["last_seen"] = today
                rec["status"] = "open"
                rec["scheme_id"] = item.get("Scheme_Id") or rec.get("scheme_id")
            else:
                known[key] = {
                    "key": key,
                    "fund_house": fund_house,
                    "strategy": strategy,
                    "scheme_id": item.get("Scheme_Id"),
                    "sif_id": item.get("sifId"),
                    "first_seen": today,
                    "last_seen": today,
                    "status": "open",
                    "launched_on": None,
                }

    # Anything previously open but absent today has closed.
    for key, rec in known.items():
        if key not in open_keys and rec.get("status") == "open":
            rec["status"] = "closed"
        if not rec.get("launched_on"):
            rec["launched_on"] = launches.get(slug(rec["strategy"]))
        if rec.get("launched_on") and rec.get("status") == "closed":
            rec["status"] = "launched"

    nfos = sorted(known.values(),
                  key=lambda r: (r.get("status") != "open", r.get("first_seen") or "", r["strategy"]),
                  reverse=False)

    body = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": NFO_API,
        "note": ("AMFI publishes the open-NFO list without dates. first_seen/last_seen are the dates "
                 "SIFintel observed each offer on that list; launched_on is the scheme's first "
                 "published NAV."),
        "open_count": sum(1 for n in nfos if n["status"] == "open"),
        "total_tracked": len(nfos),
        "nfos": nfos,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)

    print(f"wrote {os.path.basename(out_path)}: {body['open_count']} open, {len(nfos)} tracked in total")
    for n in nfos:
        if n["status"] == "open":
            print(f"   open   {n['fund_house']:<16} {n['strategy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
