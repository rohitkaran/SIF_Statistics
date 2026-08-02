# SIFintel — video pipeline (Higgsfield → Reels/Shorts)

The repeatable process to turn data into short-form videos and publish them. Weekly cadence,
~30–60 min per finished video once you're in rhythm.

```
 (1) IDEAS ──► (2) SCRIPT ──► (3) GENERATE (Higgsfield) ──► (4) EDIT ──► (5) REVIEW ──► (6) PUBLISH ──► (7) MEASURE
   data          template        clips + VO                 captions      compliance     YT/IG/LI        loop back
```

## 1. Ideas
**Public content must be fund-agnostic & educational** (no SEBI licence needed — see
`content/COMPLIANCE.md`). Do **not** name/rank specific funds or their returns in public videos.
- **Primary source (safe):** `content/video/educational-series.md` — the "SIF Academy" series (what
  SIFs are, the 5 categories, and concepts). Plus the style kit + 3 scripts in `intro-sif-scripts.md`.
- **Internal only:** `python make_video_ideas.py --analytical` writes fund-specific data briefs to a
  **git-ignored** folder — for your own analysis / the neutral data tool, **never** for publishing
  without the appropriate SEBI registration.

## 2. Script
Use the idea's hook + 3 talking points → write a 20–45s VO (≈150 wpm). Keep captions ≤ 6 words.
Always end with the CTA + disclaimer. (You can hand the idea block to an LLM: *"Turn this into a 40s
Reels script with a hook, VO, and 6 on-screen captions, jargon-free."*)

## 3. Generate in Higgsfield
- **Format:** 9:16, 1080×1920. Paste the **style kit** (from `intro-sif-scripts.md`) into every scene.
- **One clip per beat** (5–7 beats, 3–6s each). Use the per-scene prompts from the script.
- Prefer consistent **camera motion** (slow push-in / parallax) and the **brand palette** for cohesion.
- Export each clip; keep them numbered in order.

## 4. Edit (stitch + VO + captions + brand)
Tool options: **CapCut** (free, great auto-captions), **Descript** or **Submagic** (fast captions), or
**ffmpeg** for power users.
- Stitch clips in order; one whip/gradient transition between beats.
- **Voice-over:** record yourself, or generate with **ElevenLabs / PlayHT** (calm Indian-English).
- **Captions:** auto-generate, then restyle — Inter Bold, high contrast, inside safe margins.
- **Brand:** persistent **watermark** (`brand/video/watermark.svg` → export PNG, bottom corner) +
  the **end card** (`brand/video/endcard.svg` → export a 2s PNG/MP4) on the last beat.
- **Music:** minimal, modern, licensed (YouTube Audio Library / Epidemic Sound). Duck under VO.
- Export **1080×1920 MP4, <60s** (Shorts/Reels cap).

Quick ffmpeg helpers:
```
# stitch (files list one per line: file 'clip1.mp4')
ffmpeg -f concat -safe 0 -i list.txt -c copy stitched.mp4
# burn a corner watermark
ffmpeg -i stitched.mp4 -i watermark.png -filter_complex "overlay=W-w-40:H-h-60" out.mp4
```

## 5. Review (compliance — do not skip)
- Every number matches the data + shows an "as-of". No "buy/sell"/return promises.
- Burn the disclaimer into the end card **and** repeat in the caption:
  *"Educational, not investment advice. SIFs carry high risk & a ₹10 lakh minimum. Read scheme docs."*
- A human signs off before publishing.

## 6. Publish
Fill `publish/metadata.template.json`, then post to **YouTube Shorts + Instagram Reels + LinkedIn**.
- **Manual** (simplest to start): upload in each app; paste title/description/tags; add the UTM link
  (`https://www.sifintel.com/?utm_source=youtube&utm_medium=short&utm_campaign=<slug>`).
- **Semi-automated:** `publish/youtube_upload.py` (YouTube Data API) — see `publish/README.md` for the
  one-time OAuth setup. Instagram Reels needs a Business/Creator account + Graph API (also in the README).
- **Scheduling:** Buffer / Metricool / Publer can cross-post + schedule all three from one place.

## 7. Measure & loop
Track reach → link clicks → signups (UTM). Feed the winning formats/topics back into step 1. Keep a
simple log (a row per video: date, topic, platform, views, clicks).

## Tooling cheat-sheet
| Step | Tools |
|---|---|
| Ideas | `make_video_ideas.py` (this repo) |
| Video gen | **Higgsfield** |
| Voice | ElevenLabs · PlayHT · your own mic |
| Captions/edit | CapCut · Submagic · Descript · ffmpeg |
| Music | YouTube Audio Library · Epidemic Sound |
| Scheduling | Buffer · Metricool · Publer |
| Upload API | YouTube Data API (`publish/`) · Instagram Graph API · LinkedIn API |
