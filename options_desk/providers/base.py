#!/usr/bin/env python3
"""
base.py  --  The contract every market-data adapter implements. stdlib only.

A provider's only job is to turn a vendor's wire format into ChainSnapshot objects. It does
NOT compute greeks (models.ChainSnapshot.enrich does, identically for all providers) and it
does NOT place orders -- this desk is data + signals only, by design.

To add a vendor: subclass Provider, implement snapshot(), register it in providers/__init__.py.
`stream()` has a working default that polls snapshot(), so a new adapter is one method.
"""

import abc
import sys
import time


class ProviderError(RuntimeError):
    """Vendor-side failure (auth, rate limit, malformed payload) worth surfacing to the user."""


class Provider(abc.ABC):
    name = "base"
    #: True when the vendor pushes updates; False when stream() is really a poll loop.
    realtime_push = False

    def __init__(self, cfg):
        self.cfg = cfg
        self.rate = cfg.float("OPTIONS_RISK_FREE", 0.04)
        self.dividend = cfg.float("OPTIONS_DIVIDEND", 0.0)

    @abc.abstractmethod
    def snapshot(self, underlying, expiry_limit=3, strike_window=10):
        """
        Return one enriched ChainSnapshot.

        expiry_limit  -- how many near expiries to pull (chains are huge; most rules use 1-3).
        strike_window -- strikes to keep either side of ATM (0 = keep the whole chain).
        """

    def stream(self, underlyings, interval=5.0, stop=None):
        """
        Yield (underlying, ChainSnapshot) continuously.

        Default implementation polls snapshot() on `interval`. Vendors with a real push feed
        override this. A failed poll is logged and skipped rather than killing the loop --
        a dropped tick must never take down a running desk.
        """
        while not (stop and stop.is_set()):
            cycle = time.monotonic()
            for sym in underlyings:
                if stop and stop.is_set():
                    break
                try:
                    yield sym, self.snapshot(sym)
                except ProviderError as e:
                    sys.stderr.write(f"[{self.name}] {sym}: {e}\n")
                except Exception as e:                       # noqa: BLE001 - keep the desk alive
                    sys.stderr.write(f"[{self.name}] {sym}: unexpected {type(e).__name__}: {e}\n")
            slept = time.monotonic() - cycle
            if (delay := interval - slept) > 0:
                if stop:
                    stop.wait(delay)      # interruptible, so Ctrl-C is instant
                else:
                    time.sleep(delay)

    # -- helpers shared by concrete adapters ---------------------------------------

    def _window(self, quotes, spot, strike_window):
        """Trim a chain to `strike_window` strikes either side of spot, per expiry."""
        if not strike_window:
            return quotes
        keep, by_exp = [], {}
        for q in quotes:
            by_exp.setdefault(q.contract.expiry, []).append(q)
        for exp, group in by_exp.items():
            ks = sorted({q.contract.strike for q in group})
            if not ks:
                continue
            atm = min(range(len(ks)), key=lambda i: abs(ks[i] - spot))
            lo, hi = max(0, atm - strike_window), min(len(ks), atm + strike_window + 1)
            allowed = set(ks[lo:hi])
            keep.extend(q for q in group if q.contract.strike in allowed)
        return keep
