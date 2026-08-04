// Cloudflare Pages Function: POST /api/contact -> sends the contact form via Resend.
// No extra config needed for routing (Pages auto-serves /functions/**).
//
// Required env var (Pages project → Settings → Environment variables):
//   RESEND_API_KEY   – from https://resend.com (free tier ~3,000/mo)
// Optional env vars (sensible defaults below):
//   CONTACT_TO       – recipient        (default: ceo@lumesoftai.com)
//   CONTACT_FROM     – verified sender   (default: SIFintel <contact@sifintel.com>)
//                      NOTE: the FROM domain must be verified in Resend (add its DNS records).

const DEFAULT_TO = "ceo@lumesoftai.com";
const DEFAULT_FROM = "SIFintel <contact@sifintel.com>";

export async function onRequestPost({ request, env }) {
  let data;
  try { data = await request.json(); } catch { return json({ ok: false, error: "Invalid request." }, 400); }

  const name = (data.name || "").trim();
  const email = (data.email || "").trim();
  const subject = (data.subject || "").trim();
  const message = (data.message || "").trim();

  // Honeypot: bots fill the hidden "company" field. Pretend success, send nothing.
  if ((data.company || "").trim()) return json({ ok: true });

  if (!name || !email || !message)
    return json({ ok: false, error: "Please fill in your name, email and message." }, 400);
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))
    return json({ ok: false, error: "Please enter a valid email address." }, 400);
  if (message.length > 5000)
    return json({ ok: false, error: "Message is too long." }, 400);
  if (!env.RESEND_API_KEY)
    return json({ ok: false, error: "Email isn't configured yet. Please email us directly." }, 503);

  const to = env.CONTACT_TO || DEFAULT_TO;
  const from = env.CONTACT_FROM || DEFAULT_FROM;
  const subj = subject ? `[SIFintel] ${subject}` : "New SIFintel contact message";
  const text = `Name: ${name}\nEmail: ${email}\nSubject: ${subject || "(none)"}\n\n${message}`;
  const html =
    `<p><strong>Name:</strong> ${esc(name)}<br>` +
    `<strong>Email:</strong> ${esc(email)}<br>` +
    `<strong>Subject:</strong> ${esc(subject || "(none)")}</p>` +
    `<p style="white-space:pre-wrap">${esc(message)}</p>`;

  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to: [to], reply_to: email, subject: subj, text, html }),
  });

  if (!resp.ok) {
    return json({ ok: false, error: "Couldn't send right now. Please email us directly." }, 502);
  }
  return json({ ok: true });
}

// Non-POST methods
export const onRequestGet = () => json({ ok: false, error: "Method not allowed." }, 405);

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
