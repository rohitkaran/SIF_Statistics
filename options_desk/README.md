# options_desk

Real-time market data, signal rules, and replay backtesting. Python 3.9+, **standard library only** — no pip install required.

Two sides, one engine:

```bash
python -m options_desk watch SPY                          # option chains, greeks, IV signals
python -m options_desk scalp RELIANCE.NS --exchange NSE   # pivots, CPR, VWAP scalping signals
```

Both run with **no credentials** on a synthetic feed. The package keeps its original name; the scalping side works on any stock, on NSE/BSE or US.

---

## Why this is not a Rix Trade integration

You asked to connect this to **Rix Trade** (the platform behind your **Strix Options** account). I looked into it before writing any code, and it will not work as intended:

1. **RixTrade describes itself as a *simulated* options trading platform.** Its own site title is "RixTrade | Simulated Options Trading Platform," and Strix Options is a prop-firm evaluation — you trade the firm's capital in a simulated account against real-time OPRA pricing. Orders are not routed to an exchange.
2. **There is no public API.** No REST endpoints, no WebSocket feed, no developer documentation, no SDK.
3. **Automating it with your login would risk the account.** Strix's published rules prohibit "automated scripts, bots, macros, or other programmatic means."

I could not read either site directly — both domains are blocked by this environment's network egress proxy — so points 1 and 3 come from search results and Strix's published rewards terms rather than the terms of service themselves. **Worth confirming with Strix support** before relying on it.

**So this package does the part that is actually buildable.** It is **data and signals only** — nothing here places, routes, modifies, or cancels an order, and no adapter holds brokerage trading credentials. You act on the signals yourself, in whatever platform you trade.

---

## Quick start

```bash
# Runs immediately with generated data -- no key needed.
python -m options_desk watch SPY                          # options side
python -m options_desk levels SPY                         # one-shot pivots/CPR/VWAP
python -m options_desk scalp SPY                          # live scalping dashboard

# Point it at a real feed.
cp .env.example .env && chmod 600 .env
python -m options_desk config                             # check what resolved (redacted)

# Capture a session, then test your rules against it.
python -m options_desk scalp SPY --record --hours 6
python -m options_desk backtest --symbol SPY
```

## Commands

| Command | What it does |
|---|---|
| `providers` | List adapters and the credentials each needs |
| `config` | Show resolved settings, secrets redacted |
| `rules [--kind bars]` | List rule types and the active set |
| `chain SPY` | One option chain snapshot (`--json` for raw) |
| `watch [SYMS]` | Live option ladder + IV/skew signals |
| `levels SYM` | One-shot pivots / CPR / VWAP ladder |
| `scalp [SYMS]` | Live intraday levels dashboard + scalping signals |
| `record [SYMS]` | Headless chain capture |
| `data` | Summarise what has been recorded |
| `backtest` | Replay recordings through the rules and score them |

## Data providers

| Provider | Credentials | Chains | Bars | Notes |
|---|---|:--:|:--:|---|
| `synthetic` | none | ✓ | ✓ | Generated data. Default, so everything runs before you have a key. **Never trade off it.** |
| `polygon` | `POLYGON_API_KEY` | ✓ | ✓ | Real-time OPRA chains + aggregates. Free tier omits NBBO — falls back to daily closes and warns once. |
| `tradier` | `TRADIER_ACCESS_TOKEN`, `TRADIER_ENV` | ✓ | ✓ | `sandbox` is ~15 min delayed; `production` needs a funded brokerage token. |
| `yahoo` | none | — | ✓ | **Only bundled adapter covering NSE/BSE** (`RELIANCE.NS`). Delayed, undocumented, no SLA — convenience, not dependability. |

> The Yahoo adapter is parser-tested against captured payloads but **was not verified against the live endpoint**, because Yahoo is blocked by this environment's egress proxy. Sanity-check its first output against your broker's chart before trusting it.

---

## Intraday scalping: pivots, CPR, VWAP

`scalp` computes three level sets and watches price against them.

**Floor-trader pivots**, from the previous session's H/L/C:

```
P  = (H + L + C) / 3
R1 = 2P - L        S1 = 2P - H
R2 = P + (H - L)   S2 = P - (H - L)
R3 = H + 2(P - L)  S3 = L - 2(H - P)
```

**Central Pivot Range**:

```
Pivot = (H + L + C) / 3
BC    = (H + L) / 2
TC    = (Pivot - BC) + Pivot          [= 2*Pivot - BC]
```

TC computes *below* BC whenever the close sits under the range midpoint; the two are relabelled so TC is always the top. CPR width is reported as a fraction of the pivot (`width_pct`) so narrowness is comparable across a ₹300 stock and a 25,000 index. Narrow CPR ⇒ trending day; wide CPR ⇒ range day.

