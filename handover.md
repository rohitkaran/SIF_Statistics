# SIF Statistics — handover / session notes

Living notes so any new session can pick up fast. Pairs with `README.md` (user-facing docs).

## What this is
**Brand: SIFintel** (target domain **sifintel.com**, .com available as of naming). A public terminal
for India's **Specialized Investment Funds (SIFs)**: live NAV-based risk/return metrics **plus** the
fund-house monthly **portfolio disclosures** (holdings, allocation, long/short, strategy, fund
managers). Differentiator = "intel": decode each fund's *strategy* from holdings/derivatives, not just
show numbers. Product/monetization strategy lives in **`BUSINESS_PLAN.md`**.

**To go live on sifintel.com:** buy the domain → add a `CNAME` file containing `sifintel.com` at the
repo root (or set it in Settings → Pages → custom domain) → at the DNS registrar add the 4 GitHub
Pages A records (185.199.108–111.153) for the apex and a CNAME `www → rohitkaran.github.io` → enable
"Enforce HTTPS". Then update the canonical/OG URLs (already point to sifintel.com).

**Coverage: 90 / 111 scheme codes have disclosed holdings.** Remaining gaps are genuine: qsif
Sector Rotation, DynaSIF Ex-Top (old `.xls`, only 2 of 3 sheets parse), Altiva Ex-Top, and the
newest funds not yet disclosed (Summit/Invesco, Infinity/Kotak, Prism/Jio — first bi-monthly not due).

