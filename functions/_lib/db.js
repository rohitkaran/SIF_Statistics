// D1 access layer. Every SQL statement in the project lives here so the routes stay readable
// and the query shapes are reviewable in one place. Exports no handler => generates no route.

import { uuid, sha256Hex, randomToken, TOKEN_TTL_MIN } from "./session.js";

export const LISTS = {
  sif_weekly: { column: "sif_weekly", label: "SIF weekly intel", kind: "sif" },
  news_daily: { column: "news_daily", label: "Morning financial news", kind: "news" },
};

export function nowISO() {
  return new Date().toISOString();
}

// The whole product runs on India time: "the morning brief" means 7am IST, and the weekly
// digest is stamped with the IST date. Doing this by offset rather than Intl keeps it cheap
// and, unlike most timezones, IST has no DST to get wrong.
export function istDate(at = Date.now()) {
  return new Date(at + 5.5 * 3600000).toISOString().slice(0, 10);
}

export function istWeekday(dateStr) {
  return new Date(dateStr + "T00:00:00Z").getUTCDay(); // 0 Sun .. 6 Sat
}

export function normaliseEmail(email) {
  return String(email || "").trim().toLowerCase();
}

export function validEmail(email) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email) && email.length <= 254;
}

// ------------------------------------------------------------------ users

export async function findUserByEmail(db, email) {
  return db.prepare("SELECT * FROM users WHERE email = ?").bind(normaliseEmail(email)).first();
}

export async function findUserById(db, id) {
  return db.prepare("SELECT * FROM users WHERE id = ?").bind(id).first();
}

// Sign-up and sign-in are the same action: ask for a link, and you get an account if you did
// not have one. There is deliberately no separate "register" route to drift out of sync.
export async function upsertUser(db, { email, name = null, source = null, prefs = {} }) {
  const existing = await findUserByEmail(db, email);
  if (existing) {
    // A returning subscriber who had unsubscribed is reactivated by asking for a link again,
    // and any lists ticked on the form are merged in rather than replacing their choices.
    const sets = [];
    const binds = [];
    if (existing.status !== "active") sets.push("status = 'active'");
    for (const [key, meta] of Object.entries(LISTS)) {
      if (prefs[key]) sets.push(meta.column + " = 1");
    }
    if (name && !existing.name) { sets.push("name = ?"); binds.push(name); }
    if (sets.length) {
      await db.prepare("UPDATE users SET " + sets.join(", ") + " WHERE id = ?")
        .bind(...binds, existing.id).run();
    }
    return findUserById(db, existing.id);
  }

  const id = uuid();
  await db.prepare(
    "INSERT INTO users (id, email, name, created_at, status, source, sif_weekly, news_daily, news_scope) " +
    "VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)"
  ).bind(
    id, normaliseEmail(email), name, nowISO(), source,
    prefs.sif_weekly ? 1 : 0,
    prefs.news_daily ? 1 : 0,
    prefs.news_scope === "everyday" ? "everyday" : "weekdays"
  ).run();
  return findUserById(db, id);
}

export async function updatePrefs(db, userId, prefs) {
  await db.prepare(
    "UPDATE users SET sif_weekly = ?, news_daily = ?, news_scope = ?, name = ?, status = ? WHERE id = ?"
  ).bind(
    prefs.sif_weekly ? 1 : 0,
    prefs.news_daily ? 1 : 0,
    prefs.news_scope === "everyday" ? "everyday" : "weekdays",
    prefs.name || null,
    // Ticking nothing is the honest way to say "stop emailing me" — record it as such, so the
    // user does not sit in the active pool receiving nothing while counting against send caps.
    (prefs.sif_weekly || prefs.news_daily) ? "active" : "unsubscribed",
    userId
  ).run();
  return findUserById(db, userId);
}

export async function unsubscribeAll(db, userId) {
  await db.prepare(
    "UPDATE users SET status = 'unsubscribed', sif_weekly = 0, news_daily = 0 WHERE id = ?"
  ).bind(userId).run();
}

export async function unsubscribeList(db, userId, list) {
  const meta = LISTS[list];
  if (!meta) return unsubscribeAll(db, userId);
  await db.prepare("UPDATE users SET " + meta.column + " = 0 WHERE id = ?").bind(userId).run();
  await db.prepare(
    "UPDATE users SET status = 'unsubscribed' WHERE id = ? AND sif_weekly = 0 AND news_daily = 0"
  ).bind(userId).run();
}

// ----------------------------------------------------------- login tokens

export async function createLoginToken(db, userId, ip) {
  const token = randomToken(32);
  const expires = new Date(Date.now() + TOKEN_TTL_MIN * 60000).toISOString();
  await db.prepare(
    "INSERT INTO login_tokens (token_hash, user_id, created_at, expires_at, ip) VALUES (?, ?, ?, ?, ?)"
  ).bind(await sha256Hex(token), userId, nowISO(), expires, ip || null).run();
  return token;
}

