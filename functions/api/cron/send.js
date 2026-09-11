// POST /api/cron/send?kind=news|sif[&limit=100][&dry=1]
// GET  /api/cron/send?kind=news|sif&preview=1     -> render the edition in the browser
//
// The newsletter sender. Called by the scheduled GitHub Action (.github/workflows/newsletter.yml),
// which is nothing more than a clock — all the logic lives here, at the edge, where the D1
// binding and the Resend key already are.
//
// THREE PROPERTIES THIS ENDPOINT GUARANTEES, because a mailout that gets them wrong is
// unrecoverable (you cannot un-send):
//
//  1. IDEMPOTENT — the (user_id, edition) primary key on `sends` means calling this twice for
//     the same edition sends nothing the second time. A retried Action, a double cron fire, or
//     a nervous manual run are all harmless.
//  2. RESUMABLE  — each call takes the next slice of recipients who have no `sends` row yet, so
//     a run interrupted halfway resumes exactly where it stopped. The caller loops on
//     `remaining` until it hits zero.
//  3. CAPPED     — never exceeds RESEND_DAILY_CAP sends in an IST day. Resend's free tier allows
//     100/day; when you upgrade, raise the env var and nothing else changes.
//
// Auth is a bearer secret (CRON_SECRET), compared in constant time. Anyone who could call this
// could mail your whole list.

import { json, requireEnv } from "../../_lib/http.js";
import { buildEdition } from "../../_lib/digest.js";
import { wrapEmail, sendBatch } from "../../_lib/email.js";
import { unsubToken } from "../../_lib/session.js";
import {
  istDate, pendingRecipients, countPending, recordSends, sentToday, stats,
} from "../../_lib/db.js";

const DEFAULT_CAP = 100;       // Resend free tier
const DEFAULT_CHUNK = 100;     // Resend batch maximum

function authorised(request, env) {
  const header = request.headers.get("Authorization") || "";
  const supplied = (header.match(/^Bearer\s+(.+)$/i) || [])[1] || "";
  const expected = env.CRON_SECRET || "";
  if (!expected || supplied.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < supplied.length; i++) diff |= supplied.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

function parseKind(url) {
  const kind = (url.searchParams.get("kind") || "").toLowerCase();
  return kind === "news" || kind === "sif" ? kind : null;
}

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  if (!authorised(request, env)) return json({ ok: false, error: "Unauthorised." }, 401);

  const kind = parseKind(url);
  if (!kind) return json({ ok: false, error: "Pass ?kind=news or ?kind=sif." }, 400);

  const istDay = url.searchParams.get("date") || istDate();
  const edition = kind + ":" + istDay;

  // Preview renders the exact email body with placeholder links, so you can eyeball an edition
  // before the cron sends it. It never touches the database.
  if (url.searchParams.get("preview")) {
    const built = await buildEdition(kind, url.origin, { istDay });
    if (!built) return json({ ok: false, error: "No content available for this edition." }, 503);
    const html = wrapEmail({
      title: built.subject,
      preheader: built.preheader,
      body: built.body,
      unsubUrl: url.origin + "/unsubscribe",
      accountUrl: url.origin + "/account",
      site: url.origin,
    });
    return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
  }

  const bad = requireEnv(env, ["DB"]);
  if (bad) return bad;
  return json({
    ok: true,
    edition,
    pending: await countPending(env.DB, { kind, edition, istDay }),
    sent_today: await sentToday(env.DB),
    cap: Number(env.RESEND_DAILY_CAP || DEFAULT_CAP),
    list: await stats(env.DB),
  });
}

export async function onRequestPost({ request, env }) {
  const bad = requireEnv(env, ["DB", "RESEND_API_KEY", "SESSION_SECRET", "CRON_SECRET"]);
  if (bad) return bad;
  if (!authorised(request, env)) return json({ ok: false, error: "Unauthorised." }, 401);

  const url = new URL(request.url);
  const kind = parseKind(url);
  if (!kind) return json({ ok: false, error: "Pass ?kind=news or ?kind=sif." }, 400);

  const istDay = url.searchParams.get("date") || istDate();
  const edition = kind + ":" + istDay;
  const dry = !!url.searchParams.get("dry");

  const cap = Number(env.RESEND_DAILY_CAP || DEFAULT_CAP);
  const already = await sentToday(env.DB);
  const budget = Math.max(0, cap - already);
  const asked = Math.min(Number(url.searchParams.get("limit") || DEFAULT_CHUNK), DEFAULT_CHUNK);
  const take = Math.min(asked, budget);

  if (take <= 0) {
    const pending = await countPending(env.DB, { kind, edition, istDay });
    return json({
      ok: true, edition, sent: 0, failed: 0, remaining: pending, capped: true,
      message: "Daily cap of " + cap + " reached (" + already + " sent today). " + pending +
        " recipients still pending — raise RESEND_DAILY_CAP or they go out on the next run.",
    });
  }

  const slice = await pendingRecipients(env.DB, { kind, edition, istDay, limit: take });
  const recipients = slice.results || [];
  if (!recipients.length) {
    return json({ ok: true, edition, sent: 0, failed: 0, remaining: 0, message: "Nobody pending for this edition." });
  }

  // Build the content ONCE for the whole edition, not per recipient. Only the unsubscribe link
  // differs between copies, so this is the difference between one pass over nav_data.json and
  // one per subscriber — the thing that would blow the Worker CPU budget as the list grows.
  const built = await buildEdition(kind, url.origin, { istDay });
  if (!built) {
    return json({
      ok: false, edition, error: "No content available — refusing to send an empty edition.",
    }, 503);
  }

  if (dry) {
    return json({
      ok: true, edition, dry: true, subject: built.subject,
      would_send: recipients.length,
      remaining_after: await countPending(env.DB, { kind, edition, istDay }) - recipients.length,
      cap_remaining: budget,
    });
  }

  const messages = [];
  for (const r of recipients) {
    const unsubUrl = url.origin + "/unsubscribe?u=" +
      encodeURIComponent(await unsubToken(env.SESSION_SECRET, r.id)) +
      "&l=" + (kind === "news" ? "news_daily" : "sif_weekly");
    messages.push({
      userId: r.id,
      to: r.email,
      subject: built.subject.replace(/&middot;/g, "·"),
      html: wrapEmail({
        title: built.subject,
        preheader: built.preheader,
        body: built.body,
        unsubUrl,
        accountUrl: url.origin + "/account",
        site: url.origin,
      }),
      text: built.text + "\n\nUnsubscribe: " + unsubUrl,
      unsubUrl,
    });
  }

  const results = await sendBatch(env, messages);
  await recordSends(env.DB, edition, results);

  const sent = results.filter((r) => r.status === "sent").length;
  const failed = results.length - sent;
  const remaining = await countPending(env.DB, { kind, edition, istDay });

  return json({
    ok: true,
    edition,
    subject: built.subject,
    attempted: results.length,
    sent,
    failed,
    remaining,
    cap_remaining: Math.max(0, cap - (await sentToday(env.DB))),
    ...(failed ? { failures: results.filter((r) => r.status !== "sent").slice(0, 5) } : {}),
  });
}
