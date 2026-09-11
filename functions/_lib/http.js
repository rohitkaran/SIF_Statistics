// Tiny response helpers shared by the account/auth routes. No handler => no route.

export function json(obj, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

export function redirect(location, extraHeaders = {}) {
  return new Response(null, {
    status: 302,
    headers: { Location: location, "Cache-Control": "no-store", ...extraHeaders },
  });
}

// Every route that touches the database funnels through this, so a missing binding produces
// one clear message instead of "Cannot read properties of undefined (reading 'prepare')".
export function requireEnv(env, keys) {
  const missing = keys.filter((k) => !env[k]);
  if (missing.length) {
    return json({
      ok: false,
      error: "Server is not configured yet (" + missing.join(", ") + "). See NEWSLETTER.md.",
    }, 503);
  }
  return null;
}

export function clientIP(request) {
  return request.headers.get("CF-Connecting-IP") || null;
}
