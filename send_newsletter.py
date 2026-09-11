#!/usr/bin/env python3
"""
send_newsletter.py  --  Send the built weekly issue to confirmed subscribers, via Resend.

Sends ONE message per recipient rather than a bulk broadcast, because each message carries that
person's own signed unsubscribe link and the RFC 8058 one-click headers. A shared unsubscribe
link cannot identify who clicked it.

DRY RUN BY DEFAULT. Nothing leaves the machine without --send.

    python send_newsletter.py                          # show what would be sent, to whom
    python send_newsletter.py --test-to me@example.com --send
    python send_newsletter.py --send                   # the real thing

Environment:
    RESEND_API_KEY          required to send
    NEWSLETTER_SECRET       required; must match the value the Pages Functions use, or the
                            unsubscribe links in the email will not verify
    NEWSLETTER_AUDIENCE_ID  Resend audience to read recipients from
    NEWSLETTER_FROM         default: SIFintel <newsletter@sifintel.com>

stdlib only.
"""

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = "https://www.sifintel.com"
DEFAULT_FROM = "SIFintel <newsletter@sifintel.com>"
API = "https://api.resend.com"


# --- tokens: must match functions/api/_newsletter.js byte for byte --------------------

def b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def sign(secret, kind, email, ttl_days=0):
    """
    Mirror of sign() in _newsletter.js.

    The payload string and the base64url alphabet have to agree exactly across the two
    languages: a link minted here is verified by the Worker, and any difference shows up only
    as a live unsubscribe link that says "not valid" — after the email has gone out.
    """
    exp = int(dt.datetime.now(dt.timezone.utc).timestamp()) + ttl_days * 86400 if ttl_days else 0
    payload = f"{kind}:{email}:{exp}".encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{b64url(payload)}.{b64url(sig)}"


def unsubscribe_url(secret, email):
    return f"{SITE}/api/unsubscribe?t={sign(secret, 'unsub', email, 0)}"


# --- Resend ---------------------------------------------------------------------------

def api(path, key, method="GET", body=None, timeout=30):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def recipients(key, audience):
    """
    Confirmed, still-subscribed contacts.

    Written without a live Resend account to verify the response shape against, so it accepts
    the two documented spellings and fails loudly rather than silently sending to nobody.
    """
    j = api(f"/audiences/{audience}/contacts", key)
    rows = j.get("data") if isinstance(j, dict) else j
    if rows is None:
        raise SystemExit(f"[send] unexpected contacts response: {json.dumps(j)[:300]}")
    out = []
    for c in rows:
        email = (c.get("email") or "").strip().lower()
        if email and not c.get("unsubscribed"):
            out.append(email)
    return out


def send_one(key, sender, to, subject, html, text, unsub):
    body = {
        "from": sender, "to": [to], "subject": subject, "html": html, "text": text,
        # One-click unsubscribe: mail clients surface a native button and, crucially, stop
        # users reaching for "mark as spam" instead.
        "headers": {
            "List-Unsubscribe": f"<{unsub}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    api("/emails", key, method="POST", body=body)


# --- issue loading ----------------------------------------------------------------------

def load_issue(out_dir, date=None):
    d = os.path.join(HERE, out_dir)
    latest_path = os.path.join(d, "latest.json")
    if date is None:
        if not os.path.exists(latest_path):
            raise SystemExit("[send] no newsletter built yet — run build_newsletter.py first.")
        with open(latest_path, encoding="utf-8") as f:
            date = json.load(f)["date"]
    meta_subject = None
    if os.path.exists(latest_path):
        with open(latest_path, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("date") == date:
            meta_subject = meta.get("subject")
    html_path = os.path.join(d, f"{date}.email.html")
    text_path = os.path.join(d, f"{date}.email.txt")
    for p in (html_path, text_path):
        if not os.path.exists(p):
            raise SystemExit(f"[send] missing {os.path.relpath(p, HERE)} — build it first.")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    with open(text_path, encoding="utf-8") as f:
        text = f.read()
    return date, meta_subject or f"SIFintel weekly — {date}", html, text


def personalise(html, text, unsub):
    """Swap the placeholders the builder leaves for this recipient's own links."""
    html_out = html.replace(
        "{{UNSUB_HTML}}",
        f'<a href="{unsub}" style="color:#8a90a8">Unsubscribe</a>.')
    text_out = text.replace("{{UNSUB_TEXT}}", f"Unsubscribe: {unsub}")
    return html_out, text_out


def main(argv=None):
    p = argparse.ArgumentParser(description="Send the weekly SIFintel newsletter.")
    p.add_argument("--date", help="issue date YYYY-MM-DD (default: newsletter/latest.json)")
    p.add_argument("--out-dir", default="newsletter")
    p.add_argument("--send", action="store_true", help="actually send (default is a dry run)")
    p.add_argument("--test-to", help="send only to this address, ignoring the audience")
    p.add_argument("--limit", type=int, help="cap the number of recipients")
    a = p.parse_args(argv)

    secret = os.environ.get("NEWSLETTER_SECRET")
    key = os.environ.get("RESEND_API_KEY")
    audience = os.environ.get("NEWSLETTER_AUDIENCE_ID")
    sender = os.environ.get("NEWSLETTER_FROM", DEFAULT_FROM)

    if not secret:
        raise SystemExit("[send] NEWSLETTER_SECRET is not set — unsubscribe links would be "
                         "unverifiable, so refusing to send.")

    date, subject, html, text = load_issue(a.out_dir, a.date)

    if a.test_to:
        people = [a.test_to.strip().lower()]
    elif not key or not audience:
        people = []
        sys.stderr.write("[send] RESEND_API_KEY / NEWSLETTER_AUDIENCE_ID not set — "
                         "cannot read the subscriber list.\n")
    else:
        people = recipients(key, audience)
    if a.limit:
        people = people[:a.limit]

    sys.stderr.write(f"[send] issue {date}: {subject!r}\n")
    sys.stderr.write(f"[send] {len(people)} recipient(s){' (TEST)' if a.test_to else ''}\n")

    if not a.send:
        sample = people[0] if people else "nobody@example.com"
        sys.stderr.write("[send] DRY RUN — nothing sent. Re-run with --send.\n")
        sys.stderr.write(f"[send] sample unsubscribe link: {unsubscribe_url(secret, sample)}\n")
        return 0
    if not key:
        raise SystemExit("[send] RESEND_API_KEY is not set.")
    if not people:
        raise SystemExit("[send] no recipients.")

    sent = failed = 0
    for email in people:
        unsub = unsubscribe_url(secret, email)
        h, t = personalise(html, text, unsub)
        try:
            send_one(key, sender, email, subject, h, t, unsub)
            sent += 1
        except (urllib.error.URLError, OSError, ValueError) as e:
            failed += 1
            # Never abort the run: one bad address must not cost everyone else their issue.
            sys.stderr.write(f"[send] FAILED {email}: {str(e)[:160]}\n")
    sys.stderr.write(f"[send] sent {sent}, failed {failed}\n")
    return 1 if failed and not sent else 0


if __name__ == "__main__":
    raise SystemExit(main())
