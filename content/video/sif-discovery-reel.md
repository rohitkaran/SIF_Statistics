# "Nothing moved." — 28s discovery reel (Reels / Shorts)

One video, fund-agnostic and education-only, built to the pipeline in `VIDEO_PIPELINE.md`.
Format 9:16, 1080×1920, 28s. Style kit: `intro-sif-scripts.md`.

**Premise, checked against our own data before writing it.** NIFTY 50 went **24,891 → 24,252
between 25 Sep 2025 and 21 Aug 2026 — down 2.6%** over eleven months, and 7.9% below its
January peak (`benchmark_data.json`). The "market that went nowhere" is not a mood we are
asserting; it is the number, and the number opens the film.

---

## The one rule that keeps this out of the AI-slop bucket

**Generate the humans and the rooms. Never generate the screens.**

Every ugly AI ad fails in the same four places: garbled on-screen text, invented chart shapes,
melting UI, and hands doing fiddly things. All four are avoidable here, because every screen in
this film is a real asset we already own or can capture:

| On screen | Where it comes from |
|---|---|
| The flat NIFTY line | Rendered from `benchmark_data.json` — our real series |
| The TV news bar | A plain lower-third we typeset in the edit |
| Google Trends curve | A **real screenshot** of Trends for "SIF" (see compliance) |
| The SIFintel dashboard | Screen recording of sifintel.com |
| Logo / end card | `brand/video/endcard.svg`, `brand/video/watermark.svg` |

So Higgsfield generates **five live-action plates only**. Everything with a letter or a number
in it is composited in CapCut afterwards. That is the whole trick.

Three more shot rules for the same reason:
- **Nothing longer than 4 seconds.** Drift and morphing arrive around second five.
- **Faces at ¾ or from behind, mid-distance.** No close-up talking, no lip-sync.
- **No fingers on glass.** Hands hold or rest; the screen content is added later.

---

## Voice-over (28s ≈ 70 words, ~150 wpm)

> Eleven months.
> Your portfolio went... nowhere.
> Same funds. Same screen. Same number.
> *(beat — TV audio bleeds in)*
> Then you hear a word you don't know.
> S-I-F. Specialized Investment Fund.
> A new SEBI category — and it can do one thing your mutual fund can't: it can go short.
> Everyone's looking it up.
> We put every one of them in one place.
> SIFintel dot com.

**Tone:** calm, dry, a little weary at the top — then curious, never hyped. Indian-English.
This is a brand that explains things, not a tipster. The music does the lifting, not the voice.

---

## On-screen captions (≤ 6 words, burned in)

`11 months.` → `−2.6%` → `Nothing moved.` → `"...a new category called SIF"` →
`Specialized Investment Fund` → `It can go SHORT ↓` → `Everyone's searching it.` →
`Every SIF. One place.` → `SIFintel.com`

---

## Shot list

**SC1 · 0:00–0:04 · The number**
*Generated plate:* A dim living room before sunrise, curtains half drawn, a laptop open on a low
table throwing cold light onto a wall. Nobody in frame yet. Static tripod shot, shallow depth of
field, natural grain, muted greys and a single warm lamp.
*Composited:* the real NIFTY line, almost flat, drawn left to right across the laptop screen.
*Captions:* `11 months.` then `−2.6%`
*Sound:* room tone. A clock. No music yet.

**SC2 · 0:04–0:08 · The fatigue**
*Generated plate:* Man in his thirties, ¾ from behind, sitting on the sofa edge, elbows on knees,
scrolling a phone he is not really reading. Slow 10% push-in. Same cold light.
*Composited:* portfolio rows on the phone, unchanged.
*Caption:* `Nothing moved.`
*Sound:* first low synth note.

**SC3 · 0:08–0:13 · The interrupt**
*Generated plate:* His head turns toward an off-screen television; the TV's light shifts across
his face. Cut to the TV in the room, slightly out of focus, a business channel playing.
*Composited:* a clean lower-third news bar — the only text that matters in the film.
*Caption:* `"...a new category called SIF"`
*Sound:* TV chatter swells, then ducks. Music enters properly.

**SC4 · 0:13–0:18 · The look-up**
*Generated plate:* He sits up. Phone raised, face lit by it now, room still dark. Static shot,
small handheld float.
*Composited:* a real Google Trends screenshot for "SIF", the curve climbing.
*Captions:* `Specialized Investment Fund` → `Everyone's searching it.`
*Sound:* music opens up.

