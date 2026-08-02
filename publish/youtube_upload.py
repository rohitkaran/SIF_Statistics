#!/usr/bin/env python3
"""
youtube_upload.py  --  Upload a finished Short to YouTube via the YouTube Data API v3.

One-time setup (see publish/README.md): enable "YouTube Data API v3" in Google Cloud, create an
OAuth **Desktop** client, download the JSON as publish/client_secret.json. First run opens a browser
to authorize and caches publish/token.json.

Usage:
  pip install -r publish/requirements.txt
  python publish/youtube_upload.py --metadata publish/metadata.json
  # metadata.json points to the .mp4 and holds title/description/tags/privacy (see the template)

Start with "privacyStatus": "private" or "unlisted" to review on YouTube before going public.
"""

import argparse
import json
import os

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
HERE = os.path.dirname(os.path.abspath(__file__))


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token = os.path.join(HERE, "token.json")
    secret = os.path.join(HERE, "client_secret.json")
    creds = None
    if os.path.exists(token):
        creds = Credentials.from_authorized_user_file(token, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(secret):
                raise SystemExit("Missing publish/client_secret.json — see publish/README.md")
            creds = InstalledAppFlow.from_client_secrets_file(secret, SCOPES).run_local_server(port=0)
        with open(token, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload(meta):
    from googleapiclient.http import MediaFileUpload
    video = meta["video"] if os.path.isabs(meta["video"]) else os.path.join(os.getcwd(), meta["video"])
    if not os.path.exists(video):
        raise SystemExit(f"Video not found: {video}")
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "categoryId": str(meta.get("categoryId", "22")),
        },
        "status": {
            "privacyStatus": meta.get("privacyStatus", "private"),
            "selfDeclaredMadeForKids": bool(meta.get("madeForKids", False)),
        },
    }
    yt = get_service()
    media = MediaFileUpload(video, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    print(f"Uploading {os.path.basename(video)} …")
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%")
    vid = resp["id"]
    print(f"Done → https://youtu.be/{vid}  (status: {body['status']['privacyStatus']})")
    return vid


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--metadata", required=True, help="path to a metadata.json (see metadata.template.json)")
    a = p.parse_args()
    with open(a.metadata, encoding="utf-8") as f:
        upload(json.load(f))


if __name__ == "__main__":
    main()
