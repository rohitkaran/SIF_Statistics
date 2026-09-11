// Signed-cookie sessions + stateless unsubscribe tokens.
//
// This file exports no onRequest* handler, so Cloudflare Pages generates no route for it —
// it is a plain module the route files import.
//
// WHY A SIGNED COOKIE AND NOT A SESSION TABLE: sessions here are low-stakes (they gate a
// preferences page, not money or personal data beyond an email address). An HMAC-signed
// cookie needs zero database reads on every request, which matters on the D1 free tier.
// The trade-off is that we cannot revoke one early; the 30-day expiry is the bound.

const SESSION_COOKIE = "sif_session";
const SESSION_DAYS = 30;
const TOKEN_TTL_MIN = 15;

const enc = new TextEncoder();

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomToken(bytes = 32) {
  return b64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

export function uuid() {
  return crypto.randomUUID();
}

async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
}

async function sign(secret, message) {
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode(message));
  return b64url(new Uint8Array(sig));
}

// Constant-time-ish compare. Length is not secret here (both sides are fixed-width base64url).
function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", enc.encode(value));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------- sessions

export async function makeSession(secret, userId) {
  const exp = Date.now() + SESSION_DAYS * 86400000;
  const payload = `${userId}.${exp}`;
  return `${payload}.${await sign(secret, payload)}`;
}

export async function readSession(request, secret) {
  const raw = getCookie(request, SESSION_COOKIE);
  if (!raw) return null;
  const i = raw.lastIndexOf(".");
  if (i < 0) return null;
  const payload = raw.slice(0, i);
  const sig = raw.slice(i + 1);
  if (!safeEqual(sig, await sign(secret, payload))) return null;
  const [userId, exp] = payload.split(".");
  if (!userId || !exp || Number(exp) < Date.now()) return null;
  return { userId };
}

export function sessionCookie(value, { clear = false } = {}) {
  const age = clear ? 0 : SESSION_DAYS * 86400;
  return `${SESSION_COOKIE}=${clear ? "" : value}; Path=/; Max-Age=${age}; HttpOnly; Secure; SameSite=Lax`;
}

export function getCookie(request, name) {
  const header = request.headers.get("Cookie") || "";
  for (const part of header.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return null;
}

// ------------------------------------------------------- unsubscribe links

// Stateless: userId + HMAC. No table, no expiry — an unsubscribe link printed in an email
// from 2027 must still work, and one-click unsubscribe (RFC 8058) has to succeed without a
// session. The "unsub" domain separator stops a session cookie being replayed as an
// unsubscribe token or vice versa.
export async function unsubToken(secret, userId) {
  return `${userId}.${await sign(secret, `unsub:${userId}`)}`;
}

export async function readUnsubToken(secret, token) {
  const i = (token || "").lastIndexOf(".");
  if (i < 0) return null;
  const userId = token.slice(0, i);
  const sig = token.slice(i + 1);
  if (!safeEqual(sig, await sign(secret, `unsub:${userId}`))) return null;
  return userId;
}

export async function loginTokenTTL() {
  return TOKEN_TTL_MIN;
}

export { SESSION_COOKIE, TOKEN_TTL_MIN };
