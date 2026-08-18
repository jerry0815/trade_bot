import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.overlay_backtest import OptionsOverlayBacktester, OverlayConfig, run_model
from options.regime import OptionAction


def _synthetic_data(n=800, seed=0):
    """A rising-then-choppy TQQQ path with indicators and a synthetic IV series."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-01", periods=n, freq="B")
    # Trend up with noise.
    drift = np.linspace(0, 1.2, n)
    noise = rng.standard_normal(n).cumsum() * 0.02
    close = 30 * np.exp(drift + noise)
    df = pd.DataFrame({"Close": close}, index=idx)
    df["SMA"] = df["Close"].rolling(200, min_periods=1).mean()
    high = df["Close"] * 1.01
    low = df["Close"] * 0.99
    tr = (high - low)
    df["ATR"] = tr.rolling(14, min_periods=1).mean()
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI"] = (100 - 100 / (1 + rs)).fillna(50)
    # Synthetic IV oscillating 15%-45% (as ^VXN-style percent points).
    df["IV"] = 30 + 15 * np.sin(np.linspace(0, 12 * np.pi, n))
    # IV-Rank derived from the IV series' own rolling range.
    roll_min = df["IV"].rolling(252, min_periods=50).min()
    roll_max = df["IV"].rolling(252, min_periods=50).max()
    df["IV_Rank"] = ((df["IV"] - roll_min) / (roll_max - roll_min) * 100).fillna(50)
    return df


def test_all_models_run_and_produce_curves():
    data = _synthetic_data()
    for model in ("buy_hold", "trend", "static_cc", "dynamic"):
        res = run_model(data, model)
        assert len(res.equity_curve) == len(data)
        assert res.equity_curve.iloc[0] > 0
        assert np.isfinite(res.kpis["Ending Portfolio Value ($)"])
        assert res.kpis["Ending Portfolio Value ($)"] > 0


def test_buy_hold_matches_underlying_return():
    data = _synthetic_data()
    res = run_model(data, "buy_hold")
    # Buy & hold NAV should track TQQQ's cumulative return closely (no options,
    # no cash sleeve). Allow a small tolerance for the day-0 zero return.
    underlying_growth = data["Close"].iloc[-1] / data["Close"].iloc[0]
    nav_growth = res.equity_curve.iloc[-1] / res.kpis["Initial Capital ($)"]
    assert abs(nav_growth - underlying_growth) / underlying_growth < 0.02


def test_dynamic_model_opens_and_closes_options():
    data = _synthetic_data()
    res = run_model(data, "dynamic")
    assert res.kpis["Total Option Trades"] > 0
    # Some premium must have been collected from the short structures.
    assert res.kpis["Total Option Premium Collected ($)"] > 0


def test_trend_model_holds_no_options():
    data = _synthetic_data()
    res = run_model(data, "trend")
    assert res.kpis["Total Option Trades"] == 0
    assert res.kpis["Total Option Premium Collected ($)"] == 0


def test_covered_call_respects_share_collateral():
    # Tiny account can't cover even one contract of a ~$60 underlying
    # (needs 100 shares => $6k) -> no covered calls should ever open.
    data = _synthetic_data()
    res = run_model(data, "static_cc", initial_capital=500.0)
    cc_trades = [c for c in res.closed_positions if c["action"] == "SELL_COVERED_CALL"]
    assert cc_trades == []


def test_realized_option_pnl_compounds_into_equity_base():
    # A non-reinvested option ledger makes NAV == pure-equity-sleeve + Σ option
    # P&L *exactly* (the pre-fix accounting). The trend model is the pure sleeve
    # (no options), so folding realized option P&L back into the compounding base
    # must break that identity by a non-trivial margin.
    data = _synthetic_data(n=1500, seed=1)
    trend = run_model(data, "trend")
    cc = run_model(data, "static_cc")
    assert cc.kpis["Total Option Trades"] > 0
    assert abs(cc.kpis["Total Option P&L ($)"]) > 0

    sleeve_end = trend.equity_curve.iloc[-1]  # trend NAV == the pure equity sleeve
    non_reinvested_end = sleeve_end + cc.kpis["Total Option P&L ($)"]
    rel = abs(cc.equity_curve.iloc[-1] - non_reinvested_end) / sleeve_end
    assert rel > 1e-3, f"option P&L is not compounding into the base (rel={rel:.2e})"


def test_no_option_models_unaffected_by_reinvestment():
    # buy_hold and trend hold no options, so the reinvestment change must leave
    # their NAV paths untouched (Total Option P&L is exactly zero).
    data = _synthetic_data(n=1500, seed=1)
    for model in ("buy_hold", "trend"):
        res = run_model(data, model)
        assert res.kpis["Total Option P&L ($)"] == 0.0
        assert res.kpis["Total Option Trades"] == 0


def test_credit_profit_target_closes_position():
    # Drive a covered call to a decayed state and confirm the profit-target path.
    cfg = OverlayConfig(model="dynamic")
    bt = OptionsOverlayBacktester(cfg)
    from options.overlay_backtest import OptionPosition, Leg
    from options.regime import MarketRegime
    pos = OptionPosition(
        action=OptionAction.SELL_COVERED_CALL,
        contracts=1,
        entry_date=pd.Timestamp("2020-01-01"),
        entry_dte=35,
        dte_remaining=30,
        legs=[Leg("call", 120, -1, 0.95)],
        value_entry=-2.0,  # $2 credit
    )
    pos._value_now = -0.5  # decayed to $0.50 cost-to-close => 75% profit
    reason = bt._should_close(pos, MarketRegime.BULL_EXPANSION, iv_rank=40)
    assert reason == "PROFIT_TARGET"


def test_bear_regime_liquidates_covered_calls():
    cfg = OverlayConfig(model="dynamic")
    bt = OptionsOverlayBacktester(cfg)
    from options.overlay_backtest import OptionPosition, Leg
    from options.regime import MarketRegime
    pos = OptionPosition(
        action=OptionAction.SELL_COVERED_CALL,
        contracts=1,
        entry_date=pd.Timestamp("2020-01-01"),
        entry_dte=35,
        dte_remaining=30,
        legs=[Leg("call", 120, -1, 0.95)],
        value_entry=-2.0,
    )
    pos._value_now = -1.9  # barely moved, no profit target
    reason = bt._should_close(pos, MarketRegime.BEAR_DEFENSE, iv_rank=40)
    assert reason == "BEAR_CC_LIQUIDATION"
