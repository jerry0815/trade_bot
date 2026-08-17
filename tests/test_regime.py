import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.regime import (
    MarketRegime,
    OptionAction,
    RegimeParams,
    classify_regime,
)

P = RegimeParams()
SMA, ATR = 100.0, 4.0
BUF = ATR * P.atr_buffer_mult  # 6.0
BULL_PRICE = SMA + BUF + 1     # 107
BEAR_PRICE = SMA - BUF - 1     # 93
BAND_PRICE = SMA              # 100


def test_bull_low_iv_buys_put_debit_spread():
    st = classify_regime(BULL_PRICE, SMA, ATR, iv_rank=20, rsi=50)
    assert st.regime == MarketRegime.BULL_EXPANSION
    assert st.target_equity_pct == 1.0
    assert st.option_action == OptionAction.BUY_PUT_DEBIT_SPREAD


def test_bull_high_iv_sells_covered_call():
    st = classify_regime(BULL_PRICE, SMA, ATR, iv_rank=60, rsi=50)
    assert st.option_action == OptionAction.SELL_COVERED_CALL


def test_bull_mid_iv_is_idle():
    st = classify_regime(BULL_PRICE, SMA, ATR, iv_rank=35, rsi=50)
    assert st.option_action == OptionAction.IDLE


def test_bear_panic_iv_and_oversold_sells_csp():
    st = classify_regime(BEAR_PRICE, SMA, ATR, iv_rank=80, rsi=25)
    assert st.regime == MarketRegime.BEAR_DEFENSE
    assert st.target_equity_pct == 0.0
    assert st.option_action == OptionAction.SELL_CASH_SECURED_PUT


def test_bear_panic_iv_but_not_oversold_is_idle():
    st = classify_regime(BEAR_PRICE, SMA, ATR, iv_rank=80, rsi=45)
    assert st.option_action == OptionAction.IDLE


def test_bear_low_iv_is_idle():
    st = classify_regime(BEAR_PRICE, SMA, ATR, iv_rank=50, rsi=20)
    assert st.option_action == OptionAction.IDLE


def test_transition_high_iv_sells_bull_put_spread():
    st = classify_regime(BAND_PRICE, SMA, ATR, iv_rank=65, rsi=50)
    assert st.regime == MarketRegime.TRANSITION_BAND
    assert st.target_equity_pct == 0.5
    assert st.option_action == OptionAction.SELL_BULL_PUT_SPREAD


def test_transition_low_iv_is_idle():
    st = classify_regime(BAND_PRICE, SMA, ATR, iv_rank=40, rsi=50)
    assert st.option_action == OptionAction.IDLE


def test_nan_iv_rank_falls_back_to_idle_but_keeps_allocation():
    st = classify_regime(BULL_PRICE, SMA, ATR, iv_rank=float("nan"), rsi=50)
    assert st.option_action == OptionAction.IDLE
    assert st.target_equity_pct == 1.0


def test_band_boundaries_are_inclusive_of_transition():
    # Exactly on the upper bound is NOT strictly greater -> transition, not bull.
    st = classify_regime(SMA + BUF, SMA, ATR, iv_rank=10, rsi=50)
    assert st.regime == MarketRegime.TRANSITION_BAND
