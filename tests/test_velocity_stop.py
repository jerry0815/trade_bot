import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import SMATrendFollowing


def _run(prices, in_market, pct, window, mode, cooldown):
    strat = SMATrendFollowing(
        velocity_stop_pct=pct, velocity_stop_window=window,
        velocity_stop_mode=mode, velocity_stop_cooldown_days=cooldown,
    )
    df = pd.DataFrame({"Close": prices, "in_market": in_market})
    return strat._apply_velocity_stop(df).tolist()


def test_rolling_max_triggers_on_fast_drop_and_cools_down():
    # close[4]=94 is an ~8.7% drop from the 103 peak reached at close[3];
    # decision surfaces on day 5 (lookahead-free), cooldown blocks 6-7,
    # re-entry on 8.
    prices = [100, 101, 102, 103, 94, 94, 94, 94, 94]
    out = _run(prices, [True] * 9, 0.08, 3, "rolling_max", 2)
    assert out == [True, True, True, True, True, False, False, False, True]


def test_lookahead_free_exit_lags_one_day():
    # The crash at close[4] must NOT force day-4 out; it surfaces day 5.
    prices = [100, 101, 102, 103, 94, 94, 94, 94, 94]
    out = _run(prices, [True] * 9, 0.08, 3, "rolling_max", 2)
    assert out[4] is True and out[5] is False


def test_point_to_point_ignores_shallow_intrawindow_drop():
    # At the day rolling_max fires (index 5: 94 vs the 103 peak reached 2 days
    # earlier), point_to_point compares against close[1]=101 (exactly `window`
    # days back) -> only -6.9%, so it does NOT fire there. This is the mode
    # difference at the peak-relative moment. (A later window-spaced drop in the
    # flat 94 tail can still trigger p2p, so we assert the index-5 contrast, not
    # lifelong immunity.)
    prices = [100, 101, 102, 103, 94, 94, 94, 94, 94]
    rmax = _run(prices, [True] * 9, 0.08, 3, "rolling_max", 2)
    p2p = _run(prices, [True] * 9, 0.08, 3, "point_to_point", 2)
    assert rmax[5] is False       # rolling_max exited at the peak-relative drop
    assert p2p[5] is True         # point_to_point did not fire at index 5


def test_point_to_point_triggers_on_deep_window_drop():
    # close[4]=90 vs close[1]=101 (3 days earlier) is -10.9% -> p2p fires.
    prices = [100, 101, 102, 103, 90, 90, 90, 90, 90]
    p2p = _run(prices, [True] * 9, 0.08, 3, "point_to_point", 2)
    assert p2p[5] is False


def test_slow_drift_escapes_both_modes():
    # ~2%/day decline: no single 3-day window loses 8% -> neither stop fires.
    prices = [100, 98, 96, 94, 92, 90]
    assert all(_run(prices, [True] * 6, 0.08, 3, "rolling_max", 2))
    assert all(_run(prices, [True] * 6, 0.08, 3, "point_to_point", 2))


def test_trend_exit_takes_precedence_without_cooldown():
    # Flat prices, trend forces out on day 2; re-entry is immediate on day 3
    # (a trend exit must NOT start a cooldown).
    prices = [100] * 5
    out = _run(prices, [True, True, False, True, True], 0.08, 3, "rolling_max", 2)
    assert out == [True, True, False, True, True]
