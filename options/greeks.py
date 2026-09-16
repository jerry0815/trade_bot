"""Black-Scholes Greeks and a skew-adjusted delta -> strike solver.

The overlay never quotes a live option chain during a backtest; it *prices*
options analytically from the underlying price and an implied-vol input (the
^VXN index, used as an institutional proxy for TQQQ's option IV). This module
is the pricing kernel.

Conventions
-----------
* ``sigma`` is an annualized implied vol as a decimal (0.25 == 25% IV). Convert
  a ^VXN quote of 25.0 with ``sigma = vxn / 100``.
* ``T`` is time to expiry in *years* (``dte / 365``).
* ``target_delta`` in :func:`get_strike_for_delta` is the *absolute magnitude*
  in (0, 1): 0.15 means a 15-delta option whether it is a put or a call.
* Skew: OTM puts on a 3x ETF trade rich, OTM calls trade slightly cheap. We
  apply an empirical multiplicative offset (+20% IV to puts, -5% to calls) so a
  "15-delta call" strike lands where the real, skewed chain would put it.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

# Empirical TQQQ vertical-skew multipliers applied to the ATM base vol.
PUT_SKEW_MULT = 1.20   # OTM puts trade ~20% above ATM IV
CALL_SKEW_MULT = 0.95  # OTM calls trade ~5% below ATM IV


class GreeksEngine:
    """Stateless Black-Scholes calculator (all methods are class/staticmethods)."""

    @staticmethod
    def calculate_greeks(
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str = "call",
    ) -> dict:
        """Return price and Greeks for a single European option.

        ``vega`` is per 1 percentage-point move in IV; ``theta`` is per calendar
        day. Degenerate inputs (expired, zero vol, non-positive strike) return a
        zeroed dict with the option's intrinsic value so callers never divide by
        zero.
        """
        option_type = option_type.lower()
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            if option_type == "call":
                intrinsic = max(S - K, 0.0)
            else:
                intrinsic = max(K - S, 0.0)
            return {
                "price": float(intrinsic),
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
            }

        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        if option_type == "call":
            price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
            delta = norm.cdf(d1)
            theta = (
                -(S * norm.pdf(d1) * sigma) / (2 * sqrt_T)
                - r * K * math.exp(-r * T) * norm.cdf(d2)
            ) / 365.0
        elif option_type == "put":
            price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            delta = norm.cdf(d1) - 1.0
            theta = (
                -(S * norm.pdf(d1) * sigma) / (2 * sqrt_T)
                + r * K * math.exp(-r * T) * norm.cdf(-d2)
            ) / 365.0
        else:
            raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

        gamma = norm.pdf(d1) / (S * sigma * sqrt_T)
        vega = S * norm.pdf(d1) * sqrt_T / 100.0

        return {
            "price": float(price),
            "delta": float(delta),
            "gamma": float(gamma),
            "theta": float(theta),
            "vega": float(vega),
        }

    @classmethod
    def get_strike_for_delta(
        cls,
        S: float,
        T: float,
        r: float,
        base_sigma: float,
        target_delta: float,
        option_type: str = "put",
        put_skew_mult: float | None = None,
        call_skew_mult: float | None = None,
    ) -> tuple[float, dict]:
        """Solve for the strike whose delta magnitude equals ``target_delta``.

        Applies the vertical-skew offset before inverting Black-Scholes, so the
        returned strike matches where the real, skewed chain would place that
        delta. Returns ``(strike, greeks)`` where ``greeks`` is priced at the
        skew-adjusted vol.

        ``put_skew_mult`` / ``call_skew_mult`` override the module-level
        :data:`PUT_SKEW_MULT` / :data:`CALL_SKEW_MULT` when supplied (e.g. a
        single-name study calibrating its own skew). Omitting them reproduces
        the historical TQQQ behavior exactly, so the change is backward
        compatible. Only the multiplier for ``option_type`` is consulted.
        """
        option_type = option_type.lower()
        if not 0.0 < target_delta < 1.0:
            raise ValueError(f"target_delta must be in (0, 1), got {target_delta}")

        put_mult = PUT_SKEW_MULT if put_skew_mult is None else put_skew_mult
        call_mult = CALL_SKEW_MULT if call_skew_mult is None else call_skew_mult
        adj_sigma = base_sigma * (put_mult if option_type == "put" else call_mult)
        sqrt_T = math.sqrt(T)

        # For a call, delta = N(d1) -> N(d1) = target_delta.
        # For a put,  delta = N(d1) - 1 -> |delta| = 1 - N(d1) -> N(d1) = 1 - target_delta.
        n_d1 = target_delta if option_type == "call" else (1.0 - target_delta)
        d1 = float(norm.ppf(n_d1))

        # Invert d1 = (ln(S/K) + (r + 0.5 sigma^2) T) / (sigma sqrt(T)) for K.
        K = S * math.exp((r + 0.5 * adj_sigma ** 2) * T - d1 * adj_sigma * sqrt_T)
        K = round(float(K), 2)
        greeks = cls.calculate_greeks(S, K, T, r, adj_sigma, option_type)
        return K, greeks

    @classmethod
    def spread_strikes(
        cls,
        S: float,
        T: float,
        r: float,
        base_sigma: float,
        short_delta: float,
        long_delta: float,
        option_type: str = "put",
        put_skew_mult: float | None = None,
        call_skew_mult: float | None = None,
    ) -> dict:
        """Build a two-leg vertical spread by delta.

        ``short_delta`` is the nearer-the-money (larger-delta) leg that is sold;
        ``long_delta`` is the farther-OTM (smaller-delta) leg that is bought as
        protection. For a put debit spread the roles invert (the larger-delta
        leg is bought) — callers interpret net_premium's sign: positive means a
        net credit received, negative means a net debit paid.

        ``put_skew_mult`` / ``call_skew_mult`` are passed through to
        :meth:`get_strike_for_delta` unchanged (default = module constants).
        """
        short_K, short_g = cls.get_strike_for_delta(
            S, T, r, base_sigma, short_delta, option_type,
            put_skew_mult=put_skew_mult, call_skew_mult=call_skew_mult,
        )
        long_K, long_g = cls.get_strike_for_delta(
            S, T, r, base_sigma, long_delta, option_type,
            put_skew_mult=put_skew_mult, call_skew_mult=call_skew_mult,
        )
        net_credit = short_g["price"] - long_g["price"]
        return {
            "short_strike": short_K,
            "long_strike": long_K,
            "short_greeks": short_g,
            "long_greeks": long_g,
            "net_credit": float(net_credit),
        }
