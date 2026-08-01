# SIFintel — Brand guide

**Name:** SIFintel · **Domain:** sifintel.com · **One-liner:** *Intelligence on India's Specialized
Investment Funds.* · **Tagline:** *Decode the strategy behind the returns.*

The name = **SIF + intel**. Always written **SIFintel** (one word, capital S-I-F, lowercase "intel").
Never "Sifintel", "SIF Intel", "SIF-intel", or "SIFINTEL".

## Logo
| Asset | File | Use |
|---|---|---|
| Mark (app tile) | `logo-mark.svg` | favicon, avatar, app icon, small spaces |
| Wordmark (light bg) | `logo-wordmark.svg` | site header, docs, decks on white |
| Wordmark (dark bg) | `logo-wordmark-dark.svg` | dark UI, video, social |
| Favicon | `../favicon.svg` | browser tab |
| Social card | `og-image.svg` | export to `og-image.png` (1200×630) for OG/Twitter |

**The mark** is a bold **rising-trend arrow** in the bright electric gradient (with a soft glow) — an
"up and to the right" growth signal that reads as *strength and momentum*, paired with the wordmark for
the *intelligence* (SIF + intel). Full tagline lockup: `logo-lockup.svg`.

**Clear space:** keep padding ≥ the height of the tile's corner radius around the logo. **Min size:**
mark 24 px; wordmark 96 px wide. Don't recolor, stretch, rotate, add shadows, or place the light
wordmark on a busy/light photo (use the dark-bg version or the mark on a solid tile).

## Colour
| Token | Hex | Use |
|---|---|---|
| Indigo (primary) | `#5b5bf0` | primary brand, links, CTAs |
| Violet | `#8b5cf6` | gradient mid |
| Teal (accent) | `#0e9aa7` / dark `#3fd0c9` | accents, "intel" highlight |
| Ink | `#1c2338` | text on light |
| Paper | `#eef1fb` / panel `#ffffff` | light backgrounds |
| Midnight | `#0d1014` / panel `#141a21` | dark backgrounds |
| Positive / Negative | `#12a150` / `#e5484d` | up / down returns |

**Signature gradient** (logo, accent bar, headings): `#5b5bf0 → #8b5cf6 → #0e9aa7` (135°).

## Typography
- **Inter** (700/800 for headings, 400/500/600 for UI) — brand & product sans.
- **IBM Plex Mono** — all numbers/data (tabular lining), and code/URLs.

## Voice & tone
Clear, sharp, trustworthy — *analyst who explains simply*. Plain English over jargon; when we use a
term (Sharpe, capture, long-short) we define it. Never hype, never a "buy" call. Always attribute data
to its source and show the "as-of" date. Standard footer on public content: **"Educational, not
investment advice. SIFs carry high risk and a ₹10 lakh minimum. Read scheme documents."**

## Exporting the social PNG
`og-image.svg` is the master. Export a 1200×630 PNG named `og-image.png` (any of):
`npx svgexport brand/og-image.svg brand/og-image.png 1200:630` · Inkscape/Figma export · or open the
SVG in a browser at 1200×630 and screenshot. The page already references `brand/og-image.png`.
