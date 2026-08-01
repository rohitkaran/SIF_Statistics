# SIFintel — Business Plan & Product Architecture

*Brand: **SIFintel** (sifintel.com). The intelligence layer for India's Specialized Investment
Funds (SIFs) — data, strategy decoding, education and media. This document lays out the opportunity,
the three customer segments, the product pillars, how we make money, the content/video engine, the
full technical architecture, a phased roadmap, and the regulatory guardrails.*

> **North star:** be the **default source of truth and preparation** for anyone touching SIFs —
> investors researching, distributors selling, and AMCs benchmarking — and the **loudest, clearest
> voice** explaining SIFs to India through short-form video.
>
> **The wedge in the name — "intel":** don't stop at NAVs and ratios. **Decode each fund's actual
> strategy** — how the long/short book, hedges, arbitrage and asset mix *actually generate the
> returns* — from the disclosed holdings and derivative positions. This strategy-intelligence layer
> (a genuine team strength) is the differentiator competitors won't easily copy and the reason a
> distributor or AMC pays: it turns raw disclosure into *understanding*.

---

## 1. Why now — the opportunity

SIFs are a **brand-new SEBI asset class** (framework Feb 2025; first funds live from ~Sep–Oct 2025),
sitting between mutual funds and PMS/AIF: long-short and allocator strategies, **₹10 lakh minimum**,
aimed at informed/affluent investors.

- **Greenfield, fast-growing.** Industry AUM roughly **₹4,892 Cr (Dec 2025) → ₹9,711 Cr (Feb 2026) →
  ₹10,620 Cr (Mar 2026)** — a >100% quarter. ~**17 AMCs**, ~**111 scheme variants**, 5 strategy
  families, with more AMCs launching (Kotak, Invesco, Jio BlackRock, etc.).
- **No incumbent.** Value Research / Morningstar / MFI-style analytics **do not cover SIFs** (AMFI
  has no SIF holdings API; data is scattered across 17 heterogeneous AMC sites). We already solved
  that ingestion — that's the moat's foundation.
- **A regulatory tailwind for education.** SEBI now requires the **NISM Series V-D (Mutual Fund &
  SIF Distributors) certification** to sell SIFs (exam live 22 Jul 2026; transition off NISM XIII by
  Sep 2026). Every MFD who wants to sell SIFs must certify — a captive, motivated education market.
- **Distribution is the bottleneck.** AMCs openly say SIF success hinges on distributor readiness.
  Distributors are under-equipped to explain long-short/hedged products to HNI clients.

**Timing:** we are early enough to become the category's data standard before anyone else, and the
regulatory certification wave gives an immediate education wedge.

---

## 2. The problem we solve, per audience

| Audience | Their problem today | What we give them |
|---|---|---|
| **Investor** (HNI/informed) | SIFs are new, opaque, hard to compare; no neutral analytics; ₹10L is a big cheque to make blind | Trustworthy stats, holdings, risk/return, comparisons, plain-English education → confidence & awareness |
| **Distributor** (MFD/RIA) | Must get NISM V-D certified; must explain hedged products & defend them vs MFs/PMS; no ready collateral | Certification prep + AI-curated intel + client-ready comparisons & one-pagers → walk into meetings prepared |
| **AMC** (product/sales/strategy) | No neutral benchmark of where their SIF stands vs peers; hard to see competitor positioning, flows, crowding | Competitive intelligence, benchmarking, flow/holdings analytics, distributor reach → push themselves up the table |

Secondary audiences (monetizable later): **wealth platforms/fintechs** (data/API), **media &
researchers** (dataset), **family offices**, **the press**.

---

## 3. Product pillars

### P1 — SIF Data & Analytics Terminal  *(live today: the current dashboard)*
Real NAVs, ~20 risk/return metrics, disclosed **holdings** per fund (allocation, long/short, sectors,
managers, strategy), up/down capture vs NIFTY 50, multi-fund compare, CSV export. This is the free,
SEO-friendly front door and the credibility anchor.
*Roadmap adds:* screener, alerts, watchlists, portfolio X-ray/overlap, flows & AUM tracker, factsheet
archive, "Ask the data" AI chat, mobile app.

### P2 — Distributor Enablement Suite  *(primary B2B SaaS revenue)*
- **NISM V-D exam prep:** structured course, chapter notes, question bank, timed mock tests, progress
  tracking, pass guarantee. (Also micro-courses on long-short concepts, hedging, arbitrage.)
