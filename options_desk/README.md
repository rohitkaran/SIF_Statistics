# options_desk

Real-time options data, signal rules, and replay backtesting. Python 3.9+, **standard library only** — no pip install required.

```bash
python -m options_desk watch SPY        # live ladder + signals, no credentials needed
```

---

## Why this is not a Rix Trade integration

You asked to connect this to **Rix Trade** (the platform behind your **Strix Options** account). I looked into it before writing any code, and it will not work as intended. Three findings, in order of importance:

1. **RixTrade describes itself as a *simulated* options trading platform.** Its own site title is "RixTrade | Simulated Options Trading Platform," and Strix Options is a prop-firm evaluation programme — you trade the firm's capital in a simulated account against real-time OPRA pricing, and the firm pays out a profit share. Orders are not routed to an exchange. A "real-time trading system" built against it would not be trading the real market.

2. **There is no public API.** No REST endpoints, no WebSocket feed, no developer documentation, and no SDK turned up anywhere. It is a browser/app terminal with no sanctioned programmatic access.

3. **Automating it with your login would put your account at risk.** Prop firms generally restrict automation, and driving their terminal with a scraper is the kind of thing that voids an evaluation and forfeits the fee. Strix's own published rules prohibit "automated scripts, bots, macros, or other programmatic means" in the context they document.

I could not read either site directly — both domains are blocked by this environment's network egress proxy — so points 1 and 3 come from search results and Strix's published rewards terms rather than from the terms of service themselves. **Worth confirming with Strix support before relying on it:** ask whether they offer any API or sanctioned automation for funded accounts. If they say yes, adding an adapter here is a single file (see *Adding a provider*).

**So this package does the part that is actually buildable:** live chains, greeks, real-time signals, and backtesting against a documented market-data vendor. It is **data and signals only** — nothing here places, routes, modifies, or cancels an order, and no adapter holds brokerage trading credentials. You act on the signals yourself, in whatever platform you trade.

---

## Quick start

```bash
# 1. Runs immediately with generated data -- no key needed.
python -m options_desk watch SPY

# 2. Point it at a real feed.
cp .env.example .env && chmod 600 .env      # then fill in a key
python -m options_desk config               # check what resolved (secrets redacted)
python -m options_desk watch SPY QQQ

# 3. Capture a session, then test your rules against it.
python -m options_desk record SPY --hours 6
python -m options_desk backtest --symbol SPY
```

## Commands

| Command | What it does |
|---|---|
| `providers` | List data adapters and the credentials each needs |
| `config` | Show resolved settings, secrets redacted |
| `rules` | List rule types and the active rule set |
| `chain SPY` | Print one chain snapshot (`--json` for raw) |
| `watch [SYMS]` | Live ladder + signals (`--record` to capture at the same time) |
| `record [SYMS]` | Headless capture for backtesting (`--hours N`) |
| `data` | Summarise what has been recorded |
| `backtest` | Replay recordings through the rules and score them |

## Data providers

| Provider | Credentials | Notes |
|---|---|---|
| `synthetic` | none | Generated data. Default, so everything runs before you have a key. **Never trade off it.** |
| `polygon` | `POLYGON_API_KEY` | Real-time OPRA chains. Free tier omits NBBO — the desk falls back to daily closes and warns once. |
| `tradier` | `TRADIER_ACCESS_TOKEN`, `TRADIER_ENV` | `sandbox` is ~15 min delayed; `production` needs a funded brokerage token. |

## Signal rules

Rules are **data, not code** — change strategy by editing config, not Python:

```json
[
  {"type": "iv_spike",      "window_s": 300, "threshold": 0.02, "severity": "alert"},
  {"type": "spot_move",     "window_s": 300, "threshold": 0.004},
  {"type": "credit_target", "delta": 0.20, "right": "P", "min_credit": 0.80, "min_oi": 250}
]
```

```bash
python -m options_desk watch SPY --rules my_rules.json
```

| Type | Fires when |
|---|---|
| `spot_move` | Underlying moves more than `threshold` (fraction) over `window_s` |
| `iv_spike` | ATM IV moves more than `threshold` **vol points** over `window_s` |
| `iv_rank` | ATM IV sits in the top/bottom `threshold` of its retained range |
| `skew_shift` | 25-delta put/call skew moves more than `threshold` vol points |
| `credit_target` | A liquid contract at the target delta offers at least `min_credit` |

Every rule takes `severity` (`info`/`warn`/`alert`), `cooldown_s`, and `symbols` (empty = all).

Alerts go to the console, and optionally to a JSONL audit log (`--alert-log`) and a webhook (`--webhook`, Slack/Discord/ntfy compatible).

## Backtesting

`record` captures every chain snapshot to gzipped JSONL. `backtest` replays those through **the same `Engine` and the same rule objects** the live desk uses — cooldowns key off snapshot timestamps, never wall clock, so replay reproduces the live run exactly.

Scoring reports what the underlying and ATM vol did at fixed horizons after each signal:

```
credit_target  --  fired 49x
    +  60s  n=49   mean   -0.11bp  median   -0.31bp  |move|   4.63bp  up  49.0%  iv +0.08pts
    + 300s  n=48   mean   +0.96bp  median   +2.42bp  |move|  12.08bp  up  52.1%  iv -0.04pts
```

**This is not a P&L.** No fills, slippage, assignment, or margin are modelled. It answers one question — is a rule picking up anything, or firing on noise? — which is what you need when tuning thresholds.

Testing rules without waiting for a real session:

```bash
OPTIONS_SYNTH_STEP_S=60 python -m options_desk record SPY --interval 0 --max-ticks 400
python -m options_desk backtest --symbol SPY
```

## Design notes

- **Greeks are always computed locally**, never copied from the vendor. Feeds are inconsistent about which contracts carry greeks, and the engine needs them on all of them. Vendor IV is kept in `vendor_iv` as a cross-check.
- **IV comes from the OTM side of each strike.** A deep-ITM contract is nearly all intrinsic, so a penny of quote noise can put it below the model floor and make it unsolvable. Its counterpart is deep OTM, all time value, and solves cleanly — and by put-call parity they share one vol.
- **TLS verification stays on** in `providers/_http.py`. Other fetchers in this repo relax it for public data; these calls carry API keys, so relaxing it would be a credential-disclosure bug.
- **A failure never takes down the desk.** A bad tick, a broken rule, or a dead webhook is logged and skipped.

## Adding a provider

Subclass `Provider`, implement `snapshot()`, add one line to `providers/__init__.py`. `stream()` defaults to polling `snapshot()`, so a new adapter is one method. Everything downstream is written against `ChainSnapshot`, never a vendor payload.

## Tests

```bash
python -m unittest discover -s tests -v      # 53 tests, no network, no credentials
```

Vendor adapters are tested against captured payload shapes with HTTP patched out, so parsing is covered in CI with no key and no egress.
