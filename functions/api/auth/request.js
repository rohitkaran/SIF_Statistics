// POST /api/auth/request  { email, name?, lists?: {sif_weekly, news_daily}, news_scope?, source?, company? }
//
// The single entry point for both signing up and signing in. Creates the account if it does
// not exist, then emails a one-time link. There is no password, so there is nothing else to
// remember and no reset flow to build.
//
// Always answers `ok` regardless of whether the address was already registered — an endpoint
// that says "no such user" is an email-enumeration oracle for anyone who wants your list.

import { json, requireEnv, clientIP } from "../../_lib/http.js";
import {
  upsertUser, createLoginToken, recentTokenCount, purgeExpiredTokens,
  validEmail, normaliseEmail,
} from "../../_lib/db.js";
import { wrapEmail, button, paragraph, sendOne } from "../../_lib/email.js";
import { TOKEN_TTL_MIN } from "../../_lib/session.js";

const MAX_LINKS_PER_10_MIN = 4;

export async function onRequestPost(context) {
  const { request, env } = context;
  const bad = requireEnv(env, ["DB", "RESEND_API_KEY", "SESSION_SECRET"]);
  if (bad) return bad;

  let data;
  try { data = await request.json(); } catch { return json({ ok: false, error: "Invalid request." }, 400); }

  // Honeypot, same trick the contact form uses: bots fill a field humans never see.
  if ((data.company || "").trim()) return json({ ok: true });

  const email = normaliseEmail(data.email);
  if (!validEmail(email)) {
    return json({ ok: false, error: "Please enter a valid email address." }, 400);
  }

  const lists = data.lists || {};
  // A brand-new subscriber who ticks nothing still gets the weekly digest — that is the thing
  // they came for. Existing users' choices are never overwritten here (see upsertUser).
  const prefs = {
    sif_weekly: lists.sif_weekly === undefined ? true : !!lists.sif_weekly,
    news_daily: !!lists.news_daily,
    news_scope: data.news_scope === "everyday" ? "everyday" : "weekdays",
  };

  const url = new URL(request.url);
  const origin = url.origin;

  try {
    const user = await upsertUser(env.DB, {
      email,
      name: (data.name || "").trim().slice(0, 120) || null,
      source: (data.source || "").trim().slice(0, 60) || null,
      prefs,
    });

    // Rate limit per account, not per IP: the cost we are protecting against is mailing a
    // stranger's inbox repeatedly, and that is keyed to the address being targeted.
    if (await recentTokenCount(env.DB, user.id, 10) >= MAX_LINKS_PER_10_MIN) {
      return json({
        ok: true,
        throttled: true,
        message: "We have already sent a few links to that address. Please check your inbox, including spam.",
      });
    }

    const token = await createLoginToken(env.DB, user.id, clientIP(request));
    // Points at the /auth page, not the API. The page redeems with a POST so that mail
    // scanners prefetching this URL cannot burn the one-time token. See api/auth/verify.js.
    const link = origin + "/auth?t=" + encodeURIComponent(token);

    const isNew = !user.verified_at;
    const heading = isNew ? "Confirm your subscription" : "Your sign-in link";
    const body =
      '<h1 style="margin:14px 0 8px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
      'font-size:22px;line-height:1.3;color:#1c2338">' + heading + "</h1>" +
      paragraph(
        isNew
          ? "Tap the button to confirm this address and choose what SIFintel sends you."
          : "Tap the button to sign in and manage what SIFintel sends you."
      ) +
      button(link, isNew ? "Confirm and set preferences" : "Sign in to SIFintel") +
      paragraph(
        "This link works once and expires in " + TOKEN_TTL_MIN + " minutes. " +
        "If you did not ask for it, you can ignore this email &mdash; nothing will be sent to you.",
        { size: 13 }
      ) +
      paragraph(
        'If the button does not work, paste this into your browser:<br><span style="word-break:break-all;' +
        'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px">' + link + "</span>",
        { size: 13 }
      );

    await sendOne(env, {
      to: email,
      subject: isNew ? "Confirm your SIFintel subscription" : "Your SIFintel sign-in link",
      html: wrapEmail({
        title: heading,
        preheader: "Your one-time link, valid for " + TOKEN_TTL_MIN + " minutes.",
        body,
        unsubUrl: origin + "/unsubscribe",
        accountUrl: origin + "/account",
        site: origin,
      }),
      text: heading + "\n\n" + link + "\n\nThis link works once and expires in " +
        TOKEN_TTL_MIN + " minutes. If you did not request it, ignore this email.",
    });

    // Housekeeping on a warm path rather than a separate cron: the token table is the only
    // thing that grows without bound, and this keeps it swept without another moving part.
    context.waitUntil(purgeExpiredTokens(env.DB).catch(() => {}));

    return json({ ok: true, message: "Check your inbox for a sign-in link." });
  } catch (e) {
    return json({ ok: false, error: "Could not send the link. " + String(e && e.message || e).slice(0, 160) }, 500);
  }
}
