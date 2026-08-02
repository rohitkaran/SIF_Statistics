# SIFintel — publishing (YouTube / Instagram / LinkedIn)

How to get videos live on each platform. **Manual uploads are the right way to start** — build the
API automation only once you're posting regularly. All three need *your* accounts + auth, so these are
one-time setups you do.

> ⚠️ Never commit secrets. `client_secret.json`, `token.json`, and `*token*` are git-ignored.

## Metadata
Copy `metadata.template.json` → `metadata.json` per video and fill it in. Always keep the **UTM link**
(`...sifintel.com/?utm_source=<platform>&utm_medium=short&utm_campaign=<slug>`) and the disclaimer.

## YouTube Shorts — semi-automated (script provided)
A vertical video **< 60s** is treated as a Short automatically (add `#Shorts` in the title/description to help).
1. **Google Cloud Console** → create/select a project → **APIs & Services → Library** → enable
   **"YouTube Data API v3"**.
2. **APIs & Services → OAuth consent screen** → External → add yourself as a **Test user**.
3. **Credentials → Create Credentials → OAuth client ID → Desktop app** → download JSON → save as
   `publish/client_secret.json`.
4. Run it:
   ```
   pip install -r publish/requirements.txt
   python publish/youtube_upload.py --metadata publish/metadata.json
   ```
   First run opens a browser to authorize and caches `publish/token.json`. Start with
   `"privacyStatus": "private"`, review on YouTube, then flip to public.
   **Quota:** an upload costs ~1600 units; the default 10,000/day ≈ **6 uploads/day** (request more if needed).

## Instagram Reels — Graph API (more involved; start manual)
Requirements: an **Instagram Business/Creator** account linked to a **Facebook Page**, a **Meta app**
with `instagram_content_publish` + `instagram_basic` (App Review), and a **long-lived token**.
Publishing is a 2-step flow and the **video must sit at a public URL** (host it on Cloudflare **R2** / S3):
1. `POST /{ig-user-id}/media` with `media_type=REELS`, `video_url=<public mp4>`, `caption=<text+tags>`
   → returns a creation container id.
2. Poll `GET /{container-id}?fields=status_code` until `FINISHED`, then
   `POST /{ig-user-id}/media_publish` with `creation_id=<container-id>`.
Until App Review is approved, **upload Reels manually in the app** — it's faster to start.

## LinkedIn — start manual
Native video posting needs an approved LinkedIn app with `w_member_social` and the Assets/Posts API
(register upload → upload bytes → create a post referencing the asset). For a founder account,
**posting manually** (or via a scheduler) is simpler until volume justifies the API.

## Easiest path for all three: a scheduler
**Buffer**, **Metricool**, or **Publer** connect YouTube + Instagram + LinkedIn and let you upload once,
caption per platform, and **schedule** — no API/OAuth work. Recommended until you're at daily volume;
then automate YouTube with the script above and Instagram via the Graph API.

## Cadence
Aim for **2–3 shorts/week** to start (Tue/Thu/Sat). Use `make_video_ideas.py` every Monday to fill the
queue. Log each post (date · topic · platform · views · link-clicks) and double down on what lands.
