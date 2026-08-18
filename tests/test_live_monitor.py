import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.live_monitor import (
    _collar_structure_lines, select_webhook, COLLAR_CALL_DELTA, COLLAR_PUT_DELTA,
)


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


def test_select_webhook_prefers_options_channel():
    opt, shared = "https://discord/opt", "https://discord/shared"
    # Dedicated options channel wins when present.
    assert select_webhook({"OPTIONS_DISCORD_WEBHOOK": opt, "DISCORD_WEBHOOK": shared}) == opt
    # Falls back to the shared bot webhook.
    assert select_webhook({"DISCORD_WEBHOOK": shared}) == shared
    # Nothing set -> None (report prints to the log instead of posting).
    assert select_webhook({}) is None
