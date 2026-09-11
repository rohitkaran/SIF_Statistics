// Cloudflare Pages Function: GET /api/confirm?t=<token> -> completes double opt-in.

import {
  DEFAULT_NOTIFY, SITE, addContact, esc, page, sendEmail, sign, verify,
} from "./_newsletter.js";

export async function onRequestGet({ request, env }) {
  if (!env.NEWSLETTER_SECRET) {
    return page("Not configured", "The newsletter isn't set up yet",
      "<p>Please email <a href='mailto:ceo@lumesoftai.com'>ceo@lumesoftai.com</a>.</p>", false);
  }

  const token = new URL(request.url).searchParams.get("t");
  const { email, error } = await verify(env.NEWSLETTER_SECRET, "confirm", token);
  if (error) {
    return page("Link not valid", error,
      `<p>Head back to <a href="${SITE}/newsletter">the newsletter page</a> and sign up again —
       it only takes a moment.</p>`, false);
  }

  const added = await addContact(env, email);

  // The owner is notified for EVERY confirmation, deliberately. The Resend audience call above
  // was written without a live account to verify it against, so this inbox is the backstop:
  // if the audience add is wrong or unconfigured, the subscriber is still recoverable here
  // rather than silently dropped.
  const unsub = await sign(env.NEWSLETTER_SECRET, "unsub", email, 0);
  await sendEmail(env, {
    to: env.NEWSLETTER_NOTIFY || DEFAULT_NOTIFY,
    subject: `SIFintel newsletter: new subscriber (${email})`,
    text: `${email} confirmed.\n\nAudience add: ${added.ok ? "ok" : "FAILED — " + added.reason}\n`
        + `Unsubscribe token: ${unsub}\n`,
    html: `<p><strong>${esc(email)}</strong> confirmed their subscription.</p>`
        + `<p>Audience add: ${added.ok ? "ok" : "<strong>FAILED</strong> — " + esc(added.reason)}</p>`,
  });

  return page("Subscribed", "You're subscribed",
    `<p>We'll send you one email a week on India's Specialized Investment Funds — new launches,
      portfolio disclosures, AUM and flows, and how the category performed.</p>
     <p style="font-size:13px;color:var(--ink-faint)">Confirmed for ${esc(email)}.
      Every issue has a one-click unsubscribe link.</p>`);
}

export const onRequestPost = onRequestGet;
