# Campaign 1 — SIF data & API licensing

**Target:** the 17 SIF fund houses already in our data, plus wealth platforms, RIA software vendors
and research desks covering Indian funds.
**Ask:** take a free API key. The paid conversation follows once they have wired it in.
**Deal size:** ₹8,000/month (Starter) or ₹20,000/month (Pro). Four Pro customers ≈ $1,000/month.

Replace `[…]` before sending. Sign it yourself.

---

## Email A — to a fund house (product / digital / marketing head)

**Subject:** Your SIF scheme's numbers, computed independently

Hello [Name],

We run SIFintel (www.sifintel.com), an independent data platform covering every Specialized
Investment Fund in India. [Fund house]'s schemes are already on it — here is
[their scheme's page / the dashboard filtered to their funds]: [link]

We track all 111 SIF schemes from 17 fund houses, every trading day, straight from AMFI, and
normalise the portfolio disclosures that each AMC currently publishes in its own spreadsheet or PDF
format. That gives one consistent view of returns, drawdown and up/down capture across the whole
category — including the schemes you are measured against.

Two things that may be useful to you:

1. **The dataset as a feed.** A JSON API and a daily file, so your own dashboards, factsheets and
   competitor tracking run off maintained data instead of manual collection. Details and a free tier
   that needs no signup: www.sifintel.com/data
2. **A read on how you look in the category.** We can send you your schemes next to category peers
   on identical metrics — no charge, no strings. It is the same computation everyone else on the
   platform gets.

Worth a short call, or shall I just send the comparison?

[Your name]
[Title], Lume Software Private Limited
ceo@lumesoftai.com · www.sifintel.com

---

## Email B — to a platform, RIA software vendor or research desk

**Subject:** SIF data — the category has no vendor yet

Hello [Name],

Specialized Investment Funds are eighteen months old, there are 111 schemes across 17 fund houses,
and there is still no established data vendor for them. If [company] needs SIF coverage, you are
currently either scraping AMFI or waiting for someone to build it.

We built it. SIFintel maintains the full NAV history from the category's first published NAV, the
disclosed portfolios normalised into one schema, and a NIFTY 50 series aligned to the same dates so
capture ratios are computable without a second source.

It is a JSON API. The free tier needs no signup, so you can evaluate it in about a minute:

    curl "https://www.sifintel.com/api/v1/meta"
    curl "https://www.sifintel.com/api/v1/schemes?q=long-short"

Plans and redistribution terms: www.sifintel.com/data

If the schema nearly fits but not quite, tell me what shape you need it in — the pipeline is ours,
so accommodating you is a config change, not a project.

[Your name]
[Title], Lume Software Private Limited

---

## Follow-up (day 4, reply to your own thread)

**Subject:** Re: [original subject]

Hello [Name] — bumping this once in case it landed at a bad moment.

The free tier is live if you would rather just look than talk:
https://www.sifintel.com/api/v1/schemes

If SIF data isn't a priority this quarter, say so and I'll stop — no hard feelings, and I'll check
back when the category is bigger.

[Your name]

---

## If they ask "why should we trust your numbers?"

Good question, answer it directly:

- NAVs come from AMFI, the same source the AMCs report to. We do not adjust them.
- Portfolio data comes from the fund houses' own published disclosures. We normalise the format, not
  the contents.
- The methodology behind every computed metric (returns, drawdown, capture) is on the site and
  identical for every fund — nobody gets a favourable calculation.
- We take no money from fund houses to be featured, rated or ranked, and we say so on every page.
  That is precisely why the comparison is worth something.
