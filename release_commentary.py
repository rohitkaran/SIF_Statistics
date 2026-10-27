#!/usr/bin/env python3
"""
release_commentary.py  --  Release date-gated commentary drafts.

A draft named  content/commentary/_YYYY-MM-DD-slug.md  (leading underscore) is ignored by
publish_commentary.py until its date arrives. This script drops the underscore for every draft
whose date is today or earlier (UTC), so the next publish_commentary.py --push puts it live.

Run it daily from the workflow, then publish only if something was released:

    if python release_commentary.py | grep -q '^released:'; then python publish_commentary.py --push; fi

Writes nothing but the renames. No git, no network.
"""

import datetime as dt
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DRAFTS = os.path.join(HERE, "content", "commentary")


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    released = []
    for path in sorted(glob.glob(os.path.join(DRAFTS, "_*.md"))):
        name = os.path.basename(path)
        m = re.match(r"_(\d{4})-(\d{2})-(\d{2})-", name)
        if not m:
            continue
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d <= today:
            dst = os.path.join(os.path.dirname(path), name[1:])
            os.rename(path, dst)
            released.append(name[1:])
    if released:
        print("released: " + ", ".join(released))
    else:
        print("no drafts due today (" + today.isoformat() + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
