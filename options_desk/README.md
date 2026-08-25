# options_desk

Real-time market data, signal rules, and replay backtesting. Python 3.9+, **standard library only** — no pip install required.

One engine, three ways in:

```bash
python -m options_desk serve SPY QQQ --open               # web dashboard (start here)
python -m options_desk watch SPY                          # terminal: chains, greeks, IV signals
python -m options_desk scalp RELIANCE.NS --exchange NSE   # terminal: pivots, CPR, VWAP
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

## The dashboard

```bash
python -m options_desk serve SPY QQQ --open
```

Serves a single self-contained page on `http://127.0.0.1:8787/`. It runs **on your machine**,
against your credentials — nothing is hosted, and no market data or key leaves the box. Binds
to loopback by default; `--host` overrides it and warns.

### On your phone, over Tailscale

```bash
python -m options_desk serve SPY QQQ --tailscale
```

This finds the machine's own tailnet address (`tailscale ip -4`, falling back to reading the
interface list) and binds there, then prints the URL to open on your phone. Tailscale must be
connected on the phone too.

The page is built for it: it stacks to one column, charts respond to touch (tap to inspect,
tap elsewhere to dismiss — there is no hover on a phone), tap targets are thumb-sized, it
respects notch and home-indicator safe areas, and **polling stops whenever the page is
hidden**, so a backgrounded tab does not sit there pulling a 50KB payload every three seconds
all afternoon. On iOS, Share → Add to Home Screen gives it a standalone window.

**The dashboard has no login, and that is deliberate.** On a tailnet the authentication has
already happened at the network layer — only devices you enrolled can route to the address at
all — and a password on a page you open twenty times a session adds friction without adding
protection. The corollary is that *where it binds is the entire security boundary*:

| Bind | Reachable by | How |
|---|---|---|
| `127.0.0.1` | this machine only | default |
| `100.64.0.0/10` | every device on your tailnet | `--tailscale` |
| `0.0.0.0` | **every network you join**, café wifi included | `--host 0.0.0.0` — warned, never chosen for you |

Two things to avoid:

- **Never `tailscale funnel` this port.** Funnel publishes to the open internet; Serve and a
  plain tailnet bind do not. A funnelled dashboard with no login is world-readable.
- If `--tailscale` cannot find an address it **fails with instructions** rather than quietly
  falling back to a wider bind.

### Not opening on the phone?

```bash
python -m options_desk doctor
```

"It doesn't open" has several causes that look identical from the phone — the desk bound to
loopback, Tailscale down on one end, a host firewall, the wrong port, or the browser never
issuing the request at all. `doctor` checks each from the serving machine and names the fix,
then prints the exact URL to open.

Working through it by hand, in the order things actually go wrong:

1. **Is it bound to the tailnet at all?** Plain `serve` binds to `127.0.0.1`, which no other
   device can reach. The startup line says which; you want `--tailscale`.
2. **Is Tailscale connected on the phone?** Look for the VPN key icon, and check the phone
   appears in `tailscale status` on the desktop.
3. **Type the scheme.** `http://100.x.y.z:8787/` — without `http://`, Chrome's omnibox may
   treat `100.x.y.z:8787` as a search rather than an address.
4. **Host firewall.** macOS prompts per-application; Windows Defender prompts once and
   remembers a dismissal; Linux may have `ufw` active. `doctor` prints the right incantation
   for your OS.

**If Chrome specifically objects to the plain-HTTP address, stop fighting it and use HTTPS:**

```bash
tailscale serve --bg 8787          # desk stays on its default loopback bind
```

That publishes it at `https://<machine>.<tailnet>.ts.net` with a real certificate, still
tailnet-only. It removes the whole category at once — no HTTPS-First warning, no mixed-content
question, no local-network permission prompt, and a hostname the omnibox always treats as a
URL. Chrome documents an HTTPS-First exemption for RFC1918 addresses (`192.168.x`, `10.x`,
`172.16–31.x`), but Tailscale hands out `100.64.0.0/10` **CGNAT** addresses, which are not
RFC1918 — I could not confirm Chrome treats them the same way, so the certificate-backed route
is the reliable one.

