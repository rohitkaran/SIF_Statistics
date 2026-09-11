// Shared helpers for the newsletter endpoints. Leading underscore => Cloudflare Pages does not
// route this file; it is imported by subscribe/confirm/unsubscribe.
//
// The subscription is DOUBLE OPT-IN and STATELESS. There is no database: the confirmation and
// unsubscribe links carry the address plus an HMAC signature, so only a link this site generated
// can confirm an address. That matters for more than tidiness — without it anyone could sign up
// somebody else's address, which is both rude and the fastest way to get a sending domain
// blacklisted.
//
// Required env (Pages → Settings → Environment variables):
//   RESEND_API_KEY          already set for the contact form
//   NEWSLETTER_SECRET       any long random string; signs the links
// Optional:
//   NEWSLETTER_AUDIENCE_ID  Resend audience to add confirmed subscribers to
//   NEWSLETTER_FROM         default: SIFintel <newsletter@sifintel.com>
//   NEWSLETTER_NOTIFY       default: ceo@lumesoftai.com

export const DEFAULT_FROM = "SIFintel <newsletter@sifintel.com>";
export const DEFAULT_NOTIFY = "ceo@lumesoftai.com";
export const SITE = "https://www.sifintel.com";

// Confirmation links expire; unsubscribe links must not, because people unsubscribe from an
// email they dug out of the archive two months later.
export const CONFIRM_TTL_DAYS = 7;

export function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

export function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

export function normalizeEmail(raw) {
  const email = String(raw || "").trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return null;
  if (email.length > 254) return null;            // RFC 5321 maximum
  return email;
}

// --- signing ------------------------------------------------------------------------

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function unb64url(str) {
  const s = String(str).replace(/-/g, "+").replace(/_/g, "/");
  const pad = s.length % 4 ? "=".repeat(4 - (s.length % 4)) : "";
  const bin = atob(s + pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function key(secret) {
  return crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

/** token = base64url(payload) "." base64url(hmac) — payload is "kind:email:expiryEpoch". */
export async function sign(secret, kind, email, ttlDays) {
  const exp = ttlDays ? Math.floor(Date.now() / 1000) + ttlDays * 86400 : 0;
  const payload = `${kind}:${email}:${exp}`;
  const bytes = new TextEncoder().encode(payload);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", await key(secret), bytes));
  return `${b64url(bytes)}.${b64url(sig)}`;
}

/** Returns {email} when the token is authentic and unexpired, else {error}. */
export async function verify(secret, kind, token) {
  const parts = String(token || "").split(".");
  if (parts.length !== 2) return { error: "This link is not valid." };
  let payloadBytes, sigBytes;
  try {
    payloadBytes = unb64url(parts[0]);
    sigBytes = unb64url(parts[1]);
  } catch {
    return { error: "This link is not valid." };
  }
  // crypto.subtle.verify is constant-time, so this does not leak the signature by timing.
  const ok = await crypto.subtle.verify("HMAC", await key(secret), sigBytes, payloadBytes);
  if (!ok) return { error: "This link is not valid." };

  const payload = new TextDecoder().decode(payloadBytes);
  const sep = payload.indexOf(":");
  const last = payload.lastIndexOf(":");
  if (sep < 0 || last <= sep) return { error: "This link is not valid." };
  const gotKind = payload.slice(0, sep);
  const email = payload.slice(sep + 1, last);
  const exp = Number(payload.slice(last + 1));
  // A confirm token must not be usable as an unsubscribe token, or vice versa.
  if (gotKind !== kind) return { error: "This link is not valid." };
  if (exp && Date.now() / 1000 > exp)
    return { error: "This link has expired. Please subscribe again." };
  return { email };
}

// --- Resend -------------------------------------------------------------------------

export async function sendEmail(env, { to, subject, html, text, headers }) {
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: env.NEWSLETTER_FROM || DEFAULT_FROM,
      to: [to], subject, html, text,
      ...(headers ? { headers } : {}),
    }),
  });
  return resp.ok;
}

/**
 * Best-effort add to the Resend audience.
 *
 * Deliberately NOT the system of record. This code was written without access to a live Resend
 * account to verify the endpoint against, so every confirmed address is ALSO emailed to the
 * owner (see confirm.js). If this call is wrong or the audience id is unset, the subscriber is
 * still recoverable from that inbox rather than silently lost.
 */
export async function addContact(env, email) {
  const audience = env.NEWSLETTER_AUDIENCE_ID;
  if (!audience) return { ok: false, reason: "NEWSLETTER_AUDIENCE_ID not set" };
  try {
    const resp = await fetch(
      `https://api.resend.com/audiences/${encodeURIComponent(audience)}/contacts`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.RESEND_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, unsubscribed: false }),
      });
    if (resp.ok) return { ok: true };
    return { ok: false, reason: `Resend ${resp.status}: ${(await resp.text()).slice(0, 200)}` };
  } catch (e) {
    return { ok: false, reason: String(e).slice(0, 200) };
  }
}

export async function removeContact(env, email) {
  const audience = env.NEWSLETTER_AUDIENCE_ID;
  if (!audience) return { ok: false, reason: "NEWSLETTER_AUDIENCE_ID not set" };
  try {
    const resp = await fetch(
      `https://api.resend.com/audiences/${encodeURIComponent(audience)}/contacts/${encodeURIComponent(email)}`,
      { method: "DELETE", headers: { Authorization: `Bearer ${env.RESEND_API_KEY}` } });
    return resp.ok ? { ok: true } : { ok: false, reason: `Resend ${resp.status}` };
  } catch (e) {
    return { ok: false, reason: String(e).slice(0, 200) };
  }
}

// --- the little HTML pages confirm/unsubscribe land on -------------------------------

export function page(title, heading, body, ok = true) {
  const accent = ok ? "#12a150" : "#e5484d";
  return new Response(`<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} · SIFintel</title>
<meta name="robots" content="noindex">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/site.css">
<style>
  .nlwrap{max-width:560px;margin:0 auto;padding:64px 20px;text-align:center}
  .nlwrap h1{font-size:26px;margin:0 0 10px;color:var(--ink)}
  .nlwrap p{color:var(--ink-dim);line-height:1.65}
  .nlmark{font-size:34px;line-height:1;margin-bottom:14px;color:${accent}}
  .nlwrap .btn{margin-top:22px}
</style>
</head><body>
<div class="nlwrap">
  <div class="nlmark">${ok ? "&#10003;" : "&#33;"}</div>
  <h1>${esc(heading)}</h1>
  ${body}
  <a class="btn" href="${SITE}/">Go to the dashboard</a>
</div>
</body></html>`, {
    status: ok ? 200 : 400,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}
