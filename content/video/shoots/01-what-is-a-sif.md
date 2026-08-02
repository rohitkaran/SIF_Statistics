# SHOOT PACK — Video #1: "What is a SIF?"

**Format:** 9:16 vertical, 1080×1920, **~40s** · **Goal:** educational explainer (no fund names) ·
**Platforms:** YouTube Shorts + Instagram Reels + LinkedIn.

Everything you need is below. Do the steps in order — ~30–45 min total.

---

## A. Locked script (timed)

| Time | Voice-over | On-screen caption | Higgsfield scene |
|---|---|---|---|
| 0–4s | "There's a new way to invest in India — and it can do something your mutual fund can't." | **A new way to invest 🇮🇳** | S1 |
| 4–11s | "Meet the SIF — a Specialized Investment Fund. Think of it as your mutual fund's *advanced mode*." | **Meet the SIF** → **Your fund's advanced mode** | S2 |
| 11–19s | "Run by the same fund houses, under the same tight rules — but a SIF can also bet *against* stocks, not just buy them." | **It can go SHORT ↓** | S3 |
| 19–27s | "That means it can hedge — and aim to fall *less* when the market drops." | **Falls LESS when markets drop** | S4 |
| 27–34s | "The catch? It's built for informed investors — a ten-lakh-rupee minimum, and higher risk." | **₹10 lakh min · higher risk** | S5 |
| 34–40s | "Sitting between mutual funds and PMS, it's India's newest asset class. Learn the basics at SIFintel." | **India's newest asset class** → end card | S6 + end card |

**VO script (clean, for recording / AI voice — ~92 words):**
> There's a new way to invest in India — and it can do something your mutual fund can't. Meet the SIF, a
> Specialized Investment Fund. Think of it as your mutual fund's advanced mode. Run by the same fund
> houses, under the same tight rules — but a SIF can also bet against stocks, not just buy them. That
> means it can hedge, and aim to fall less when the market drops. The catch? It's built for informed
> investors — a ten-lakh-rupee minimum, and higher risk. Sitting between mutual funds and P-M-S, it's
> India's newest asset class. Learn the basics at SIFintel.

**Voice:** calm, confident Indian-English. Record on your phone (quiet room, mic close), **or** use
**ElevenLabs** (voice e.g. "Charlotte"/"Daniel", Stability ~50, Similarity ~75, Style ~0). Aim ~150 wpm.

---

## B. Generate the 6 clips in Higgsfield

