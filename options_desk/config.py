#!/usr/bin/env python3
"""
config.py  --  Credential + settings loading for the options desk. stdlib only.

Reads a local .env (never committed -- see .gitignore) and lets real environment variables
win over it, so CI/systemd can inject secrets without a file on disk.

Secrets are held only in this process and are redacted by `describe()`, which is the only
function anything else should use when printing configuration.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV_PATH = os.path.join(ROOT, ".env")

# Keys whose values must never reach a log line, a JSON dump or the terminal.
_SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASS", "CREDENTIAL")

# Vendor settings that are not OPTIONS_-prefixed but must still be settable from the real
# environment, so CI/systemd can inject them without writing a .env to disk.
_VENDOR_KEYS = ("POLYGON_API_KEY", "TRADIER_ACCESS_TOKEN", "TRADIER_ENV")
_CREDENTIAL_SUFFIXES = ("_API_KEY", "_ACCESS_TOKEN", "_TOKEN", "_SECRET", "_KEY")

DEFAULTS = {
    "OPTIONS_PROVIDER": "synthetic",
    "OPTIONS_UNDERLYINGS": "SPY",
    "OPTIONS_POLL_SECONDS": "5",
    "OPTIONS_RISK_FREE": "0.04",
    "OPTIONS_DIVIDEND": "0.0",
    "OPTIONS_MAX_SPREAD_PCT": "0.10",
    "OPTIONS_MIN_OI": "0",
    "OPTIONS_EXPIRY_LIMIT": "3",
    "OPTIONS_STRIKE_WINDOW": "10",
    "OPTIONS_RECORD_DIR": os.path.join(ROOT, ".options_data"),
    # Scalping side: which exchange's session defines VWAP anchoring and regular hours.
    "OPTIONS_EXCHANGE": "US",
    "OPTIONS_BAR_INTERVAL": "5m",
    "OPTIONS_BAR_LOOKBACK_DAYS": "5",
    "OPTIONS_ALERT_WEBHOOK": "",
    # Synthetic provider only: seconds of virtual time per snapshot (0 = real time).
    "OPTIONS_SYNTH_STEP_S": "0",
}


def parse_env_file(path):
    """
    Minimal dotenv parser: KEY=VALUE, '#' comments, optional 'export ', optional quotes.

    Deliberately not a full dotenv implementation -- no interpolation, no multiline. A
    credentials file should be boring, and a parser that does less has less to get wrong.
    """
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]           # strip matching quotes only
            else:
                v = v.split(" #", 1)[0].rstrip()   # trailing comment on unquoted values
            if k:
                out[k] = v
    return out


class Config(dict):
    """Case-sensitive settings map with typed accessors."""

    def str(self, key, default=None):
        v = self.get(key)
        return default if v is None or v == "" else str(v)

    def int(self, key, default=0):
        try:
            return int(float(self.str(key, "")))
        except (TypeError, ValueError):
            return default

    def float(self, key, default=0.0):
        try:
            return float(self.str(key, ""))
        except (TypeError, ValueError):
            return default

    def list(self, key, default=()):
        v = self.str(key)
        return [x.strip().upper() for x in v.replace(";", ",").split(",") if x.strip()] if v else list(default)

    def require(self, *keys):
        """Fail loudly and early with the exact key names rather than deep in an HTTP 401."""
        missing = [k for k in keys if not self.str(k)]
        if missing:
            raise SystemExit(
                f"[config] missing required setting(s): {', '.join(missing)}\n"
                f"[config] add them to {ENV_PATH} (see .env.example) or export them."
            )
        return [self.str(k) for k in keys]

    def describe(self):
        """Settings with every secret redacted -- safe to print or log."""
        out = {}
        for k in sorted(self):
            v = self.str(k, "")
            if v and any(h in k.upper() for h in _SECRET_HINTS):
                v = f"<set:{len(v)} chars>"
            out[k] = v
        return out


def load(env_path=None, overrides=None):
    """Precedence: explicit overrides > real environment > .env file > DEFAULTS."""
    cfg = Config(DEFAULTS)
    cfg.update(parse_env_file(env_path or ENV_PATH))
    for k, v in os.environ.items():
        if _from_environment(k) or k in cfg:
            cfg[k] = v
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def _from_environment(key):
    """Whether a real environment variable should be adopted as a setting."""
    return (key.startswith("OPTIONS_")
            or key in _VENDOR_KEYS
            or key.endswith(_CREDENTIAL_SUFFIXES))


def main(argv=None):
    """`python -m options_desk.config` -- show resolved settings, secrets redacted."""
    cfg = load()
    where = ENV_PATH if os.path.exists(ENV_PATH) else "(no .env file -- using defaults/env)"
    sys.stderr.write(f"[config] source: {where}\n")
    for k, v in cfg.describe().items():
        sys.stderr.write(f"  {k} = {v}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