// Redeem is deliberately compare-then-claim. D1 has no SELECT ... FOR UPDATE, so the UPDATE
// carries `used_at IS NULL` in its WHERE clause and we check meta.changes: if a second request
// raced us to the same link (mail scanners prefetch links constantly), exactly one sees 1.
export async function redeemLoginToken(db, token) {
  const hash = await sha256Hex(token);
  const row = await db.prepare("SELECT * FROM login_tokens WHERE token_hash = ?").bind(hash).first();
  if (!row) return { ok: false, reason: "unknown" };
  if (row.used_at) return { ok: false, reason: "used" };
  if (row.expires_at < nowISO()) return { ok: false, reason: "expired" };

  const claim = await db.prepare(
    "UPDATE login_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL"
  ).bind(nowISO(), hash).run();
  if (!claim.meta || claim.meta.changes !== 1) return { ok: false, reason: "used" };

  await db.prepare(
    "UPDATE users SET verified_at = COALESCE(verified_at, ?), last_login_at = ?, status = 'active' WHERE id = ?"
  ).bind(nowISO(), nowISO(), row.user_id).run();
  return { ok: true, userId: row.user_id };
}

// Cheap abuse brake without KV: how many links has this address asked for recently?
export async function recentTokenCount(db, userId, minutes = 10) {
  const since = new Date(Date.now() - minutes * 60000).toISOString();
  const row = await db.prepare(
    "SELECT COUNT(*) AS n FROM login_tokens WHERE user_id = ? AND created_at > ?"
  ).bind(userId, since).first();
  return row ? row.n : 0;
}

export async function purgeExpiredTokens(db) {
  await db.prepare("DELETE FROM login_tokens WHERE expires_at < ?")
    .bind(new Date(Date.now() - 86400000).toISOString()).run();
}

// ---------------------------------------------------------------- sending

// Recipients for one edition who have not SUCCESSFULLY been sent it yet. The NOT EXISTS
// against `sends` is what makes a chunked run resume correctly: each call returns the next
// slice, and a crash mid-run costs at most the emails already delivered but not yet recorded.
//
// Note `s.status = 'sent'` in the subquery. A recipient whose send failed (a Resend blip, a
// timeout) stays pending and is retried on the next pass rather than silently missing the
// edition. The caller stops looping when a pass delivers nothing, so a permanently bad address
// costs one attempt per run instead of spinning.
export async function pendingRecipients(db, { kind, edition, limit, istDay }) {
  const notSent =
    "   AND NOT EXISTS (SELECT 1 FROM sends s WHERE s.user_id = u.id AND s.edition = ? AND s.status = 'sent') ";
  if (kind === "news") {
    const weekday = istWeekday(istDay);
    const isWeekend = weekday === 0 || weekday === 6;
    return db.prepare(
      "SELECT u.id, u.email, u.name FROM users u " +
      " WHERE u.status = 'active' AND u.news_daily = 1 " +
      "   AND (? = 0 OR u.news_scope = 'everyday') " +
      notSent +
      " ORDER BY u.created_at LIMIT ?"
    ).bind(isWeekend ? 1 : 0, edition, limit).all();
  }
  return db.prepare(
    "SELECT u.id, u.email, u.name FROM users u " +
    " WHERE u.status = 'active' AND u.sif_weekly = 1 " +
    notSent +
    " ORDER BY u.created_at LIMIT ?"
  ).bind(edition, limit).all();
}

export async function countPending(db, { kind, edition, istDay }) {
  const res = await pendingRecipients(db, { kind, edition, istDay, limit: 100000 });
  return (res.results || []).length;
}

export async function recordSends(db, edition, rows) {
  if (!rows.length) return;
  const at = nowISO();
  await db.batch(rows.map((r) => db.prepare(
    "INSERT OR REPLACE INTO sends (user_id, edition, sent_at, status, detail) VALUES (?, ?, ?, ?, ?)"
  ).bind(r.userId, edition, at, r.status, r.detail || null)));
}

// How much of today's provider allowance is already spent. This is what lets the same code run
// on Resend's free tier (100/day) today and a paid tier later by changing one env var.
export async function sentToday(db) {
  const row = await db.prepare(
    "SELECT COUNT(*) AS n FROM sends WHERE status = 'sent' AND sent_at > ?"
  ).bind(istDate() + "T00:00:00.000Z").first();
  return row ? row.n : 0;
}

export async function stats(db) {
  const q = async (sql) => (await db.prepare(sql).first()) || {};
  return {
    subscribers: (await q("SELECT COUNT(*) AS n FROM users WHERE status = 'active'")).n || 0,
    sif_weekly: (await q("SELECT COUNT(*) AS n FROM users WHERE status = 'active' AND sif_weekly = 1")).n || 0,
    news_daily: (await q("SELECT COUNT(*) AS n FROM users WHERE status = 'active' AND news_daily = 1")).n || 0,
    unsubscribed: (await q("SELECT COUNT(*) AS n FROM users WHERE status = 'unsubscribed'")).n || 0,
    sent_today: await sentToday(db),
  };
}
