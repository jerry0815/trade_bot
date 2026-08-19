import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from options.live_monitor import (
    _collar_structure_lines, select_webhook, position_maintenance_lines,
    COLLAR_CALL_DELTA, COLLAR_PUT_DELTA,
)
from options.regime import MarketRegime


def test_collar_lines_put_below_spot_below_call():
    S = 80.0
    lines = _collar_structure_lines(S, iv_pct=25.0)
    text = "\n".join(lines)
    # Both legs described, with the roll/close-on-bear management rule and the
    # never-sell-puts guardrail present.
    assert "Sell" in text and "call" in text
    assert "Buy" in text and "put" in text
    assert "never sell puts" in text.lower()

    # Extract the two guidance strikes and check put < spot < call.
    import re
    strikes = [float(m) for m in re.findall(r"strike ≈ ([\d.]+)", text)]
    assert len(strikes) == 2
    call_k, put_k = strikes[0], strikes[1]
    assert put_k < S < call_k


def test_collar_deltas_are_the_winning_config():
    assert COLLAR_CALL_DELTA == 0.20
    assert COLLAR_PUT_DELTA == 0.15


def _pos(expiry):
    return {"open": True, "entry_date": "2026-08-15", "expiry": expiry,
            "call_strike": 88, "put_strike": 65, "contracts": 3}


def test_position_maintenance_hold_then_roll_then_expired():
    today = pd.Timestamp("2026-08-20")
    bull = MarketRegime.BULL_EXPANSION
    # 29 DTE -> hold, with a roll countdown.
    hold = "\n".join(position_maintenance_lines(_pos("2026-09-18"), today, bull))
    assert "Hold" in hold and "roll in" in hold.lower()
    # 15 DTE (<=21) -> roll now.
    roll = "\n".join(position_maintenance_lines(_pos("2026-09-04"), today, bull))
    assert "ROLL NOW" in roll
    # past expiry -> expired.
    exp = "\n".join(position_maintenance_lines(_pos("2026-08-10"), today, bull))
    assert "Expired" in exp


def test_position_maintenance_bear_says_close_both_legs():
    today = pd.Timestamp("2026-08-20")
    lines = "\n".join(position_maintenance_lines(_pos("2026-09-18"), today, MarketRegime.BEAR_DEFENSE))
    assert "close BOTH legs" in lines


def test_position_maintenance_none_prompts_to_record():
    today = pd.Timestamp("2026-08-20")
    bull = position_maintenance_lines(None, today, MarketRegime.BULL_EXPANSION)
    assert bull and "No open collar recorded" in bull[0]
    # In a bear with nothing recorded, no position line is needed.
    assert position_maintenance_lines(None, today, MarketRegime.BEAR_DEFENSE) == []


def test_select_webhook_prefers_options_channel():
    opt, shared = "https://discord/opt", "https://discord/shared"
    # Dedicated options channel wins when present.
    assert select_webhook({"OPTIONS_DISCORD_WEBHOOK": opt, "DISCORD_WEBHOOK": shared}) == opt
    # Falls back to the shared bot webhook.
    assert select_webhook({"DISCORD_WEBHOOK": shared}) == shared
    # Nothing set -> None (report prints to the log instead of posting).
    assert select_webhook({}) is None