- **Live:** https://rohitkaran.github.io/SIF_Statistics/  · repo `rohitkaran/SIF_Statistics`
- `sif-dashboard/` is its **own git root** (nested inside `C:\Users\rohit\ClaudeCodeTradingView`;
  the outer folder's unrelated `tv-backtest/` is not part of this repo).
- Pages was enabled once via `gh api repos/rohitkaran/SIF_Statistics/pages -X POST -f build_type=workflow`
  (the workflow token can't auto-create the Pages site on first run).

## Architecture
| File | Role |
|---|---|
| `fetch_amfi_sif.py` | NAV fetcher (Python **stdlib only**). AMFI JSON APIs → `nav_data.json`. Also `--serve` for local dev. |
| `fetch_sif_portfolios.py` | Portfolio fetcher (needs `requirements.txt`: openpyxl, pdfplumber). Registry-driven. → `portfolios/`. |
| `sif_dashboard.html` | Single-file dashboard. Metrics block is unit-tested (`==METRICS==` markers → run under node). |
| `portfolios/registry.json` | Per-AMC disclosure sources + brand/parent/managers/strategy/presentation. **Hand-maintained.** |
| `portfolios/index.json` | Generated: scheme-code → periods; AMC metadata block (with `nav_sif`). |
| `portfolios/raw/<amc>/<period>/…` | Original Excel/zip saved verbatim (committed). |
| `portfolios/data/<period>/<amc>__<fund>.json` | Normalised holdings (committed). |
| `.github/workflows/refresh-and-deploy.yml` | Daily NAV + monthly portfolio refresh → commits data back → deploys Pages. |

### Portfolio pipeline design
- **Discovery methods** (registry `discovery.method`): `http_listing` (regex a page for the file URL),
  `template` (build candidate month-end URLs from a strftime-ish template, keep the 200s), `manual`
  (pinned `{period,as_of,url}` list — for WAF/SPA/API-only sites).
- **Adapter** `sebi_xlsx`: parses the SEBI-standard monthly-portfolio layout every AMC uses; also
  unpacks a **zip-of-xlsx** bundle (ICICI). Tolerant of header variants (`% to Net Assets` /
  `% to AUM`, `Market Value (Rs. Lakhs)`, double-spaces). Reads the statement date from the sheet.
- **Scheme mapping** by **strategy token** (`hybrid` / `equitylong` / `extop` / `alloc` / `sector`) —
  robust to the wildly inconsistent fund-name lines. One disclosed fund fans out to its Direct/Regular
  × Growth/IDCW scheme codes.
- **Metadata**: AMC-level `managers/strategy/presentation`, with per-strategy `funds` overrides for
  multi-fund AMCs (dynasif, isif, arudha, titanium). Attached to each fund JSON at parse time.

## AMC coverage (as of 2026-08-01, 17 funds → 70/111 scheme codes)
Disclosed & wired (fetch works over plain HTTP unless noted):
apex, titanium(2), dynasif(2), arudha(2), **isif(4, zip)**, diviniti, magnum, arthaya, sapphire,
platinum(template), redhex(template), wsif(2).

Not disclosed yet (funds too new — registered with empty `discovery.files`, re-check dates in the
registry `_note`): **quant/qsif** (~Sep 2026), **summit/invesco**, **infinity/kotak**, **prism/jio**
(~10 Aug 2026). When they publish: add the URL/pattern, run `python fetch_sif_portfolios.py --amc <k>`,
and fill managers/strategy/presentation.

**WAF caveat:** several sites (Arudha F5, iSIF/Edelweiss Akamai, Franklin SPA, Kotak Radware) block
plain `curl`. They currently work from this dev machine but **may fail from the GitHub Actions runner**.
If a monthly CI run can't fetch them, the pinned `manual` URL + `--file` drop still work, or move those
to a browser-based fetch (see deferred). The workflow's portfolio step is best-effort (won't block deploy).

## Frontend features added this session
- New trailing-return columns: **2M, 3M, 6M, YTD, FYTD** (Indian FY, 1-Apr). In `periodReturns`.
- **Hover tooltips** (plain-English) on every metric header via the `HELP` map (`ⓘ` marker + `title`).
- **Dark-theme readability**: brighter ink, theme-aware color-band tints (`TINT_DARK`), re-render on toggle.
- **Row display**: brand + **parent AMC** (`amcMetaFor` via `index.amcs[*].nav_sif`) + `▣` badge when a
  portfolio exists.
- **Portfolio panel**: strategy + fund managers + presentation link; allocation now uses `cash_other`.
- **Mobile**: `@media (max-width:640px)` — sticky first column, compact spacing, static footer, bigger
  tap targets. (Couldn't emulate <640px in the test browser; rule verified parsed.)

## DONE since first handover
- **Up/Down capture vs NIFTY 50** — `fetch_benchmark.py` (stdlib, Yahoo `^NSEI`) → `benchmark_data.json`;
  `SIFMetrics.captureRatios(windowedSeries, benchByDate)` in the tested metrics block; two columns
  (Up Cap %, Dn Cap %) with tooltips; Dn Cap tinted green when low/negative. Workflow fetches it daily.
- **Compare chart** — checkbox on each row + a *Compare (n)* button opens a modal overlaying the ticked
  funds' NAVs (rebased to 100) vs NIFTY 50, with a metrics table. Vanilla SVG.
- **Altiva (Edelweiss)** added — it was missing from the registry (not old, just omitted). Akamai blocks
  curl, so its file was fetched via the browser (same-origin Blob download) and parsed with `--file`.
  Only Oct-2025 Hybrid is disclosed; manager left blank (only an unreliable aggregator name found —
  needs primary-source confirmation).
- **Mobile redesign** — control panel collapses behind a *☰ Filters* toggle (default collapsed on
  ≤820px via `header.collapsed`); table defaults to a **curated column set** (`MOBILE_HIDE` + `.mhide`,
  toggled by `#allcols` → `body.allcols`); first column pinned; pinch-zoom enabled; denser, polished.
- **Chart axes** — shared `axisSVG`/`niceTicks` helpers give NAV / underwater / compare charts labelled
  X (time) and Y (NAV ₹ / Drawdown % / rebased-NAV) axes with gridlines.
- Note: rows whose nav `sif` is already a full AMC name (Kotak/Mirae/Jio/HSBC/Franklin/Invesco) show a
  slightly redundant brand+parent (e.g. "Kotak Mahindra Mutual Fund" / "Kotak Mahindra"). Cosmetic;
  could special-case later. The SIF-branded ones (Apex SIF / Aditya Birla) read perfectly.

## Deferred / next session (with design notes)
1. **CI robustness / auto-discovery**: for WAF AMCs, add a headless-browser fetch (Playwright) step, or a
   per-AMC API call (SBI POST `ajaxcall/CMS/GetSIFSchemePortfolioSheets`, Union OData
   `/api/downloads/documents`, Invesco Sitefinity OData `/api/default/documents`). Also **auto-detect new
   funds**: the fetcher already enumerates schemes from `nav_data.json`, so new SIFs appear automatically
   in the table; extend discovery to log/attempt any registry AMC whose `files` are empty each run.
4. **Presentations → auto-strategy**: strategies are currently curated from each fund's
   presentation/ISID (see registry + `presentation` links). Could auto-summarise the PDF, but curated
   text is more reliable; keep curating as new funds launch.

## How to run / common tasks
```bash
# NAV (stdlib only)
python fetch_amfi_sif.py --from 2025-10-01 --to $(date +%F)
python fetch_amfi_sif.py --serve                # http://127.0.0.1:8765/sif_dashboard.html

# Portfolios
pip install -r requirements.txt
python fetch_sif_portfolios.py                  # all AMCs, latest disclosed period
python fetch_sif_portfolios.py --amc redhex --period 2026-06
python fetch_sif_portfolios.py --file mine.xlsx --amc <k> --period 2026-06   # manual drop
python fetch_sif_portfolios.py --list

# Metrics unit test (extract ==METRICS== block, run under node) — see prior session for the snippet.
```
**Add an AMC:** one entry in `registry.json` (site + discovery + nav_sif + managers/strategy). If the
file layout is new, add an adapter in `fetch_sif_portfolios.py` (`ADAPTERS`/`DISCOVERERS`).

## Gotchas
- Don't name a Python scratch file `inspect.py` (shadows stdlib, breaks openpyxl).
- Manual URLs with spaces are fine — `http_get` percent-encodes.
- WSIF/others without a date in the filename: period comes from the **sheet's** "as on" date; raw may
  land under a `raw/<amc>/unknown/` folder (cosmetic).
- `index.html` is generated by the workflow (`cp sif_dashboard.html index.html`) and git-ignored.
