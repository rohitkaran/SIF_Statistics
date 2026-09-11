// Resend transport + the SIFintel email shell. Exports no handler => generates no route.
//
// DELIVERABILITY NOTES (these are not decoration — Gmail and Yahoo enforce them for bulk
// senders since Feb 2024, and getting them wrong lands the newsletter in spam):
//   * List-Unsubscribe + List-Unsubscribe-Post => the native "Unsubscribe" button in Gmail.
//     The POST variant must work WITHOUT a login, which is why unsubscribe tokens are HMACs
//     rather than sessions (see _lib/session.js).
//   * A visible unsubscribe link in the footer as well — the header alone is not enough.
//   * A postal identity in the footer.
//   * The From domain must have SPF/DKIM/DMARC set up in Resend. sifintel.com already does
//     this for the contact form; the newsletter reuses the same verified domain.
//
// Email HTML is deliberately 2005-era: one centred table, inline styles, no external CSS, no
// web fonts, no media queries beyond a single max-width. Outlook renders nothing else reliably.

const RESEND_API = "https://api.resend.com/emails";
const BATCH_API = "https://api.resend.com/emails/batch";
const BATCH_MAX = 100; // Resend's hard limit per batch call

export function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function fromAddress(env) {
  return env.NEWSLETTER_FROM || "SIFintel <news@sifintel.com>";
}

export function replyTo(env) {
  return env.NEWSLETTER_REPLY_TO || env.CONTACT_TO || "ceo@lumesoftai.com";
}

// ------------------------------------------------------------- the shell

const INK = "#1c2338";
const DIM = "#4a5578";
const FAINT = "#8a93b2";
const LINE = "#e5e9f4";
const TEAL = "#17a67a";
const ACCENT = "#5b5bf0";

export function button(href, label) {
  return (
    '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:18px 0">' +
    '<tr><td style="border-radius:8px;background:' + ACCENT + '">' +
    '<a href="' + esc(href) + '" style="display:inline-block;padding:11px 22px;font-family:' +
    '-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:15px;font-weight:600;' +
    'color:#ffffff;text-decoration:none">' + esc(label) + "</a></td></tr></table>"
  );
}

export function section(title) {
  return (
    '<h2 style="margin:26px 0 10px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
    "font-size:13px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:" + TEAL +
    ';border-bottom:1px solid ' + LINE + ';padding-bottom:7px">' + esc(title) + "</h2>"
  );
}

export function paragraph(html, { size = 15, color = DIM } = {}) {
  return (
    '<p style="margin:0 0 12px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
    "font-size:" + size + "px;line-height:1.6;color:" + color + '">' + html + "</p>"
  );
}

// One headline + source line. Used by the news brief.
export function newsItem({ title, url, source, summary, official }) {
  return (
    '<div style="padding:11px 0;border-bottom:1px solid ' + LINE + '">' +
    '<a href="' + esc(url) + '" style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
    'font-size:16px;font-weight:600;line-height:1.4;color:' + INK + ';text-decoration:none">' +
    esc(title) + "</a>" +
    (summary ? '<p style="margin:5px 0 0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
      "font-size:14px;line-height:1.55;color:" + DIM + '">' + esc(summary) + "</p>" : "") +
    '<p style="margin:6px 0 0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;' +
    "font-size:11.5px;color:" + (official ? TEAL : FAINT) + '">' +
    esc(source) + (official ? " &#9733;" : "") + "</p></div>"
  );
}

// A fund + number row. Used by the SIF digest.
export function statRow(label, sub, value, positive) {
  const colour = positive === undefined ? INK : positive ? TEAL : "#d94a4a";
  return (
    '<tr><td style="padding:9px 0;border-bottom:1px solid ' + LINE + ';font-family:-apple-system,' +
    'Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14.5px;color:' + INK + '">' + esc(label) +
    (sub ? '<span style="display:block;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;' +
      "font-size:11px;color:" + FAINT + '">' + esc(sub) + "</span>" : "") +
    '</td><td align="right" style="padding:9px 0;border-bottom:1px solid ' + LINE + ';' +
    "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;font-weight:600;" +
    "color:" + colour + ';white-space:nowrap">' + esc(value) + "</td></tr>"
  );
}

export function table(rows) {
  return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" ' +
    'style="margin:6px 0 4px">' + rows.join("") + "</table>";
}

