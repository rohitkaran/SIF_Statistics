#!/usr/bin/env python3
"""Publish market-commentary notes to https://www.sifintel.com/commentary/

This is the hand-off point between the research session (which WRITES the notes) and the site.
The research session only has to do two things:

    1. Write a markdown file into  content/commentary/  (see that folder's README.md for the format)
    2. Run                          python publish_commentary.py --push

Everything else — rendering, the index page, index.json, the sitemap, the git commit and push —
happens here. Cloudflare Pages picks up the push and the note is live in about a minute.

Usage
-----
    python publish_commentary.py                 # render only (inspect locally first)
    python publish_commentary.py --push          # render, commit and push (goes live)
    python publish_commentary.py --check         # validate the markdown, write nothing

Standard library only.
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sitetpl import SITE, KW, build, article_ld  # noqa: E402

SRC_DIR = os.path.join(HERE, "content", "commentary")
OUT_DIR = os.path.join(HERE, "commentary")
SITEMAP = os.path.join(HERE, "sitemap.xml")
SITEMAP_BEGIN = "  <!-- commentary:begin -->"
SITEMAP_END = "  <!-- commentary:end -->"

DISCLAIMER = ('<div class="callout warn">Market commentary is general information and education only — '
              'it is not investment, legal or tax advice, not a research report, and not a recommendation '
              'to buy or sell any security, fund or strategy. SIFintel is not a SEBI-registered investment '
              'adviser or research analyst. Views are as at the date of writing and may change without notice. '
              'Consult a SEBI-registered adviser before acting on anything you read here.</div>')


# --------------------------------------------------------------------------- front matter
def parse_front_matter(text: str, path: str) -> tuple[dict, str]:
    """Split a '---' delimited key: value header off the top of the file."""
    if not text.lstrip().startswith("---"):
        raise ValueError(f"{os.path.basename(path)}: missing '---' front-matter block at the top")
    text = text.lstrip()
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError(f"{os.path.basename(path)}: front matter is not closed with '---'")
    head, body = text[3:end], text[end + 4:]

    meta: dict = {}
    key = None
    for line in head.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", line)
        if m:
            key = m.group(1).strip().lower()
            meta[key] = m.group(2).strip()
        elif key and line.startswith((" ", "\t")):          # simple line continuation
            meta[key] = (meta[key] + " " + line.strip()).strip()
    for k, v in list(meta.items()):
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            meta[k] = v[1:-1]
    return meta, body.lstrip("\n")


def parse_tags(raw: str) -> list[str]:
    raw = (raw or "").strip().strip("[]")
    return [t.strip().strip("\"'") for t in raw.split(",") if t.strip()]


# --------------------------------------------------------------------------- markdown
def md_to_html(md: str) -> str:
    """A deliberately small markdown subset: headings, lists, tables, quotes, rules, code,
    bold/italic/code/links. Input is HTML-escaped first, so raw HTML in the source is inert."""
    lines = md.replace("\r\n", "\n").split("\n")

    # Shift headings so the shallowest one in the document becomes <h2> (the page <h1> is the title).
    levels = [len(m.group(1)) for m in (re.match(r"^(#{1,6})\s+\S", ln) for ln in lines) if m]
    shift = (2 - min(levels)) if levels else 0

    out: list[str] = []
    i, n = 0, len(lines)
    para: list[str] = []

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(para).strip()) + "</p>")
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_para()
            i += 1
            continue

        if stripped.startswith("```"):                                    # fenced code
            flush_para()
            lang = stripped[3:].strip()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            i += 1
            cls = f' class="lang-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>" + "\n".join(buf) + "</code></pre>")
            continue

        if re.match(r"^(\*\s*\*\s*\*|-\s*-\s*-|_\s*_\s*_)[\s*\-_]*$", stripped):   # hr
            flush_para()
            out.append("<hr>")
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)                      # heading
        if m:
            flush_para()
            lvl = min(max(len(m.group(1)) + shift, 2), 5)
            out.append(f"<h{lvl}>{inline(m.group(2).strip())}</h{lvl}>")
            i += 1
            continue

        if stripped.startswith(">"):                                      # blockquote
            flush_para()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append('<blockquote class="callout">' + inline(" ".join(buf)) + "</blockquote>")
            continue

        if "|" in stripped and i + 1 < n and re.match(r"^\s*\|?[\s:\-|]+\|[\s:\-|]*$", lines[i + 1]):
            flush_para()                                                  # table
            header = split_row(stripped)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i].strip()))
                i += 1
            out.append('<div class="tablewrap"><table class="data"><thead><tr>'
                       + "".join(f"<th>{inline(c)}</th>" for c in header)
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
                       + "</tbody></table></div>")
            continue

        if re.match(r"^([-*+]|\d+[.)])\s+", stripped):                    # list
            flush_para()
            ordered = bool(re.match(r"^\d+[.)]\s+", stripped))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < n and lines[i].strip():
                s = lines[i].strip()
                mi = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", s)
                if mi:
                    items.append(mi.group(2).strip())
                elif items:                                               # wrapped continuation
                    items[-1] += " " + s
                else:
                    break
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(it)}</li>" for it in items) + f"</{tag}>")
            continue

        para.append(stripped)
        i += 1

    flush_para()
    return "\n".join(out)


def split_row(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noopener">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<em>\1</em>", s)
    return s


# --------------------------------------------------------------------------- posts
def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:80]


def load_posts() -> list[dict]:
    posts = []
    for path in sorted(glob.glob(os.path.join(SRC_DIR, "*.md"))):
        name = os.path.basename(path)
        if name.lower() in ("readme.md",) or name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            meta, body = parse_front_matter(f.read(), path)

        missing = [k for k in ("title", "date") if not meta.get(k)]
        if missing:
            raise ValueError(f"{name}: front matter is missing {', '.join(missing)}")
        try:
            date = datetime.strptime(meta["date"][:10], "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"{name}: date '{meta['date']}' must be YYYY-MM-DD") from None
        if not body.strip():
            raise ValueError(f"{name}: the note has no body text")

        slug = meta.get("slug") or slugify(os.path.splitext(name)[0])
        summary = meta.get("summary") or re.sub(r"\s+", " ", re.sub(r"[#*`>_\[\]]", "", body))[:200].strip()
        posts.append({
            "slug": slug,
            "title": meta["title"],
            "date": date.isoformat(),
            "summary": summary,
            "author": meta.get("author", "SIFintel"),
            "tags": parse_tags(meta.get("tags", "")),
            "body": body,
            "source": name,
        })

    dupes = {p["slug"] for p in posts if [q["slug"] for q in posts].count(p["slug"]) > 1}
    if dupes:
        raise ValueError(f"duplicate slug(s): {', '.join(sorted(dupes))} — rename the file or set 'slug:'")
    posts.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)
    return posts


def render_post(p: dict) -> None:
    canon = f"{SITE}/commentary/{p['slug']}"
    nice_date = datetime.strptime(p["date"], "%Y-%m-%d").strftime("%d %B %Y")
    tags = "".join(f'<span class="pill">{html.escape(t)}</span>' for t in p["tags"])
    main = (f'<article class="doc">\n<h1>{html.escape(p["title"])}</h1>\n'
            f'<p class="lede">{html.escape(p["summary"])}</p>\n'
            f'<p class="meta">{html.escape(p["author"])} · {nice_date}'
            + (f'<br>{tags}' if tags else "") + '</p>\n'
            + md_to_html(p["body"]) + "\n" + DISCLAIMER
            + '\n<p class="meta" style="margin-top:22px"><a href="/commentary/">← All market commentary</a>'
              ' · <a href="/news">World financial news</a> · <a href="/">SIF dashboard</a></p>\n</article>')
    build(f"commentary/{p['slug']}.html",
          f"{p['title']} | SIFintel market commentary",
          p["summary"][:300],
          KW + ", market commentary, market outlook, macro commentary, " + ", ".join(p["tags"]),
          canon, "commentary",
          [("Home", "/"), ("Commentary", "/commentary/"), (p["title"][:40], None)],
          main,
          article_ld(canon, p["title"], p["summary"][:300], published=p["date"]))


def render_index(posts: list[dict]) -> None:
    if posts:
        cards = "\n".join(
            f'<a class="postcard" href="/commentary/{p["slug"]}">'
            f'<span class="tag">{datetime.strptime(p["date"], "%Y-%m-%d").strftime("%d %b %Y")}</span>'
            f'<h3>{html.escape(p["title"])}</h3><p>{html.escape(p["summary"][:220])}</p>'
            + ("".join(f'<span class="pill">{html.escape(t)}</span>' for t in p["tags"]))
            + "</a>" for p in posts)
        listing = f'<div class="postlist">\n{cards}\n</div>'
    else:
        listing = ('<div class="callout"><b>The first note is on its way.</b> Our market commentary starts '
                   'shortly — it will appear here as soon as it is published.</div>')

    main = f'''<article class="doc">
<h1>Market commentary</h1>
<p class="lede">Our regular written notes on what markets actually did and the macro backdrop behind the moves —
rates, inflation, currencies, flows — and what it means for the way long-short strategies behave.</p>
<p class="meta">SIFintel · {len(posts)} note{"" if len(posts) == 1 else "s"} · updated {datetime.now(timezone.utc).strftime("%d %B %Y")}</p>
{listing}
<h2>Read alongside</h2>
<div class="grid">
<a class="card" href="/news"><span class="tag">Live</span><h3>World financial news</h3><p>The headlines behind the commentary — refreshed every 30 minutes.</p></a>
<a class="card" href="/"><span class="tag">Tool</span><h3>SIF comparison dashboard</h3><p>See how every Indian SIF actually performed through the period.</p></a>
</div>
{DISCLAIMER}
</article>'''
    ld = ('{"@context":"https://schema.org","@type":"Blog","name":"SIFintel market commentary",'
          '"description":"Regular market and macro commentary from SIFintel.","inLanguage":"en-IN"}')
    build("commentary/index.html",
          "Market commentary — macro & markets | SIFintel",
          "Regular SIFintel market commentary: what markets did, the macro backdrop behind the moves, and what it "
          "means for long-short strategies. Educational only, not investment advice.",
          KW + ", market commentary, market outlook, macro commentary, India market view",
          f"{SITE}/commentary/", "commentary", [("Home", "/"), ("Commentary", None)],
          main, ld, ogtype="website", wrap_class="wide")

    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "count": len(posts),
            "posts": [{k: p[k] for k in ("slug", "title", "date", "summary", "author", "tags")}
                      | {"url": f"{SITE}/commentary/{p['slug']}"} for p in posts],
        }, f, ensure_ascii=False, indent=1)
    print(f"wrote commentary/index.json ({len(posts)} posts)")


def update_sitemap(posts: list[dict]) -> None:
    with open(SITEMAP, encoding="utf-8") as f:
        xml = f.read()
    if SITEMAP_BEGIN not in xml or SITEMAP_END not in xml:
        print("  note: sitemap markers not found — skipping sitemap update", file=sys.stderr)
        return
    entries = "\n".join(
        f'  <url><loc>{SITE}/commentary/{p["slug"]}</loc><lastmod>{p["date"]}</lastmod>'
        f'<changefreq>monthly</changefreq><priority>0.7</priority></url>' for p in posts)
    start, end = xml.index(SITEMAP_BEGIN) + len(SITEMAP_BEGIN), xml.index(SITEMAP_END)
    xml = xml[:start] + ("\n" + entries + "\n" if entries else "\n") + xml[end:]
    with open(SITEMAP, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"updated sitemap.xml ({len(posts)} commentary URLs)")


def git_push(posts: list[dict]) -> int:
    def run(*args):
        return subprocess.run(args, cwd=HERE, capture_output=True, text=True)

    run("git", "add", "commentary", "content/commentary", "sitemap.xml")
    if run("git", "diff", "--cached", "--quiet").returncode == 0:
        print("Nothing new to publish — the site already matches these notes.")
        return 0
    latest = posts[0]["title"] if posts else "commentary"
    msg = f"commentary: publish {latest[:60]}"
    r = run("git", "commit", "-m", msg)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    run("git", "pull", "--rebase", "--autostash", "origin", "main")
    r = run("git", "push")
    if r.returncode != 0:
        print("Commit made, but the push failed:\n" + r.stdout + r.stderr, file=sys.stderr)
        return 1
    print(f"Pushed. Live at {SITE}/commentary/ in about a minute.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Render and publish SIFintel market commentary.")
    ap.add_argument("--push", action="store_true", help="commit and push (publishes to the live site)")
    ap.add_argument("--check", action="store_true", help="validate the markdown only; write nothing")
    args = ap.parse_args()

    os.makedirs(SRC_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    try:
        posts = load_posts()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.check:
        for p in posts:
            print(f"ok  {p['source']:<44} -> /commentary/{p['slug']}  ({p['date']})")
        print(f"{len(posts)} note(s) valid.")
        return 0

    # Drop pages whose source markdown has been deleted, so the site never keeps orphans.
    live = {f"{p['slug']}.html" for p in posts} | {"index.html", "index.json"}
    for stale in os.listdir(OUT_DIR):
        if stale.endswith(".html") and stale not in live:
            os.remove(os.path.join(OUT_DIR, stale))
            print(f"removed stale commentary/{stale}")

    for p in posts:
        render_post(p)
    render_index(posts)
    update_sitemap(posts)

    if args.push:
        return git_push(posts)
    print(f"\n{len(posts)} note(s) rendered locally. Run with --push to publish them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
