-- SIFintel accounts + newsletter — Cloudflare D1 schema.
--
-- Apply with:
--   wrangler d1 create sifintel
--   wrangler d1 execute sifintel --remote --file=db/schema.sql
-- then bind it to the Pages project as  DB  (Settings -> Bindings -> D1 database).
--
-- Design notes:
--  * No password column anywhere. Sign-in is magic-link only, so the worst case for a
--    database leak is a list of email addresses, not credentials.
--  * login_tokens stores only the SHA-256 hash of the token. The plaintext exists solely
--    inside the one email we send.
--  * sends has a composite primary key (user_id, edition). That single constraint is what
--    makes the sender idempotent AND resumable: a re-run cannot double-send, and a partial
--    run simply picks up whoever has no row yet.

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,                      -- uuid v4
  email         TEXT NOT NULL UNIQUE,                  -- always stored lowercased/trimmed
  name          TEXT,
  created_at    TEXT NOT NULL,                         -- ISO8601 UTC
  verified_at   TEXT,                                  -- set the first time a magic link is used
  last_login_at TEXT,
  status        TEXT NOT NULL DEFAULT 'active',        -- active | unsubscribed | bounced
  source        TEXT,                                  -- page/campaign they signed up from

  -- newsletter preferences
  sif_weekly    INTEGER NOT NULL DEFAULT 1,            -- the weekly SIF intel digest
  news_daily    INTEGER NOT NULL DEFAULT 0,            -- the morning financial-news brief
  news_scope    TEXT    NOT NULL DEFAULT 'weekdays',   -- weekdays | everyday
  timezone      TEXT    NOT NULL DEFAULT 'Asia/Kolkata'
);

-- The sender's two hot queries: "who wants the SIF digest" / "who wants the news brief".
CREATE INDEX IF NOT EXISTS idx_users_sif  ON users(status, sif_weekly);
CREATE INDEX IF NOT EXISTS idx_users_news ON users(status, news_daily);

CREATE TABLE IF NOT EXISTS login_tokens (
  token_hash TEXT PRIMARY KEY,                         -- sha256 hex of the emailed token
  user_id    TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,                            -- 15 minutes after creation
  used_at    TEXT,                                     -- single use: set on redemption
  ip         TEXT
);
CREATE INDEX IF NOT EXISTS idx_tokens_user    ON login_tokens(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tokens_expires ON login_tokens(expires_at);

CREATE TABLE IF NOT EXISTS sends (
  user_id TEXT NOT NULL,
  edition TEXT NOT NULL,                               -- 'news:2026-09-11' | 'sif:2026-09-08'
  sent_at TEXT NOT NULL,
  status  TEXT NOT NULL,                               -- sent | failed
  detail  TEXT,
  PRIMARY KEY (user_id, edition)
);
CREATE INDEX IF NOT EXISTS idx_sends_edition ON sends(edition, status);
CREATE INDEX IF NOT EXISTS idx_sends_sent_at ON sends(sent_at);
