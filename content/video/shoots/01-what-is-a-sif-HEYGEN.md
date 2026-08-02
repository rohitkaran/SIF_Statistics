# HEYGEN PILOT — Video #1: "What is a SIF?" (AI presenter)

A small, fast test of HeyGen as your generator. **One avatar, ~45s, one topic.** ~20 min on the free
trial. Goal: decide if the avatar + voice + brand look good enough to scale the SIF Academy series.

**Format:** Portrait **9:16**, ~45s. **Style:** an AI "SIFintel host" speaking to camera + on-screen
text + an end card. Fully educational, no fund named (compliance-safe).

---

## The spoken script (paste verbatim — the avatar reads exactly this)
> There's a new way to invest in India — and it can do something your mutual fund can't.
> Meet the SIF: a Specialized Investment Fund. Think of it as your mutual fund's advanced mode.
> It's run by the same fund houses, under the same tight rules — but a SIF can also bet against
> stocks, not just buy them. That means it can hedge, and aim to fall less when the market drops.
> The catch? It's built for informed investors — a ten lakh rupee minimum, and higher risk.
> Sitting between mutual funds and P M S, it's India's newest asset class.
> Want to understand it properly? Learn the basics at SIFintel.

*(~85 words ≈ 40–45s. "P M S" spaced so it's read as letters. Keep it exactly — it's compliant.)*

## On-screen text overlays (add as text elements, timed to the lines)
1. **Meet the SIF** (as they say it)
2. **It can go SHORT ↓**
3. **Falls LESS when markets drop**
4. **₹10 lakh min · higher risk**
5. **India's newest asset class**

---

## Do this in HeyGen (step-by-step)
1. **heygen.com → sign up (free trial)** → **Create Video → Portrait (9:16)**.
2. **Avatar:** pick a clean, professional stock avatar (business attire, neutral background). *(Later you
   can make an "Instant Avatar" of yourself for a real founder face.)*
3. **Voice:** choose an **Indian-English** voice (HeyGen has several) — or connect your **ElevenLabs**
   voice for consistency with future videos. Aim for a calm, confident tone.
4. **Script:** paste the spoken script above into the script box for the avatar.
5. **Background:** set a solid **deep navy (#0b1220)** background (matches the brand), or a subtle dark
   gradient. Keep it clean — the avatar + text should pop.
6. **Captions:** turn on **auto-captions** (bold, white, high-contrast) — most Shorts are watched muted.
7. **Text overlays:** add the 5 text elements above, timed to the matching lines (Inter/bold, brand teal
   `#22c88f` accents).
8. **Watermark:** upload `brand/video/watermark.png` and place it small in the **bottom-left** for the
   whole video.
9. **End card:** add a final **2-second scene** and drop in `brand/video/endcard.png` (full-frame).
10. **Generate** → review the preview → **Export** as MP4 (1080×1920). Save to `renders/`.

*(Assets are in your repo: `sif-dashboard/brand/video/watermark.png` and `endcard.png`.)*

---

## Compliance check (must pass)
- [ ] No specific fund named/shown/ranked · [ ] no "buy/best/returns promise" · [ ] disclaimer on the
  end card + in the caption · [ ] you watched it fully and approved.

## Publish (reuse what we prepped)
Upload manually to YouTube Shorts / IG Reels / LinkedIn, or run
`python publish/youtube_upload.py --metadata publish/metadata.json` (starts private). Title/description/
tags are in `publish/metadata.json` and section E of `01-what-is-a-sif.md`.

---

## What to judge in this pilot
- Does the **avatar** look credible (not uncanny) for finance education?
- Is the **voice/pacing** natural? (tweak speed, add pauses/commas if rushed)
- Does the **brand** (navy bg, teal text, end card, watermark) look cohesive?
- Time & credits used → is it worth a subscription for 2–3 videos/week?

If yes → we lock HeyGen, set a reusable **brand template** there, and I'll wire `make_video_ideas.py`
to export HeyGen-ready scripts for the rest of the SIF Academy series (E2, E3, …), plus the optional
API automation with a human-approve gate.
