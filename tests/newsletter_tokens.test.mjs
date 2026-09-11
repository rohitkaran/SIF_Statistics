#!/usr/bin/env node
// Tests for the newsletter link signing used by the Cloudflare Pages Functions.
//
//   node tests/newsletter_tokens.test.mjs
//
// These links ARE the access control: a valid signature is the only thing separating "this
// person asked to subscribe" from "somebody typed their address in". Everything below is a way
// that could go wrong.

import { sign, verify, normalizeEmail } from "../functions/api/_newsletter.js";

const SECRET = "test-secret-abc123";
let failed = 0;
const ok = (cond, msg) => {
  if (!cond) { console.log("  FAIL:", msg); failed++; } else console.log("  ok:", msg); };

// --- round trip ---------------------------------------------------------------------
const token = await sign(SECRET, "confirm", "a@b.com", 7);
ok((await verify(SECRET, "confirm", token)).email === "a@b.com", "valid token round-trips");

// --- forgery ------------------------------------------------------------------------
const [payload, sig] = token.split(".");
ok((await verify(SECRET, "confirm", payload + "." + sig.slice(0, -2) + "AA")).error,
   "tampered signature rejected");

// The attack that matters: keep a real signature, swap in your own address.
const forged = Buffer.from("confirm:evil@x.com:9999999999").toString("base64url");
ok((await verify(SECRET, "confirm", forged + "." + sig)).error, "tampered payload rejected");
ok((await verify("other-secret", "confirm", token)).error, "wrong secret rejected");

// --- kind confusion -----------------------------------------------------------------
// A confirm link must not double as an unsubscribe link, or one careless forward
// unsubscribes the sender.
const unsub = await sign(SECRET, "unsub", "a@b.com", 0);
ok((await verify(SECRET, "unsub", token)).error, "confirm token cannot unsubscribe");
ok((await verify(SECRET, "confirm", unsub)).error, "unsubscribe token cannot confirm");
ok((await verify(SECRET, "unsub", unsub)).email === "a@b.com", "unsubscribe token verifies");

// --- expiry -------------------------------------------------------------------------
const stale = await sign(SECRET, "confirm", "a@b.com", -1);
ok(/expired/i.test((await verify(SECRET, "confirm", stale)).error || ""),
   "expired confirm token rejected, with a message that says so");
ok((await verify(SECRET, "unsub", unsub)).email === "a@b.com",
   "unsubscribe tokens never expire (people unsubscribe from old mail)");

// --- garbage ------------------------------------------------------------------------
for (const junk of ["", null, undefined, "abc", "a.b.c", "!!!.???", ".", "x."])
  ok((await verify(SECRET, "confirm", junk)).error, `garbage rejected: ${JSON.stringify(junk)}`);

// --- address shapes that break naive parsers ----------------------------------------
// The payload is "kind:email:exp", so anything with a colon or a plus must survive the split.
for (const email of ["a+tag@b.com", "first.last@sub.domain.co.in", "x@y.io", "a'b@c.com"]) {
  const t = await sign(SECRET, "confirm", email, 7);
  ok((await verify(SECRET, "confirm", t)).email === email, `round-trips ${email}`);
}

// --- normaliser ---------------------------------------------------------------------
ok(normalizeEmail("  A@B.COM ") === "a@b.com", "email trimmed and lowercased");
ok(normalizeEmail("bad") === null, "address without a domain rejected");
ok(normalizeEmail("a b@c.com") === null, "address with a space rejected");
ok(normalizeEmail("a@" + "x".repeat(300) + ".com") === null, "over-long address rejected");
ok(normalizeEmail("") === null && normalizeEmail(null) === null, "empty address rejected");

console.log(failed ? `\n${failed} FAILURE(S)` : "\nall newsletter token tests passed");
process.exit(failed ? 1 : 0);
