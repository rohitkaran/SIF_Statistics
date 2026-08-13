// Cloudflare Pages Function: the SIFintel Data API  —  /api/v1/*
//
// Sells access to the dataset the site already maintains: every Indian SIF's NAV history since the
// category launched, plus the disclosed portfolios. The data itself is the committed JSON in this
// repo; this layer adds shape, filtering and key gating.
//
//   GET /api/v1/schemes                       list every scheme (metadata)
//   GET /api/v1/nav?code=SIF-120&from=&to=    NAV series for one scheme (or all, with a key)
//   GET /api/v1/portfolios?scheme=&period=    disclosed holdings
//   GET /api/v1/meta                          dataset coverage + your plan
//
// AUTH:  Authorization: Bearer <key>   (or ?key=<key>)
// Keys live in the Pages env var API_KEYS as a comma-separated list of  key:label:tier
//   e.g.  API_KEYS = "sk_live_abc:Acme AMC:pro,sk_live_xyz:Beta Wealth:starter"
// Set it in Cloudflare → Pages → sif-statistics → Settings → Environment variables (encrypted).
//
// No key still works, deliberately: it returns the last 30 days for a single scheme so an evaluator
// can try before buying. That free tier IS the sales demo.
//
// NOTE ON RATE LIMITING: proper per-key quotas need KV or Durable Objects (a paid/bound resource).
// Until one is bound, this enforces plan-based *scope* limits only, not request counts. Add KV and
// wire incrementUsage() when the first paying customer signs.

const PLANS = {
  free:    { days: 30,   schemes: 1,        portfolios: false, label: "Free evaluation" },
  starter: { days: 400,  schemes: Infinity, portfolios: false, label: "Starter" },
  pro:     { days: 9999, schemes: Infinity, portfolios: true,  label: "Pro" },
};

export async function onRequestGet(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  const route = (url.pathname.replace(/^\/api\/v1\/?/, "").replace(/\/+$/, "") || "meta").toLowerCase();

  const auth = authenticate(request, url, env);
  const plan = PLANS[auth.tier] || PLANS.free;

  try {
    switch (route) {
      case "meta":
        return json(await meta(url.origin, auth, plan));
      case "schemes":
        return json(await schemes(url.origin, url));
      case "nav":
        return json(await nav(url.origin, url, plan, auth));
      case "portfolios":
        return json(await portfolios(url.origin, url, plan, auth));
      default:
        return json({ error: `Unknown endpoint '${route}'.`, endpoints: ["meta", "schemes", "nav", "portfolios"] }, 404);
    }
  } catch (e) {
    return json({ error: String(e && e.message || e) }, 500);
  }
}

function authenticate(request, url, env) {
  const header = request.headers.get("Authorization") || "";
  const key = (header.match(/^Bearer\s+(.+)$/i) || [])[1] || url.searchParams.get("key") || "";
  if (!key) return { tier: "free", client: null };

  for (const entry of String(env.API_KEYS || "").split(",")) {
    const [k, label, tier] = entry.split(":").map((s) => (s || "").trim());
    if (k && k === key) return { tier: tier || "starter", client: label || "client" };
  }
  return { tier: "free", client: null, rejected: true };
}

async function load(origin, path) {
  const res = await fetch(origin + path, { cf: { cacheTtl: 300, cacheEverything: true } });
  if (!res.ok) throw new Error(`could not load ${path}`);
  return res.json();
}

async function meta(origin, auth, plan) {
  const n = await load(origin, "/nav_data.json");
  const dates = n.schemes.flatMap((s) => (s.series || []).map((p) => p[0])).sort();
  return {
    dataset: "Indian Specialized Investment Funds (SIFs)",
    publisher: "SIFintel — Lume Software Private Limited",
    schemes: n.schemes.length,
    fund_houses: new Set(n.schemes.map((s) => s.sif)).size,
    observations: n.schemes.reduce((a, s) => a + (s.series || []).length, 0),
    coverage: { from: dates[0] || null, to: dates[dates.length - 1] || null },
    updated: n.generated,
    source: n.source,
    your_plan: {
      tier: Object.keys(PLANS).find((k) => PLANS[k] === plan),
      label: plan.label,
      client: auth.client,
      nav_history_days: plan.days === 9999 ? "full" : plan.days,
      schemes_per_request: plan.schemes === Infinity ? "all" : plan.schemes,
      portfolios: plan.portfolios,
      ...(auth.rejected ? { notice: "The key supplied was not recognised — serving the free tier." } : {}),
    },
    upgrade: "https://www.sifintel.com/data",
    terms: "Attribution to SIFintel required on redistribution. NAVs sourced from AMFI.",
  };
}

async function schemes(origin, url) {
  const n = await load(origin, "/nav_data.json");
  const q = (url.searchParams.get("q") || "").toLowerCase();
  const house = (url.searchParams.get("sif") || "").toLowerCase();
  const items = n.schemes
    .filter((s) => !q || s.name.toLowerCase().includes(q))
    .filter((s) => !house || (s.sif || "").toLowerCase().includes(house))
    .map((s) => ({
      code: s.code, name: s.name, category: s.cat, fund_house: s.sif, isin: s.isin,
      observations: (s.series || []).length,
      latest: s.series && s.series.length ? { date: s.series[s.series.length - 1][0], nav: s.series[s.series.length - 1][1] } : null,
    }));
  return { count: items.length, updated: n.generated, schemes: items };
}

async function nav(origin, url, plan, auth) {
  const n = await load(origin, "/nav_data.json");
  const code = url.searchParams.get("code");
  const isin = url.searchParams.get("isin");

  let picked = n.schemes;
  if (code) picked = picked.filter((s) => s.code === code);
  else if (isin) picked = picked.filter((s) => s.isin === isin);

  if (!picked.length) return { error: "No scheme matched. Try /api/v1/schemes to list codes.", count: 0, schemes: [] };
  if (picked.length > plan.schemes) {
    return {
      error: `Your plan returns ${plan.schemes} scheme per request. Pass ?code= or upgrade.`,
      upgrade: "https://www.sifintel.com/data",
      count: 0, schemes: [],
    };
  }

  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");
  const floor = plan.days >= 9999 ? null : isoDaysAgo(plan.days);

  const out = picked.map((s) => {
    let series = s.series || [];
    if (floor) series = series.filter((p) => p[0] >= floor);
    if (from) series = series.filter((p) => p[0] >= from);
    if (to) series = series.filter((p) => p[0] <= to);
    return {
      code: s.code, name: s.name, category: s.cat, fund_house: s.sif, isin: s.isin,
      count: series.length,
      series: series.map((p) => ({ date: p[0], nav: p[1] })),
    };
  });

  return {
    count: out.length, updated: n.generated,
    truncated_to_days: floor ? plan.days : null,
    ...(floor ? { upgrade: "https://www.sifintel.com/data" } : {}),
    schemes: out,
  };
}

async function portfolios(origin, url, plan) {
  if (!plan.portfolios) {
    return { error: "Disclosed portfolios are available on the Pro plan.", upgrade: "https://www.sifintel.com/data" };
  }
  const index = await load(origin, "/portfolios/index.json");
  const period = url.searchParams.get("period");
  const scheme = url.searchParams.get("scheme");
  if (!period || !scheme) {
    return { periods: index.periods, note: index.note, usage: "/api/v1/portfolios?period=2026-06&scheme=<file>", index };
  }
  return load(origin, `/portfolios/data/${encodeURIComponent(period)}/${encodeURIComponent(scheme)}.json`);
}

function isoDaysAgo(days) {
  return new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 1), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