Still: `tailscale serve` is tailnet-only and fine. **`tailscale funnel` is not** — that
publishes to the open internet, and this dashboard has no login.

What's on it, and why each panel earns its place:

| Panel | What it tells you |
|---|---|
| **Stat row** | Price vs previous close, VWAP + z-score, CPR position, ATM IV, expected move, ATM straddle, max pain, put/call ratio, relative volume |
| **Intraday chart** | Price and VWAP on one axis, VWAP ±1σ/±2σ envelope, the CPR band, and every pivot near the day's range |
| **Long / short read** | A weighted score with **every component shown** — CPR position, VWAP side, VWAP stretch, move vs previous close, 25d skew, PCR |
| **Levels ladder** | Every level price-sorted with spot slotted in, nearest one highlighted |
| **Open interest by strike** | Back-to-back calls/puts — the walls that act like pivots |
| **IV smile** | Call and put IV by strike; the shape *is* your skew |
| **Option chain** | Bid/ask/IV/Δ/OI/volume both sides, ATM highlighted, OI magnitude bars inline |
| **Signals** | Fired rules, newest first |

Beyond what you asked for, four reads I'd want on screen:

- **Expected move** — two estimates: the ATM straddle (what the move actually costs) and
  `spot × IV × √T` (the model's 1σ). When the straddle is much richer than the sigma
  estimate, the market is paying for an event plain vol doesn't capture. Also the fastest
  sanity check on a scalp target: if your CPR target sits outside the day's expected move,
  you are counting on an outlier.
- **Max pain** — where the most open contracts expire worthless. One crowded reference point,
  not a forecast; the pull is weak until the last day or two.
- **Put/call ratio** on both OI and volume. They diverge when a crowded book starts unwinding,
  which is the part worth noticing.
- **OI walls** — the biggest call/put OI strikes, shown next to the pivots because they act
  the same way and deserve one mental model, not two.

Use a different feed for each side when it helps — Tradier chains with Yahoo bars, say:

```bash
python -m options_desk serve RELIANCE.NS --exchange NSE --bar-provider yahoo
```

> **On the long/short read:** it is a weighted sum of readings already on the screen, with the
> weights chosen by hand. It is not backtested as a strategy, has no edge of its own, and
> ignores spread, slippage, position size and risk. Its components are all displayed precisely
> so you can disagree with it. Treat it as a summary, never as a trigger.

> **NSE options:** the bundled chain adapters (Polygon, Tradier) cover **US options via OPRA**.
> For NSE option chains you need an Indian broker API — Zerodha Kite, Upstox, Dhan, Fyers or
> Angel One SmartAPI. That is one adapter file (see *Adding a provider*); the intraday side
> already works for NSE today through the Yahoo adapter.

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
| `serve [SYMS]` | **Local web dashboard** — chain, levels, analytics, signals (`--tailscale` for phone access) |
| `doctor` | Diagnose why the dashboard is not reachable from another device |
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
python -m unittest discover -s tests -v      # 153 tests, no network, no credentials
```

Vendor adapters are tested against captured payload shapes with HTTP patched out. Every scalping rule is tested twice — once on data that must trigger it, once on data that must not. The dashboard's HTTP layer is tested against a real server on an ephemeral loopback port.

The page was rendered and inspected in light, dark, 430px and an emulated touch phone
(390×844, `has_touch`): zero horizontal overflow, no console errors, no tap target under 30px,
tap-to-inspect latches and dismisses correctly, and polling verifiably stops while hidden and
resumes on return. Its categorical palette passes the colourblind-separation and
contrast gates in both modes. Direction is never carried by colour alone — every bullish or
bearish mark ships an arrow and a word, and the bull/bear pair is blue/red rather than the
conventional green/red, which is precisely the red-green confusion case.
