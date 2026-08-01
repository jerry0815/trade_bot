"""
Stationary-bootstrap tail-risk analysis (Politis & Romano, 1994): resamples
the strategy's own realized daily returns using geometrically-distributed
block lengths (expected length calibrated to real crisis cadence, not an
arbitrary fixed window) to build many synthetic 26-year equity paths, then
reports the distribution of max drawdown and annualized TWR across them.

Why stationary bootstrap and not fixed-length blocks: an earlier fixed
60-day-block version of this script produced a badly biased result. With
110 fixed 60-day blocks per 26-year path, and crash-window days making up
12.8% of history, each synthetic path drew ~14 blocks touching a real
crisis on average — but any actual 26-year stretch of history has only
ever contained 2-4 major crises. The fixed-block version was effectively
simulating a world with 5-7x more crises packed into 26 years than has
ever happened. The stationary bootstrap's EXPECTED_BLOCK_LENGTH is
calibrated (see calibrate_expected_block_length()) so the average number
of crisis-touching blocks per synthetic path matches that real-world rate,
not to eliminate resampling variety altogether.

Caveat (by design, not a bug, same as the fixed-block version): this
resamples the strategy's already-realized daily returns, which already
bake in real historical entry/exit timing. It shows what a different
ORDERING/COMBINATION of the return regimes the strategy has actually
experienced could look like — it does NOT re-simulate how the strategy
would react to a genuinely different price history.

Run manually:
    python backtest/bootstrap_tail_risk.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import SMATrendFollowing, Backtester

TRADING_DAYS_PER_YEAR = 252
HORIZON_YEARS = 26
HORIZON_DAYS = HORIZON_YEARS * TRADING_DAYS_PER_YEAR
N_SIMULATIONS = 2000
SEED = 20260728            # fixed seed for reproducibility; not a "real" date, just a memorable constant
TARGET_CRASH_BLOCKS_PER_PATH = 3.0  # real 26-year windows contain ~2-4 major crises

# Known major crisis windows, used only to (a) calibrate the expected block
# length and (b) report how well-calibrated the result turned out to be —
# NOT used to bias which days get resampled.
CRISIS_WINDOWS = [
    ("Black Monday 1987",   "1987-08-25", "1987-12-04"),
    ("Dot-com crash",       "2000-03-24", "2002-10-09"),
    ("2008 GFC",            "2007-10-09", "2009-03-09"),
    ("COVID crash",         "2020-02-19", "2020-03-23"),
    ("2022 rate-shock bear","2022-01-03", "2022-10-12"),
]


def get_realized_daily_returns():
    """Runs the strategy once over the longest available history and
    returns its realized daily % return series (derived from the engine's
    own equity curve, not reimplemented), plus a same-length boolean mask
    marking which days fall inside a known crisis window."""
    strat = SMATrendFollowing(sma_window=200, atr_multiplier=2.5, t2_confirmation=True)
    env = Backtester(
        base_ticker="^NDX", signal_ticker="^GSPC", start_date="1986-04-29",
        period_years=40, leverage=3, expense_ratio=0.0095, initial_fund=10000,
        verbose=False,
    )
    res = env.run(strat)
    equity = res["equity_curve"]
    daily_returns = equity.pct_change().dropna()

    crisis_mask = pd.Series(False, index=daily_returns.index)
    for _, start, end in CRISIS_WINDOWS:
        crisis_mask.loc[start:end] = True

    return daily_returns.values, crisis_mask.values


def calibrate_expected_block_length(n_available, crisis_density, target_crash_blocks, horizon_days):
    """Picks the geometric distribution's expected block length so that the
    average number of crisis-touching blocks per synthetic path matches
    TARGET_CRASH_BLOCKS_PER_PATH, by direct search rather than a closed-form
    approximation (block/crisis overlap probability isn't a clean formula
    once block length is itself random and crisis days are clustered, not
    scattered uniformly)."""
    rng = np.random.default_rng(SEED - 1)  # separate stream from the main simulation
    candidate_lengths = [100, 200, 300, 500, 750, 1000, 1500, 2000, 3000]
    best_length, best_diff = candidate_lengths[0], float("inf")

    for L in candidate_lengths:
        p = 1.0 / L
        touches = []
        for _ in range(200):  # small calibration sample, not the full N_SIMULATIONS
            n_blocks = 0
            days_built = 0
            crash_block_count = 0
            while days_built < horizon_days:
                block_len = min(rng.geometric(p), horizon_days - days_built)
                start = rng.integers(0, n_available)
                idx = (np.arange(start, start + block_len)) % n_available
                if crisis_density[idx].any():
                    crash_block_count += 1
                days_built += block_len
                n_blocks += 1
            touches.append(crash_block_count)
        avg_touches = float(np.mean(touches))
        diff = abs(avg_touches - target_crash_blocks)
        if diff < best_diff:
            best_diff, best_length, best_avg_touches = diff, L, avg_touches

    return best_length, best_avg_touches


def stationary_bootstrap_path(daily_returns, target_length, expected_block_length, rng):
    """One synthetic path via Politis-Romano stationary bootstrap: block
    lengths are geometrically distributed (mean = expected_block_length),
    start positions uniform random, circular wraparound at series end."""
    n = len(daily_returns)
    p = 1.0 / expected_block_length
    blocks = []
    days_built = 0
    while days_built < target_length:
        block_len = min(rng.geometric(p), target_length - days_built)
        start = rng.integers(0, n)
        idx = (np.arange(start, start + block_len)) % n
        blocks.append(daily_returns[idx])
        days_built += block_len
    return np.concatenate(blocks)[:target_length]


def run_simulations(daily_returns, n_simulations, horizon_days, expected_block_length, seed):
    rng = np.random.default_rng(seed)
    results = []
    for _ in range(n_simulations):
        path_returns = stationary_bootstrap_path(daily_returns, horizon_days, expected_block_length, rng)

        equity = 10000 * np.cumprod(1 + path_returns)
        running_peak = np.maximum.accumulate(equity)
        drawdown = (equity - running_peak) / running_peak
        max_dd = drawdown.min() * 100

        total_growth = equity[-1] / 10000
        twr = (total_growth ** (TRADING_DAYS_PER_YEAR / horizon_days) - 1) * 100

        results.append({"max_drawdown": max_dd, "twr": twr})
    return pd.DataFrame(results)


if __name__ == "__main__":
    print("Fetching realized daily returns (single 1986-2026 run, bot.py's live SMA config)...")
    daily_returns, crisis_mask = get_realized_daily_returns()
    n_available = len(daily_returns)
    crisis_density = crisis_mask
    print(f"  {n_available} daily returns available to resample from "
          f"({crisis_mask.sum()} of them ({crisis_mask.mean()*100:.1f}%) fall inside a known crisis window)")

    print(f"\nCalibrating expected block length so ~{TARGET_CRASH_BLOCKS_PER_PATH:.0f} crisis-touching "
          f"blocks appear per {HORIZON_YEARS}-year synthetic path (matching real history's ~2-4 crises "
          "per 26-year window)...")
    expected_block_length, achieved_avg = calibrate_expected_block_length(
        n_available, crisis_density, TARGET_CRASH_BLOCKS_PER_PATH, HORIZON_DAYS
    )
    print(f"  Chosen expected block length: {expected_block_length} trading days "
          f"(~{expected_block_length / TRADING_DAYS_PER_YEAR:.1f} years)")
    print(f"  Achieved avg crisis-touching blocks per path in calibration sample: {achieved_avg:.2f}")

    print(f"\nRunning {N_SIMULATIONS} stationary-bootstrap simulations...")
    sim_df = run_simulations(daily_returns, N_SIMULATIONS, HORIZON_DAYS, expected_block_length, SEED)

    dd = sim_df["max_drawdown"].sort_values()
    twr = sim_df["twr"]

    print("\n=== Simulated Max Drawdown Distribution (2000 synthetic 26-year paths) ===")
    for pct in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        print(f"  P{pct:>2}: {dd.quantile(pct / 100):.2f}%")
    print(f"  Worst of {N_SIMULATIONS}: {dd.min():.2f}%")
    print(f"  Best of {N_SIMULATIONS}:  {dd.max():.2f}%")

    print("\n=== Simulated Annualized TWR Distribution ===")
    for pct in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        print(f"  P{pct:>2}: {twr.quantile(pct / 100):.2f}%")

    actual_worst_dd = -84.99  # bot.py's live config, Table 1's published Worst DD at 3x
    pct_worse_than_actual = (dd < actual_worst_dd).mean() * 100
    print("\n=== Context ===")
    print(f"Actual historical worst rolling-window drawdown (Table 1, 3x): {actual_worst_dd:.2f}%")
    print(f"  {pct_worse_than_actual:.1f}% of the {N_SIMULATIONS} simulated paths were WORSE than this")
    threshold = -80.0
    pct_worse_than_80 = (dd < threshold).mean() * 100
    print(f"Simulated paths with max drawdown worse than {threshold:.0f}%: {pct_worse_than_80:.1f}%")
