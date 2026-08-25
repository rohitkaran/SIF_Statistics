#!/usr/bin/env python3
"""
cli.py  --  Command-line entry point for the options desk. stdlib only.

    python -m options_desk providers                 # what adapters exist
    python -m options_desk config                    # resolved settings (secrets redacted)
    python -m options_desk chain SPY                 # one-shot chain
    python -m options_desk watch SPY QQQ             # live dashboard + signals
    python -m options_desk record SPY --hours 6      # headless capture for backtesting
    python -m options_desk data                      # what has been recorded
    python -m options_desk backtest --symbol SPY     # replay recordings through the rules

Every command defaults to the `synthetic` provider so the whole tool is runnable with no
credentials; set OPTIONS_PROVIDER (or --provider) once a real key is in .env.
"""

import argparse
import datetime as dt
import json
import os
import sys
import threading

from . import alerts, config, providers, rules as rules_mod, store
from .backtest import Backtest
from .dashboard import Dashboard
from .engine import Engine, install_sigint


def _cfg(a):
    over = {}
    if getattr(a, "provider", None):
        over["OPTIONS_PROVIDER"] = a.provider
    if getattr(a, "record_dir", None):
        over["OPTIONS_RECORD_DIR"] = a.record_dir
    return config.load(env_path=getattr(a, "env", None) or None, overrides=over)


def _rules(a):
    if getattr(a, "rules", None):
        with open(a.rules, encoding="utf-8") as f:
            spec = json.load(f)
        if isinstance(spec, dict):
            spec = spec.get("rules", [])
        return rules_mod.build(spec)
    return rules_mod.build(rules_mod.DEFAULT_RULES)


def _symbols(a, cfg):
    return [s.upper() for s in (a.symbols or cfg.list("OPTIONS_UNDERLYINGS", ["SPY"]))]


# -- commands ----------------------------------------------------------------------

def cmd_providers(a):
    cfg = _cfg(a)
    sys.stderr.write("[providers] available adapters:\n")
    for name in providers.AVAILABLE:
        active = " (active)" if name == cfg.str("OPTIONS_PROVIDER") else ""
        need = {"synthetic": "no credentials -- generated data, never trade off it",
                "polygon": "POLYGON_API_KEY",
                "tradier": "TRADIER_ACCESS_TOKEN, TRADIER_ENV"}.get(name, "")
        sys.stderr.write(f"  {name:<12}{active:<10} {need}\n")
    return 0


def cmd_config(a):
    return config.main([])


def cmd_rules(a):
    sys.stderr.write("[rules] available types: " + ", ".join(rules_mod.available()) + "\n")
    sys.stderr.write("[rules] active set:\n")
    for r in _rules(a):
        sys.stderr.write(f"  {r.describe()}  cooldown={r.cooldown_s:g}s severity={r.severity}\n")
    return 0