export function wrapEmail({ title, preheader, body, unsubUrl, accountUrl, site }) {
  const base = site || "https://www.sifintel.com";
  return (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<meta name="color-scheme" content="light"><title>' + esc(title) + "</title></head>" +
    '<body style="margin:0;padding:0;background:#eef1fb">' +
    // Preheader: the grey preview line next to the subject in the inbox list. Hidden in the
    // body itself. Without it, clients show whatever text comes first — usually "View online".
    '<div style="display:none;max-height:0;overflow:hidden;opacity:0">' + esc(preheader || "") +
    "&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;</div>" +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" ' +
    'style="background:#eef1fb;padding:22px 12px"><tr><td align="center">' +
    '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" ' +
    'style="max-width:600px;width:100%;background:#ffffff;border:1px solid ' + LINE + ';border-radius:12px">' +

    // masthead
    '<tr><td style="padding:20px 26px 0">' +
    '<a href="' + base + '" style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
    "font-size:19px;font-weight:700;letter-spacing:-.5px;color:" + INK + ';text-decoration:none">' +
    'SIF<span style="color:' + TEAL + '">intel</span></a></td></tr>' +

    // body
    '<tr><td style="padding:6px 26px 26px">' + body + "</td></tr>" +

    // footer
    '<tr><td style="padding:18px 26px 22px;border-top:1px solid ' + LINE + ';background:#f5f7fd;' +
    'border-radius:0 0 12px 12px">' +
    '<p style="margin:0 0 8px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
    "font-size:12px;line-height:1.6;color:" + FAINT + '">' +
    "You are receiving this because you subscribed at sifintel.com. " +
    '<a href="' + esc(accountUrl) + '" style="color:' + FAINT + '">Manage what you get</a> &middot; ' +
    '<a href="' + esc(unsubUrl) + '" style="color:' + FAINT + '">Unsubscribe</a></p>' +
    '<p style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;' +
    "font-size:11.5px;line-height:1.6;color:" + FAINT + '">' +
    "SIFintel is published by Lume Software Private Limited, India. Data is for information and " +
    "analysis only &mdash; it is not investment advice and no fund is recommended. " +
    "NAVs originate from AMFI; portfolio disclosures from the fund houses." +
    "</p></td></tr></table></td></tr></table></body></html>"
  );
}

// -------------------------------------------------------------- transport

function unsubHeaders(unsubUrl, mailto) {
  return {
    "List-Unsubscribe": "<" + unsubUrl + ">" + (mailto ? ", <mailto:" + mailto + "?subject=unsubscribe>" : ""),
    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
  };
}

export async function sendOne(env, { to, subject, html, text, unsubUrl }) {
  const res = await fetch(RESEND_API, {
    method: "POST",
    headers: { Authorization: "Bearer " + env.RESEND_API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: fromAddress(env),
      to: [to],
      subject,
      html,
      text,
      reply_to: replyTo(env),
      ...(unsubUrl ? { headers: unsubHeaders(unsubUrl, replyTo(env)) } : {}),
    }),
  });
  if (!res.ok) throw new Error("Resend " + res.status + ": " + (await res.text()).slice(0, 300));
  return res.json();
}

// Batch send. Resend accepts up to 100 messages per call; we chunk and return a per-recipient
// result so the caller can write exactly who succeeded into `sends`.
//
// IMPORTANT: Resend's batch endpoint returns ids in REQUEST ORDER, so results are zipped back
// by index. If a whole chunk fails we mark every recipient in it failed rather than guessing.
export async function sendBatch(env, messages) {
  const out = [];
  for (let i = 0; i < messages.length; i += BATCH_MAX) {
    const chunk = messages.slice(i, i + BATCH_MAX);
    const payload = chunk.map((m) => ({
      from: fromAddress(env),
      to: [m.to],
      subject: m.subject,
      html: m.html,
      text: m.text,
      reply_to: replyTo(env),
      headers: unsubHeaders(m.unsubUrl, replyTo(env)),
    }));

    let res, body;
    try {
      res = await fetch(BATCH_API, {
        method: "POST",
        headers: { Authorization: "Bearer " + env.RESEND_API_KEY, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      body = await res.json().catch(() => ({}));
    } catch (e) {
      for (const m of chunk) out.push({ userId: m.userId, status: "failed", detail: String(e).slice(0, 200) });
      continue;
    }

    if (!res.ok) {
      const detail = ("resend " + res.status + " " + (body && body.message ? body.message : "")).slice(0, 200);
      for (const m of chunk) out.push({ userId: m.userId, status: "failed", detail });
      continue;
    }

    const ids = (body && body.data) || [];
    chunk.forEach((m, idx) => {
      const id = ids[idx] && ids[idx].id;
      out.push({ userId: m.userId, status: id ? "sent" : "failed", detail: id || "no id returned" });
    });
  }
  return out;
}

export { BATCH_MAX };
