import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.cc_income import CCConfig
from options.realized_iv import build_iv_frame
from options import cc_optimizer as opt


def _price_df(returns, start=100.0):
    prices = start * np.exp(np.cumsum(np.r_[0.0, returns]))
    idx = pd.bdate_range("2021-01-01", periods=len(prices))
    return pd.DataFrame({"Close": prices, "High": prices, "Low": prices}, index=idx)


def _fixture(seed=21, drift=0.0006, n=450):
    rng = np.random.default_rng(seed)
    px = _price_df(rng.normal(drift, 0.02, n))
    iv = build_iv_frame(px["Close"], vrp_mult=1.15)
    common = px.index.intersection(iv.index)
    return px.loc[common], iv.loc[common]


def test_grid_has_sixty_configs():
    price_df, iv = _fixture()
    rows = opt.sweep(price_df, iv, [], CCConfig(shares=1000))
    assert len(rows) == 60
    # Each row carries both the grid params and the KPI keys.
    assert {"delta", "dte", "ivr_gate", "earnings_rule"} <= set(rows[0])
    assert "Annualized Premium Yield (%)" in rows[0]


def test_higher_ivr_gate_means_fewer_trades():
    # A longer series makes the gate=0 ⊇ gate=30 ⊇ gate=50 opening-day subset
    # relationship dominate over reopen-timing noise.
    price_df, iv = _fixture(n=900)
    rows = opt.sweep(price_df, iv, [], CCConfig(shares=1000))
    # Hold delta/dte/earnings fixed; cycles must be non-increasing in the gate.
    for delta in (0.10, 0.20):
        for dte in (30, 45):
            for rule in ("ignore", "skip"):
                sub = sorted(
                    (r for r in rows if r["delta"] == delta and r["dte"] == dte and r["earnings_rule"] == rule),
                    key=lambda r: r["ivr_gate"],
                )
                cycles = [r["Total Cycles"] for r in sub]  # in ivr_gate order 0,30,50
                assert all(cycles[i] >= cycles[i + 1] for i in range(len(cycles) - 1))


def test_score_config_filters_on_keep_rate_and_drag():
    good = {"Keep Rate (%)": 95.0, "Total-Return Drag (pp/yr)": 1.0, "Annualized Premium Yield (%)": 10.0}
    low_keep = {"Keep Rate (%)": 70.0, "Total-Return Drag (pp/yr)": 1.0, "Annualized Premium Yield (%)": 20.0}
    high_drag = {"Keep Rate (%)": 95.0, "Total-Return Drag (pp/yr)": 5.0, "Annualized Premium Yield (%)": 20.0}
    assert opt.score_config(good)[0] == 1
    assert opt.score_config(low_keep)[0] == 0
    assert opt.score_config(high_drag)[0] == 0
    # An eligible config outranks a higher-yield but ineligible one.
    assert opt.score_config(good) > opt.score_config(low_keep)


def test_recommendation_is_deterministic():
    price_df, iv = _fixture()
    rows = opt.sweep(price_df, iv, [], CCConfig(shares=1000))
    r1 = opt.recommend(rows)
    r2 = opt.recommend(rows)
    assert (r1["delta"], r1["dte"], r1["ivr_gate"], r1["earnings_rule"]) == (
        r2["delta"], r2["dte"], r2["ivr_gate"], r2["earnings_rule"]
    )


def test_report_contains_recommendation_and_caveats():
    price_df, iv = _fixture()
    rows = opt.sweep(price_df, iv, [], CCConfig(shares=1000))
    rec = opt.recommend(rows)
    report = opt.build_report(
        {"NVDA": {"recommendation": opt._recommendation_line(rec), "table": opt._table(rows, top_n=5)}},
        span="2021-01-01 to 2023-01-01",
    )
    assert "Recommended:" in report
    assert "not tradeable P&L" in report
    assert "Keep Rate" in report
