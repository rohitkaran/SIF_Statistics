// Builds the two newsletter editions from the data this repo already publishes.
// Exports no handler => generates no route.
//
// Everything is derived at send time from the committed JSON (nav_data.json, nfo_data.json,
// portfolios/index.json, commentary/index.json) and the live /api/news aggregator — the same
// sources the website renders. There is no separate newsletter content store to keep in sync:
// if the dashboard is right, the email is right.

import { esc, section, paragraph, newsItem, statRow, table, button, wrapEmail } from "./email.js";

const DAY = 86400000;

async function loadJSON(origin, path, { optional = false } = {}) {
  try {
    const res = await fetch(origin + path, { cf: { cacheTtl: 120, cacheEverything: true } });
    if (!res.ok) {
      if (optional) return null;
      throw new Error("could not load " + path + " (" + res.status + ")");
    }
    return await res.json();
  } catch (e) {
    if (optional) return null;
    throw e;
  }
}

function pct(x) {
  return (x >= 0 ? "+" : "") + x.toFixed(2) + "%";
}

function fmtDate(iso) {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

// ------------------------------------------------------ the morning news brief

// How many headlines go in the email. The /news page shows everything; the brief is a scan
// over breakfast, so it is capped and official (central bank / regulator) items float up.
const NEWS_LIMIT = 12;
const NEWS_OFFICIAL_LIMIT = 4;
// No single outlet may take over the brief. RBI alone files several routine press releases a
// day (VRRR auctions, money-market operations); without this the "official" block and the
// India block both fill with RBI and the reader sees one regulator's admin, not the world.
const NEWS_PER_SOURCE = 3;

function capPerSource(items, cap = NEWS_PER_SOURCE) {
  const seen = new Map();
  return items.filter((i) => {
    const n = (seen.get(i.source) || 0) + 1;
    seen.set(i.source, n);
    return n <= cap;
  });
}

export async function newsDigest(origin, { istDay }) {
  // Prefer the live edge aggregator (never more than 30 min stale); fall back to the committed
  // snapshot if it is down, so a feed outage degrades the brief rather than cancelling it.
  let items = [];
  const live = await loadJSON(origin, "/api/news", { optional: true });
  if (live && Array.isArray(live.items)) items = live.items;
  if (!items.length) {
    const snap = await loadJSON(origin, "/news_data.json", { optional: true });
    if (snap && Array.isArray(snap.items)) items = snap.items;
  }
  if (!items.length) return null; // nothing to say — the caller skips the send entirely

  // Only genuinely recent news. A brief that leads with three-day-old headlines trains people
  // to stop opening it.
  const cutoff = Date.now() - 36 * 3600000;
  const fresh = items.filter((it) => {
    const t = Date.parse(it.published || it.date || "");
    return !Number.isFinite(t) || t >= cutoff;
  });
  const pool = capPerSource(fresh.length >= 6 ? fresh : items);

  const official = pool.filter((i) => i.official).slice(0, NEWS_OFFICIAL_LIMIT);
  const rest = pool.filter((i) => !official.includes(i));
  const india = rest.filter((i) => i.region === "India").slice(0, 4);
  const world = rest.filter((i) => !india.includes(i)).slice(0, NEWS_LIMIT - official.length - india.length);

  let body = paragraph(
    "Here is what moved the financial world overnight &mdash; central banks and regulators first, " +
    "then India, then the rest.", { size: 15 }
  );

  if (official.length) {
    body += section("From the central banks & regulators");
    body += official.map((i) => newsItem({ ...i, official: true })).join("");
  }
  if (india.length) {
    body += section("India");
    body += india.map((i) => newsItem(i)).join("");
  }
  if (world.length) {
    body += section("World");
    body += world.map((i) => newsItem(i)).join("");
  }

  body += button(origin + "/news", "Read the full news desk");

  const lead = (official[0] || india[0] || world[0] || {}).title || "";
  return {
    subject: "Morning brief &middot; " + fmtDate(istDay),
    preheader: lead.slice(0, 140),
    body,
    text: [
      "SIFintel morning brief - " + fmtDate(istDay),
      "",
      ...[...official, ...india, ...world].map((i) => "* " + i.title + "\n  " + i.source + " - " + i.url),
      "",
      "Full news desk: " + origin + "/news",
    ].join("\n"),
  };
}

// --------------------------------------------------------- the weekly SIF digest

// One NAV series -> return over the trailing `days`. Returns null when the series does not
// actually span the window (a fund that listed on Wednesday has no weekly number, and
// inventing one from its first NAV would put a fake +40% at the top of the movers table).
function trailingReturn(series, days) {
  if (!series || series.length < 2) return null;
  const last = series[series.length - 1];
  const cutoff = new Date(Date.parse(last[0] + "T00:00:00Z") - days * DAY).toISOString().slice(0, 10);
  let start = null;
  for (const p of series) {
    if (p[0] <= cutoff) start = p;
    else break;
  }
  if (!start || !start[1]) return null;
  // Guard against a hole in the series. `start` is the last point at or before the cutoff, so
  // if a fund stopped reporting for a while that point can be far older than the window and we
  // would print a multi-week move labelled as a week. 14 days leaves room for a long holiday
  // close (Indian markets shut for several consecutive days more than once a year).
  const span = (Date.parse(last[0]) - Date.parse(start[0])) / DAY;
  if (span > days * 2) return null;
  return { pct: (last[1] / start[1] - 1) * 100, from: start[0], to: last[0], nav: last[1], span };
}

// AMFI lists every plan/option as its own scheme code, so one fund appears up to four times
// with near-identical NAVs. Without collapsing them, the movers table shows the same fund
// three times and crowds out real ones.
//
// The naming is genuinely inconsistent across fund houses — all of these are real:
//   "WSIF Equity Long-Short Fund - Direct Growth"                (plan, then option)
//   "qsif Hybrid Long-Short Fund - Growth Option - Direct Plan"  (option, then plan)
//   "qsif Sector Rotation Long-Short Fund - Growth Option - RegularPlan"   (no space)
//   "Apex Equity Long-short Fund-Direct Growth"                  (no spaces around the dash)
//   "Sapphire Equity Long-Short SIF - Growth"                    (plan omitted entirely)
// so anything that splits on a separator and takes the first part gets it wrong somewhere.
// Instead: delete the plan/option vocabulary wherever it appears, then compare what is left.
// Payout frequency is part of the packaging too: Arudha alone ships Annual, Half Yearly,
// Fortnightly, Monthly and Quarterly IDCW variants of one fund. Dropping these here means the
// collapse does not depend on the fund having disclosed a portfolio yet.
const PLAN_WORDS = /\b(direct|regular|plan|growth|idcw|option|payout|reinvest(?:ment)?|dividend|annual(?:ly)?|half\s*yearly|semi\s*annual|fortnightly|monthly|quarterly|weekly|daily)\b/gi;

function nameKey(scheme) {
  const norm = String(scheme.name)
    .replace(/([a-z])(Plan|Option)\b/g, "$1 $2")   // "RegularPlan" -> "Regular Plan"
    .toLowerCase()
    .replace(PLAN_WORDS, " ")
    .replace(/[^a-z0-9]+/g, " ")                    // "Ex- Top 100" == "Ex-Top 100"
    .trim();
  return (scheme.sif || "") + "|" + norm;
}

// Collapse to the Direct Growth line — the cleanest read on manager skill (no distributor
// commission, no payout drag) and the one the dashboard already sorts on.
function preferredPlanRank(name) {
  const n = name.toLowerCase();
  let rank = 0;
  if (n.includes("direct")) rank += 2;
  if (n.includes("growth")) rank += 1;
  return rank;
}

// Names alone are not quite enough: fund houses make typos, and an AMC that spells one fund
// "Actice Asset Allocator" on its IDCW codes and "Active Asset Allocator" on its Growth codes
// would appear twice. portfolios/index.json already resolves scheme code -> disclosed fund
// (the portfolio fetcher maps by strategy token, not name), so where it has an opinion it is
// authoritative. Use it to merge groups the names left apart — a tiny union-find.
function dedupeToFunds(schemes, codeToFund) {
  const parent = new Map();
  const find = (x) => {
    while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); }
    return x;
  };
  const union = (a, b) => {
    const ra = find(a), rb = find(b);
    if (ra !== rb) parent.set(ra, rb);
  };

  for (const s of schemes) {
    const k = nameKey(s);
    if (!parent.has(k)) parent.set(k, k);
  }
  if (codeToFund) {
    const byPortfolioFund = new Map();
    for (const s of schemes) {
      const fund = codeToFund[s.code];
      if (!fund) continue;
      const k = nameKey(s);
      if (byPortfolioFund.has(fund)) union(k, byPortfolioFund.get(fund));
      else byPortfolioFund.set(fund, k);
    }
  }

  const best = new Map();
  for (const s of schemes) {
    const root = find(nameKey(s));
    const rank = preferredPlanRank(s.name);
    const prev = best.get(root);
    if (!prev || rank > prev.rank) best.set(root, { scheme: s, rank });
  }
  return [...best.values()].map((v) => v.scheme);
}

