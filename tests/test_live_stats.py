"""Live-report stats: "action" must be the position for the NEXT open, decided
on today's close, while "position" is what was held today. Network-free."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot
from backtest.strat_backtest import SMATrendFollowing


def _data(closes):
    idx = pd.bdate_range("2025-01-01", periods=len(closes), name="Date")
    c = np.asarray(closes, dtype=float)
    frames = {
        "X": pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c}, index=idx),
        "^VIX": pd.DataFrame({"Open": 15.0, "High": 15.0, "Low": 15.0, "Close": 15.0}, index=idx),
    }
    df = pd.concat(frames, axis=1).swaplevel(axis=1)
    df.columns.names = ["Price", "Ticker"]
    return df


UPTREND = list(100 + np.arange(300) * 0.1)   # ends ~129.9, SMA ~119.9, band ~ +/-2.5


def _stats(closes, **kw):
    return SMATrendFollowing(sma_window=200, **kw).get_live_stats("X", "X", data=_data(closes))


def test_steady_uptrend_holds():
    st = _stats(UPTREND)
    assert (st["action"], st["position"], st["signal_changed"]) == ("BUY/HOLD", "invested", False)


def test_break_today_is_reported_today_without_t2():
    st = _stats(UPTREND + [80.0])
    assert st["trend"] == "BEARISH"
    assert (st["action"], st["position"], st["signal_changed"]) == ("SELL/CASH", "invested", True)
    assert "confirmed, SELL at next open" in bot.status_note(st["trend"], st)


def test_single_close_below_band_is_unconfirmed_with_t2():
    st = _stats(UPTREND + [80.0], t2_confirmation=True)
    assert st["trend"] == "BEARISH"
    assert (st["action"], st["position"], st["signal_changed"]) == ("BUY/HOLD", "invested", False)
    assert "not confirmed yet" in bot.status_note(st["trend"], st)


def test_second_close_below_band_confirms_with_t2():
    st = _stats(UPTREND + [80.0, 79.0], t2_confirmation=True)
    assert (st["action"], st["position"], st["signal_changed"]) == ("SELL/CASH", "invested", True)


def test_trailing_stop_breach_at_todays_close_sells_next_open():
    # 9% under the peak but still above the lower band: only the stop fires.
    st = _stats(UPTREND + [UPTREND[-1] * 0.91], trailing_stop_pct=0.08)
    assert st["trend"] != "BEARISH"
    assert (st["action"], st["position"], st["signal_changed"]) == ("SELL/CASH", "invested", True)


def test_next_open_view_agrees_with_backtest_history():
    s = SMATrendFollowing(sma_window=200, t2_confirmation=True)
    s.get_live_stats("X", "X", data=_data(UPTREND + [80.0, 79.0, 78.0]))
    # Appending the placeholder row must not change any real day's position.
    assert s.df_next["in_market"].iloc[:-1].equals(s.df["in_market"])
