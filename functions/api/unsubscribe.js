// Cloudflare Pages Function: /api/unsubscribe?t=<token> -> removes an address.
//
// Handles GET (someone clicked the link) and POST (RFC 8058 one-click unsubscribe, which mail
// clients fire on the List-Unsubscribe-Post header without a human ever seeing a page).
// Unsubscribe tokens never expire: people unsubscribe from an email they dug up months later,
// and an expired opt-out link is a spam complaint waiting to happen.

import { DEFAULT_NOTIFY, SITE, esc, page, removeContact, sendEmail, verify } from "./_newsletter.js";

async function handle(request, env) {
  if (!env.NEWSLETTER_SECRET) {
    return page("Not configured", "The newsletter isn't set up yet",
      "<p>Please email <a href='mailto:ceo@lumesoftai.com'>ceo@lumesoftai.com</a>.</p>", false);
  }

  const url = new URL(request.url);
  let token = url.searchParams.get("t");
  if (!token && request.method === "POST") {
    // One-click clients POST the body; some put the token in a form field instead of the query.
    try {
      const form = await request.formData();
      token = form.get("t") || token;
    } catch { /* no body: fall through to the query token */ }
  }

  const { email, error } = await verify(env.NEWSLETTER_SECRET, "unsub", token);
  if (error) {
    return page("Link not valid", error,
      `<p>Email <a href="mailto:${DEFAULT_NOTIFY}">${DEFAULT_NOTIFY}</a> and we'll remove you by hand.</p>`,
      false);
  }

  const removed = await removeContact(env, email);
  await sendEmail(env, {
    to: env.NEWSLETTER_NOTIFY || DEFAULT_NOTIFY,
    subject: `SIFintel newsletter: unsubscribe (${email})`,
    text: `${email} unsubscribed.\n\nAudience remove: ${removed.ok ? "ok" : "FAILED — " + removed.reason}\n`,
    html: `<p><strong>${esc(email)}</strong> unsubscribed.</p>`
        + `<p>Audience remove: ${removed.ok ? "ok" : "<strong>FAILED</strong> — " + esc(removed.reason)}</p>`,
  });

  return page("Unsubscribed", "You're unsubscribed",
    `<p>We won't email you again. No hard feelings.</p>
     <p style="font-size:13px;color:var(--ink-faint)">Removed ${esc(email)}.
      The dashboard, data and archive stay free to read at
      <a href="${SITE}/">sifintel.com</a>.</p>`);
}

export const onRequestGet = ({ request, env }) => handle(request, env);
export const onRequestPost = ({ request, env }) => handle(request, env);
