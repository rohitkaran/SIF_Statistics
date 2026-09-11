#!/usr/bin/env python3
"""Set, show or clear the editor's note that leads the next SIF Weekly.

The weekly digest is generated from data (see functions/_lib/digest.js), but the top of the
email is yours. There are two ways to fill it, and the builder prefers them in this order:

  1. newsletter_note.json  — what this script writes. The deliberate "I want to say something
     this week" lever.
  2. The newest post in commentary/ — if you published one in the last 8 days, it leads
     automatically. Nothing to do.
  3. Neither — the digest opens with a plain one-line standfirst. Still a complete email.

Written as a committed root-level tool (like publish_commentary.py) so it works from a fresh
clone. The output file is committed and served as a static asset, which is how the edge
function reads it at send time — no database, no admin UI.

    python newsletter_note.py --title "Why three funds went to cash" --file note.md
    python newsletter_note.py --title "Quick one" --text "Two things worth flagging this week."
    python newsletter_note.py --show
    python newsletter_note.py --clear

EXPIRY: a note is stamped with an expiry (default 8 days). A note you forget to clear stops
leading the newsletter on its own rather than fronting a digest a month later.

Standard library only.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
NOTE = os.path.join(ROOT, "newsletter_note.json")

# Inline styles only — the note is dropped straight into an HTML email, where a <style> block
# is stripped by Gmail and ignored by Outlook. These match _lib/email.js.
P = '<p style="margin:0 0 12px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.65;color:#4a5578">'
LI = '<li style="margin:0 0 6px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:#4a5578">'


def to_html(text: str) -> str:
    """A deliberately small Markdown subset: paragraphs, **bold**, *italic*, [links](url),
    and `-` bullet lists. Everything else is escaped and left alone — this is a short note,
    not an article, and a full Markdown engine would be a dependency for no gain."""
    blocks = re.split(r"\n\s*\n", text.strip())
    out = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if lines and all(ln.startswith(("- ", "* ")) for ln in lines):
            items = "".join(LI + inline(ln[2:]) + "</li>" for ln in lines)
            out.append('<ul style="margin:0 0 12px;padding-left:20px">' + items + "</ul>")
        else:
            out.append(P + inline(" ".join(lines)) + "</p>")
    return "".join(out)


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
               r'<a href="\2" style="color:#0e9aa7">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r'<strong style="color:#1c2338">\1</strong>', s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage the editor's note on the next SIF Weekly.")
    ap.add_argument("--title", help="Headline for the note (becomes the email subject too).")
    ap.add_argument("--text", help="Note body, inline.")
    ap.add_argument("--file", help="Note body, read from a file (Markdown subset).")
    ap.add_argument("--days", type=int, default=8,
                    help="Days until the note stops being used (default 8).")
    ap.add_argument("--clear", action="store_true", help="Remove the note.")
    ap.add_argument("--show", action="store_true", help="Print the current note.")
    args = ap.parse_args()

    if args.show:
        if not os.path.exists(NOTE):
            print("No note set — the next SIF Weekly will lead with recent commentary, or with the data.")
            return 0
        with open(NOTE, encoding="utf-8") as f:
            note = json.load(f)
        expired = note.get("expires", "") < date.today().isoformat()
        print(f"title   : {note.get('title')}")
        print(f"expires : {note.get('expires')}" + ("  (EXPIRED — will not be used)" if expired else ""))
        print(f"active  : {note.get('active')}")
        print("-" * 60)
        print(note.get("source_text") or note.get("html"))
        return 0

    if args.clear:
        if os.path.exists(NOTE):
            os.remove(NOTE)
            print("Cleared. The next SIF Weekly leads with recent commentary, or with the data.")
        else:
            print("Nothing to clear.")
        return 0

    body = args.text
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            body = f.read()
    if not body or not args.title:
        ap.error("give --title and one of --text / --file (or use --show / --clear)")

    note = {
        "active": True,
        "title": args.title.strip(),
        "html": to_html(body),
        "source_text": body.strip(),
        "expires": (date.today() + timedelta(days=args.days)).isoformat(),
        "_note": "Written by newsletter_note.py. Read at send time by functions/_lib/digest.js. "
                 "Committed and served as a static file — that is how the edge function sees it.",
    }
    with open(NOTE, "w", encoding="utf-8") as f:
        json.dump(note, f, indent=1, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote newsletter_note.json — leads the SIF Weekly until {note['expires']}.")
    print(f"  title: {note['title']}")
    print("  Commit and push it, then preview with:")
    print("    curl -H \"Authorization: Bearer $CRON_SECRET\" \\")
    print("      \"https://www.sifintel.com/api/cron/send?kind=sif&preview=1\" > preview.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
