// Cloudflare Pages Function: GET /api/news
//
// Aggregates world financial / macro news from public RSS feeds AT THE EDGE and serves it as JSON.
// The result is cached for 30 minutes (Cache API + Cache-Control), so /news is never more than
// half an hour stale while costing zero Cloudflare *builds*.
//
// WHY NOT A CRON COMMIT: a GitHub Action committing every 30 min = ~1,440 pushes/month, and every
// push triggers a Cloudflare Pages build. The free plan allows 500 builds/month — it would break
// the whole site's deploys. So live news is served from here; fetch_news.py still writes a
// committed news_data.json snapshot a few times a day purely as an offline fallback.
//
// No API keys, no paid services: everything below is a public RSS/Atom feed.

const FEEDS = [
  // ---- global markets & business ----
  { url: "https://feeds.bbci.co.uk/news/business/rss.xml",                        source: "BBC Business",   region: "Global" },
  { url: "https://www.theguardian.com/uk/business/rss",                           source: "The Guardian",   region: "Global" },
  { url: "https://finance.yahoo.com/news/rssindex",                               source: "Yahoo Finance",  region: "Global" },
  { url: "https://feeds.content.dowjones.io/public/rss/mw_topstories",            source: "MarketWatch",    region: "US" },
  { url: "https://www.investing.com/rss/news.rss",                                source: "Investing.com",  region: "Global" },
  { url: "https://www.cnbc.com/id/100727362/device/rss/rss.html",                 source: "CNBC International", region: "Global" },
  { url: "https://www.cnbc.com/id/20910258/device/rss/rss.html",                  source: "CNBC Economy",   region: "Global" },
  { url: "https://www.cnbc.com/id/10000664/device/rss/rss.html",                  source: "CNBC Finance",   region: "Global" },
  // ---- central banks & regulators (primary sources) ----
  { url: "https://www.federalreserve.gov/feeds/press_all.xml",                    source: "US Federal Reserve", region: "US",     official: true },
  { url: "https://www.ecb.europa.eu/rss/press.html",                              source: "ECB",            region: "Europe",    official: true },
  { url: "https://rbi.org.in/pressreleases_rss.xml",                              source: "RBI",            region: "India",     official: true },
  { url: "https://www.sebi.gov.in/sebirss.xml",                                   source: "SEBI",           region: "India",     official: true },
  // ---- India (economy-first: the markets feeds alone are mostly single-stock chatter) ----
  { url: "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", source: "ET Economy", region: "India" },
  { url: "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",  source: "ET Markets",     region: "India" },
  { url: "https://www.livemint.com/rss/economy",                                  source: "Mint Economy",   region: "India" },
];

// NOT fetched from the edge — all verified via /api/news?debug=1:
//   news.google.com        503   blocks Cloudflare's ranges
//   business-standard.com  403   blocks Cloudflare's ranges
//   bing.com/news …&format=RSS   answers with a non-RSS page (0 items parsed)
// They all work from GitHub Actions, so fetch_news.py collects them into news_data.json and
// mergeSnapshot() folds that in below — that is what keeps the Reuters/Bloomberg/WSJ-class wire
// coverage on the page.
const SNAPSHOT = "/news_data.json";

// This page is about news that moves — or hints at — the financial world. Indian market feeds in
// particular carry a lot of single-stock retail chatter that is noise at that altitude; drop it.
const NOISE = new RegExp(
  "\\b(bags? (an? )?(order|contract|deal)|order worth|wins? (an? )?(order|contract)|stocks? to watch|" +
  "shares? in focus|buy or sell|target price|price target|brokerage|analysts? (say|recommend)|" +
  "multibagger|penny stock|f&o ban|block deal|bonus issue|stock split|record date|" +
  "board meeting|trade setup|technical (view|picks?)|top picks?|stocks? to buy|hot stocks?|" +
  "gmp|grey market premium|should you subscribe|listing gains?|dividend alert|last day to buy|" +
  "ex-dividend|smart talk|on tradingview|positive breakout|negative breakout|" +
  "\\bdmas?\\b|moving averages?|muhurat|zodiac|horoscope)\\b|" +
  // insider-trade filings and single-stock clickbait — noise on a page about the world
  "\\b(buys?|sold|sells?|purchases?) \\$[\\d.,]+[kmb]? (in|of) (stock|shares)|" +
  "\\binsider (buying|selling|trades?)\\b|" +
  "\\bwhy (is|are|did) .{2,40}\\b(stock|shares|share price)\\b", "i");

// No single wire should dominate a page about the *world*. ET Markets alone can publish 30+ items
// in a day; without this the feed reads like one newspaper's markets section.
const PER_SOURCE_CAP = 12;

// Aggregator/newsletter spam that Google News sometimes surfaces as a "publisher".
const BLOCK_SOURCES = new Set(["tradingview", "insider monkey", "zacks", "simply wall st"]);

