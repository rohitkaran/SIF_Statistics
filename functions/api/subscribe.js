// Cloudflare Pages Function: POST /api/subscribe -> sends a confirmation email.
//
// Step one of double opt-in. Nothing is added to the list here; the address is only recorded
// once the person clicks the signed link in the email this sends. See _newsletter.js.

import {
  CONFIRM_TTL_DAYS, SITE, esc, json, normalizeEmail, sendEmail, sign,
} from "./_newsletter.js";

export async function onRequestPost({ request, env }) {
  let data;
  try { data = await request.json(); }
  catch { return json({ ok: false, error: "Invalid request." }, 400); }

  // Honeypot, same trick the contact form uses: bots fill the hidden field. Report success and
  // send nothing, so the bot has no signal to retry against.
  if ((data.company || "").trim()) return json({ ok: true });

  const email = normalizeEmail(data.email);
  if (!email) return json({ ok: false, error: "Please enter a valid email address." }, 400);

  if (!env.RESEND_API_KEY || !env.NEWSLETTER_SECRET) {
    return json({ ok: false,
      error: "The newsletter isn't configured yet. Please email ceo@lumesoftai.com." }, 503);
  }

  const token = await sign(env.NEWSLETTER_SECRET, "confirm", email, CONFIRM_TTL_DAYS);
  const link = `${SITE}/api/confirm?t=${encodeURIComponent(token)}`;

  const text =
`Confirm your SIFintel newsletter subscription

Click to confirm:
${link}

You'll get one email a week covering India's Specialized Investment Funds — new launches
and NFOs, fresh portfolio disclosures, AUM and flows, and the week's performance.

If you didn't request this, ignore this email. Nothing was added to any list, and this
link expires in ${CONFIRM_TTL_DAYS} days.`;

  const html =
`<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;color:#14161f;line-height:1.6">
  <h2 style="font-size:19px;margin:0 0 12px">Confirm your subscription</h2>
  <p style="margin:0 0 18px;color:#4a5170">One click and you're on the list — one email a week
  on India's Specialized Investment Funds: new launches and NFOs, fresh portfolio disclosures,
  AUM and flows, and the week's performance.</p>
  <p style="margin:0 0 22px">
    <a href="${esc(link)}" style="display:inline-block;background:#5b5bf0;color:#fff;
       font-weight:600;text-decoration:none;padding:11px 20px;border-radius:8px">Confirm subscription</a>
  </p>
  <p style="margin:0 0 6px;font-size:13px;color:#6b7291">Or paste this into your browser:</p>
  <p style="margin:0 0 22px;font-size:12px;word-break:break-all;color:#6b7291">${esc(link)}</p>
  <p style="font-size:13px;color:#6b7291;margin:0">If you didn't request this, just ignore it —
  nothing has been added to any list, and the link expires in ${CONFIRM_TTL_DAYS} days.</p>
</div>`;

  const sent = await sendEmail(env, {
    to: email,
    subject: "Confirm your SIFintel newsletter subscription",
    text, html,
  });
  if (!sent) {
    return json({ ok: false,
      error: "Couldn't send the confirmation email. Please try again shortly." }, 502);
  }
  return json({ ok: true });
}

export const onRequestGet = () => json({ ok: false, error: "Method not allowed." }, 405);
