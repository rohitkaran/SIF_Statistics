#!/usr/bin/env python3
"""Build news_data.json — a committed snapshot of world financial news.

The LIVE news on /news comes from the Cloudflare Pages Function `functions/api/news.js`, which
re-aggregates the same feeds at the edge every 30 minutes. This script exists for two reasons:

  1. Fallback — if the edge function or an upstream feed is down, the page still renders
     something (the client falls back to /news_data.json).
  2. History — the snapshot is versioned in git alongside NAVs, so we can see what the world
     looked like on a given day.

It runs on the existing GitHub Action crons (a few times a day), NOT every 30 minutes: every
commit triggers a Cloudflare Pages build, and the free plan allows only 500 builds/month.

Python standard library only — no pip install needed.

    python fetch_news.py --out news_data.json
"""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# Keep this list in sync with functions/api/news.js (FEEDS).
FEEDS = [
    # global markets & business
    ("https://feeds.bbci.co.uk/news/business/rss.xml",                       "BBC Business",        "Global", False, False),
    ("https://www.theguardian.com/uk/business/rss",                          "The Guardian",        "Global", False, False),
    ("https://finance.yahoo.com/news/rssindex",                              "Yahoo Finance",       "Global", False, False),
    ("https://feeds.content.dowjones.io/public/rss/mw_topstories",           "MarketWatch",         "US",     False, False),
    ("https://www.investing.com/rss/news.rss",                               "Investing.com",       "Global", False, False),
    ("https://www.cnbc.com/id/100727362/device/rss/rss.html",                "CNBC International",  "Global", False, False),
    ("https://www.cnbc.com/id/20910258/device/rss/rss.html",                 "CNBC Economy",        "Global", False, False),
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html",                 "CNBC Finance",        "Global", False, False),
    # central banks & regulators (primary sources)
    ("https://www.federalreserve.gov/feeds/press_all.xml",                   "US Federal Reserve",  "US",     True,  False),
    ("https://www.ecb.europa.eu/rss/press.html",                             "ECB",                 "Europe", True,  False),
    ("https://rbi.org.in/pressreleases_rss.xml",                             "RBI",                 "India",  True,  False),
    ("https://www.sebi.gov.in/sebirss.xml",                                  "SEBI",                "India",  True,  False),
    # India (economy-first: the markets feeds alone are mostly single-stock chatter)
    ("https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", "ET Economy",     "India",  False, False),
    ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "ET Markets",          "India",  False, False),
    ("https://www.livemint.com/rss/economy",                                 "Mint Economy",        "India",  False, False),
    ("https://www.business-standard.com/rss/economy-102.rss",                "Business Standard",   "India",  False, False),
    # broad macro sweep
    ("https://news.google.com/rss/search?q=(federal+reserve+OR+ECB+OR+%22central+bank%22+OR+inflation+OR+%22interest+rates%22+OR+tariffs+OR+%22oil+prices%22)+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     "Google News", "Global", False, True),
]

CATEGORIES = [
    ("Central banks & rates", r"\b(fed|federal reserve|fomc|rbi|ecb|bank of england|boj|bank of japan|pboc|central bank|interest rate|rate cut|rate hike|repo rate|monetary policy|yield|treasur(y|ies)|bond market|quantitative)\b"),
    ("Inflation & growth",    r"\b(inflation|cpi|wpi|ppi|deflation|gdp|recession|slowdown|unemployment|payroll|jobs report|pmi|consumer price)\b"),
    ("Markets",               r"\b(stocks?|equit(y|ies)|shares|nasdaq|s&p ?500|dow jones|nifty|sensex|ftse|nikkei|hang seng|dax|index|rally|sell-?off|correction|bear market|bull market|volatilit|vix|earnings)\b"),
    ("Currencies",            r"\b(dollar|rupee|euro|yen|yuan|renminbi|sterling|forex|currency|exchange rate|devaluat)\b"),
    ("Commodities & energy",  r"\b(oil|crude|brent|wti|opec|gold|silver|copper|natural gas|lng|commodit|metals?|coal|energy prices)\b"),
    ("Geopolitics & trade",   r"\b(tariff|trade war|sanction|export ban|geopolit|conflict|war|election|summit|g20|g7|treaty|trade deal|supply chain)\b"),
    ("India",                 r"\b(india|indian|rbi|sebi|rupee|nifty|sensex|mumbai|nse|bse|budget|gst)\b"),
    ("Regulation",            r"\b(sebi|regulator|regulation|compliance|circular|guidelines|amfi|irdai|sec |fca |esma)\b"),
    ("Crypto",                r"\b(bitcoin|crypto|ethereum|stablecoin|digital asset|cbdc)\b"),
    ("Corporate & deals",     r"\b(merger|acquisition|m&a|ipo|buyback|stake sale|bankrupt|layoff|profit|revenue|guidance)\b"),
]
CAT_RE = [(name, re.compile(pat, re.I)) for name, pat in CATEGORIES]

