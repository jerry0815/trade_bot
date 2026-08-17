import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options import position_sizer as sz


def test_covered_call_one_contract_per_100_shares():
    assert sz.covered_call_contracts(350) == 3
    assert sz.covered_call_contracts(99) == 0
    assert sz.covered_call_contracts(350, already_short_calls=2) == 1


def test_covered_call_never_negative():
    assert sz.covered_call_contracts(100, already_short_calls=5) == 0


def test_cash_secured_put_respects_collateral():
    # $50k, strike 40 => 40*100 = $4k per contract => 12 contracts.
    assert sz.cash_secured_put_contracts(50_000, 40) == 12
    # Already-secured notional reduces capacity.
    assert sz.cash_secured_put_contracts(50_000, 40, already_secured_notional=42_000) == 2


def test_cash_secured_put_zero_when_underfunded():
    assert sz.cash_secured_put_contracts(1_000, 40) == 0


def test_debit_spread_capped_by_budget_fraction():
    # 1% of $100k = $1k budget; $2/share debit => $200/contract => 5 contracts.
    assert sz.debit_spread_contracts(100_000, 2.0, max_premium_fraction=0.01) == 5


def test_validate_collateral_flags_naked_calls():
    ok, reason = sz.validate_collateral(
        short_calls=4, short_puts=0, put_strike=0, tqqq_shares=300, cash_plus_sgov=0
    )
    assert not ok and "naked" in reason


def test_validate_collateral_flags_undersecured_puts():
    ok, reason = sz.validate_collateral(
        short_calls=0, short_puts=5, put_strike=40, tqqq_shares=0, cash_plus_sgov=10_000
    )
    assert not ok and "secured" in reason


def test_validate_collateral_passes_when_within_limits():
    ok, reason = sz.validate_collateral(
        short_calls=3, short_puts=2, put_strike=40, tqqq_shares=300, cash_plus_sgov=8_000
    )
    assert ok and reason == "ok"