// Everything from the first plan/option word onward is packaging, not the fund's name.
function cleanFundName(name) {
  const m = String(name).match(/\s*[-–—]?\s*\b(direct|regular|growth|idcw|plan|option)\b/i);
  const out = (m ? name.slice(0, m.index) : name).replace(/[\s\-–—]+$/, "").trim();
  return out || name;
}

export async function sifDigest(origin, { istDay }) {
  const nav = await loadJSON(origin, "/nav_data.json");
  const bench = await loadJSON(origin, "/benchmark_data.json", { optional: true });
  const nfo = await loadJSON(origin, "/nfo_data.json", { optional: true });
  const pf = await loadJSON(origin, "/portfolios/index.json", { optional: true });
  const commentary = await loadJSON(origin, "/commentary/index.json", { optional: true });
  const note = await loadJSON(origin, "/newsletter_note.json", { optional: true });

  // scheme code -> disclosed fund identity, where the portfolio pipeline knows one.
  const codeToFund = {};
  if (pf && pf.schemes) {
    for (const [code, entry] of Object.entries(pf.schemes)) {
      if (entry && entry.fund) codeToFund[code] = (entry.amc || "") + "|" + entry.fund;
    }
  }

  const funds = dedupeToFunds(nav.schemes || [], codeToFund);
  const moves = funds
    .map((s) => ({ s, r: trailingReturn(s.series, 7) }))
    .filter((m) => m.r)
    .sort((a, b) => b.r.pct - a.r.pct);

  if (!moves.length) return null;

  const benchWeek = bench && bench.series ? trailingReturn(bench.series, 7) : null;
  const asOf = moves[0].r.to;

  let body = "";

  // ---- the optional note from you -------------------------------------------------
  // Two ways to lead the email with something human. newsletter_note.json wins (it is the
  // deliberate "I want to say something this week" lever); otherwise a commentary post
  // published since the last send leads instead. With neither, the data speaks for itself.
  const noteActive = note && note.active !== false &&
    (!note.expires || note.expires >= istDay);
  const recentPost = commentary && commentary.posts &&
    commentary.posts.find((p) => p.date && Date.parse(p.date) >= Date.now() - 8 * DAY);

  if (noteActive && note.html) {
    if (note.title) {
      body += '<h1 style="margin:14px 0 8px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,' +
        'sans-serif;font-size:23px;line-height:1.25;letter-spacing:-.4px;color:#1c2338">' +
        esc(note.title) + "</h1>";
    }
    body += '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
      'font-size:15px;line-height:1.65;color:#4a5578">' + note.html + "</div>";
  } else if (recentPost) {
    body += '<h1 style="margin:14px 0 8px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,' +
      'sans-serif;font-size:23px;line-height:1.25;letter-spacing:-.4px;color:#1c2338">' +
      esc(recentPost.title) + "</h1>";
    body += paragraph(esc(recentPost.summary || ""));
    body += button(origin + "/commentary/" + recentPost.slug, "Read the full piece");
  } else {
    body += paragraph(
      "Your weekly read on India's Specialized Investment Funds &mdash; who moved, what they now " +
      "hold, and what is new in the category. Week to " + fmtDate(asOf) + ".", { size: 15 }
    );
  }

  // ---- the week in numbers --------------------------------------------------------
  body += section("The week in numbers");
  const up = moves.filter((m) => m.r.pct > 0).length;
  let intro = "<strong>" + up + " of " + moves.length + "</strong> SIF funds finished the week higher";
  if (benchWeek) {
    intro += ", against NIFTY 50 at <strong>" + pct(benchWeek.pct) + "</strong>";
  }
  body += paragraph(intro + ".");

  const winners = moves.slice(0, 5);
  const losers = moves.slice(-5).reverse().filter((m) => !winners.includes(m));

  body += table(winners.map((m) => statRow(
    cleanFundName(m.s.name), m.s.sif, pct(m.r.pct), m.r.pct >= 0
  )));

  if (losers.length) {
    body += section("Weakest of the week");
    body += table(losers.map((m) => statRow(
      cleanFundName(m.s.name), m.s.sif, pct(m.r.pct), m.r.pct >= 0
    )));
  }

  // ---- newly disclosed portfolios -------------------------------------------------
  if (pf && pf.periods && pf.periods.length) {
    const latest = pf.periods[pf.periods.length - 1];
    const count = Object.values(pf.schemes || {}).filter((s) => s.periods && s.periods[latest]).length;
    if (count) {
      body += section("Latest portfolio disclosures");
      body += paragraph(
        "<strong>" + count + "</strong> scheme" + (count === 1 ? "" : "s") + " now have holdings disclosed " +
        "for <strong>" + latest + "</strong> &mdash; what each fund is actually long, short and holding in cash."
      );
      body += button(origin + "/", "Open the holdings view");
    }
  }

  // ---- new fund offers ------------------------------------------------------------
  if (nfo && Array.isArray(nfo.nfos)) {
    const open = nfo.nfos.filter((n) => n.status === "open");
    if (open.length) {
      body += section("Open new fund offers");
      body += table(open.slice(0, 6).map((n) => statRow(n.strategy || n.key, n.fund_house, "open")));
      body += paragraph('<a href="' + origin + '/nfo" style="color:#0e9aa7">See every tracked NFO</a>', { size: 14 });
    }
  }

  body += button(origin + "/", "Open the full SIF dashboard");

  return {
    subject: "SIF weekly &middot; " +
      (noteActive && note.title ? note.title : recentPost ? recentPost.title : winners[0] ? cleanFundName(winners[0].s.name) + " leads the week" : fmtDate(asOf)),
    preheader: up + " of " + moves.length + " SIF funds finished the week higher" +
      (benchWeek ? ", NIFTY 50 " + pct(benchWeek.pct) : "") + ".",
    body,
    text: [
      "SIFintel weekly - week to " + fmtDate(asOf),
      "",
      up + " of " + moves.length + " SIF funds finished higher" + (benchWeek ? "; NIFTY 50 " + pct(benchWeek.pct) : "") + ".",
      "",
      "Leaders:",
      ...winners.map((m) => "  " + cleanFundName(m.s.name) + " (" + m.s.sif + ") " + pct(m.r.pct)),
      ...(losers.length ? ["", "Laggards:", ...losers.map((m) => "  " + cleanFundName(m.s.name) + " (" + m.s.sif + ") " + pct(m.r.pct))] : []),
      "",
      "Full dashboard: " + origin + "/",
    ].join("\n"),
  };
}

export async function buildEdition(kind, origin, opts) {
  const built = kind === "news" ? await newsDigest(origin, opts) : await sifDigest(origin, opts);
  if (!built) return null;
  return built;
}

export { wrapEmail, loadJSON };