def cmd_chain(a):
    cfg = _cfg(a)
    prov = providers.get(cfg.str("OPTIONS_PROVIDER"), cfg)
    snap = prov.snapshot(a.symbol.upper(),
                         expiry_limit=a.expiries if a.expiries is not None
                         else cfg.int("OPTIONS_EXPIRY_LIMIT", 3),
                         strike_window=a.strikes if a.strikes is not None
                         else cfg.int("OPTIONS_STRIKE_WINDOW", 10))
    if a.json:
        json.dump(snap.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    from .history import History
    h = History()
    h.update(snap)
    Dashboard(rows=a.rows).update(snap, h, [])
    return 0


def _run_live(a, show_dashboard):
    cfg = _cfg(a)
    prov = providers.get(cfg.str("OPTIONS_PROVIDER"), cfg)
    syms = _symbols(a, cfg)
    rules = _rules(a)

    rec = None
    if getattr(a, "record", False) or a.cmd == "record":
        root = cfg.str("OPTIONS_RECORD_DIR")
        rec = store.Recorder(root)
        sys.stderr.write(f"[desk] recording chains to {root}\n")

    disp = alerts.build(cfg, console=not show_dashboard,
                        jsonl_path=a.alert_log, webhook=a.webhook)
    engine = Engine(prov, rules, disp, recorder=rec)
    dash = Dashboard(rows=a.rows) if show_dashboard else None

    # `is not None`, not `or`: --interval 0 means 'poll flat out' (used for accelerated
    # synthetic runs) and must not silently fall back to the configured default.
    interval = a.interval if a.interval is not None else cfg.float("OPTIONS_POLL_SECONDS", 5.0)
    stop = install_sigint(threading.Event())
    if getattr(a, "hours", None):
        threading.Timer(a.hours * 3600, stop.set).start()

    sys.stderr.write(f"[desk] provider={prov.name} symbols={','.join(syms)} "
                     f"interval={interval:g}s rules={len(rules)}\n")
    sys.stderr.write("[desk] data and signals only -- this tool never places orders.\n")

    on_tick = (lambda snap, fired: dash.update(snap, engine.history, fired)) if dash else None
    engine.run(syms, interval=interval, stop=stop, on_tick=on_tick, max_ticks=a.max_ticks)
    sys.stderr.write("\n" + engine.report() + "\n")
    if rec:
        sys.stderr.write(f"[desk] recorded {rec.written} snapshots\n")
    return 0


def cmd_watch(a):
    return _run_live(a, show_dashboard=not a.no_dashboard)


def cmd_record(a):
    return _run_live(a, show_dashboard=False)


def cmd_data(a):
    cfg = _cfg(a)
    root = cfg.str("OPTIONS_RECORD_DIR")
    s = store.summary(root)
    if not s:
        sys.stderr.write(f"[data] nothing recorded under {root}\n")
        sys.stderr.write("[data] run:  python -m options_desk record SPY --hours 1\n")
        return 0
    sys.stderr.write(f"[data] {root}\n")
    for sym, e in sorted(s.items()):
        sys.stderr.write(f"  {sym:<8} {e['ticks']:>8,} ticks  {e['days']:>3} day(s)  "
                         f"{e['first']} .. {e['last']}\n")
    return 0


def cmd_backtest(a):
    cfg = _cfg(a)
    root = cfg.str("OPTIONS_RECORD_DIR")
    start = dt.date.fromisoformat(a.start) if a.start else None
    end = dt.date.fromisoformat(a.end) if a.end else None
    snaps = store.replay(root, a.symbol, start, end, limit=a.limit)

    bt = Backtest(_rules(a), horizons_s=[int(h) for h in a.horizons.split(",")])
    disp = alerts.build(cfg, console=a.verbose, jsonl_path=None, webhook=None)
    stats = bt.run(snaps, dispatcher=disp)

    if not stats["ticks"]:
        sys.stderr.write(f"[backtest] no recorded snapshots under {root}"
                         f"{' for ' + a.symbol if a.symbol else ''}\n")
        sys.stderr.write("[backtest] record some first:  python -m options_desk record SPY --hours 1\n")
        return 1
    sys.stderr.write(f"[backtest] replayed {stats['ticks']} snapshots\n")
    sys.stderr.write(bt.report() + "\n")
    return 0


# -- wiring ------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="options_desk",
        description="Real-time options data, signal rules and replay backtesting. "
                    "Never places orders.")
    p.add_argument("--provider", help=f"override provider ({', '.join(providers.AVAILABLE)})")
    p.add_argument("--env", help="path to a .env file (default: repo root .env)")
    p.add_argument("--rules", help="path to a rules JSON file (default: built-in set)")
    p.add_argument("--rows", type=int, default=8, help="strikes shown either side of ATM")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("providers", help="list data adapters").set_defaults(fn=cmd_providers)
    sub.add_parser("config", help="show resolved settings (secrets redacted)").set_defaults(fn=cmd_config)
    sub.add_parser("rules", help="list rule types and the active set").set_defaults(fn=cmd_rules)

    c = sub.add_parser("chain", help="print one chain snapshot")
    c.add_argument("symbol")
    c.add_argument("--expiries", type=int, help="how many near expiries")
    c.add_argument("--strikes", type=int, help="strikes either side of ATM (0 = all)")
    c.add_argument("--json", action="store_true", help="emit the snapshot as JSON on stdout")
    c.set_defaults(fn=cmd_chain)

    for name, fn, help_ in (("watch", cmd_watch, "live dashboard + signals"),
                            ("record", cmd_record, "headless capture for backtesting")):
        w = sub.add_parser(name, help=help_)
        w.add_argument("symbols", nargs="*", help="underlyings (default: OPTIONS_UNDERLYINGS)")
        w.add_argument("--interval", type=float, help="seconds between polls")
        w.add_argument("--hours", type=float, help="stop automatically after N hours")
        w.add_argument("--max-ticks", type=int, dest="max_ticks", help="stop after N ticks")
        w.add_argument("--alert-log", dest="alert_log", help="append fired signals as JSONL")
        w.add_argument("--webhook", help="POST signals to this URL")
        w.add_argument("--record-dir", dest="record_dir", help="where to write recordings")
        if name == "watch":
            w.add_argument("--record", action="store_true", help="also record while watching")
            w.add_argument("--no-dashboard", action="store_true", dest="no_dashboard",
                           help="plain log lines instead of the ladder")
        w.set_defaults(fn=fn)

    d = sub.add_parser("data", help="summarise recorded chains")
    d.add_argument("--record-dir", dest="record_dir")
    d.set_defaults(fn=cmd_data)

    b = sub.add_parser("backtest", help="replay recordings through the rules")
    b.add_argument("--symbol", help="underlying (default: all recorded)")
    b.add_argument("--start", help="UTC date YYYY-MM-DD")
    b.add_argument("--end", help="UTC date YYYY-MM-DD")
    b.add_argument("--limit", type=int, help="max snapshots to replay")
    b.add_argument("--horizons", default="60,300,900", help="forward horizons in seconds")
    b.add_argument("--record-dir", dest="record_dir")
    b.add_argument("--verbose", action="store_true", help="print every signal as it fires")
    b.set_defaults(fn=cmd_backtest)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        sys.stderr.write("\n[desk] interrupted\n")
        return 130
    except providers.ProviderError as e:
        sys.stderr.write(f"[desk] provider error: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