- **AI-curated intelligence feed ("Prep for the meeting"):** daily/weekly tit-bits on SIFs, global
  markets, hedge-fund strategies, macro — curated & summarized by AI, human-reviewed. Distributor
  walks into a client meeting current and confident.
- **Client-ready collateral generator:** compliant one-pagers, fund comparison sheets, "SIF vs MF vs
  PMS" explainers, risk illustrations — branded to the distributor. (Guardrail: factual/education,
  not personalized advice.)
- **Lead & client tools (lite CRM):** save watchlists, share reports, track which clients saw what.

### P3 — AMC Intelligence & Benchmarking  *(enterprise, highest ACV)*
- **Competitive benchmarking dashboards:** where each of my schemes ranks vs peers on returns, risk,
  capture, flows, holdings overlap, net exposure.
- **Industry analytics:** stock/sector crowding across all SIFs (most-held longs, most-crowded
  shorts), net-long trends, category flows, launch tracker.
- **White-label widgets & data API** for the AMC's own site; **sponsored/verified fund profiles**;
  **market-intelligence reports.**

### P4 — Content & Media Engine  *(top-of-funnel growth + sponsorship revenue)*
AI-generated **short videos** (via **Higgsfield**) + written explainers on SIFs, investing, market
events, hedge-fund concepts — published to **Instagram Reels, YouTube Shorts, LinkedIn**. Every video
funnels to the platform. This is how we reach a mass audience cheaply and build the brand. (See §5.)

### P5 — Community & Voices  *(moat + credibility, unlocked at critical mass)*
Once traffic/authority is real: **fund-manager & product-head interviews**, AMAs, expert columns,
webinars, a verified-voices program. Turns a data tool into the category's town square.

---

## 4. How we make money

Layered so each segment monetizes differently; free terminal + content drive the top of funnel.

| Stream | Segment | Model | Notes |
|---|---|---|---|
| **Freemium Pro** | Investor | ₹/month or ₹/yr | Advanced analytics, alerts, X-ray, unlimited compare/export, "Ask the data" |
| **Distributor SaaS** | Distributor | Per-seat subscription (tiers) | The core recurring B2B revenue; bundles NISM prep + intel feed + collateral |
| **NISM V-D course** | Distributor | One-time (+ renewals/CPE) | Captive regulatory demand; strong standalone funnel |
| **AMC Enterprise** | AMC | Annual contracts / data licensing | Benchmarking, industry analytics, API, white-label — highest ACV |
| **Data & API** | Fintech/media | Usage or licence | Sell the normalized SIF dataset (NAVs, holdings, flows) |
| **Content sponsorship** | AMC/brands | Sponsored series, brand deals, YT/IG ad share | Monetize the media engine's reach |
| **Lead-gen** | AMC/distributor | Qualified investor/distributor leads | From the free audience (compliant, opt-in) |
| **Events/webinars** | All | Ticketed / sponsored | At community stage |

**Why B2B leads:** Indian retail rarely pays for research, but **distributors and AMCs pay for tools
that win/retain AUM**, and the certification is a must-buy. Investor free tier is the audience &
credibility engine, not the main revenue.

---

## 5. Content & AI-video engine (Higgsfield → Reels/Shorts)

A repeatable pipeline, human-reviewed for accuracy & compliance:

1. **Source** — AI scans our own data events (new disclosures, big NAV moves, new fund launches,
   manager changes, crowding shifts) + curated market/hedge-fund news → topic queue.
2. **Script** — LLM drafts a 20–45s script + hook + on-screen captions + CTA, in a consistent brand
   voice; **human editor reviews** for factual accuracy and compliance (no advice, disclaimers).
3. **Generate** — **Higgsfield** produces the video (b-roll/avatar/motion); auto-brand (logo, colors,
   lower-thirds), captions burned in, voiceover.
4. **Review & approve** — a person signs off (compliance checklist + source attribution) before publish.
5. **Publish & schedule** — post to Instagram Reels, YouTube Shorts, LinkedIn via their APIs/schedulers,
   with UTM links back to the relevant fund/terminal page.
6. **Measure & loop** — track reach → clicks → signups; feed winners back into the topic model.

**Content pillars:** "SIF explained in 30s", "This week in SIFs" (data-driven), "Hedge-fund concept of
the day", "Market event → what it means", "Fund spotlight" (neutral, factual), later "Manager in 60s".
**Purpose:** cheap, scalable top-of-funnel + brand authority; each short is a mini-ad for the platform.

