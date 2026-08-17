"""Two-tier regime state machine: price trend x volatility regime.

Tier 1 (trend) classifies the daily close against the 200-day SMA with an
ATR-sized buffer into BULL_EXPANSION / TRANSITION_BAND / BEAR_DEFENSE, which
fixes the equity allocation (100% TQQQ / 50-50 / 100% SGOV).

Tier 2 (volatility) reads the 252-day IV-Rank (and RSI in the bear case) to pick
the option structure to overlay. The mapping is the execution matrix from the
engineering handoff; every threshold is a tunable field on :class:`RegimeParams`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MarketRegime(str, Enum):
    BULL_EXPANSION = "BULL_EXPANSION"
    TRANSITION_BAND = "TRANSITION_BAND"
    BEAR_DEFENSE = "BEAR_DEFENSE"


class OptionAction(str, Enum):
    IDLE = "IDLE"
    BUY_PUT_DEBIT_SPREAD = "BUY_PUT_DEBIT_SPREAD"   # low-IV tail hedge (bull)
    SELL_COVERED_CALL = "SELL_COVERED_CALL"         # high-IV premium harvest (bull)
    SELL_BULL_PUT_SPREAD = "SELL_BULL_PUT_SPREAD"   # high-IV sideways premium (transition)
    SELL_CASH_SECURED_PUT = "SELL_CASH_SECURED_PUT" # panic-IV vega harvest (bear)


@dataclass(frozen=True)
class RegimeParams:
    """Thresholds governing the state machine.

    Defaults follow the engineering handoff. Note the production trend bot
    (``bot.py``) uses ``atr_buffer_mult=2.5``; the options matrix was designed
    around 1.5, which is the default here. Override to align the two.
    """

    sma_period: int = 200
    atr_period: int = 14
    atr_buffer_mult: float = 1.5

    # IV-Rank thresholds (0-100).
    ivr_low: float = 30.0     # below this in a bull -> buy cheap put debit spread
    ivr_cc: float = 40.0      # at/above this in a bull -> sell covered calls
    ivr_bps: float = 60.0     # at/above this in transition -> sell bull put spread
    ivr_panic: float = 75.0   # at/above this in a bear -> sell CSP (with RSI gate)

    rsi_period: int = 14
    rsi_oversold: float = 30.0  # bear CSP also requires RSI below this

    # Target deltas (absolute magnitudes).
    cc_delta: float = 0.15         # short covered-call leg
    csp_delta: float = 0.10        # short cash-secured-put leg
    debit_long_delta: float = 0.30  # long leg of the bull put-debit hedge
    debit_short_delta: float = 0.15  # short leg of the bull put-debit hedge
    bps_short_delta: float = 0.30   # short leg of the transition bull-put spread
    bps_long_delta: float = 0.15    # long leg of the transition bull-put spread


@dataclass(frozen=True)
class RegimeState:
    """Result of classifying one day."""

    regime: MarketRegime
    option_action: OptionAction
    target_equity_pct: float  # fraction of portfolio held in TQQQ that day
    upper_bound: float
    lower_bound: float


def classify_regime(
    price: float,
    sma: float,
    atr: float,
    iv_rank: float,
    rsi: float,
    params: RegimeParams = RegimeParams(),
) -> RegimeState:
    """Classify a single day into trend regime + option action + allocation.

    ``iv_rank`` and ``rsi`` may be ``nan`` during indicator warm-up; the option
    action then falls back to IDLE while the equity allocation still resolves
    from the (defined) price/SMA/ATR bands.
    """
    buffer = atr * params.atr_buffer_mult
    upper = sma + buffer
    lower = sma - buffer

    ivr_known = iv_rank == iv_rank  # False only for NaN
    rsi_known = rsi == rsi

    if price > upper:
        regime = MarketRegime.BULL_EXPANSION
        target_equity = 1.0
        action = OptionAction.IDLE
        if ivr_known:
            if iv_rank < params.ivr_low:
                action = OptionAction.BUY_PUT_DEBIT_SPREAD
            elif iv_rank >= params.ivr_cc:
                action = OptionAction.SELL_COVERED_CALL
            # 30 <= IVR < 40: no edge either way -> stay idle
    elif price < lower:
        regime = MarketRegime.BEAR_DEFENSE
        target_equity = 0.0
        action = OptionAction.IDLE
        if ivr_known and rsi_known and iv_rank >= params.ivr_panic and rsi < params.rsi_oversold:
            action = OptionAction.SELL_CASH_SECURED_PUT
    else:
        regime = MarketRegime.TRANSITION_BAND
        target_equity = 0.5
        action = OptionAction.IDLE
        if ivr_known and iv_rank >= params.ivr_bps:
            action = OptionAction.SELL_BULL_PUT_SPREAD

    return RegimeState(
        regime=regime,
        option_action=action,
        target_equity_pct=target_equity,
        upper_bound=float(upper),
        lower_bound=float(lower),
    )
