#!/usr/bin/env python3
"""
patch_footer.py  --  Refresh the shared footer in every committed HTML page.

The page generators live in .build/ (gitignored scratch), so editing sitetpl.py alone updates
future builds but not the HTML already in the repo. This walks the committed pages and swaps
their footer block for the current sitetpl.FOOTER, keeping template and output in step.

Idempotent: a page already carrying the current footer is left untouched.

    python patch_footer.py            # apply
    python patch_footer.py --check    # report what would change, touch nothing
"""

import argparse
import os
import re
import sys

import sitetpl

HERE = os.path.dirname(os.path.abspath(__file__))

# The subscribe block sits immediately above the footer, so both are replaced as one unit.
BLOCK = re.compile(
    r'(?:<section class="subwrap".*?</script>\s*)?<footer class="site">.*?</footer>',
    re.S)

SKIP_DIRS = {".git", ".build", "node_modules", "portfolios", "assets", "brand",
             "functions", "monitor", "options_desk", "tests", "publish", "newsletter"}


# index.html is the bespoke dashboard: it carries its own chrome and never loads
# /assets/site.css, so the shared block would arrive unstyled. It gets a self-contained
# partial instead -- same markup and endpoint, styles inlined.
DASHBOARD_PARTIAL = os.path.join(HERE, "assets", "subscribe-dashboard.html")


def patch_dashboard(check=False):
    path = os.path.join(HERE, "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    if 'id="subscribe"' in html:
        return False                       # already carries it; idempotent
    marker = '<div class="sfoot" aria-label="Site footer">'
    if marker not in html:
        sys.stderr.write("[footer] index.html: .sfoot marker not found, skipped\n")
        return False
    with open(DASHBOARD_PARTIAL, encoding="utf-8") as f:
        partial = f.read()
    html = html.replace(marker, partial + marker, 1)
    html = html.replace('<a href="/about">About us</a>\n      <a href="/videos">Videos</a>',
                        '<a href="/about">About us</a>\n      <a href="/newsletter">Newsletter</a>'
                        '\n      <a href="/videos">Videos</a>', 1)
    if not check:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    return True


def pages():
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.endswith(".html") and not f.startswith("desk"):
                yield os.path.join(root, f)


def main(argv=None):
    p = argparse.ArgumentParser(description="Refresh the shared footer across committed pages.")
    p.add_argument("--check", action="store_true", help="report only")
    a = p.parse_args(argv)

    changed, skipped, missing = [], [], []
    for path in sorted(pages()):
        rel = os.path.relpath(path, HERE)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        if not BLOCK.search(html):
            missing.append(rel)
            continue
        new = BLOCK.sub(lambda _m: sitetpl.FOOTER, html, count=1)
        if new == html:
            skipped.append(rel)
            continue
        changed.append(rel)
        if not a.check:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)

    if patch_dashboard(a.check):
        changed.append("index.html")
        if "index.html" in missing:
            missing.remove("index.html")

    for rel in changed:
        sys.stderr.write(f"[footer] {'would update' if a.check else 'updated'} {rel}\n")
    if missing:
        # Not an error: the newsletter archive pages are generated whole by sitetpl already.
        sys.stderr.write(f"[footer] no footer block found in: {', '.join(missing)}\n")
    sys.stderr.write(f"[footer] {len(changed)} changed, {len(skipped)} already current, "
                     f"{len(missing)} without a footer\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