// Keyword → category. First match wins per rule; an item can carry several categories.
const CATEGORIES = [
  ["Central banks & rates", /\b(fed|federal reserve|fomc|rbi|ecb|bank of england|boj|bank of japan|pboc|central bank|interest rate|rate cut|rate hike|repo rate|monetary policy|yield|treasur(y|ies)|bond market|quantitative)\b/i],
  ["Inflation & growth",    /\b(inflation|cpi|wpi|ppi|deflation|gdp|recession|slowdown|unemployment|payroll|jobs report|pmi|consumer price)\b/i],
  ["Markets",               /\b(stocks?|equit(y|ies)|shares|nasdaq|s&p ?500|dow jones|nifty|sensex|ftse|nikkei|hang seng|dax|index|rally|sell-?off|correction|bear market|bull market|volatilit|vix|earnings)\b/i],
  ["Currencies",            /\b(dollar|rupee|euro|yen|yuan|renminbi|sterling|forex|currency|exchange rate|devaluat)\b/i],
  ["Commodities & energy",  /\b(oil|crude|brent|wti|opec|gold|silver|copper|natural gas|lng|commodit|metals?|coal|energy prices)\b/i],
  ["Geopolitics & trade",   /\b(tariff|trade war|sanction|export ban|geopolit|conflict|war|election|summit|g20|g7|treaty|trade deal|supply chain)\b/i],
  ["India",                 /\b(india|indian|rbi|sebi|rupee|nifty|sensex|mumbai|nse|bse|budget|gst)\b/i],
  ["Regulation",            /\b(sebi|regulator|regulation|compliance|circular|guidelines|amfi|irdai|sec |fca |esma)\b/i],
  ["Crypto",                /\b(bitcoin|crypto|ethereum|stablecoin|digital asset|cbdc)\b/i],
  ["Corporate & deals",     /\b(merger|acquisition|m&a|ipo|buyback|stake sale|bankrupt|layoff|profit|revenue|guidance)\b/i],
];

const MAX_ITEMS = 140;
const MAX_AGE_DAYS = 4;
const CACHE_SECONDS = 1800; // 30 minutes

export async function onRequestGet(context) {
  const { request, waitUntil } = context;
  const url = new URL(request.url);
  const debug = url.searchParams.get("debug") === "1";
  const bypass = debug || url.searchParams.get("refresh") === "1";

  const cache = caches.default;
  const cacheKey = new Request(url.origin + "/api/news", { method: "GET" });

  if (!bypass) {
    const hit = await cache.match(cacheKey);
    if (hit) return hit;
  }

  const [settled, snapshot] = await Promise.all([
    Promise.allSettled(FEEDS.map(fetchFeed)),
    mergeSnapshot(url.origin),
  ]);

  const items = [];
  const ok = [];
  const failed = [];
  const errors = {};
  settled.forEach((r, i) => {
    if (r.status === "fulfilled" && r.value.length) {
      ok.push(FEEDS[i].source);
      items.push(...r.value);
    } else {
      failed.push(FEEDS[i].source);
      // Publishers block datacenter IPs from time to time, and what works from a laptop can fail
      // from the edge. /api/news?debug=1 reports why, so a dead feed is diagnosable not guessable.
      errors[FEEDS[i].source] =
        r.status === "rejected" ? String(r.reason && r.reason.message || r.reason) : "0 items parsed";
    }
  });

  // Live feeds first, so when the same story appears in both the live pull and the snapshot the
  // live copy wins dedupe and the snapshot only ever adds coverage.
  items.push(...snapshot);

  const cutoff = Date.now() - MAX_AGE_DAYS * 86400000;
  const seen = new Set();
  const perSource = new Map();
  const clean = items
    .filter((it) => it.title && it.url)
    .filter((it) => !it.ts || it.ts >= cutoff)
    .filter((it) => it.official || !NOISE.test(it.title))
    .filter((it) => !BLOCK_SOURCES.has(it.source.toLowerCase()))
    .sort((a, b) => (b.ts || 0) - (a.ts || 0))
    .filter((it) => {
      const k = dedupeKey(it.title);
      if (seen.has(k)) return false;
      const src = it.source.toLowerCase();
      const n = perSource.get(src) || 0;
      if (n >= PER_SOURCE_CAP) return false;
      seen.add(k);
      perSource.set(src, n + 1);
      return true;
    })
    .slice(0, MAX_ITEMS);

  const body = {
    generated: new Date().toISOString(),
    refresh_seconds: CACHE_SECONDS,
    count: clean.length,
    sources_ok: ok,
    sources_failed: failed,
    ...(debug ? { errors } : {}),
    items: clean.map((it) => ({
      title: it.title,
      url: it.url,
      source: it.source,
      region: it.region,
      official: !!it.official,
      published: it.ts ? new Date(it.ts).toISOString() : null,
      summary: it.summary || "",
      categories: it.categories,
    })),
  };

  const resp = new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": `public, max-age=${CACHE_SECONDS}`,
      "Access-Control-Allow-Origin": "*",
    },
  });

  if (waitUntil && !debug) waitUntil(cache.put(cacheKey, resp.clone()));
  return resp;
}

