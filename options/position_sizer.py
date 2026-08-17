"""Contract sizing and collateral guardrails.

Enforces the risk rules from the handoff so the backtest can never open a
position the account could not actually collateralize:

* Covered calls:  ``total_short_calls <= tqqq_shares // 100`` (zero naked calls).
* Cash-secured puts: ``short_put_notional <= cash + sgov`` (100% cash-secured).
* Debit spreads: capped by a max fraction of equity spent on premium.

Every option in this engine is written on TQQQ with the standard 100-share
multiplier.
"""

from __future__ import annotations

CONTRACT_MULTIPLIER = 100


def covered_call_contracts(tqqq_shares: float, already_short_calls: int = 0) -> int:
    """Max NEW covered calls sellable: one per 100 uncovered shares."""
    capacity = int(tqqq_shares // CONTRACT_MULTIPLIER) - already_short_calls
    return max(0, capacity)


def cash_secured_put_contracts(
    cash_plus_sgov: float,
    strike: float,
    already_secured_notional: float = 0.0,
) -> int:
    """Max NEW cash-secured puts: collateral is strike x 100 per contract.

    Notional already tied up by open short puts is subtracted from available
    collateral so total secured notional never exceeds cash + SGOV.
    """
    if strike <= 0:
        return 0
    available = cash_plus_sgov - already_secured_notional
    per_contract = strike * CONTRACT_MULTIPLIER
    if per_contract <= 0 or available <= 0:
        return 0
    return int(available // per_contract)


def debit_spread_contracts(
    portfolio_value: float,
    net_debit_per_contract: float,
    max_premium_fraction: float = 0.01,
) -> int:
    """Contracts affordable within ``max_premium_fraction`` of the portfolio.

    ``net_debit_per_contract`` is the per-share debit; actual cash out is
    ``net_debit_per_contract * 100`` per contract. Tail hedges are meant to be
    cheap, so the default cap is 1% of equity.
    """
    if net_debit_per_contract <= 0:
        return 0
    budget = portfolio_value * max_premium_fraction
    per_contract_cost = net_debit_per_contract * CONTRACT_MULTIPLIER
    if per_contract_cost <= 0:
        return 0
    return int(budget // per_contract_cost)


def validate_collateral(
    short_calls: int,
    short_puts: int,
    put_strike: float,
    tqqq_shares: float,
    cash_plus_sgov: float,
) -> tuple[bool, str]:
    """Post-condition check the simulator asserts after opening a position.

    Returns ``(ok, reason)``. ``ok`` is False with a human-readable reason if any
    guardrail is violated — used as a defensive assert, not a routine path.
    """
    if short_calls * CONTRACT_MULTIPLIER > tqqq_shares + 1e-6:
        return False, (
            f"naked calls: {short_calls} contracts cover "
            f"{short_calls * CONTRACT_MULTIPLIER} shares but only {tqqq_shares:.0f} held"
        )
    secured = short_puts * put_strike * CONTRACT_MULTIPLIER
    if secured > cash_plus_sgov + 1e-6:
        return False, (
            f"under-secured puts: need ${secured:,.0f} collateral, "
            f"have ${cash_plus_sgov:,.0f}"
        )
    return True, "ok"
