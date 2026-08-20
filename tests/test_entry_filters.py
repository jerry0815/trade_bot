import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.overlay_backtest import OptionsOverlayBacktester, OverlayConfig, run_model
from options.regime import OptionAction
from options.run_benchmark import _adx
from tests.test_overlay_backtest import _synthetic_data

NAN = float("nan")


# -- _entry_allowed unit logic ---------------------------------------------- #
def _bt(**kw):
    return OptionsOverlayBacktester(OverlayConfig(use_entry_filters=True, **kw))


def test_filters_off_allows_everything():
    bt = OptionsOverlayBacktester(OverlayConfig(use_entry_filters=False))
    ok, _ = bt._entry_allowed(OptionAction.SELL_COVERED_CALL, rsi=99, adx=99)
    assert ok


def test_high_adx_blocks_premium_sellers():
    bt = _bt(premium_adx_max=40.0)
    for action in (OptionAction.SELL_COVERED_CALL,
                   OptionAction.SELL_CASH_SECURED_PUT,
                   OptionAction.SELL_BULL_PUT_SPREAD):
        ok, reason = bt._entry_allowed(action, rsi=50, adx=55)
        assert not ok and "ADX" in reason


def test_low_adx_allows_premium_sellers():
    bt = _bt(premium_adx_max=40.0)
    ok, _ = bt._entry_allowed(OptionAction.SELL_BULL_PUT_SPREAD, rsi=50, adx=20)
    assert ok


def test_falling_knife_rsi_blocks_premium_sellers():
    bt = _bt(premium_rsi_min=20.0)
    ok, reason = bt._entry_allowed(OptionAction.SELL_CASH_SECURED_PUT, rsi=15, adx=NAN)
    assert not ok and "RSI" in reason


def test_blowoff_rsi_blocks_only_covered_calls():
    bt = _bt(cc_rsi_max=80.0)
    ok_cc, _ = bt._entry_allowed(OptionAction.SELL_COVERED_CALL, rsi=85, adx=20)
    ok_csp, _ = bt._entry_allowed(OptionAction.SELL_CASH_SECURED_PUT, rsi=85, adx=20)
    assert not ok_cc      # covered call capped by a blow-off run
    assert ok_csp         # high RSI is fine for a put sell


def test_protective_structures_never_filtered():
    bt = _bt(premium_adx_max=10.0, premium_rsi_min=90.0)
    # Extreme thresholds that would block any premium seller must not touch the hedge.
    ok, _ = bt._entry_allowed(OptionAction.BUY_PUT_DEBIT_SPREAD, rsi=95, adx=99)
    assert ok


def test_nan_indicators_never_block():
    bt = _bt()
    ok, _ = bt._entry_allowed(OptionAction.SELL_COVERED_CALL, rsi=NAN, adx=NAN)
    assert ok


# -- integration: filters change behavior only when enabled ----------------- #
def test_filters_off_is_identical_to_default():
    data = _synthetic_data(n=1200, seed=2)
    base = run_model(data, "dynamic")
    off = run_model(data, "dynamic", use_entry_filters=False)
    assert base.equity_curve.iloc[-1] == off.equity_curve.iloc[-1]
    assert off.kpis["Entry-Filter Blocks"] == 0


def test_high_adx_column_blocks_dynamic_premium_opens():
    data = _synthetic_data(n=1200, seed=2).copy()
    data["ADX"] = 60.0  # everywhere above premium_adx_max -> block all premium sells
    filtered = run_model(data, "dynamic", use_entry_filters=True, premium_adx_max=40.0)
    unfiltered = run_model(data, "dynamic", use_entry_filters=False)
    assert filtered.kpis["Entry-Filter Blocks"] > 0
    # Fewer premium-selling round-trips survive when every open is blocked.
    prem_filtered = [c for c in filtered.closed_positions if c["pnl"] is not None
                     and c["action"] in ("SELL_COVERED_CALL", "SELL_CASH_SECURED_PUT",
                                          "SELL_BULL_PUT_SPREAD")]
    prem_unfiltered = [c for c in unfiltered.closed_positions
                       if c["action"] in ("SELL_COVERED_CALL", "SELL_CASH_SECURED_PUT",
                                          "SELL_BULL_PUT_SPREAD")]
    assert len(prem_filtered) < len(prem_unfiltered)


def test_low_adx_column_does_not_block():
    data = _synthetic_data(n=1200, seed=2).copy()
    data["ADX"] = 10.0  # calm/range-bound everywhere
    res = run_model(data, "dynamic", use_entry_filters=True, premium_adx_max=40.0)
    # RSI extremes in synthetic data can still block a few, but ADX must not.
    assert res.kpis["Total Option Trades"] > 0


# -- ADX indicator sanity --------------------------------------------------- #
def test_adx_high_in_strong_trend_low_in_chop():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    trend_close = pd.Series(np.linspace(100, 300, 300), index=idx)
    trend = pd.DataFrame({"Close": trend_close,
                          "High": trend_close * 1.005,
                          "Low": trend_close * 0.995})
    chop_close = pd.Series(100 + 2 * np.sin(np.arange(300)), index=idx)
    chop = pd.DataFrame({"Close": chop_close,
                         "High": chop_close + 0.5,
                         "Low": chop_close - 0.5})
    assert _adx(trend).iloc[-1] > 40      # persistent uptrend => high ADX
    assert _adx(chop).iloc[-1] < 30       # oscillation => low ADX
