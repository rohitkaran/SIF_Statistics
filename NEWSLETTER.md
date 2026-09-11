# Newsletter — setup and operation

Weekly digest of India's SIF category, built from the JSON this repo already commits and sent
with [Resend](https://resend.com) (the same account the contact form uses).

## How it works

```
  visitor types email          →  POST /api/subscribe     →  confirmation email
  clicks the link in it        →  GET  /api/confirm       →  added to the Resend audience
  Mondays 09:00 IST            →  build_newsletter.py     →  archive page + email HTML/text
                               →  send_newsletter.py      →  one message per subscriber
  clicks unsubscribe           →  /api/unsubscribe        →  removed
```

**Double opt-in, with no database.** The confirmation and unsubscribe links carry the address
plus an HMAC signature, so only a link this site generated can confirm an address. That stops
anyone signing up somebody else's address — which is both rude and the fastest way to get a
sending domain blacklisted. Confirmation links expire after 7 days; unsubscribe links never do,
because people unsubscribe from mail they dug out of the archive months later.

## Set it up

**1. Cloudflare Pages → Settings → Environment variables**

| Variable | Value |
|---|---|
| `RESEND_API_KEY` | already set for the contact form |
| `NEWSLETTER_SECRET` | a long random string — `openssl rand -hex 32` |
| `NEWSLETTER_AUDIENCE_ID` | from Resend → Audiences (create one called "SIFintel weekly") |
| `NEWSLETTER_FROM` | optional, default `SIFintel <newsletter@sifintel.com>` |
| `NEWSLETTER_NOTIFY` | optional, default `ceo@lumesoftai.com` |

The `NEWSLETTER_FROM` domain must be verified in Resend (add its DNS records), exactly as
`contact@sifintel.com` already is.

**2. GitHub → Settings → Secrets and variables → Actions**

Add `RESEND_API_KEY`, `NEWSLETTER_SECRET` and `NEWSLETTER_AUDIENCE_ID` as **secrets**.

> `NEWSLETTER_SECRET` must be **identical** in both places. Python mints the unsubscribe links
> and a Cloudflare Worker verifies them; if the two differ, every unsubscribe link in a sent
> email says "not valid" — and you find out only after the email has gone.

**3. Rehearse before the first real send**

Actions → *Weekly newsletter* → Run workflow → set **test_to** to your own address and
**send** to true. That mails only you. Check the unsubscribe link actually works before letting
the schedule run.

## Running it by hand

```bash
python build_newsletter.py                    # build this week's issue + archive pages
python build_newsletter.py --week 2026-08-21  # rebuild a specific week
python build_newsletter.py --pages-only       # just the landing page and archive index

NEWSLETTER_SECRET=... python send_newsletter.py                      # dry run (the default)
NEWSLETTER_SECRET=... RESEND_API_KEY=... python send_newsletter.py \
    --test-to you@example.com --send                                 # one rehearsal message
```

`send_newsletter.py` never sends without `--send`.

## What's in an issue

Industry AUM, net flows, folios and scheme count from AMFI's month-end filings with the MoM
move; the week's NAV movers, one row per strategy rather than four rows of the same fund's plan
variants; new launches; open NFOs; and fresh portfolio disclosures. Every figure comes from the
same committed JSON the dashboard reads, so the newsletter cannot disagree with the site.

If AMFI has not published since the requested week, the window slides back to the last week that
actually has NAVs and the email says so. Publishing "no movers this week" when the truth is "no
data yet" is the one thing that makes a data newsletter untrustworthy.

## Abuse: turn on rate limiting

`/api/subscribe` has a honeypot field that silently drops bots, but **no request-rate limit** —
proper per-IP counting needs Cloudflare KV or Durable Objects, which this project has not bound
(the same reason `functions/api/v1/[[route]].js` cannot meter API keys yet). Without one, someone
could hammer the endpoint to fire confirmation emails at addresses that never asked, burning the
Resend quota and the sending reputation along with it.

Fix it with configuration rather than code: **Cloudflare → the site → Security → WAF → Rate
limiting rules**, matching `URI Path equals /api/subscribe`, something like 5 requests per
minute per IP, action *Block*. Worth doing before the signup form gets any real traffic.

## Where the subscriber list lives

In the Resend audience. **It is not the only copy**: every confirmation also emails
`NEWSLETTER_NOTIFY`, because the Resend Audiences calls in `functions/api/_newsletter.js` were
written without a live account to verify them against. If those calls are wrong or the audience
id is unset, the subscriber is still in that inbox rather than silently lost. Once you have seen
real confirmations land in the audience, that belt-and-braces email is safe to drop.

## Tests

```bash
python -m unittest discover -s tests -q     # builder, sender, cross-language token check
node tests/newsletter_tokens.test.mjs       # link signing, forgery and expiry
```
