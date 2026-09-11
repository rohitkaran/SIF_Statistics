// GET  /api/unsubscribe?u=<token>[&l=<list>]  -> who this token belongs to (for the page to show)
// POST /api/unsubscribe                        -> actually unsubscribe
//
// Two callers, two very different needs:
//
//  1. A human clicking "Unsubscribe" in the footer. They land on /unsubscribe, the page GETs
//     here to show whose subscription it is, and they confirm. We do NOT unsubscribe on the
//     GET — same mail-scanner problem as magic links: a prefetch would silently unsubscribe
//     people who never clicked anything.
//
//  2. Gmail/Yahoo's native unsubscribe button, which POSTs `List-Unsubscribe=One-Click` to
//     this URL with no cookie and no page (RFC 8058). That must take effect immediately and
//     answer 200, so the one-click branch below acts without confirmation.
//
// Tokens are stateless HMACs (see _lib/session.js) — an unsubscribe link in a two-year-old
// email must still work, long after any session has expired.

import { json, requireEnv } from "../_lib/http.js";
import { readUnsubToken } from "../_lib/session.js";
import { findUserById, unsubscribeAll, unsubscribeList, LISTS } from "../_lib/db.js";

export async function onRequestGet({ request, env }) {
  const bad = requireEnv(env, ["DB", "SESSION_SECRET"]);
  if (bad) return bad;

  const url = new URL(request.url);
  const userId = await readUnsubToken(env.SESSION_SECRET, url.searchParams.get("u") || "");
  if (!userId) return json({ ok: false, error: "That unsubscribe link is not valid." }, 400);

  const user = await findUserById(env.DB, userId);
  if (!user) return json({ ok: false, error: "That subscription no longer exists." }, 404);

  return json({
    ok: true,
    email: user.email,
    status: user.status,
    prefs: {
      sif_weekly: !!user.sif_weekly,
      news_daily: !!user.news_daily,
    },
    lists: Object.fromEntries(Object.entries(LISTS).map(([k, v]) => [k, v.label])),
  });
}

export async function onRequestPost({ request, env }) {
  const bad = requireEnv(env, ["DB", "SESSION_SECRET"]);
  if (bad) return bad;

  const url = new URL(request.url);
  const type = request.headers.get("Content-Type") || "";

  // One-click (RFC 8058) arrives form-encoded with the token in the query string.
  let token = url.searchParams.get("u") || "";
  let list = url.searchParams.get("l") || "";
  let oneClick = false;

  if (type.includes("application/x-www-form-urlencoded")) {
    const form = await request.formData().catch(() => null);
    if (form && String(form.get("List-Unsubscribe") || "") === "One-Click") oneClick = true;
    if (form && form.get("u")) token = String(form.get("u"));
    if (form && form.get("l")) list = String(form.get("l"));
  } else if (type.includes("application/json")) {
    const data = await request.json().catch(() => ({}));
    if (data.u) token = String(data.u);
    if (data.l) list = String(data.l);
  }

  const userId = await readUnsubToken(env.SESSION_SECRET, token);
  if (!userId) {
    // Never fail a one-click request loudly — mail providers penalise senders whose
    // unsubscribe endpoint errors. Accept it and move on.
    return oneClick ? new Response("OK", { status: 200 }) : json({ ok: false, error: "That unsubscribe link is not valid." }, 400);
  }

  if (list && LISTS[list]) await unsubscribeList(env.DB, userId, list);
  else await unsubscribeAll(env.DB, userId);

  return oneClick
    ? new Response("OK", { status: 200 })
    : json({ ok: true, message: list && LISTS[list] ? "Removed from " + LISTS[list].label + "." : "You have been unsubscribed." });
}