**VWAP**, anchored to the session open and reset on the exchange-local date, with volume-weighted standard-deviation bands. Extended-hours bars are excluded — thin pre-market prints carry real volume weight and would drag the anchor.

### Scalping rules

| Type | Fires when |
|---|---|
| `narrow_cpr` | CPR width ≤ `threshold_pct` of the pivot — trending-day setup. Once per session. |
| `cpr_breakout` | Closed outside TC/BC having been inside, optionally gated on `min_rvol` and `max_width_pct` |
| `cpr_reject` | Pierced TC/BC intrabar but closed back inside, leaving a wick ≥ `min_wick_frac` of the range |
| `vwap_cross` | Price reclaimed or lost session VWAP, optionally gated on `min_rvol` |
| `vwap_band` | Price stretched ≥ `threshold` σ from VWAP — mean-reversion fade |
| `confluence` | A pivot/CPR level sits on VWAP **and** price is there — the highest-conviction zone |
| `level_test` | Price reached any named level (`P`, `R1`–`R3`, `S1`–`S3`, `TC`, `BC`, `PDH`, `PDL`, `PDC`) |

See `scalp.example.json` for a documented starting set:

```bash
python -m options_desk --rules options_desk/scalp.example.json scalp RELIANCE.NS --exchange NSE
```

> **`OPTIONS_EXCHANGE` matters.** It sets regular trading hours and the VWAP anchor (`NSE`/`BSE` = 09:15–15:30 IST, `US` = 09:30–16:00 ET). Set it wrong and VWAP anchors to the wrong open, so every derived level is wrong.

### Options rules

| Type | Fires when |
|---|---|
| `spot_move` | Underlying moves more than `threshold` (fraction) over `window_s` |
| `iv_spike` | ATM IV moves more than `threshold` **vol points** over `window_s` |
| `iv_rank` | ATM IV in the top/bottom `threshold` of its retained range |
| `skew_shift` | 25-delta put/call skew moves more than `threshold` vol points |
| `credit_target` | A liquid contract at the target delta offers at least `min_credit` |

Every rule takes `severity` (`info`/`warn`/`alert`), `cooldown_s`, and `symbols` (empty = all). Alerts go to the console, and optionally to a JSONL audit log (`--alert-log`) and a webhook (`--webhook`).

---

## Backtesting

`--record` captures every snapshot to gzipped JSONL. `backtest` replays those through **the same `Engine` and the same rule objects** the live desk uses — cooldowns key off snapshot timestamps, never wall clock, so replay reproduces the live run exactly. It auto-detects whether a recording holds chains or bars and picks the matching rule set.

```
confluence  --  fired 4x
    + 300s  n=3   mean  -18.92bp  median  -10.87bp  |move|  31.26bp  up  33.3%  z -1.62
```

**This is not a P&L.** No fills, slippage, assignment, or margin are modelled — and for scalping, spread and slippage dominate the economics. It answers one question: is a rule picking up anything, or firing on noise?

Testing rules without waiting for a real session:

```bash
OPTIONS_SYNTH_STEP_S=300 python -m options_desk scalp SPY --poll 0 --max-ticks 150 --record
python -m options_desk backtest --symbol SPY
```

## Design notes

- **One engine, two snapshot kinds.** `ChainSnapshot` and `BarSnapshot` each declare what they contribute (`series_values`, `mark_price`, `vol_metric`), so history, alerting, recording, and backtesting are shared rather than duplicated.
- **Greeks and levels are always computed locally**, never copied from a vendor. Feeds disagree on anchoring and on whether extended-hours prints are included; a level you cannot reproduce is one you cannot trust.
- **IV comes from the OTM side of each strike.** A deep-ITM contract is nearly all intrinsic, so quote noise can push it below the model floor. Its counterpart is deep OTM and solves cleanly — and by put-call parity they share one vol.
- **Zero-volume bars give a VWAP of `None`**, not zero. Cash indices report no volume; there is no traded value to weight by, and saying so is better than inventing a number.
- **TLS verification stays on** in `providers/_http.py`. Other fetchers in this repo relax it for public data; these calls carry API keys.
- **A failure never takes down the desk.** A bad tick, a broken rule, or a dead webhook is logged and skipped.

## Adding a provider

Subclass `Provider` and implement `snapshot()` (chains) and/or `bars()` + `daily_bars()` (intraday), then add one line to `providers/__init__.py`. `bar_snapshot()` and `stream()`/`stream_bars()` are inherited, so levels and VWAP are derived identically for every adapter.

## Tests

```bash
python -m unittest discover -s tests -v      # 103 tests, no network, no credentials
```

Vendor adapters are tested against captured payload shapes with HTTP patched out. Every scalping rule is tested twice — once on data that must trigger it, once on data that must not.
