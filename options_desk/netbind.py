#!/usr/bin/env python3
"""
netbind.py  --  Working out what address to serve the dashboard on. stdlib only.

The dashboard has no login. That is a deliberate choice, not an oversight: on a tailnet the
authentication already happened at the network layer -- only devices you enrolled can route to
the address at all -- and bolting a password onto a page you open twenty times a session buys
nothing on top of that.

The corollary is that WHERE it binds is the entire security boundary, so this module exists to
make the safe choice easy and the unsafe one loud:

    127.0.0.1        this machine only                      (default)
    100.64.0.0/10    your tailnet -- phone, laptop, iPad    (--tailscale)
    0.0.0.0          every interface, including cafe wifi   (warned, never chosen for you)
"""

import ipaddress
import os
import re
import shutil
import subprocess
import sys

#: Tailscale hands out addresses from the CGNAT range. An address inside it is reachable only
#: by devices on the same tailnet.
TAILNET = ipaddress.ip_network("100.64.0.0/10")

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
WILDCARD = {"0.0.0.0", "::", ""}

#: Where the CLI lives. The macOS app bundles it outside PATH, which is why this is a list.
_CLI_PATHS = (
    "tailscale",
    "/usr/bin/tailscale",
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
)

_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")


def is_tailnet(addr):
    """True if `addr` is a Tailscale (CGNAT-range) address."""
    try:
        return ipaddress.ip_address(str(addr).strip()) in TAILNET
    except ValueError:
        return False


def pick_tailnet_ip(candidates):
    """
    First tailnet address out of a pile of candidate strings.

    Split out from the discovery calls so the selection rule is testable without a tailnet.
    """
    for c in candidates:
        for found in _IPV4.findall(str(c)):
            if is_tailnet(found):
                return found
    return None


def from_cli(timeout=4):
    """Ask the Tailscale CLI directly. Returns None if it is absent or not connected."""
    for path in _CLI_PATHS:
        exe = shutil.which(path) if os.path.basename(path) == path else (
            path if os.path.exists(path) else None)
        if not exe:
            continue
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True,
                                 timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        ip = pick_tailnet_ip([out.stdout])
        if ip:
            return ip
    return None


def from_interfaces(timeout=4):
    """
    Fall back to reading the machine's own interface list.

    Covers the case where Tailscale is up but its CLI is not reachable -- a sandboxed install,
    or a PATH the desk does not share.
    """
    for cmd in (["ip", "-4", "-o", "addr"], ["ifconfig"]):
        exe = shutil.which(cmd[0])
        if not exe:
            continue
        try:
            out = subprocess.run([exe] + cmd[1:], capture_output=True, text=True,
                                 timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        ip = pick_tailnet_ip(out.stdout.splitlines())
        if ip:
            return ip
    return None


def detect_tailnet_ip():
    """This machine's Tailscale IPv4 address, or None."""
    return from_cli() or from_interfaces()


def classify(host):
    """How exposed is this bind address: 'loopback' | 'tailnet' | 'wildcard' | 'other'."""
    h = (host or "").strip()
    if h in LOOPBACK:
        return "loopback"
    if h in WILDCARD:
        return "wildcard"
    return "tailnet" if is_tailnet(h) else "other"


def resolve(host):
    """
    Turn a requested bind address into a real one.

    'tailscale' / 'ts' are resolved to this machine's tailnet IP, failing with an actionable
    message rather than silently falling back to something more exposed.
    """
    if (host or "").strip().lower() in ("tailscale", "ts", "tailnet"):
        ip = detect_tailnet_ip()
        if not ip:
            raise SystemExit(
                "[serve] could not find a Tailscale address on this machine.\n"
                "[serve]   * is Tailscale running?   tailscale status\n"
                "[serve]   * is this machine logged in?   tailscale up\n"
                "[serve] or pass the address yourself:  --host 100.x.y.z")
        return ip
    return host


def advise(host, port):
    """Lines to print about the chosen bind: what can reach it, and what to do about it."""
    kind = classify(host)
    url = f"http://{host}:{port}/"
    if kind == "loopback":
        return [f"[serve] {url} -- this machine only."]
    if kind == "tailnet":
        return [
            f"[serve] {url} -- reachable from every device on your tailnet.",
            "[serve] open that URL on your phone (Tailscale must be connected there too).",
            "[serve] there is no login: your tailnet ACLs are the access control. Do NOT run "
            "`tailscale funnel` on this port -- that publishes it to the open internet.",
        ]
    if kind == "wildcard":
        return [
            f"[serve] listening on ALL interfaces, port {port}.",
            "[serve] WARNING: that includes whatever network you are on -- cafe wifi, hotel, "
            "conference. There is no login on this dashboard.",
            "[serve] prefer --tailscale (tailnet only) or the default loopback bind.",
        ]
    return [
        f"[serve] {url}",
        f"[serve] WARNING: {host} is not loopback and not a tailnet address. Anyone who can "
        "reach this port sees your positions and signals; there is no login.",
    ]
