// POST /api/auth/logout — clear the session cookie.
import { json } from "../../_lib/http.js";
import { sessionCookie } from "../../_lib/session.js";

export async function onRequestPost() {
  return json({ ok: true }, 200, { "Set-Cookie": sessionCookie("", { clear: true }) });
}
