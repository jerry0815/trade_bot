"""Regime-adaptive, two-sided options overlay for the TQQQ trend system.

This package layers a Greek-governed options engine on top of the existing
200-day SMA + ATR trend model (``backtest/strat_backtest.py``). It is a
*self-contained* extension: it reuses the base engine's indicators and data
loaders where practical, but runs its own event-driven daily simulation so it
can track per-leg option state (DTE, profit targets, collateral) that the
vectorized trend engine has no notion of.

Modules
-------
greeks           Black-Scholes pricing + skew-adjusted delta->strike solver.
iv_loader        ^VXN ingestion and rolling 252-day IV-Rank series.
regime           2-tier state machine (price trend x IV regime).
position_sizer   Collateral validation and integer-contract sizing.
overlay_backtest Event-driven options-overlay simulator (the 4 benchmark models).
run_benchmark    CLI entry point that runs the 4-model comparison suite.
"""

from .greeks import GreeksEngine
from .regime import RegimeState, MarketRegime, OptionAction, classify_regime

__all__ = [
    "GreeksEngine",
    "RegimeState",
    "MarketRegime",
    "OptionAction",
    "classify_regime",
]