const UA = "Mozilla/5.0 (compatible; SIFintelNewsBot/1.0; +https://www.sifintel.com/news)";
// Some publishers (e.g. Business Standard) 403 anything with "bot" in the UA even on their own
// public RSS feed — retry those once as a plain browser client.
const UA_FALLBACK =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

// Fold in the committed snapshot (written by fetch_news.py on the GitHub Action) so publishers
// that block Cloudflare still reach the page. Never fatal: no snapshot just means fewer items.
async function mergeSnapshot(origin) {
  try {
    const res = await fetch(origin + SNAPSHOT, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return [];
    const j = await res.json();
    return (j.items || []).map((it) => ({
      title: it.title,
      url: it.url,
      source: it.source,
      region: it.region,
      official: it.official,
      ts: it.published ? Date.parse(it.published) || null : null,
      summary: it.summary || "",
      categories: it.categories && it.categories.length ? it.categories : categorise(it.title),
    }));
  } catch {
    return [];
  }
}

async function fetchFeed(feed) {
  let res = await get(feed.url, UA);
  if ([401, 403, 406, 429].includes(res.status)) res = await get(feed.url, UA_FALLBACK);
  if (!res.ok) throw new Error(`${feed.source}: HTTP ${res.status}`);
  return parseFeed(await res.text(), feed);
}

function get(url, ua) {
  return fetch(url, {
    headers: {
      "User-Agent": ua,
      Accept: "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    },
    signal: AbortSignal.timeout(7000),
    cf: { cacheTtl: 900, cacheEverything: true },
  });
}

// ---- XML parsing -----------------------------------------------------------
// Workers have no DOMParser, so this is a deliberately small, forgiving regex reader.
// It handles RSS <item> and Atom <entry>, CDATA, and namespaced date fields.

function parseFeed(xml, feed) {
  const blocks = xml.match(/<(item|entry)\b[\s\S]*?<\/\1>/g) || [];
  const out = [];
  for (const b of blocks) {
    let title = clean(pick(b, "title"));
    if (!title) continue;

    let link = pick(b, "link");
    if (!link || /^\s*$/.test(link)) {
      const href = b.match(/<link[^>]*\bhref=["']([^"']+)["']/i);
      link = href ? href[1] : "";
    }
    link = clean(link);
    if (!link) continue;

    const dateStr =
      pick(b, "pubDate") || pick(b, "published") || pick(b, "updated") || pick(b, "dc:date") || "";
    const parsed = Date.parse(clean(dateStr));
    const ts = Number.isFinite(parsed) ? parsed : null;

    let source = feed.source;
    if (feed.googleNews) {
      // Google News titles read "Headline - Publisher"; recover the real publisher.
      const m = title.match(/^(.*)\s+-\s+([^-]{2,40})$/);
      if (m) {
        title = m[1].trim();
        source = m[2].trim();
      }
    } else if (feed.bingNews) {
      // Bing carries the publisher in <News:Source> and wraps links in an apiclick redirect
      // that holds the real URL in its ?url= parameter — unwrap it so readers land on the source.
      const s = clean(pick(b, "News:Source"));
      if (s) source = s;
      const real = link.match(/[?&]url=([^&]+)/);
      if (real) {
        try {
          link = decodeURIComponent(real[1]);
        } catch { /* keep the redirect link */ }
      }
    }

    let summary = "";
    if (!feed.googleNews) {
      const raw = pick(b, "description") || pick(b, "summary") || pick(b, "content:encoded") || "";
      summary = stripTags(clean(raw)).slice(0, 240).trim();
      if (/^https?:\/\//.test(summary)) summary = "";
    }

    out.push({
      title,
      url: link,
      source,
      region: feed.region,
      official: feed.official,
      ts,
      summary,
      categories: categorise(title + " " + summary),
    });
  }
  return out;
}

function pick(block, tag) {
  const re = new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)</${tag}>`, "i");
  const m = block.match(re);
  return m ? m[1] : "";
}

function clean(s) {
  return decodeEntities(
    String(s)
      .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
      .trim()
  ).replace(/\s+/g, " ");
}

function stripTags(s) {
  return s.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ");
}

function decodeEntities(s) {
  return s
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => safeChar(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => safeChar(parseInt(d, 10)))
    .replace(/&nbsp;/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function safeChar(code) {
  try {
    return String.fromCodePoint(code);
  } catch {
    return "";
  }
}

// Topic tags come from the headline only — the publisher's home market is carried separately in
// "region", so an Indian paper reporting on OPEC doesn't get mis-tagged "India".
function categorise(text) {
  const cats = [];
  for (const [name, re] of CATEGORIES) {
    if (re.test(text)) cats.push(name);
  }
  if (!cats.length) cats.push("Markets");
  return cats.slice(0, 4);
}

function dedupeKey(title) {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "").slice(0, 55);
}
