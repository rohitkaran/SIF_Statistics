# Accounts & newsletters — setup and runbook

Logins and two email newsletters, on the existing Cloudflare Pages site. Nothing here needs a
build step, a server, or a framework.

- **Sign-in:** magic link only. No passwords are stored, hashed, or reset.
- **SIF Weekly:** Mondays. Generated from the site's own data, optionally led by a note from you.
- **Morning Brief:** weekday mornings (subscriber can choose every day). Generated from `/api/news`.

---

## 1. What you have to set up (once, ~20 minutes)

Nothing below is code — it is all configuration in two dashboards.

### 1.1 Create the database

```bash
npx wrangler d1 create sifintel
npx wrangler d1 execute sifintel --remote --file=db/schema.sql
```

The first command prints a `database_id`. Keep the terminal output.

### 1.2 Bind it to the Pages project

Cloudflare dashboard → **Workers & Pages → sif-statistics → Settings → Bindings → Add → D1 database**

| Field | Value |
|---|---|
| Variable name | `DB` ← must be exactly this |
| D1 database | `sifintel` |

Add it to **both** Production and Preview, or preview deployments will 503 on every account route.

### 1.3 Environment variables

Same Settings page → **Environment variables**. Mark the two secrets as **Encrypted**.

| Variable | Value | Notes |
|---|---|---|
| `SESSION_SECRET` | a long random string | **Encrypted.** Signs session cookies and unsubscribe tokens. Generate with `python -c "import secrets;print(secrets.token_urlsafe(48))"`. Changing it later signs everyone out and invalidates every unsubscribe link already sitting in people's inboxes — so set it once and leave it. |
| `CRON_SECRET` | a long random string | **Encrypted.** The only thing standing between the public and your whole mailing list. Must match the GitHub secret in 1.5. |
| `RESEND_API_KEY` | your Resend key | Already set for the contact form — the newsletter reuses it. |
| `NEWSLETTER_FROM` | `SIFintel <news@sifintel.com>` | Optional. Must be a domain verified in Resend. |
| `NEWSLETTER_REPLY_TO` | `ceo@lumesoftai.com` | Optional; falls back to `CONTACT_TO`. |
| `RESEND_DAILY_CAP` | `100` | Resend's free-tier daily limit. Raise it the day you upgrade — see §4. |

### 1.4 Verify the sending domain in Resend

Resend → Domains → `sifintel.com` → add the SPF, DKIM and DMARC records it gives you to
Cloudflare DNS. **Do not skip this.** Without DKIM and DMARC, Gmail and Yahoo route bulk mail
straight to spam, and a newsletter nobody sees is worse than no newsletter.

### 1.5 The GitHub secret

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `CRON_SECRET` | the same string as in 1.3 |

Optionally add a *variable* (not a secret) `NEWSLETTER_SITE` if you ever want the workflow to
point somewhere other than `https://www.sifintel.com`.

---

## 2. Check it works

```bash
# 1. Status — proves the D1 binding and the secret are live.
curl -H "Authorization: Bearer $CRON_SECRET" \
  "https://www.sifintel.com/api/cron/send?kind=sif" | jq

# 2. Preview an edition in your browser without sending anything.
curl -H "Authorization: Bearer $CRON_SECRET" \
  "https://www.sifintel.com/api/cron/send?kind=sif&preview=1" > preview.html && open preview.html

# 3. Subscribe yourself at https://www.sifintel.com/subscribe, click the emailed link.

# 4. Dry run — builds the edition and counts recipients, sends nothing.
curl -X POST -H "Authorization: Bearer $CRON_SECRET" \
  "https://www.sifintel.com/api/cron/send?kind=sif&dry=1" | jq

# 5. For real (you are the only subscriber at this point).
curl -X POST -H "Authorization: Bearer $CRON_SECRET" \
  "https://www.sifintel.com/api/cron/send?kind=sif" | jq
```

Then run the workflow by hand once: **Actions → Send newsletters → Run workflow**, leaving
*Dry run* ticked.

---

## 3. Writing the weekly note

The SIF Weekly builds itself. The top of it is yours, and there are three ways it gets filled —
the builder takes the first one that applies:

1. **`newsletter_note.json`** — what you wrote with `newsletter_note.py`.
2. **A commentary post** published in the last 8 days — leads automatically, nothing to do.
3. **Neither** — the digest opens with a one-line standfirst. Still a complete email.

```bash
python newsletter_note.py --title "Why three funds went to cash" --file note.md
python newsletter_note.py --show
python newsletter_note.py --clear
git add newsletter_note.json && git commit -m "newsletter: note for this week" && git push
```

The note supports a small Markdown subset: paragraphs, `**bold**`, `*italic*`,
`[links](https://…)` and `-` bullets. It **must be committed and pushed** — the edge function
reads it as a static file from the deployed site, so an uncommitted note will not appear.

Notes expire after 8 days by default (`--days`), so one you forget to clear stops leading the
newsletter by itself instead of fronting a digest a month later.

---

## 4. The Resend free tier is the real constraint

Free Resend is **100 emails/day, 3,000/month**. The daily brief is what hits this first:

