// GET  /api/account   -> the signed-in user's profile + preferences
// POST /api/account    -> update preferences
//
// The only thing an account does today. Keeping the surface this small is deliberate: the
// users table is the foundation for API keys and watchlists later, but none of that has to
// exist for the newsletter to work.

import { json, requireEnv } from "../_lib/http.js";
import { readSession, sessionCookie, unsubToken } from "../_lib/session.js";
import { findUserById, updatePrefs } from "../_lib/db.js";

function shape(user, unsub) {
  return {
    ok: true,
    user: {
      email: user.email,
      name: user.name,
      created_at: user.created_at,
      status: user.status,
      prefs: {
        sif_weekly: !!user.sif_weekly,
        news_daily: !!user.news_daily,
        news_scope: user.news_scope,
      },
    },
    unsubscribe_url: unsub,
  };
}

async function currentUser(request, env) {
  const session = await readSession(request, env.SESSION_SECRET);
  if (!session) return null;
  return findUserById(env.DB, session.userId);
}

export async function onRequestGet({ request, env }) {
  const bad = requireEnv(env, ["DB", "SESSION_SECRET"]);
  if (bad) return bad;

  const user = await currentUser(request, env);
  // A valid cookie for a deleted account clears itself rather than looping the sign-in page.
  if (!user) {
    return json({ ok: false, error: "Not signed in." }, 401, { "Set-Cookie": sessionCookie("", { clear: true }) });
  }

  const origin = new URL(request.url).origin;
  const unsub = origin + "/unsubscribe?u=" + encodeURIComponent(await unsubToken(env.SESSION_SECRET, user.id));
  return json(shape(user, unsub));
}

export async function onRequestPost({ request, env }) {
  const bad = requireEnv(env, ["DB", "SESSION_SECRET"]);
  if (bad) return bad;

  const user = await currentUser(request, env);
  if (!user) return json({ ok: false, error: "Not signed in." }, 401);

  const data = await request.json().catch(() => ({}));
  const prefs = {
    sif_weekly: !!data.sif_weekly,
    news_daily: !!data.news_daily,
    news_scope: data.news_scope === "everyday" ? "everyday" : "weekdays",
    name: typeof data.name === "string" ? data.name.trim().slice(0, 120) : user.name,
  };

  const updated = await updatePrefs(env.DB, user.id, prefs);
  const origin = new URL(request.url).origin;
  const unsub = origin + "/unsubscribe?u=" + encodeURIComponent(await unsubToken(env.SESSION_SECRET, user.id));
  return json({ ...shape(updated, unsub), saved: true });
}