**Settings:** 9:16 · 1080×1920 · ~5s each · slow, cinematic camera motion.
**Paste this STYLE line at the start of every prompt:**
> *Vertical 9:16, premium fintech, cinematic. Deep navy background (#0b1220) with an electric blue-to-
> teal-green gradient glow (#2f6fd6 → #17a67a → #22c88f). Sleek, minimal, glossy 3D, data-driven, soft
> depth of field, subtle grain. No text on screen.*

Then the scene:
- **S1 (hook):** Glowing particles swirl and coalesce into a sleek abstract emblem on the dark navy backdrop; slow push-in; a soft teal-green light pulse. Mysterious, high-tech.
- **S2 (upgrade):** A clean minimalist mobile investing app floating in space **transforms/upgrades** into a darker, more advanced trading terminal with more dials and glowing charts; smooth parallax push-in.
- **S3 (short):** A glossy 3D candlestick stock chart; one candle turns red and **falls**, and a glowing teal **downward arrow** lights up as a position profits from the fall; holographic close-up.
- **S4 (hedge):** Split-screen: on the left a jagged red market line **crashes down**; on the right a smoother line dips only slightly and **holds steady**; elegant, slow dolly.
- **S5 (₹10L):** A sleek minimalist glowing **threshold/gateway** in a dark premium space; sense of exclusivity and entry; slow push-in. *(leave the center clear — you'll overlay ₹10,00,000)*
- **S6 (end):** An elegant abstract **three-tier ladder** of glowing platforms rising left→right; the **middle** platform glows brightest; clean, premium, aspirational.

Export each clip; keep them named `s1.mp4 … s6.mp4` in order.

---

## C. Edit (CapCut recommended — free)
1. New project 9:16 → drop `s1…s6` on the timeline in order; trim so total ≈ 38–40s.
2. Add a subtle **whip/zoom transition** between clips.
3. **Voice-over:** import your VO (or record in-app); align to the beats in section A. Add light music
   from CapCut's library, **volume ~15%**, ducked under the voice.
4. **Captions:** use **Auto captions** for word-by-word VO text (Inter/bold, white, thick outline).
   Then add the **big beat captions** from `01-what-is-a-sif.srt` (import it) — large, centered, in the
   safe zone.
5. **Watermark:** export `brand/video/watermark.svg` → PNG (transparent), place small in the **bottom-
   left**, opacity ~85%, whole video.
6. **End card:** export `brand/video/endcard.svg` → PNG, add as the last **2 seconds** (34→40s) over S6.
7. **Export:** 1080×1920, 30fps, MP4, high quality. Save as `renders/01-what-is-a-sif.mp4`.

*(ffmpeg alternative: `content/video/VIDEO_PIPELINE.md` has stitch + watermark one-liners.)*

---

## D. Compliance check (must pass — see content/COMPLIANCE.md)
- [ ] No specific fund is named, shown, or ranked. ✅ (this script is fully generic)
- [ ] No return promises / "buy" / "best". ✅
- [ ] Disclaimer on the end card **and** in the caption. ✅ (below)
- [ ] A human watched it end-to-end and approved.

---

## E. Publish
**Title:** What is a SIF? India's new asset class explained #Shorts
**Description:**
> A Specialized Investment Fund (SIF) is SEBI's new category between mutual funds and PMS — it can hedge
> and short, with a ₹10 lakh minimum. Here's the 40-second explainer.
>
> Explore the data & learn more: https://www.sifintel.com/?utm_source=youtube&utm_medium=short&utm_campaign=what-is-a-sif
>
> Educational content, not investment advice. SIFintel is not a SEBI-registered adviser, research
> analyst, or distributor. SIFs carry high risk and a ₹10 lakh minimum. Read the scheme documents.
>
> #SIF #SpecializedInvestmentFund #InvestingIndia #MutualFunds #SIFintel

**Hashtags (IG/LinkedIn):** #SIF #SpecializedInvestmentFund #InvestingIndia #MutualFunds #PersonalFinanceIndia #SIFintel
**Thumbnail (optional):** dark navy bg, big **"WHAT IS A SIF?"**, the SIFintel star logo corner.

**Upload:**
- **Simplest:** upload the MP4 in the YouTube app / Instagram (Reel) / LinkedIn; paste title/description;
  keep the UTM link.
- **YouTube via script** (after the one-time OAuth in `publish/README.md`): copy the JSON below to
  `publish/metadata.json`, then `python publish/youtube_upload.py --metadata publish/metadata.json`
  (starts **private** — review, then make public).

```json
{
  "video": "renders/01-what-is-a-sif.mp4",
  "title": "What is a SIF? India's new asset class explained #Shorts",
  "description": "A Specialized Investment Fund (SIF) is SEBI's new category between mutual funds and PMS — it can hedge and short, with a ₹10 lakh minimum. Here's the 40-second explainer.\n\nExplore the data & learn more: https://www.sifintel.com/?utm_source=youtube&utm_medium=short&utm_campaign=what-is-a-sif\n\nEducational content, not investment advice. SIFintel is not a SEBI-registered adviser, research analyst, or distributor. SIFs carry high risk and a ₹10 lakh minimum. Read the scheme documents.\n\n#SIF #SpecializedInvestmentFund #InvestingIndia #MutualFunds #SIFintel",
  "tags": ["SIF","Specialized Investment Fund","SIF India","what is a SIF","investing india","mutual funds","long short","SIFintel"],
  "categoryId": "22",
  "privacyStatus": "private",
  "madeForKids": false
}
```

---
**When it's live**, log it (date · platform · link) and we go again with **E2/E3** from the series.
