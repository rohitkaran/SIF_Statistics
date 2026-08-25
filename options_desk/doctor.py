#!/usr/bin/env python3
"""
doctor.py  --  Work out why the dashboard is not reachable from your phone. stdlib only.

"It doesn't open" has half a dozen causes that look identical on the phone: the desk bound to
loopback, Tailscale not running on one end, a host firewall, the wrong port, or the browser
never issuing the request at all. Guessing between them from the phone is miserable, so this
checks each one from the machine that is serving and names the specific fix.

    python -m options_desk doctor
"""

import json
import os
import platform
import socket
import subprocess
import sys
from dataclasses import dataclass

from . import netbind

PASS, FAIL, WARN, INFO = "pass", "fail", "warn", "info"
_MARK = {PASS: "OK  ", FAIL: "FAIL", WARN: "WARN", INFO: "  · "}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""


# --- pure helpers (unit-tested without a tailnet) -----------------------------------

def parse_status(text):
    """
    Pull what we need out of `tailscale status --json`.

    Returns {} on anything unparseable -- a missing or renamed field must degrade into
    "cannot tell" rather than a traceback in a diagnostic tool.
    """
    try:
        j = json.loads(text)
    except (TypeError, ValueError):
        return {}
    self_node = j.get("Self") or {}
    dns = (self_node.get("DNSName") or "").rstrip(".")
    ips = [ip for ip in (self_node.get("TailscaleIPs") or []) if netbind.is_tailnet(ip)]
    return {
        "backend_state": j.get("BackendState") or "",
        "dns_name": dns,
        "ips": ips,
        "peers": len(j.get("Peer") or {}),
    }


def backend_check(state):
    """Turn Tailscale's BackendState into a check with the right remedy."""
    if not state:
        return Check("tailscale daemon", WARN, "could not read state",
                     "is Tailscale installed and running?")
    if state == "Running":
        return Check("tailscale daemon", PASS, "Running")
    if state == "NeedsLogin":
        return Check("tailscale daemon", FAIL, "NeedsLogin", "run:  tailscale up")
    if state == "Stopped":
        return Check("tailscale daemon", FAIL, "Stopped", "run:  tailscale up")
    return Check("tailscale daemon", WARN, state, "run:  tailscale status")


