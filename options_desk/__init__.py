"""
options_desk  --  Real-time options data, signal rules and replay backtesting. stdlib only.

DATA AND SIGNALS ONLY. Nothing in this package places, routes, modifies or cancels an order,
and no adapter here holds brokerage trading credentials. See options_desk/README.md.
"""

__version__ = "1.0.0"
__all__ = ["config", "models", "greeks", "history", "rules", "engine",
           "alerts", "store", "backtest", "dashboard", "providers"]
