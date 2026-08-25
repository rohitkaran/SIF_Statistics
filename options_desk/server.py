#!/usr/bin/env python3
"""
server.py  --  Local web dashboard: option chain, intraday levels, and a long/short read.

Runs on the machine that holds your credentials and serves a single self-contained page over
localhost. It is deliberately NOT a hosted app: the whole point is that market data and API
keys never leave your machine.

    python -m options_desk serve SPY

Architecture is two threads and one dict. A worker polls the providers, folds each snapshot
through the same Engine the CLI uses, and swaps a finished payload into shared state. The HTTP
handler only ever reads that payload -- it never touches a provider -- so a slow or failing
vendor cannot block the page, and refreshing the browser costs nothing.

Binds to 127.0.0.1 by default. The payload carries market data and signals but never
credentials; even so, do not expose this to a network you do not control.
"""

import datetime as dt
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import alerts, analytics, netbind, providers, rules as rules_mod
from .engine import Engine
from .history import History

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
MAX_SIGNALS = 60


class DeskState:
    """Shared, lock-guarded payload. Written by the worker, read by HTTP handlers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._payload = {"status": "starting", "symbols": [], "data": {}, "errors": []}
        self.signals = []

    def read(self):
        with self._lock:
            return self._payload

    def write(self, payload):
        # Payloads are built whole and swapped in, never mutated in place, so a reader can
        # never observe a half-updated dashboard.
        with self._lock:
            self._payload = payload

    def add_signals(self, sigs):
        with self._lock:
            self.signals.extend(s.to_dict() for s in sigs)
            del self.signals[:-MAX_SIGNALS]

    def recent_signals(self, symbol=None):
        with self._lock:
            rows = list(self.signals)
        if symbol:
            rows = [r for r in rows if r["underlying"] == symbol]
        return list(reversed(rows))


class Worker(threading.Thread):
    """Polls chains and bars, runs the rules, republishes the dashboard payload."""

    daemon = True

    def __init__(self, cfg, state, symbols, chain_provider, bar_provider,
                 rules, interval, bar_interval, stop=None):
        super().__init__(name="desk-worker")
        self.cfg, self.state, self.symbols = cfg, state, symbols
        self.chain_provider, self.bar_provider = chain_provider, bar_provider
        self.interval, self.bar_interval = interval, bar_interval
        self.stop_event = stop or threading.Event()
        self.dispatcher = alerts.Dispatcher()
        self.engine = Engine(None, rules, self.dispatcher, history=History())
        self.ticks = 0

    def run(self):
        while not self.stop_event.is_set():
            started = time.monotonic()
            data, errors = {}, []
            for sym in self.symbols:
                try:
                    data[sym] = self._one(sym, errors)
                except Exception as e:                  # noqa: BLE001 - never kill the desk
                    errors.append(f"{sym}: {type(e).__name__}: {e}")
            self.ticks += 1
            self.state.write({
                "status": "ok" if data else "error",
                "generated": _now_iso(),
                "symbols": self.symbols,
                "tick": self.ticks,
                "interval": self.interval,
                "providers": {"chain": self.chain_provider.name if self.chain_provider else None,
                              "bars": self.bar_provider.name if self.bar_provider else None},
                "exchange": self.cfg.str("OPTIONS_EXCHANGE", "US"),
                "data": data,
                "errors": errors,
            })
            self.stop_event.wait(max(0.0, self.interval - (time.monotonic() - started)))

    def _one(self, symbol, errors):
        out = {"symbol": symbol}
        chain = bars = None

        if self.chain_provider is not None:
            try:
                chain = self.chain_provider.snapshot(
                    symbol,
                    self.cfg.int("OPTIONS_EXPIRY_LIMIT", 3),
                    self.cfg.int("OPTIONS_STRIKE_WINDOW", 12))
                self.state.add_signals(self.engine.tick(chain))
                out["chain"] = _chain_payload(chain)
                out["analytics"] = analytics.chain_analytics(chain)
            except Exception as e:                      # noqa: BLE001
                errors.append(f"{symbol} chain: {e}")

        if self.bar_provider is not None:
            try:
                bars = self.bar_provider.bar_snapshot(
                    symbol, self.bar_interval,
                    self.cfg.int("OPTIONS_BAR_LOOKBACK_DAYS", 5))
                self.state.add_signals(self.engine.tick(bars))
                out["bars"] = _bars_payload(bars)
            except Exception as e:                      # noqa: BLE001
                errors.append(f"{symbol} bars: {e}")

        out["bias"] = analytics.bias(bars, chain) if (bars or chain) else None
        out["signals"] = self.state.recent_signals(symbol)[:20]
        return out


# --- payload shaping ---------------------------------------------------------------

def _chain_payload(snap):
    """One row per strike, calls and puts side by side -- the shape the table renders."""
    exp = snap.nearest_expiry()
    rows = []
    for k in snap.strikes(exp):
        c, p = snap.get(exp, k, "C"), snap.get(exp, k, "P")
        rows.append({"strike": k, "call": _quote_row(c), "put": _quote_row(p)})
    return {
        "underlying": snap.underlying, "spot": snap.spot, "ts": snap.ts.isoformat(),
        "provider": snap.provider, "expiry": exp.isoformat() if exp else None,
        "atm_strike": snap.atm_strike(exp), "rows": rows,
    }


def _quote_row(q):
    if q is None:
        return None
    return {"bid": q.bid, "ask": q.ask, "mid": q.mid, "iv": q.iv, "delta": q.delta,
            "gamma": q.gamma, "theta": q.theta, "vega": q.vega,
            "oi": q.open_interest, "volume": q.volume, "spread_pct": q.spread_pct}


def _bars_payload(snap):
    from .levels import running_vwap

    track = running_vwap(snap.bars.session, list(snap.bars))
    series = [{"ts": b.ts.isoformat(), "o": b.open, "h": b.high, "l": b.low,
               "c": b.close, "v": b.volume, "vwap": v} for b, v in track]
    sd = snap.vwap.stdev
    return {
        "underlying": snap.underlying, "price": snap.price, "ts": snap.ts.isoformat(),
        "provider": snap.provider, "exchange": snap.exchange, "interval": snap.interval,
        "vwap": snap.vwap_value, "vwap_stdev": sd, "vwap_z": snap.vwap_z,
        "bands": {"s1": list(snap.vwap.band(1)), "s2": list(snap.vwap.band(2))},
        "cpr_position": snap.cpr_position,
        "relative_volume": snap.relative_volume(),
        "session_volume": snap.session_volume(),
        "minutes_left": snap.bars.session.minutes_left(snap.ts),
        "levels": snap.levels.to_dict() if snap.levels else None,
        "named_levels": snap.levels.named() if snap.levels else {},
        "width_pct": snap.levels.width_pct if snap.levels else None,
        "series": series,
    }


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# --- HTTP --------------------------------------------------------------------------

def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = "options_desk"

        def do_GET(self):                                  # noqa: N802 - stdlib API
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._file(os.path.join(WEB, "index.html"), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._json(state.read())
            if path == "/api/health":
                return self._json({"ok": True, "time": _now_iso()})
            self.send_error(404, "not found")

        def _json(self, payload):
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # Live data must never be cached, by the browser or anything in between.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path, ctype):
            try:
                with open(path, "rb") as f:
                    body = f.read()
            except OSError:
                return self.send_error(500, f"missing asset: {os.path.basename(path)}")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass                                           # the desk log is the useful one

    return Handler


def serve(cfg, symbols, port=8787, host="127.0.0.1", interval=None, bar_interval=None,
          rules=None, open_browser=False):
    """Start the worker and block serving HTTP until interrupted."""
    interval = interval if interval is not None else cfg.float("OPTIONS_POLL_SECONDS", 5.0)
    bar_interval = bar_interval or cfg.str("OPTIONS_BAR_INTERVAL", "5m")

    chain_provider = _maybe(cfg, cfg.str("OPTIONS_PROVIDER"), "chains")
    bar_name = cfg.str("OPTIONS_BAR_PROVIDER") or cfg.str("OPTIONS_PROVIDER")
    bar_provider = (chain_provider if bar_name == cfg.str("OPTIONS_PROVIDER")
                    else _maybe(cfg, bar_name, "bars"))
    if chain_provider is None and bar_provider is None:
        raise SystemExit("[serve] no usable provider for chains or bars")

    rules = rules or rules_mod.build(rules_mod.default_specs("chain")
                                     + rules_mod.default_specs("bars"))
    state = DeskState()
    stop = threading.Event()
    worker = Worker(cfg, state, symbols, chain_provider, bar_provider,
                    rules, interval, bar_interval, stop)
    worker.start()

    # 'tailscale' resolves to this machine's tailnet address; anything else is taken as given.
    host = netbind.resolve(host)
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    url = f"http://{host}:{port}/"
    sys.stderr.write(f"[serve] chains={_pname(chain_provider)} bars={_pname(bar_provider)} "
                     f"exchange={cfg.str('OPTIONS_EXCHANGE')} symbols={','.join(symbols)} "
                     f"refresh={interval:g}s\n")
    sys.stderr.write("[serve] data and signals only -- this dashboard never places orders.\n")
    for line in netbind.advise(host, port):
        sys.stderr.write(line + "\n")
    if open_browser:
        import webbrowser
        # A wildcard/tailnet bind is not a URL this machine's browser should open.
        local = url if netbind.classify(host) == "loopback" else f"http://127.0.0.1:{port}/"
        threading.Timer(0.5, lambda: webbrowser.open(local)).start()

    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        sys.stderr.write("\n[serve] stopping\n")
    finally:
        stop.set()
        httpd.shutdown()
        httpd.server_close()
    return 0


def _maybe(cfg, name, what):
    """Build a provider, downgrading a missing-credential exit into a warning."""
    if not name:
        return None
    try:
        return providers.get(name, cfg)
    except SystemExit as e:
        sys.stderr.write(f"[serve] {name} unavailable for {what}: "
                         f"{str(e).splitlines()[0]}\n")
        return None


def _pname(p):
    return p.name if p is not None else "-"
