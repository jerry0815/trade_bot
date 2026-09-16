import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.cc_income import (
    CCConfig,
    run_cc_income,
    synthetic_earnings_dates,
)
from options.realized_iv import build_iv_frame


def _price_df(returns, start=100.0):
    prices = start * np.exp(np.cumsum(np.r_[0.0, returns]))
    idx = pd.bdate_range("2021-01-01", periods=len(prices))
    return pd.DataFrame({"Close": prices, "High": prices, "Low": prices}, index=idx)


def _aligned(price_df, vrp_mult=1.15):
    iv = build_iv_frame(price_df["Close"], vrp_mult=vrp_mult)
    common = price_df.index.intersection(iv.index)
    return price_df.loc[common], iv.loc[common]


def test_flat_market_keeps_shares_and_collects_income():
    rng = np.random.default_rng(11)
    # Zero-drift noise: far-OTM calls should mostly expire/close worthless.
    px = _price_df(rng.normal(0.0, 0.012, 900))
    price_df, iv = _aligned(px)
    cfg = CCConfig(ticker="NVDA", shares=1000, delta=0.10, dte=30, ivr_gate=0)
    res = run_cc_income(price_df, iv, [], cfg)

    assert res.premium_collected > 0
    assert res.cycles > 0
    assert res.kpis["Keep Rate (%)"] >= 90.0
    assert res.kpis["Annualized Premium Yield (%)"] > 0


def test_strong_uptrend_causes_assignments_and_drag():
    rng = np.random.default_rng(12)
    # Steady strong drift: the short call is repeatedly ITM => assignments, drag.
    px = _price_df(rng.normal(0.003, 0.02, 900))
    price_df, iv = _aligned(px)
    cfg = CCConfig(ticker="NVDA", shares=1000, delta=0.20, dte=30, ivr_gate=0)
    res = run_cc_income(price_df, iv, [], cfg)

    assert res.assigned_cycles > 0
    assert res.kpis["Keep Rate (%)"] < 100.0
    # Capping upside in a rip must cost total return vs buy & hold.
    assert res.kpis["Total-Return Drag (pp/yr)"] > 0


def test_collateral_never_exceeds_share_lots():
    rng = np.random.default_rng(13)
    px = _price_df(rng.normal(0.001, 0.02, 700))
    price_df, iv = _aligned(px)
    shares = 350  # 3 lots
    cfg = CCConfig(ticker="PLTR", shares=shares, delta=0.15, dte=30, ivr_gate=0)
    res = run_cc_income(price_df, iv, [], cfg)

    max_lots = shares // 100
    assert res.cycles > 0
    for trade in res.closed_trades:
        assert trade["contracts"] <= max_lots


def test_nav_reconciles_to_shares_price_plus_cash_each_day():
    rng = np.random.default_rng(14)
    px = _price_df(rng.normal(0.0005, 0.02, 800))
    price_df, iv = _aligned(px)
    shares = 500
    cfg = CCConfig(ticker="TQQQ", shares=shares, delta=0.15, dte=45, ivr_gate=0)
    res = run_cc_income(price_df, iv, [], cfg)

    reconstructed = shares * price_df["Close"] + res.cash_curve
    assert np.allclose(res.equity_curve.values, reconstructed.values, atol=1e-6)


def test_ivr_gate_reduces_trade_count():
    rng = np.random.default_rng(15)
    px = _price_df(rng.normal(0.0005, 0.02, 900))
    price_df, iv = _aligned(px)
    low = run_cc_income(price_df, iv, [], CCConfig(shares=1000, delta=0.15, dte=30, ivr_gate=0))
    high = run_cc_income(price_df, iv, [], CCConfig(shares=1000, delta=0.15, dte=30, ivr_gate=50))
    assert high.cycles <= low.cycles


def test_earnings_skip_reduces_or_matches_cycles():
    rng = np.random.default_rng(16)
    px = _price_df(rng.normal(0.0005, 0.02, 900))
    price_df, iv = _aligned(px)
    earnings = synthetic_earnings_dates("NVDA", price_df.index[0], price_df.index[-1])
    ignore = run_cc_income(
        price_df, iv, earnings, CCConfig(shares=1000, delta=0.15, dte=30, earnings_rule="ignore")
    )
    skip = run_cc_income(
        price_df, iv, earnings, CCConfig(shares=1000, delta=0.15, dte=30, earnings_rule="skip")
    )
    # Skipping earnings can only forgo openings, never add them.
    assert skip.cycles <= ignore.cycles


def test_synthetic_earnings_are_quarterly_and_in_window():
    start, end = pd.Timestamp("2021-01-01"), pd.Timestamp("2023-01-01")
    dates = synthetic_earnings_dates("NVDA", start, end)
    assert len(dates) >= 6  # ~4/yr over 2 years
    assert all(start <= d <= end for d in dates)
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    assert all(80 <= g <= 100 for g in gaps)
