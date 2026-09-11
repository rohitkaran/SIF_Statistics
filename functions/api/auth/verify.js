// POST /api/auth/verify   — redeem a magic-link token and start a session.
//
// WHY POST AND NOT GET: corporate mail gateways, Outlook Safe Links, Slack unfurls and
// antivirus scanners all fetch every URL in an incoming email before a human sees it. If the
// emailed link redeemed the token on GET, the scanner would burn it and the real user would
// arrive to "this link has already been used" — the classic magic-link failure.
//
// So the email points at /auth?t=..., a static page, and only a deliberate POST from there
// redeems. Scanners issue GETs and never run scripts, so the token survives them. The page
// carries a plain <form method="post"> too, which keeps it working without JavaScript.
//
// Accepts either JSON ({t}) or a form post (t=...), and answers in kind: JSON for the fetch
// path, a 302 for the no-JS form path.

import { json, redirect, requireEnv } from "../../_lib/http.js";
import { redeemLoginToken } from "../../_lib/db.js";
import { makeSession, sessionCookie } from "../../_lib/session.js";

const REASONS = {
  missing: "That link was incomplete. Please request a new one.",
  unknown: "That link is not valid. It may have been mistyped — please request a new one.",
  used: "That link has already been used. Sign-in links work once; please request a fresh one.",
  expired: "That link has expired. Links are valid for 15 minutes — please request a new one.",
};

export async function onRequestPost({ request, env }) {
  const bad = requireEnv(env, ["DB", "SESSION_SECRET"]);
  if (bad) return bad;

  const type = request.headers.get("Content-Type") || "";
  const wantsForm = type.includes("application/x-www-form-urlencoded");

  let token = "";
  if (wantsForm) {
    const form = await request.formData();
    token = String(form.get("t") || "");
  } else {
    const data = await request.json().catch(() => ({}));
    token = String(data.t || "");
  }

  const fail = (reason) => wantsForm
    ? redirect("/account?e=" + reason)
    : json({ ok: false, reason, error: REASONS[reason] || REASONS.unknown }, 400);

  if (!token) return fail("missing");

  const result = await redeemLoginToken(env.DB, token);
  if (!result.ok) return fail(result.reason);

  const cookie = sessionCookie(await makeSession(env.SESSION_SECRET, result.userId));
  return wantsForm
    ? redirect("/account?welcome=1", { "Set-Cookie": cookie })
    : json({ ok: true, next: "/account?welcome=1" }, 200, { "Set-Cookie": cookie });
}

// A GET here means something prefetched the link or a human pasted the API URL directly.
// Never redeem — just point at the page that can.
export async function onRequestGet({ request }) {
  const t = new URL(request.url).searchParams.get("t");
  return redirect(t ? "/auth?t=" + encodeURIComponent(t) : "/account");
}