| Subscribers to the daily brief | Free tier |
|---|---|
| up to ~100 | fine |
| ~100–130 | daily cap hit; the workflow warns and the rest go out next run |
| above ~140 | over the 3,000/month ceiling too |

`RESEND_DAILY_CAP` stops the sender before Resend starts rejecting, so you get a warning in the
Actions log rather than silent failures. Nothing else changes when you upgrade — set
`RESEND_DAILY_CAP` to `50000` on Resend's $20/month tier and the same code carries on.

Watch the number with:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" \
  "https://www.sifintel.com/api/cron/send?kind=news" | jq .list
```

---

## 5. How it fits together

```
  Browser                     Cloudflare Pages Functions                D1
  ───────                     ──────────────────────────                ──
  /subscribe  ──POST──────▶   /api/auth/request ──┬─▶ upsert user  ───▶ users
                                                  └─▶ mint token   ───▶ login_tokens
                                      │
                                      └── Resend ──▶ magic link email
  /auth?t=…   ──POST──────▶   /api/auth/verify  ──▶ redeem token   ───▶ login_tokens
                                      └─▶ Set-Cookie: sif_session (signed, 30d)
  /account    ──GET/POST──▶   /api/account      ──▶ read/write prefs──▶ users
  /unsubscribe─GET/POST──▶    /api/unsubscribe  ──▶ opt out        ───▶ users

  GitHub Actions (a clock, nothing more)
      └── POST /api/cron/send?kind=news|sif
              ├─ build the edition from nav_data.json / /api/news / …
              ├─ pick recipients not yet sent this edition          ───▶ users, sends
              ├─ Resend batch (≤100 per call)
              └─ record who received it                             ───▶ sends
```

### Files

| Path | Role |
|---|---|
| `db/schema.sql` | The D1 schema. Apply once. |
| `functions/_lib/session.js` | HMAC session cookies, magic-link and unsubscribe tokens. |
| `functions/_lib/db.js` | Every SQL statement in the project. |
| `functions/_lib/email.js` | Resend transport + the email shell. |
| `functions/_lib/digest.js` | Builds both editions from the site's own JSON. |
| `functions/api/auth/*.js` | request / verify / logout. |
| `functions/api/account.js` | Read and write preferences. |
| `functions/api/unsubscribe.js` | Confirmed and one-click (RFC 8058) opt-out. |
| `functions/api/cron/send.js` | The sender. Idempotent, resumable, capped. |
| `build_accounts.py` | Generates `/subscribe`, `/account`, `/auth`, `/unsubscribe`. |
| `newsletter_note.py` | Sets the editor's note on the next SIF Weekly. |
| `.github/workflows/newsletter.yml` | The clock. |

Files under `functions/_lib/` export no request handler, so Pages generates no route for them —
they are plain modules the route files import.

---

## 6. Things that will bite you

**A magic link that says "already used".** Corporate mail gateways and link scanners fetch every
URL in an incoming email. This is why the emailed link points at `/auth` (a static page) and
redemption happens on a `POST` — a scanner's GET cannot burn the token. If you ever change that
flow, you will get support mail about broken links within a day.

**Never turn one-click unsubscribe off.** `List-Unsubscribe` and `List-Unsubscribe-Post` are
required by Gmail and Yahoo for bulk senders. The endpoint deliberately answers `200 OK` even for
a token it cannot parse, because providers penalise senders whose unsubscribe endpoint errors.

**GitHub's scheduler is late.** Routinely by 5–20 minutes, occasionally more, and it skips runs
when GitHub is busy. "7am IST" means "shortly after 7am IST". The sender is idempotent, so a
missed run can be triggered by hand with no risk of double-sending. If exact timing ever matters,
move the schedule to a Cloudflare Worker cron — `send.js` itself would not change.

**Editions are keyed by IST date.** `news:2026-09-11`, `sif:2026-09-08`. Re-running the same
edition sends to nobody who already got it. That is the safety net — use it freely.

**A failed send is retried; a failing pass stops the loop.** Recipients whose send errored stay
pending and are picked up on the next pass, but if a whole pass delivers nothing the workflow
stops rather than hammering a bad key or a dead address 30 times.

**`SESSION_SECRET` is load-bearing for unsubscribe links.** Rotating it invalidates every
unsubscribe link in every email you have ever sent. Only rotate it if it leaks, and accept that
people will have to use `/account` to opt out afterwards.

---

## 7. Deliberately not built

Called out so nobody assumes they exist:

- **No payments.** Both newsletters are free; the paid product is still the data feed on `/data`,
  and API keys are still hand-issued via the `API_KEYS` env var.
- **No bounce or complaint handling.** Resend records them; nothing writes them back to `users`.
  Add a Resend webhook → `status = 'bounced'` when the list is big enough to matter.
- **No admin UI.** Subscriber counts come from `GET /api/cron/send?kind=…` (the `list` block).
- **No per-user personalisation.** Everyone on a list gets the same edition; only the unsubscribe
  link differs. Watchlist-driven digests would need the saved-funds feature first.
- **No double opt-in beyond the magic link.** Confirming the link *is* the confirmation, which is
  the standard bar and satisfies DPDP consent — but no separate "yes I really meant it" step.