# This page is about news that moves — or hints at — the financial world. Indian market feeds in
# particular carry a lot of single-stock retail chatter that is noise at that altitude; drop it.
NOISE = re.compile(
    r"\b(bags? (an? )?(order|contract|deal)|order worth|wins? (an? )?(order|contract)|stocks? to watch|"
    r"shares? in focus|buy or sell|target price|price target|brokerage|analysts? (say|recommend)|"
    r"multibagger|penny stock|f&o ban|block deal|bonus issue|stock split|record date|"
    r"board meeting|trade setup|technical (view|picks?)|top picks?|stocks? to buy|hot stocks?|"
    r"gmp|grey market premium|should you subscribe|listing gains?|dividend alert|last day to buy|"
    r"ex-dividend|smart talk|on tradingview|positive breakout|negative breakout|"
    r"\bdmas?\b|moving averages?|muhurat|zodiac|horoscope)\b|"
    # insider-trade filings and single-stock clickbait — noise on a page about the world
    r"\b(buys?|sold|sells?|purchases?) \$[\d.,]+[kmb]? (in|of) (stock|shares)|"
    r"\binsider (buying|selling|trades?)\b|"
    r"\bwhy (is|are|did) .{2,40}\b(stock|shares|share price)\b", re.I)

# No single wire should dominate a page about the *world*. ET Markets alone can publish 30+ items
# in a day; without this the feed reads like one newspaper's markets section.
PER_SOURCE_CAP = 12

# Aggregator/newsletter spam that Google News sometimes surfaces as a "publisher".
BLOCK_SOURCES = {"tradingview", "insider monkey", "zacks", "simply wall st"}

UA = "Mozilla/5.0 (compatible; SIFintelNewsBot/1.0; +https://www.sifintel.com/news)"
# Some publishers (e.g. Business Standard) 403 anything with "bot" in the UA even on their own
# public RSS feed — retry those once as a plain browser client.
UA_FALLBACK = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MAX_ITEMS = 140
MAX_AGE_DAYS = 4
TIMEOUT = 20


def fetch(url: str) -> str:
    try:
        raw = _get(url, UA)
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403, 406, 429):
            raise
        raw = _get(url, UA_FALLBACK)
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _get(url: str, ua: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def clean(s: str) -> str:
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", s)).strip()


def pick(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>", block, re.S | re.I)
    return m.group(1) if m else ""


def parse_date(s: str):
    s = clean(s)
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def categorise(text: str) -> list[str]:
    # Topic tags come from the headline only — the publisher's home market is carried separately
    # in "region", so an Indian paper reporting on OPEC doesn't get mis-tagged "India".
    cats = [name for name, rx in CAT_RE if rx.search(text)]
    return (cats or ["Markets"])[:4]


def parse_feed(xml: str, source: str, region: str, official: bool, google: bool) -> list[dict]:
    out = []
    for m in re.finditer(r"<(item|entry)\b.*?</\1>", xml, re.S | re.I):
        block = m.group(0)
        title = clean(pick(block, "title"))
        if not title:
            continue

        link = clean(pick(block, "link"))
        if not link:
            href = re.search(r"<link[^>]*\bhref=[\"']([^\"']+)[\"']", block, re.I)
            link = href.group(1) if href else ""
        if not link:
            continue

        dt = (parse_date(pick(block, "pubDate")) or parse_date(pick(block, "published"))
              or parse_date(pick(block, "updated")) or parse_date(pick(block, "dc:date")))

        item_source = source
        if google:
            gm = re.match(r"^(.*)\s+-\s+([^-]{2,40})$", title)
            if gm:
                title, item_source = gm.group(1).strip(), gm.group(2).strip()

        summary = ""
        if not google:
            raw = pick(block, "description") or pick(block, "summary") or pick(block, "content:encoded")
            summary = strip_tags(clean(raw))[:240].strip()
            if summary.startswith(("http://", "https://")):
                summary = ""

        out.append({
            "title": title,
            "url": link,
            "source": item_source,
            "region": region,
            "official": official,
            "published": dt.isoformat().replace("+00:00", "Z") if dt else None,
            "_ts": dt.timestamp() if dt else 0.0,
            "summary": summary,
            "categories": categorise(f"{title} {summary}"),
        })
    return out


def dedupe_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:55]


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot world financial news into news_data.json")
    ap.add_argument("--out", default="news_data.json")
    args = ap.parse_args()

    items, ok, failed = [], [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch, f[0]): f for f in FEEDS}
        for fut in concurrent.futures.as_completed(futures):
            url, source, region, official, google = futures[fut]
            try:
                parsed = parse_feed(fut.result(), source, region, official, google)
                if not parsed:
                    raise ValueError("no items parsed")
                items.extend(parsed)
                ok.append(source)
            except Exception as e:                                  # noqa: BLE001 - one bad feed must not fail the run
                failed.append(source)
                print(f"  warn: {source} failed ({e})", file=sys.stderr)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).timestamp()
    seen, per_source, clean_items = set(), {}, []
    for it in sorted(items, key=lambda x: x["_ts"], reverse=True):
        if it["_ts"] and it["_ts"] < cutoff:
            continue
        if not it["official"] and NOISE.search(it["title"]):
            continue
        src = it["source"].lower()
        if src in BLOCK_SOURCES:
            continue
        if per_source.get(src, 0) >= PER_SOURCE_CAP:
            continue
        k = dedupe_key(it["title"])
        if k in seen:
            continue
        seen.add(k)
        per_source[src] = per_source.get(src, 0) + 1
        it.pop("_ts", None)
        clean_items.append(it)
        if len(clean_items) >= MAX_ITEMS:
            break

    if not clean_items:
        print("No news items fetched — keeping the existing snapshot.", file=sys.stderr)
        return 1

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "refresh_seconds": 1800,
        "count": len(clean_items),
        "sources_ok": sorted(set(ok)),
        "sources_failed": sorted(set(failed)),
        "items": clean_items,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"wrote {args.out}: {len(clean_items)} items from {len(set(ok))} feeds"
          + (f" ({len(set(failed))} failed: {', '.join(sorted(set(failed)))})" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
