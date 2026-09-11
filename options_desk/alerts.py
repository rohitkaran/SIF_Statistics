#!/usr/bin/env python3
"""
alerts.py  --  Where fired signals go. stdlib only.

Sinks are deliberately dumb and independent: one failing sink (a dead webhook) must never
stop the others or kill the engine, so dispatch catches per-sink and keeps going.
"""

import json
import os
import sys
import urllib.error
import urllib.request

# ANSI, only when stderr is a real terminal -- piping to a file should stay plain text.
_COLOR = {"info": "\033[36m", "warn": "\033[33m", "alert": "\033[31m"}
_RESET = "\033[0m"


class Sink:
    name = "sink"

    def emit(self, signal):
        raise NotImplementedError

    def close(self):
        pass


class ConsoleSink(Sink):
    """Human-readable stream to stderr, so stdout stays free for piped data."""
    name = "console"

    def __init__(self, stream=None, color=None):
        self.stream = stream or sys.stderr
        self.color = self.stream.isatty() if color is None else color

    def emit(self, signal):
        line = signal.line()
        if self.color:
            line = f"{_COLOR.get(signal.severity, '')}{line}{_RESET}"
        self.stream.write(line + "\n")
        self.stream.flush()


class JsonlSink(Sink):
    """Append one JSON object per signal -- the durable audit trail of what fired and when."""
    name = "jsonl"

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")

    def emit(self, signal):
        self._fh.write(json.dumps(signal.to_dict(), ensure_ascii=False) + "\n")
        self._fh.flush()          # flush per signal: a crashed desk must not lose its log

    def close(self):
        self._fh.close()


class WebhookSink(Sink):
    """
    POST each signal as JSON (Slack/Discord/ntfy compatible).

    Fire-and-forget with a short timeout: an alert is worthless if delivering it stalls the
    tick that produced it.
    """
    name = "webhook"

    def __init__(self, url, timeout=5):
        self.url = url
        self.timeout = timeout

    def emit(self, signal):
        payload = dict(signal.to_dict())
        payload["text"] = signal.line()          # Slack/Discord render `text` directly
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "options-desk/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout):
                pass
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Host only -- webhook URLs commonly embed a token in the path.
            sys.stderr.write(f"[alerts] webhook delivery failed: {type(e).__name__}\n")


class Dispatcher:
    """Fan one signal out to every sink, isolating failures."""

    def __init__(self, sinks=None):
        self.sinks = list(sinks or [])
        self.count = 0

    def add(self, sink):
        self.sinks.append(sink)
        return self

    def emit(self, signal):
        self.count += 1
        for s in self.sinks:
            try:
                s.emit(signal)
            except Exception as e:                # noqa: BLE001 - a sink must not kill the desk
                sys.stderr.write(f"[alerts] sink {s.name} failed: {type(e).__name__}: {e}\n")

    def emit_all(self, signals):
        for s in signals:
            self.emit(s)

    def close(self):
        for s in self.sinks:
            try:
                s.close()
            except Exception:                     # noqa: BLE001
                pass


def build(cfg, console=True, jsonl_path=None, webhook=None):
    """Assemble the dispatcher the CLI uses, from config + explicit overrides."""
    d = Dispatcher()
    if console:
        d.add(ConsoleSink())
    if jsonl_path:
        d.add(JsonlSink(jsonl_path))
    hook = webhook or cfg.str("OPTIONS_ALERT_WEBHOOK")
    if hook:
        d.add(WebhookSink(hook))
    return d