---

## 6. Technical architecture

### 6.1 Where we are (MVP, live)
Static site on **GitHub Pages**, data produced by **Python fetchers** (`fetch_amfi_sif.py` NAVs,
`fetch_sif_portfolios.py` holdings, `fetch_benchmark.py` NIFTY 50) run by **GitHub Actions** on a
schedule, committing JSON back to the repo. Zero infra, perfect for validation and SEO — **keep it as
the public marketing/terminal front even as we scale.**

### 6.2 Target platform (as we add accounts, payments, education, content, video)

```
                         ┌──────────────────────────────────────────────┐
   Investors / MFDs /    │  Web app (terminal + Pro)  ·  Mobile app/PWA  │
   AMCs / social traffic │  Distributor console  ·  AMC console          │
                         └───────────────┬──────────────────────────────┘
                                         │  HTTPS / API
                         ┌───────────────▼──────────────────────────────┐
                         │  API Gateway  +  Auth (accounts, roles/entitlements)  │
                         └───────────────┬──────────────────────────────┘
          ┌──────────────┬──────────────┼──────────────┬───────────────┐
          ▼              ▼              ▼              ▼               ▼
   Core Data API   Content/CMS API   Education/LMS   Billing/Subs   Analytics
   (schemes, NAVs, (articles, video   (courses, quiz, (Razorpay/     (usage,
   holdings, flows, assets, feeds)    mock tests,     Stripe,        funnels,
   metrics, screener)                 progress)       entitlements)  cohorts)
          │
          ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │  Data platform:  Postgres (normalized) + object store (raw files) │
   │  + time-series (NAVs) + search index                              │
   └───────────────▲─────────────────────────────────────────────────┘
                   │ ETL / normalize / QC
   ┌───────────────┴─────────────────────────────────────────────────┐
   │  Ingestion workers (extend today's fetchers):                     │
   │   • AMFI SIF NAV APIs (daily)                                      │
   │   • Per-AMC portfolio disclosures (bi-monthly) — incl. HEADLESS    │
   │     BROWSER (Playwright) for WAF/Akamai/JS sites (ICICI, Edelweiss,│
   │     Bandhan, Franklin, Kotak, qsif accordion…)                    │
   │   • Benchmarks (NIFTY 50, hybrid indices), flows/AUM, factsheets   │
   │   • Auto-detect NEW funds & new periods; alert on manager changes  │
   └───────────────────────────────────────────────────────────────────┘

   AI services (side-car):  LLM (curation, scripts, "Ask the data" RAG over our dataset,
   one-pager generation)  +  Higgsfield (video)  +  a compliance/editorial review step
   +  social publishers (IG/YT/LinkedIn).
```

**Key engineering notes**
- **Headless-browser ingestion is the critical upgrade.** Several AMC sites block plain HTTP
  (Akamai/F5/Radware) or render via JS; a scheduled **Playwright** worker (same-origin fetch /
  download, like we did manually for Altiva & qsif) makes portfolio ingestion fully automated and CI-safe.
- **Keep the fetchers as the ingestion core** — they already normalize the SEBI-standard xlsx and map
  funds to schemes; wrap them in workers writing to Postgres instead of JSON files.
- **Entitlements everywhere:** free vs Pro vs Distributor vs AMC gating at the API layer.
- **RAG "Ask the data":** vector index over holdings/metrics/news so users can ask natural-language
  questions ("which SIFs are most short financials?") — grounded in our data, with citations.
- **Hosting migration path:** Pages (now) → Cloudflare/Vercel + a managed Postgres + a worker/queue
  (Cloudflare Workers / a small cloud) as accounts and content grow. Keep costs lean until B2B revenue.

### 6.3 Data moat & defensibility
- The **normalized, historical SIF dataset** (NAVs + bi-monthly holdings + flows across 17+ AMCs) is
  hard to assemble (heterogeneous, WAF-protected sources) and **compounds over time** — every period
  we capture is one a competitor can't backfill.
- **First-mover brand** in a category with no incumbent; content engine builds audience & SEO moat.
- **Two-sided pull:** distributors want the intel; AMCs want the benchmarking & reach — reinforcing.

---

## 7. Regulatory & compliance (India) — non-negotiable guardrails
- **We are DATA + EDUCATION + TOOLS, not advice.** No personalized recommendations (that triggers SEBI
  **RIA** registration); no "buy/sell" ratings or research recommendations (triggers SEBI **RA**
  registration) unless/until we register and staff for it.
