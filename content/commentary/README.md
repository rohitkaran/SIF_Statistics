# Market commentary — hand-off contract

**Read this if you are the session that writes the market-commentary reports.**

Everything published at <https://www.sifintel.com/commentary/> starts life as one markdown file in
this folder. You write the file; `publish_commentary.py` does the rest (renders the page, rebuilds
the index, updates the sitemap, commits and pushes). Cloudflare Pages deploys the push, so a note is
live roughly a minute after you publish it.

## The two commands

```bash
cd C:\Users\rohit\ClaudeCodeTradingView\sif-dashboard

# 1. write your note to  content/commentary/<YYYY-MM-DD>-<short-slug>.md   (format below)

# 2. publish it
python publish_commentary.py --check    # validate the front matter, write nothing
python publish_commentary.py            # render locally so you can read the HTML first
python publish_commentary.py --push     # render + commit + push  -> live in ~1 min
```

There is no draft state and no approval gate: **anything you leave in this folder is published on
the next `--push`.** If a note is not ready, keep it outside this folder or prefix the filename with
an underscore (`_wip-2026-08-14.md`) — underscore files are ignored.

## File format

Filename: `YYYY-MM-DD-short-slug.md` → published at `/commentary/YYYY-MM-DD-short-slug`.

```markdown
---
title: Rate cut hopes fade as US inflation surprises
date: 2026-08-13
summary: One or two sentences. This is the standfirst on the page, the blurb on the index card, and the description search engines show.
author: SIFintel Research
tags: macro, rates, india
---

Your note starts here. Plain markdown.

## A section heading

Ordinary paragraphs. **Bold**, *italic*, `code`, and [links](https://www.sifintel.com) all work.

- Bullet lists
- work too

| Index | Close | 1D |
| --- | --- | --- |
| NIFTY 50 | 24,150 | +0.6% |

> A blockquote renders as a highlighted callout.
```

**Front matter rules**

| Field | Required | Notes |
| --- | --- | --- |
| `title` | yes | Plain text, no markdown. Used as the page `<h1>` and `<title>`. |
| `date` | yes | `YYYY-MM-DD`. Sorts the index (newest first). |
| `summary` | recommended | 1–2 sentences. Auto-derived from the opening text if omitted. |
| `author` | no | Defaults to `SIFintel`. |
| `tags` | no | Comma-separated, e.g. `macro, rates, india`. Shown as pills. |
| `slug` | no | Overrides the filename-derived URL. |

Supported markdown: headings, paragraphs, bullet/numbered lists, tables, blockquotes, fenced code,
horizontal rules, bold, italic, inline code, links. Raw HTML is escaped, not rendered — the renderer
is a deliberately small subset (see `md_to_html` in `publish_commentary.py`).

Heading levels are shifted automatically so your shallowest heading becomes an `<h2>` under the page
title — use `#` or `##` for sections, whichever you prefer.

## What to write (and what not to)

SIFintel is **not** a SEBI-registered investment adviser or research analyst, and the site says so on
every page. That shapes the commentary:

- **Do**: describe what happened and why it plausibly happened — index moves, rates, inflation
  prints, currency and commodity moves, policy decisions, flows; explain mechanisms; connect the
  macro backdrop to how long-short strategies behave in general.
- **Don't**: recommend, rate or rank any specific security, fund, AMC or SIF scheme; give price
  targets or buy/sell/hold calls; promise or project returns; address an individual's situation.
- Attribute figures to their source and date them. Prefer "as at 13 Aug 2026" over "currently".
- A standard educational-only disclaimer is appended to every note automatically — you do not need
  to write one.

## Where it ends up

```
content/commentary/2026-08-13-rate-cut-hopes-fade.md    <- you write this
        |
        |  python publish_commentary.py --push
        v
commentary/2026-08-13-rate-cut-hopes-fade.html          <- rendered page   (/commentary/<slug>)
commentary/index.html                                   <- listing page    (/commentary/)
commentary/index.json                                   <- machine-readable feed of all notes
sitemap.xml                                             <- commentary URLs refreshed
```

Deleting a markdown file here and re-running the publisher removes the corresponding live page — the
publisher prunes orphans on every run.

## Useful inputs while writing

- `https://www.sifintel.com/api/news` — JSON of the last few days of world financial headlines
  (the same feed powering `/news`), refreshed every 30 minutes. Handy for grounding a note in what
  actually happened.
- `nav_data.json` in the repo root — every Indian SIF's NAV history, refreshed daily.
- `benchmark_data.json` — NIFTY 50 series used for the dashboard's capture ratios.
