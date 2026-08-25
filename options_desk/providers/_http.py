#!/usr/bin/env python3
"""
_http.py  --  Small JSON-over-HTTPS helper shared by the credentialed adapters. stdlib only.

Unlike the public-data fetchers elsewhere in this repo, these calls carry API keys, so TLS
verification is left ON. Never relax it here: an unverified socket that a bearer token is
written to is a credential-disclosure bug, not a convenience.
"""

import gzip
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import ProviderError

UA = "SIF-Statistics-options-desk/1.0 (+https://github.com/rohitkaran/sif_statistics)"
_CTX = ssl.create_default_context()          # verified; see module docstring

# Statuses worth retrying: rate limit + transient upstream failures.
_RETRY = {429, 500, 502, 503, 504}


def get_json(url, params=None, headers=None, timeout=30, retries=3, backoff=1.5):
    """
    GET a JSON document, retrying rate limits and 5xx with exponential backoff.

    Raises ProviderError with the vendor's own message on 4xx (auth/plan problems), because
    that text is nearly always the actionable part ("unknown symbol", "not entitled").
    """
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url = f"{url}?{urllib.parse.urlencode(clean)}"
    hdrs = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"}
    hdrs.update(headers or {})

    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = _body(e)
            if e.code in _RETRY and attempt < retries:
                # Honour Retry-After when the vendor sends one, else back off.
                wait = _retry_after(e) or backoff ** attempt
                time.sleep(min(wait, 30))
                last = e
                continue
            raise ProviderError(f"HTTP {e.code} from {_host(url)}: {body}") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < retries:
                time.sleep(backoff ** attempt)
                last = e
                continue
            raise ProviderError(f"{_host(url)} unreachable or malformed: {e}") from e
    raise ProviderError(f"{_host(url)} failed after {retries} retries: {last}")


def _retry_after(e):
    try:
        return float(e.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        return None


def _body(e, limit=300):
    try:
        raw = e.read().decode("utf-8", "replace").strip()
    except Exception:                      # noqa: BLE001 - error path must not raise
        return "(no body)"
    try:                                   # most vendors nest the useful text in JSON
        j = json.loads(raw)
        for k in ("message", "error", "detail", "fault", "errors"):
            if k in j:
                return str(j[k])[:limit]
    except json.JSONDecodeError:
        pass
    return raw[:limit] or "(empty body)"


def _host(url):
    """Host only -- keeps API keys out of exception text when they ride in the query string."""
    try:
        return urllib.parse.urlsplit(url).netloc or url
    except ValueError:
        return "remote"