- **Distributor tooling** must stay factual/comparative; if we ever facilitate transactions we need the
  appropriate ARN/distributor arrangements.
- **Content & video:** factual, sourced, with standard disclaimers ("not investment advice; SIFs carry
  high risk; ₹10L minimum; read scheme documents"). Human editorial + compliance sign-off before publish.
- **Data attribution & accuracy:** every number traces to the AMC/AMFI source; visible "as-of" dates;
  correction process. (We already do source attribution in the terminal.)
- **Data privacy:** DPDP Act compliance for user accounts; consent for lead-gen; secure PII handling.
- **AMC relationships:** benchmarking must be fair/neutral to avoid disputes; give AMCs a "claim/verify
  your profile" path.

---

## 8. Go-to-market & growth flywheel
1. **Free terminal + SEO** (live) → capture everyone Googling any SIF/scheme.
2. **Short-form video engine** → mass awareness, funnel to terminal.
3. **NISM V-D course** → captive distributor acquisition (regulatory must-buy).
4. **Distributor SaaS** → convert certified distributors into paying subscribers (intel + collateral).
5. **AMC enterprise** → sell benchmarking/data once we have audience + distributor reach they want.
6. **Community/interviews** → authority → more audience → repeat.

Flywheel: *content → audience → free users → distributor/AMC revenue → fund more content & data →
bigger moat.*

---

## 9. Roadmap (phased)

- **Phase 0 — Foundation (now):** free terminal live; holdings for 90/111 schemes; NAVs + capture +
  compare; SEO pages per scheme. **Ship the Playwright ingestion worker** to automate WAF/JS AMCs.
- **Phase 1 — Audience & content (0–3 mo):** launch the video engine (Higgsfield) + weekly cadence;
  newsletter + WhatsApp/Telegram; screener, alerts, watchlists; scheme landing pages for SEO.
- **Phase 2 — Distributor wedge (3–9 mo):** NISM V-D course + mock tests; AI intel feed; collateral
  generator; accounts + billing; launch Distributor SaaS.
- **Phase 3 — AMC & data (9–18 mo):** benchmarking console, industry analytics (crowding/flows),
  API/white-label, sponsored profiles; "Ask the data" RAG; mobile app.
- **Phase 4 — Community (18 mo+):** fund-manager interviews, webinars, verified voices, events.

## 10. KPIs
Traffic & SEO rank; video reach → click → signup; free→Pro conversion; **distributor MRR & seats**;
NISM course enrollments/pass-rate; **AMC contracts & ACV**; dataset coverage (schemes with holdings,
periods captured); retention/NRR; CAC vs LTV per segment.

## 11. Risks & mitigations
- **Data-source fragility (WAF/format drift):** Playwright workers + adapters + monitoring + manual
  drop fallback; alert on parse failures.
- **Regulatory:** stay on the data/education side; disclaimers; register RA/RIA only if we deliberately
  add advice/ratings.
- **AMC pushback on benchmarking:** neutrality, "claim your profile", make them a customer not a foe.
- **Monetization (willingness to pay):** lead with must-buy certification + B2B tools, not retail paywall.
- **Content accuracy/AI errors:** human review + compliance sign-off gate before publish.
- **Category risk:** SIFs are new; if growth stalls, the education/content/data moat still has value and
  the platform can extend to adjacent products (PMS/AIF analytics).

## 12. "What else can we put here" — expansion backlog
Screener & smart alerts · portfolio **overlap/X-ray** across SIFs · **stock/sector crowding** (most-held
longs, most-crowded shorts) · net-exposure & long/short trends · **flows & AUM tracker** · NFO/launch
calendar · manager tracker (tenure, changes) · factsheet & document archive (searchable) · risk-band
tracker · **"Ask the data" AI chat** · compliant one-pager/pitch-deck generator · "SIF vs MF vs PMS/AIF"
explainers · WhatsApp/Telegram bot & newsletter · webinars/masterclasses · mobile app · white-label
widgets & API · verified AMC profiles · leaderboards/"category snapshot" (neutral) · distributor
lead/CRM-lite · glossary & academy · global hedge-fund/long-short education track · job board · events.

---

*This plan pairs with `README.md` (product docs) and `handover.md` (build state). It is a living
document — revise as the category, regulation, and traction evolve.*