**SC5 · 0:18–0:24 · The answer**
*Generated plate:* Over-shoulder, the laptop again — but he is upright now, engaged, curtains
open, daylight arriving. The room has changed temperature: cold grey → warm.
*Composited:* a screen recording of the SIFintel dashboard, funds sorting and comparing.
*Captions:* `It can go SHORT ↓` → `Every SIF. One place.`
*Sound:* music at full.

**SC6 · 0:24–0:28 · End card**
*No generation.* `brand/video/endcard.svg`. Wordmark, `sifintel.com`, and the disclaimer line.
*Caption:* `SIFintel.com`
*Sound:* music resolves, one soft hit on the logo.

---

## Higgsfield prompts (paste with the style kit; plates only, no text in frame)

1. `Cinematic still-life interior, pre-dawn living room, half-drawn curtains, an open laptop on a low table casting cold blue light onto a bare wall, nobody in frame, static tripod shot, 35mm, shallow depth of field, natural film grain, muted grey-blue palette with one warm lamp, photorealistic, no text, no on-screen graphics, 9:16 vertical`
2. `A man in his thirties seen three-quarters from behind, sitting on the edge of a sofa, elbows on knees, holding a phone low, tired posture, dim pre-dawn room, very slow push-in, 50mm, shallow depth of field, photorealistic documentary look, natural grain, no text, blank phone screen, 9:16 vertical`
3. `The same man turning his head toward an off-screen television, flickering TV light moving across his face, dim room, static shot, 50mm, photorealistic, natural grain, no text, 9:16 vertical` — then — `A flat-screen television on a sideboard in a dim living room, slightly out of focus, a business news channel playing, warm screen glow, static shot, photorealistic, no legible text on screen, 9:16 vertical`
4. `The same man sitting upright on the sofa, holding a phone up so its light catches his face, room still dark, alert and curious expression, slight handheld float, 50mm, shallow depth of field, photorealistic, natural grain, blank phone screen, no text, 9:16 vertical`
5. `Over-the-shoulder shot of the same man now sitting upright at a low table with an open laptop, curtains open behind him, early morning daylight filling the room, warm tone, slow push-in, 35mm, photorealistic, natural grain, blank laptop screen, no text, 9:16 vertical`

> Every prompt says **no text** and **blank screen** deliberately. The screens get filled in the
> edit with the real thing. If a plate comes back with invented UI on the glass, regenerate it —
> do not try to cover it.

---

## Compliance (per `VIDEO_PIPELINE.md` §5 — do not skip)

- **Fund-agnostic.** No fund, AMC or return is named or shown. The dashboard recording must be
  scrolling/sorting, not resting on a leaderboard.
- **The −2.6% needs an as-of.** Burn `NIFTY 50 · 25 Sep 2025 – 21 Aug 2026` small under SC1.
  It is our own data and it must be attributable on screen.
- **The Google Trends shot must be REAL.** Capture it, date it, and only use it if the curve
  genuinely is climbing. A drawn-in rising line in a finance ad is the kind of thing that ends
  a data brand's credibility, and it is not worth four seconds of film. If the real trend is
  flat, cut SC4 to the dashboard instead and drop the "everyone's searching" line.
- **No promise, stated or implied.** "It can go short" is a mechanism, not an outcome. Nothing
  in the VO suggests SIFs did better than the flat market — the film never makes that comparison,
  and it must not be added in the caption either.
- **End card disclaimer, burned in:** *"Educational, not investment advice. SIFs carry high risk
  and a ₹10 lakh minimum. Read scheme documents."*
- Human sign-off before publishing.

## Publishing

UTM: `https://www.sifintel.com/?utm_source=instagram&utm_medium=reel&utm_campaign=nothing-moved`

**Caption (IG/YT):**
> Eleven months. The NIFTY 50 went from 24,891 to 24,252 — down 2.6%.
> Meanwhile a new SEBI fund category quietly appeared: the Specialized Investment Fund.
> Same fund houses you know, one extra ability — a SIF can go short, not just buy.
> We track every one of them in one place → sifintel.com
> Educational, not investment advice. SIFs carry high risk and a ₹10 lakh minimum. Read scheme documents.
