#!/usr/bin/env python3
"""
build_preview.py  --  Export the dashboard as ONE self-contained HTML file. stdlib only.

Takes a live payload, bakes it into the page, and writes a file that needs no server, no
network and no credentials -- openable from a phone, a share link, or a static host.

    python -m options_desk.build_preview --out desk-preview.html

By default it uses the synthetic provider, so the export is a demo of the interface rather
than anyone's market data. Point it at a real provider with --provider and it exports a frozen
snapshot of that instead; the page says which, and says it is frozen, because a dashboard that
looks live and is not is worse than no dashboard.
"""

import argparse
import datetime as dt
import json
import os
import sys
import threading

from . import config, providers, rules as rules_mod
from .server import DeskState, Worker

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "web", "index.html")


def build_payload(cfg, symbols, warmup=0, bar_interval="5m", ticks=12):
    """Run the desk far enough to have a session's worth of history, then snapshot it."""
    prov = providers.get(cfg.str("OPTIONS_PROVIDER"), cfg)
    # Advance the synthetic clock so the intraday chart shows a full session rather than the
    # three bars that exist a moment after start-up.
    for _ in range(warmup):
        if hasattr(prov, "_now"):
            prov._now()

    state = DeskState()
    worker = Worker(cfg, state, symbols, prov, prov,
                    rules_mod.build(rules_mod.default_specs("chain")
                                    + rules_mod.default_specs("bars")),
                    interval=1, bar_interval=bar_interval, stop=threading.Event())

    # Several ticks, not one: rules need history before they fire, so a single-tick export
    # shows an empty signals feed and an unpopulated bias -- an interface demo that fails to
    # demonstrate the interesting half.
    data, errors = {}, []
    for i in range(max(1, ticks)):
        errors = []
        for sym in symbols:
            try:
                data[sym] = worker._one(sym, errors)
            except Exception as e:                   # noqa: BLE001 - report, do not abort
                errors.append(f"{sym}: {type(e).__name__}: {e}")

    return {
        "status": "ok" if data else "error",
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "symbols": [s for s in symbols if s in data],
        "tick": 1,
        "providers": {"chain": prov.name, "bars": prov.name},
        "exchange": cfg.str("OPTIONS_EXCHANGE", "US"),
        "data": data,
        "errors": errors,
    }


def render_page(payload, note):
    """Inject the payload into the dashboard page as a frozen snapshot."""
    with open(PAGE, encoding="utf-8") as f:
        html = f.read()
    payload = dict(payload)
    payload["snapshot"] = note
    blob = json.dumps(payload, default=str, separators=(",", ":"))
    # Injected before the page script runs, so poll() takes the static branch on first call.
    inject = ("<script>window.__DESK_STATE__ = "
              + blob.replace("</", "<\\/") + ";</script>\n</head>")
    return html.replace("</head>", inject, 1)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="options_desk.build_preview",
        description="Export the dashboard as one self-contained HTML file.")
    p.add_argument("symbols", nargs="*", default=None,
                   help="underlyings (default: OPTIONS_UNDERLYINGS)")
    p.add_argument("--out", default="desk-preview.html",
                   help="self-contained page with the payload baked in")
    p.add_argument("--json-out",
                   help="also write the payload as standalone JSON (for a static host)")
    p.add_argument("--page-out",
                   help="also write the dashboard page that FETCHES that JSON")
    p.add_argument("--provider", help="override OPTIONS_PROVIDER")
    p.add_argument("--exchange", help="NSE | BSE | US")
    p.add_argument("--warmup", type=int, default=78,
                   help="synthetic clock ticks to advance before snapshotting")
    p.add_argument("--ticks", type=int, default=12,
                   help="engine ticks to run so the rules have history and can fire")
    p.add_argument("--note", help="text for the static-preview banner")
    a = p.parse_args(argv)

    over = {}
    if a.provider:
        over["OPTIONS_PROVIDER"] = a.provider
    if a.exchange:
        over["OPTIONS_EXCHANGE"] = a.exchange
    if a.provider and a.provider != "synthetic":
        over.setdefault("OPTIONS_SYNTH_STEP_S", "0")
    else:
        over.setdefault("OPTIONS_SYNTH_STEP_S", "300")
    cfg = config.load(overrides=over)

    symbols = [s.upper() for s in (a.symbols or cfg.list("OPTIONS_UNDERLYINGS", ["SPY"]))]
    payload = build_payload(cfg, symbols, warmup=a.warmup, ticks=a.ticks)

    provider = payload["providers"]["chain"]
    note = a.note or (
        "Generated market data — this is a demo of the interface, not real prices. "
        "Nothing here is tradeable."
        if provider == "synthetic" else
        f"Frozen snapshot from {provider}, taken {payload['generated']}. "
        "Not live — re-export to refresh.")

    payload_out = dict(payload)
    payload_out["snapshot"] = note

    if a.json_out:
        # Separate JSON + page: the page is cached hard, the data is refreshed on its own
        # schedule. Baking the payload in would mean redeploying the page for every tick.
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(payload_out, f, default=str, separators=(",", ":"))
        sys.stderr.write(f"[preview] {a.json_out}  "
                         f"{os.path.getsize(a.json_out)/1024:.0f} KB\n")
    if a.page_out:
        with open(PAGE, encoding="utf-8") as f:
            shell = f.read()
        with open(a.page_out, "w", encoding="utf-8") as f:
            f.write(shell)
        sys.stderr.write(f"[preview] {a.page_out}  "
                         f"{os.path.getsize(a.page_out)/1024:.0f} KB (fetches desk_data.json)\n")

    html = render_page(payload, note)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    size = os.path.getsize(a.out)
    sys.stderr.write(f"[preview] {a.out}  {size/1024:.0f} KB  "
                     f"provider={provider} symbols={','.join(payload['symbols'])}\n")
    if payload["errors"]:
        for e in payload["errors"]:
            sys.stderr.write(f"[preview] {e}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
