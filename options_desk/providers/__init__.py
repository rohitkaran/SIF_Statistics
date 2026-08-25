#!/usr/bin/env python3
"""
providers  --  Adapter registry. `get(name, cfg)` is the only way the app builds a provider.

Adding a vendor is: write the adapter, add one line to _REGISTRY. Nothing else in the tree
needs to know the vendor exists.
"""

from .base import Provider, ProviderError          # noqa: F401 - re-exported

_REGISTRY = {}


def _load(name):
    if name == "synthetic":
        from .synthetic import SyntheticProvider
        return SyntheticProvider
    if name == "polygon":
        from .polygon import PolygonProvider
        return PolygonProvider
    if name == "tradier":
        from .tradier import TradierProvider
        return TradierProvider
    if name == "yahoo":
        from .yahoo import YahooProvider
        return YahooProvider
    return None


AVAILABLE = ("synthetic", "polygon", "tradier", "yahoo")


def get(name, cfg):
    """Instantiate a provider by name, with a useful error for typos."""
    key = (name or "synthetic").strip().lower()
    cls = _REGISTRY.get(key) or _load(key)
    if cls is None:
        raise SystemExit(f"[providers] unknown provider {name!r}; available: {', '.join(AVAILABLE)}")
    return cls(cfg)
