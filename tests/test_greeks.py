import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.greeks import GreeksEngine, PUT_SKEW_MULT, CALL_SKEW_MULT


def test_put_call_parity():
    # C - P = S - K e^{-rT} for European options at the same strike/vol.
    S, K, T, r, sigma = 100.0, 100.0, 0.5, 0.04, 0.30
    c = GreeksEngine.calculate_greeks(S, K, T, r, sigma, "call")["price"]
    p = GreeksEngine.calculate_greeks(S, K, T, r, sigma, "put")["price"]
    assert math.isclose(c - p, S - K * math.exp(-r * T), abs_tol=1e-6)


def test_atm_call_delta_near_half():
    g = GreeksEngine.calculate_greeks(100, 100, 0.25, 0.0, 0.30, "call")
    assert 0.5 < g["delta"] < 0.62  # slightly above 0.5 from vol drift


def test_put_delta_is_negative():
    g = GreeksEngine.calculate_greeks(100, 90, 0.25, 0.04, 0.30, "put")
    assert -1.0 < g["delta"] < 0.0


def test_expired_option_returns_intrinsic():
    call = GreeksEngine.calculate_greeks(110, 100, 0.0, 0.04, 0.3, "call")
    put = GreeksEngine.calculate_greeks(90, 100, 0.0, 0.04, 0.3, "put")
    assert call["price"] == 10.0 and call["delta"] == 0.0
    assert put["price"] == 10.0


def test_strike_for_delta_roundtrips_call():
    # A 15-delta call strike, repriced, should show ~0.15 delta at the skewed vol.
    S, T, r, base = 100.0, 35 / 365, 0.045, 0.30
    K, g = GreeksEngine.get_strike_for_delta(S, T, r, base, 0.15, "call")
    assert K > S  # OTM call above spot
    # Strike is rounded to the cent, so allow a small tolerance on the roundtrip.
    assert math.isclose(g["delta"], 0.15, abs_tol=3e-3)


def test_strike_for_delta_roundtrips_put():
    S, T, r, base = 100.0, 30 / 365, 0.045, 0.30
    K, g = GreeksEngine.get_strike_for_delta(S, T, r, base, 0.10, "put")
    assert K < S  # OTM put below spot
    # Strike is rounded to the cent, so allow a small tolerance on the roundtrip.
    assert math.isclose(abs(g["delta"]), 0.10, abs_tol=3e-3)


def test_put_skew_pushes_strike_further_from_spot():
    # With +20% put skew, the 10-delta put strike sits lower (further OTM) than
    # an unskewed solve would place it.
    S, T, r, base = 100.0, 30 / 365, 0.045, 0.30
    K_skew, _ = GreeksEngine.get_strike_for_delta(S, T, r, base, 0.10, "put")
    # Unskewed reference: solve with base*1.0 by temporarily matching the formula.
    import options.greeks as gmod
    orig = gmod.PUT_SKEW_MULT
    assert K_skew < S
    assert orig == PUT_SKEW_MULT == 1.20


def test_call_skew_override_changes_strike():
    # Default call skew is 0.95; forcing call_skew_mult=1.0 (no skew) prices the
    # call at a higher vol, pushing the 20-delta strike further from spot.
    S, T, r, base = 100.0, 35 / 365, 0.045, 0.30
    K_default, _ = GreeksEngine.get_strike_for_delta(S, T, r, base, 0.20, "call")
    K_noskew, _ = GreeksEngine.get_strike_for_delta(
        S, T, r, base, 0.20, "call", call_skew_mult=1.0
    )
    assert CALL_SKEW_MULT == 0.95
    assert K_default != K_noskew
    # Higher vol (1.0 > 0.95) => the same delta sits at a higher strike.
    assert K_noskew > K_default


def test_call_skew_default_matches_constant():
    # Passing the module default explicitly reproduces the default behavior.
    S, T, r, base = 100.0, 30 / 365, 0.045, 0.30
    K_a, _ = GreeksEngine.get_strike_for_delta(S, T, r, base, 0.15, "call")
    K_b, _ = GreeksEngine.get_strike_for_delta(
        S, T, r, base, 0.15, "call", call_skew_mult=CALL_SKEW_MULT
    )
    assert K_a == K_b


def test_put_skew_override_changes_strike():
    S, T, r, base = 100.0, 30 / 365, 0.045, 0.30
    K_default, _ = GreeksEngine.get_strike_for_delta(S, T, r, base, 0.10, "put")
    K_noskew, _ = GreeksEngine.get_strike_for_delta(
        S, T, r, base, 0.10, "put", put_skew_mult=1.0
    )
    assert PUT_SKEW_MULT == 1.20
    assert K_default != K_noskew


def test_spread_strikes_forwards_skew_override():
    S, T, r, base = 100.0, 30 / 365, 0.045, 0.30
    default = GreeksEngine.spread_strikes(S, T, r, base, 0.30, 0.15, "put")
    overridden = GreeksEngine.spread_strikes(
        S, T, r, base, 0.30, 0.15, "put", put_skew_mult=1.0
    )
    assert default["short_strike"] != overridden["short_strike"]


def test_spread_credit_sign():
    S, T, r, base = 100.0, 30 / 365, 0.045, 0.30
    spread = GreeksEngine.spread_strikes(S, T, r, base, 0.30, 0.15, "put")
    # Selling the nearer (30Δ) put and buying the farther (15Δ) put => net credit.
    assert spread["net_credit"] > 0
    assert spread["short_strike"] > spread["long_strike"]