def port_check(host, port):
    """Can we bind here, and if not, is that because the desk is already running?"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return Check(f"bind {host}:{port}", PASS, "address is available")
    except OSError as e:
        # EADDRINUSE here is good news -- it means something is already serving.
        if e.errno in (98, 48):
            return Check(f"bind {host}:{port}", INFO, "already in use (the desk, hopefully)")
        return Check(f"bind {host}:{port}", FAIL, str(e),
                     "that address does not exist on this machine -- check `tailscale ip -4`")
    finally:
        s.close()


def http_check(host, port, timeout=3):
    """Does something actually answer on that address:port?"""
    import urllib.error
    import urllib.request
    url = f"http://{host}:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            ok = json.loads(r.read()).get("ok")
            return Check("desk responds", PASS if ok else WARN, f"{url} -> HTTP {r.status}")
    except urllib.error.HTTPError as e:
        return Check("desk responds", WARN, f"{url} -> HTTP {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        return Check("desk responds", FAIL, f"{url} unreachable: {e}",
                     "start it:  python -m options_desk serve SPY --tailscale")


def firewall_hint(port=8787):
    """OS-specific reason a bound port still refuses connections from other devices."""
    sysname = platform.system()
    if sysname == "Darwin":
        return ("macOS firewall can block incoming connections per-application. "
                "System Settings -> Network -> Firewall -> Options: allow python3, "
                "or turn the firewall off while you test.")
    if sysname == "Windows":
        return ("Windows Defender Firewall prompts once per program. If you dismissed it: "
                "Allow an app through firewall -> add python.exe for Private networks.")
    return ("If ufw/firewalld is active, allow the port on the tailnet interface, e.g.\n"
            f"        sudo ufw allow in on tailscale0 to any port {port}")


def render(checks, url=None, https_url=None):
    lines = ["", "options_desk doctor", "=" * 58]
    for c in checks:
        lines.append(f"  [{_MARK[c.status]}] {c.name}" + (f" -- {c.detail}" if c.detail else ""))
        if c.fix:
            for fixline in c.fix.split("\n"):
                lines.append(f"         {fixline}")
    lines.append("")
    if url:
        from . import qr
        try:
            lines.append(qr.render(url, color=sys.stderr.isatty()))
        except (ValueError, OSError):
            pass
        lines.append(f"  Scan that, or type it -- INCLUDING the http:// prefix:")
        lines.append(f"      {url}")
        lines.append("")
        lines.append("  Chrome on a phone, specifically:")
        lines.append("    * Type the whole URL with http:// -- without a scheme the omnibox")
        lines.append("      may treat 100.x.y.z:8787 as a search instead of an address.")
        lines.append("    * Tailscale must be CONNECTED on the phone too (check the VPN key")
        lines.append("      icon in the status bar), and logged into the same tailnet.")
        lines.append("    * If Chrome complains the connection is not secure, or you get a")
        lines.append("      'local network' permission prompt, allow it -- or better, use the")
        lines.append("      HTTPS address below, which avoids the question entirely.")
    if https_url:
        lines.append("")
        lines.append("  HTTPS, with a real certificate and no browser warnings:")
        lines.append("      tailscale serve --bg 8787")
        lines.append(f"      then open   {https_url}")
        lines.append("      (run the desk on the default loopback bind and let Serve front it)")
        lines.append("      Do NOT use `tailscale funnel` -- that publishes it to the internet.")
    lines.append("")
    return "\n".join(lines)


# --- the run ------------------------------------------------------------------------

def _tailscale_status_json(timeout=5):
    for path in netbind._CLI_PATHS:
        import shutil
        exe = shutil.which(path) if os.path.basename(path) == path else (
            path if os.path.exists(path) else None)
        if not exe:
            continue
        try:
            out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True,
                                 timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.stdout.strip():
            return out.stdout, exe
    return None, None


#: What to call the address under test, so a loopback probe is not reported as a tailnet one.
_LABEL = {"tailnet": "this machine's tailnet IP", "loopback": "address under test (loopback)",
          "wildcard": "address under test (all interfaces)", "other": "address under test"}


def run(port=8787, host=None):
    checks = []
    st, raw = {}, None

    # Checking an explicit non-tailnet address (a loopback smoke test, say) does not need
    # Tailscale at all, so its absence is reported as context rather than as a failure.
    tailscale_relevant = (host is None) or netbind.is_tailnet(host)

    if tailscale_relevant:
        raw, exe = _tailscale_status_json()
        if exe:
            checks.append(Check("tailscale CLI", PASS, exe))
        else:
            checks.append(Check("tailscale CLI", FAIL, "not found",
                                "install from https://tailscale.com/download, or pass the\n"
                                "address yourself:  serve --host <ip>"))
        st = parse_status(raw or "")
        if raw:
            checks.append(backend_check(st.get("backend_state")))
            if st.get("peers"):
                checks.append(Check("tailnet peers", INFO,
                                    f"{st['peers']} other device(s) known -- your phone should "
                                    "be one of them"))
    else:
        checks.append(Check("tailscale", INFO,
                            f"not consulted -- checking {host} directly"))

    ip = host or (st.get("ips") or [None])[0] or netbind.detect_tailnet_ip()
    kind = netbind.classify(ip) if ip else None
    if ip:
        checks.append(Check(_LABEL[kind], PASS, ip))
        if kind == "loopback":
            checks.append(Check("reachable from a phone", FAIL, "no -- loopback is this machine only",
                                "bind to the tailnet instead:\n"
                                "  python -m options_desk serve SPY --tailscale"))
    else:
        checks.append(Check("this machine's tailnet IP", FAIL, "none found",
                            "run:  tailscale up     then re-run this command"))

    url = https_url = None
    if ip:
        checks.append(port_check(ip, port))
        checks.append(http_check(ip, port))
        checks.append(Check("host firewall", INFO, "cannot be tested from here",
                            firewall_hint(port)))
        if kind == "tailnet":
            url = f"http://{ip}:{port}/"

    dns = st.get("dns_name")
    if dns:
        checks.append(Check("MagicDNS name", PASS, dns))
        https_url = f"https://{dns}/"

    return checks, url, https_url


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="options_desk doctor",
                                description="Diagnose phone/tailnet access to the dashboard.")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--host", help="check a specific address instead of auto-detecting")
    a = p.parse_args(argv)
    checks, url, https_url = run(a.port, a.host)
    sys.stderr.write(render(checks, url, https_url))
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
