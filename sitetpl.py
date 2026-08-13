#!/usr/bin/env python3
"""Shared SIFintel page chrome — header, nav, footer, <head> template.

Both generators import this so a nav or footer change lands on every page at once:
  * .build/build_site.py     — the static content pages (learn/, about, contact, videos, news)
  * publish_commentary.py    — the market-commentary posts written by the research session

This module lives at the repo ROOT, not in .build/, because .build/ is gitignored scratch and
publish_commentary.py is a committed tool that must keep working from a fresh clone.

Standard library only.
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

SITE = "https://www.sifintel.com"
EMAIL = "ceo@lumesoftai.com"
COMPANY = "Lume Software Private Limited"

STAR = ('<svg class="star" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.5 L14.3 9.7 '
        'L22.5 12 L14.3 14.3 L12 22.5 L9.7 14.3 L1.5 12 L9.7 9.7 Z"/></svg>')

# NOTE: /videos is intentionally footer-only. It is still built, linked and in the sitemap — it just
# doesn't earn a top-nav slot while it has no videos on it. Add ("videos", "/videos", "Videos") back
# here the day the first one is published.
NAV = [("home", "/", "Dashboard"),
       ("news", "/news", "News"),
       ("nfo", "/nfo", "NFOs"),
       ("aum", "/aum", "AUM"),
       ("attribution", "/attribution", "Attribution"),
       ("commentary", "/commentary/", "Commentary"),
       ("learn", "/learn/", "Learn"),
       ("distributors", "/distributors", "For distributors"),
       ("data", "/data", "Data &amp; API"),
       ("about", "/about", "About")]


def nav_html(active, depth=0):
    links = []
    for key, href, label in NAV:
        cls = ' class="active"' if key == active else ''
        links.append(f'<a href="{href}"{cls}>{label}</a>')
    return "\n      ".join(links)


def header(active):
    return f'''<header class="site">
  <div class="navwrap">
    <a href="/" style="text-decoration:none"><h1 class="wm">SIF<span class="in">intel{STAR}</span></h1></a>
    <nav class="main">
      {nav_html(active)}
    </nav>
    <span class="navspace"></span>
    <a class="navcta" href="/contact">Contact</a>
    <button class="themebtn" onclick="(function(){{var d=document.documentElement;var n=d.getAttribute('data-theme')==='dark'?'':'dark';if(n)d.setAttribute('data-theme','dark');else d.removeAttribute('data-theme');try{{localStorage.setItem('sif-theme',n)}}catch(e){{}}}})()">◐</button>
  </div>
</header>'''


FOOTER = f'''<footer class="site">
  <div class="footwrap">
    <div class="footcol">
      <h4>SIFintel</h4>
      <a href="/">SIF comparison dashboard</a>
      <a href="/news">World financial news</a>
      <a href="/nfo">SIF new fund offers</a>
      <a href="/aum">AUM &amp; market share</a>
      <a href="/attribution">Return attribution</a>
      <a href="/commentary/">Market commentary</a>
      <a href="/learn/">Learn about SIFs</a>
      <a href="/videos">Videos</a>
    </div>
    <div class="footcol">
      <h4>Learn</h4>
      <a href="/learn/what-is-a-sif">What is a SIF?</a>
      <a href="/learn/sif-categories">The SIF categories</a>
      <a href="/learn/sif-regulatory-framework">SEBI regulatory framework</a>
    </div>
    <div class="footcol">
      <h4>For distributors</h4>
      <a href="/distributors">Distributor guide</a>
      <a href="/learn/sif-certification-study-guide">Certification study guide</a>
      <a href="/learn/sif-tax-suitability-guide">Tax &amp; suitability primer</a>
    </div>
    <div class="footcol">
      <h4>For business</h4>
      <a href="/data">SIF data &amp; API</a>
      <a href="/services">Build with us</a>
      <a href="/api/v1/meta">API reference</a>
    </div>
    <div class="footcol">
      <h4>Company</h4>
      <a href="/about">About us</a>
      <a href="/contact">Contact</a>
      <a href="mailto:{EMAIL}">{EMAIL}</a>
    </div>
  </div>
  <div class="legal">
    <p>SIFintel is an independent data &amp; education platform for India's Specialized Investment Funds (SIFs),
    built to help investors and distributors understand this new asset class. We are not a SEBI-registered
    investment adviser, research analyst or distributor. Content is for education only and is not investment,
    legal or tax advice; no fund is recommended, ranked or promoted. SIFs carry higher risk — read scheme
    documents and consult a SEBI-registered adviser before investing.</p>
    <p>© 2026 {COMPANY}. All rights reserved.</p>
  </div>
</footer>'''


def breadcrumb(crumbs):
    # crumbs: list of (label, href|None)
    parts = []
    for label, href in crumbs:
        if href:
            parts.append(f'<a href="{href}">{label}</a>')
        else:
            parts.append(label)
    return '<div class="crumb">' + " / ".join(parts) + '</div>'


def q(s):  # minimal JSON string
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def article_ld(url, headline, desc, published=None):
    date = f',"datePublished":"{published}","dateModified":"{published}"' if published else ""
    return ('{"@context":"https://schema.org","@type":"Article",'
            f'"headline":{q(headline)},"description":{q(desc)}{date},'
            f'"author":{{"@type":"Organization","name":"SIFintel"}},'
            f'"publisher":{{"@type":"Organization","name":"SIFintel","logo":{{"@type":"ImageObject","url":"{SITE}/brand/logo-mark.svg"}}}},'
            f'"inLanguage":"en-IN","isAccessibleForFree":true,"mainEntityOfPage":"{url}"}}')


TPL = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE%</title>
<meta name="description" content="%DESC%">
<meta name="keywords" content="%KEYWORDS%">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="%CANON%">
<meta property="og:type" content="%OGTYPE%">
<meta property="og:site_name" content="SIFintel">
<meta property="og:title" content="%TITLE%">
<meta property="og:description" content="%DESC%">
<meta property="og:url" content="%CANON%">
<meta property="og:image" content="%SITE%/brand/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="%SITE%/brand/og-image.png">
<meta name="theme-color" content="#5b5bf0">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/brand/logo-mark.svg">
<script>try{if(localStorage.getItem('sif-theme')==='dark')document.documentElement.setAttribute('data-theme','dark');}catch(e){}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/site.css">
<script type="application/ld+json">%LD%</script>
</head>
<body>
%HEADER%
<main class="wrap%WRAPCLASS%">
%CRUMB%
%MAIN%
</main>
%FOOTER%
</body>
</html>'''


def build(outpath, title, desc, keywords, canon, active, crumbs, main_html, ld,
          ogtype="article", wrap_class=""):
    html = TPL
    repl = {"%TITLE%": title, "%DESC%": desc, "%KEYWORDS%": keywords, "%CANON%": canon,
            "%OGTYPE%": ogtype, "%SITE%": SITE, "%LD%": ld, "%HEADER%": header(active),
            "%WRAPCLASS%": (" " + wrap_class) if wrap_class else "",
            "%CRUMB%": breadcrumb(crumbs) if crumbs else "", "%MAIN%": main_html, "%FOOTER%": FOOTER}
    for k, v in repl.items():
        html = html.replace(k, v)
    full = os.path.join(ROOT, outpath)
    os.makedirs(os.path.dirname(full) or ROOT, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", outpath, f"({len(html)} bytes)")


KW = ("SIF, Specialized Investment Fund, SIF India, long-short fund, SIF NAV, SIF comparison, "
      "SIF categories, SEBI SIF, SIF distributor, NISM SIF, SIF taxation, SIFintel")
