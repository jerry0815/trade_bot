"""Event-driven options-overlay backtester.

Unlike the vectorized trend engine in ``backtest/strat_backtest.py``, this
simulator walks the daily bars one at a time because option legs carry state the
trend engine has no notion of: days-to-expiry, per-leg mark-to-market, profit
targets, and collateral. It layers that overlay on top of a 3-state equity
sleeve (100% TQQQ / 50-50 / 100% SGOV) driven by the regime state machine.

Accounting model
----------------
NAV is decomposed as::

    nav = sleeve_value + unrealized_option_pnl

* ``sleeve_value`` is the compounding book (equity + cash). It grows daily by the
  sleeve return ``w_eq * r_tqqq + (1 - w_eq) * cash_daily`` where ``w_eq`` is the
  regime's target equity weight and TQQQ's *actual* (already-3x) daily return is
  used. When an option position closes, its realized P&L is **settled into**
  ``sleeve_value`` so it compounds thereafter — exactly as a real account's
  option cashflows reduce (or add to) the capital that keeps compounding.
* Each open option position contributes its mark-to-market P&L relative to
  inception, ``(value_now - value_entry) * 100 * contracts`` where ``value`` is
  the structure's per-share value from a long holder's perspective
  (``sum(direction * leg_price)``). Opening is therefore NAV-neutral, decay of a
  short shows up as positive P&L, and assignment risk shows up as negative P&L.

Options are cash-settled at intrinsic on expiry — a deliberate simplification
that captures the economics (capped upside on covered calls, tail losses on
puts) without modelling share assignment. Because realized option P&L is folded
back into the compounding base, the reported returns and drawdowns stay
self-consistent even when cumulative option P&L is large relative to the book
(the earlier "linear, non-reinvested" ledger distorted drawdowns in that case).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .greeks import GreeksEngine, PUT_SKEW_MULT, CALL_SKEW_MULT
from .regime import (
    MarketRegime,
    OptionAction,
    RegimeParams,
    classify_regime,
)
from . import position_sizer as sizer

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Position representation
# --------------------------------------------------------------------------- #
@dataclass
class Leg:
    option_type: str  # "call" or "put"
    strike: float
    direction: int    # +1 long, -1 short
    skew_mult: float  # IV multiplier applied to base vol for this leg


@dataclass
class OptionPosition:
    action: OptionAction
    contracts: int
    entry_date: pd.Timestamp
    entry_dte: int
    dte_remaining: int
    legs: list[Leg]
    value_entry: float          # per-share structure value at inception (signed)
    label: str = ""
    _value_now: float = 0.0     # cached per-share value, refreshed each reprice

    @property
    def is_credit(self) -> bool:
        return self.value_entry < 0

    def pnl(self) -> float:
        return (self._value_now - self.value_entry) * 100 * self.contracts


@dataclass
class OverlayConfig:
    model: str = "dynamic"          # buy_hold | trend | static_cc | dynamic | hedge_only
    initial_capital: float = 10_000.0
    risk_free: float = 0.045
    cash_yield: float = 0.045        # SGOV sleeve annual yield
    regime: RegimeParams = field(default_factory=RegimeParams)

    # DTE at entry per structure (matrix midpoints).
    dte_put_debit: int = 45
    dte_covered_call: int = 35
    dte_csp: int = 30
    dte_bull_put: int = 30
    dte_static_cc: int = 30

    # Exit triggers.
    profit_take_pct: float = 0.50    # close shorts at 50% of max profit
    min_dte_exit: int = 21           # gamma cutoff for shorts
    bps_loss_mult: float = 2.0       # bull-put stop: cost-to-close >= 2x credit
    debit_take_gain: float = 2.0     # close debit spread at +100% (value doubles)
    debit_stop_frac: float = 0.50    # close debit spread at -50%
    debit_ivr_exit: float = 55.0     # also close debit spread if IVR climbs here

    static_cc_delta: float = 0.20    # Model 3 fixed covered-call delta

    # -- entry filters (opt-in) ------------------------------------------- #
    # Extra confirmation gates applied *before opening a premium-selling*
    # structure (covered call, cash-secured put, bull-put spread, static CC).
    # Premium sellers are short gamma: a strong, fast trend runs through the
    # short strike and turns theta income into a loss. These filters skip those
    # opens; protective structures (hedge_only, collar) are never filtered.
    # Default OFF so existing benchmark numbers are unchanged — enable with
    # use_entry_filters=True (needs an "ADX" column for the ADX gate; the RSI
    # gate works from the always-present "RSI" column).
    use_entry_filters: bool = False
    adx_period: int = 14
    premium_adx_max: float = 40.0   # skip premium sells when ADX >= this (strong trend)
    cc_rsi_max: float = 80.0        # skip covered calls when RSI >= this (blow-off run)
    premium_rsi_min: float = 20.0   # skip premium sells when RSI <= this (falling knife)

    # ^VXN is the *1x* Nasdaq-100 vol index, but options here are on the *3x*
    # TQQQ, whose realized vol runs ~2.5x VXN (measured 2018-2026: median 2.51x,
    # mean 2.58x). Pricing off raw VXN underprices every option ~2.5x in vol
    # terms and makes *buying* options look like free money; this multiplier
    # lifts the pricing/strike-selection vol toward TQQQ's real level. IV-Rank
    # (regime gating) is a scale-invariant percentile and is left on raw VXN.
    pricing_iv_mult: float = 2.5

    # Sizing caps.
    debit_premium_fraction: float = 0.01  # tail hedge budget as fraction of NAV

    # -- hedge_only model (Model 5): long put-debit hedge held as *insurance* -- #
    # Insurance semantics differ from the dynamic model's debit *trade*: the hedge
    # is held through vol spikes (no IVR exit, no -50% stop — those sell protection
    # exactly when it starts paying off) and is only carried while equity is at
    # risk. It is rolled near expiry and profit-taken on a crash.
    hedge_in_bull: bool = True            # carry the hedge in BULL_EXPANSION
    hedge_in_transition: bool = True      # carry the hedge in TRANSITION_BAND
    hedge_max_ivr: float = 100.0          # only *open* when IV-Rank <= this (cheap vol)
    hedge_premium_fraction: float = 0.01  # per-roll budget as fraction of NAV
    hedge_take_gain: float = 3.0          # let a working hedge run to +200% before taking

    # -- collar model (Model 6): covered call financing a protective put -- #
    collar_call_delta: float = 0.20   # short overwrite call
    collar_put_delta: float = 0.15    # long protective put (financed by the call)
    dte_collar: int = 30

    # -- taxable-account model -------------------------------------------- #
    # When taxable=True the simulator switches to a two-bucket (equity + cash)
    # book with real cost-basis tracking: it trades only on regime changes
    # (not the daily reweight), realizes gains when it sells equity or closes an
    # option, and taxes net realized short-term gains once a year at tax_rate,
    # carrying losses forward. tax_rate=0 gives the pre-tax version of the same
    # regime-traded framework (to isolate the tax drag).
    taxable: bool = False
    tax_rate: float = 0.35   # blended short-term (federal + state); options + fast rotations are ST


@dataclass
class BacktestResult:
    model: str
    equity_curve: pd.Series
    kpis: dict
    closed_positions: list


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #
class OptionsOverlayBacktester:
    """Runs one model over a prepared daily DataFrame.

    Expected columns in ``data`` (indexed by date):
        Close   : TQQQ daily close (actual ETF price)
        SMA     : 200-day SMA of Close
        ATR     : 14-day ATR of TQQQ
        RSI     : 14-day RSI of Close
        IV      : implied-vol proxy in percent (^VXN close, e.g. 25.0)
        IV_Rank : rolling 252-day IV-Rank (0-100)
    """

    def __init__(self, config: OverlayConfig | None = None):
        self.cfg = config or OverlayConfig()

    # -- per-leg / per-position pricing ----------------------------------- #
    def _reprice(self, pos: OptionPosition, S: float, sigma_base: float) -> float:
        """Refresh and return the position's per-share value at (S, sigma)."""
        T = max(pos.dte_remaining, 0) / 365.0
        value = 0.0
        for leg in pos.legs:
            g = GreeksEngine.calculate_greeks(
                S, leg.strike, T, self.cfg.risk_free, sigma_base * leg.skew_mult, leg.option_type
            )
            value += leg.direction * g["price"]
        pos._value_now = value
        return value

    # -- entry filters ----------------------------------------------------- #
    #: premium-selling (short-gamma) actions the filters apply to.
    _PREMIUM_SELLERS = frozenset({
        OptionAction.SELL_COVERED_CALL,
        OptionAction.SELL_CASH_SECURED_PUT,
        OptionAction.SELL_BULL_PUT_SPREAD,
    })

    def _entry_allowed(self, action: OptionAction, rsi: float, adx: float) -> tuple[bool, str]:
        """Confirmation gate before opening a premium-selling structure.

        Returns ``(allowed, reason)``. When ``use_entry_filters`` is off, always
        allows. Only premium sellers are gated; unknown (NaN) indicator values
        never block, so the ADX gate no-ops when no "ADX" column is supplied.
        """
        cfg = self.cfg
        if not cfg.use_entry_filters or action not in self._PREMIUM_SELLERS:
            return True, ""
        # Strong, fast trend -> short strikes get run over.
        if adx == adx and adx >= cfg.premium_adx_max:
            return False, f"ADX {adx:.0f} >= {cfg.premium_adx_max:.0f}"
        # Falling knife -> don't sell into a collapse (covers CSP/BPS too).
        if rsi == rsi and rsi <= cfg.premium_rsi_min:
            return False, f"RSI {rsi:.0f} <= {cfg.premium_rsi_min:.0f}"
        # Blow-off momentum -> a covered call caps the very run we want.
        if action == OptionAction.SELL_COVERED_CALL and rsi == rsi and rsi >= cfg.cc_rsi_max:
            return False, f"RSI {rsi:.0f} >= {cfg.cc_rsi_max:.0f}"
        return True, ""

    # -- hedge_only (Model 5) helpers ------------------------------------- #
    def _hedge_eligible(self, regime: MarketRegime, iv_rank: float) -> bool:
        """True when a hedge may be *opened* this day (equity at risk, cheap vol)."""
        cfg = self.cfg
        in_zone = (
            (regime == MarketRegime.BULL_EXPANSION and cfg.hedge_in_bull)
            or (regime == MarketRegime.TRANSITION_BAND and cfg.hedge_in_transition)
        )
        if not in_zone:
            return False
        # IV-Rank NaN (warm-up) counts as eligible; only an above-threshold reading blocks.
        return not (iv_rank == iv_rank and iv_rank > cfg.hedge_max_ivr)

    def _should_close_hedge(self, pos: OptionPosition, regime: MarketRegime) -> str | None:
        """Insurance-style exits: roll near expiry, take a crash payoff, drop when
        equity is no longer at risk. Deliberately no IVR-exit and no stop-loss —
        both would sell protection exactly when it begins to work."""
        cfg = self.cfg
        if pos.dte_remaining <= 0:
            return "EXPIRY"
        if pos.value_entry > 0 and pos._value_now >= cfg.hedge_take_gain * pos.value_entry:
            return "HEDGE_TAKE_PROFIT"
        if pos.dte_remaining <= cfg.min_dte_exit:
            return "HEDGE_ROLL_21DTE"
        # Danger passed: fully back into cash (bear sleeve is 100% SGOV) -> stop paying.
        if regime == MarketRegime.BEAR_DEFENSE:
            return "HEDGE_REGIME_EXIT"
        return None

    # -- exit decisions ---------------------------------------------------- #
    def _should_close(self, pos: OptionPosition, regime: MarketRegime, iv_rank: float) -> str | None:
        """Return a close reason, or None to keep the position open."""
        cfg = self.cfg

        # Bear regime forces buy-to-close on covered calls before equity exit.
        if pos.action == OptionAction.SELL_COVERED_CALL and regime == MarketRegime.BEAR_DEFENSE:
            return "BEAR_CC_LIQUIDATION"

        if pos.dte_remaining <= 0:
            return "EXPIRY"

        if pos.is_credit:
            entry, now = pos.value_entry, pos._value_now  # both <= 0 at credit
            # value_entry is a negative credit; capturing `profit_take_pct` of it
            # means the cost-to-close has decayed to (1 - pct) of the credit, i.e.
            # now (still negative) has risen to entry * (1 - pct).
            if now >= entry * (1 - cfg.profit_take_pct):
                return "PROFIT_TARGET"
            if pos.action == OptionAction.SELL_BULL_PUT_SPREAD:
                # Stop when cost-to-close (=-now) reaches loss_mult x credit (=-entry).
                if -now >= cfg.bps_loss_mult * (-entry):
                    return "STOP_LOSS_2X"
            if pos.dte_remaining <= cfg.min_dte_exit:
                return "GAMMA_21DTE"
        else:
            entry, now = pos.value_entry, pos._value_now  # both > 0 (debit)
            if entry > 0:
                if now >= cfg.debit_take_gain * entry:
                    return "DEBIT_TAKE_100PCT"
                if now <= cfg.debit_stop_frac * entry:
                    return "DEBIT_STOP_50PCT"
            if iv_rank == iv_rank and iv_rank > cfg.debit_ivr_exit:
                return "DEBIT_IVR_EXIT"
            if pos.dte_remaining <= 0:
                return "EXPIRY"
        return None

    # -- position construction -------------------------------------------- #
    def _open_position(
        self,
        action: OptionAction,
        S: float,
        sigma_base: float,
        nav: float,
        w_eq: float,
        date: pd.Timestamp,
        premium_fraction: float | None = None,
    ) -> OptionPosition | None:
        cfg = self.cfg
        rp = cfg.regime
        r = cfg.risk_free

        if action == OptionAction.SELL_COVERED_CALL:
            dte = cfg.dte_covered_call
            delta = rp.cc_delta
            T = dte / 365.0
            K, g = GreeksEngine.get_strike_for_delta(S, T, r, sigma_base, delta, "call")
            shares = (nav * w_eq) / S
            contracts = sizer.covered_call_contracts(shares)
            if contracts < 1:
                return None
            legs = [Leg("call", K, -1, CALL_SKEW_MULT)]
            value_entry = -g["price"]
            label = f"CC {delta:.2f}Δ K={K}"

        elif action == OptionAction.SELL_CASH_SECURED_PUT:
            dte = cfg.dte_csp
            delta = rp.csp_delta
            T = dte / 365.0
            K, g = GreeksEngine.get_strike_for_delta(S, T, r, sigma_base, delta, "put")
            cash = nav * (1.0 - w_eq) if w_eq < 1.0 else nav
            contracts = sizer.cash_secured_put_contracts(cash, K)
            if contracts < 1:
                return None
            legs = [Leg("put", K, -1, PUT_SKEW_MULT)]
            value_entry = -g["price"]
            label = f"CSP {delta:.2f}Δ K={K}"

        elif action == OptionAction.SELL_BULL_PUT_SPREAD:
            dte = cfg.dte_bull_put
            T = dte / 365.0
            spread = GreeksEngine.spread_strikes(
                S, T, r, sigma_base, rp.bps_short_delta, rp.bps_long_delta, "put"
            )
            width = spread["short_strike"] - spread["long_strike"]
            if width <= 0:
                return None
            collateral = nav * (1.0 - w_eq) if w_eq < 1.0 else nav
            contracts = int(collateral // (width * 100))
            if contracts < 1:
                return None
            legs = [
                Leg("put", spread["short_strike"], -1, PUT_SKEW_MULT),
                Leg("put", spread["long_strike"], +1, PUT_SKEW_MULT),
            ]
            value_entry = spread["long_greeks"]["price"] - spread["short_greeks"]["price"]
            label = f"BPS {spread['short_strike']}/{spread['long_strike']}"

        elif action == OptionAction.BUY_PUT_DEBIT_SPREAD:
            dte = cfg.dte_put_debit
            T = dte / 365.0
            long_K, long_g = GreeksEngine.get_strike_for_delta(
                S, T, r, sigma_base, rp.debit_long_delta, "put"
            )
            short_K, short_g = GreeksEngine.get_strike_for_delta(
                S, T, r, sigma_base, rp.debit_short_delta, "put"
            )
            net_debit = long_g["price"] - short_g["price"]
            if net_debit <= 0:
                return None
            frac = cfg.debit_premium_fraction if premium_fraction is None else premium_fraction
            contracts = sizer.debit_spread_contracts(nav, net_debit, frac)
            if contracts < 1:
                return None
            legs = [
                Leg("put", long_K, +1, PUT_SKEW_MULT),
                Leg("put", short_K, -1, PUT_SKEW_MULT),
            ]
            value_entry = net_debit
            label = f"PDS {long_K}/{short_K}"
        else:
            return None

        pos = OptionPosition(
            action=action,
            contracts=contracts,
            entry_date=date,
            entry_dte=dte,
            dte_remaining=dte,
            legs=legs,
            value_entry=float(value_entry),
            label=label,
        )
        pos._value_now = float(value_entry)
        return pos

    def _static_cc_position(self, S, sigma_base, nav, w_eq, date) -> OptionPosition | None:
        """Model 3: mechanical fixed-delta covered call ignoring IV-Rank."""
        cfg = self.cfg
        dte = cfg.dte_static_cc
        T = dte / 365.0
        K, g = GreeksEngine.get_strike_for_delta(
            S, T, cfg.risk_free, sigma_base, cfg.static_cc_delta, "call"
        )
        shares = (nav * w_eq) / S
        contracts = sizer.covered_call_contracts(shares)
        if contracts < 1:
            return None
        pos = OptionPosition(
            action=OptionAction.SELL_COVERED_CALL,
            contracts=contracts,
            entry_date=date,
            entry_dte=dte,
            dte_remaining=dte,
            legs=[Leg("call", K, -1, CALL_SKEW_MULT)],
            value_entry=float(-g["price"]),
            label=f"StaticCC {cfg.static_cc_delta:.2f}Δ K={K}",
        )
        pos._value_now = pos.value_entry
        return pos

    def _collar_position(self, S, sigma_base, nav, w_eq, date) -> OptionPosition | None:
        """Model 6: short overwrite call + long protective put on the same equity.
        The call premium partly (or fully) finances the put, so the structure
        caps the top AND cuts the tail for little net cost."""
        cfg = self.cfg
        dte = cfg.dte_collar
        T = dte / 365.0
        r = cfg.risk_free
        Kc, gc = GreeksEngine.get_strike_for_delta(S, T, r, sigma_base, cfg.collar_call_delta, "call")
        Kp, gp = GreeksEngine.get_strike_for_delta(S, T, r, sigma_base, cfg.collar_put_delta, "put")
        shares = (nav * w_eq) / S
        contracts = sizer.covered_call_contracts(shares)
        if contracts < 1:
            return None
        pos = OptionPosition(
            action=OptionAction.SELL_COVERED_CALL,
            contracts=contracts,
            entry_date=date,
            entry_dte=dte,
            dte_remaining=dte,
            legs=[Leg("call", Kc, -1, CALL_SKEW_MULT), Leg("put", Kp, +1, PUT_SKEW_MULT)],
            value_entry=float(-gc["price"] + gp["price"]),  # short call credit + long put debit
            label=f"Collar C{cfg.collar_call_delta:.2f}/P{cfg.collar_put_delta:.2f}",
        )
        pos._value_now = pos.value_entry
        return pos

    def _should_close_collar(self, pos: OptionPosition, regime: MarketRegime) -> str | None:
        """Roll near expiry; hold the put through the transition crash; drop once
        the sleeve is fully in cash (bear)."""
        if pos.dte_remaining <= 0:
            return "EXPIRY"
        if pos.dte_remaining <= self.cfg.min_dte_exit:
            return "COLLAR_ROLL"
        if regime == MarketRegime.BEAR_DEFENSE:
            return "COLLAR_REGIME_EXIT"
        return None

    # -- main loop --------------------------------------------------------- #
    def run(self, data: pd.DataFrame) -> BacktestResult:
        cfg = self.cfg
        if cfg.taxable:
            return self._run_taxable(data)
        df = data.dropna(subset=["Close"]).copy()
        n = len(df)

        close = df["Close"].values.astype(float)
        sma = df["SMA"].values.astype(float)
        atr = df["ATR"].values.astype(float)
        rsi = df["RSI"].values.astype(float)
        iv = df["IV"].values.astype(float)
        ivr = df["IV_Rank"].values.astype(float)
        adx = (df["ADX"].values.astype(float) if "ADX" in df.columns
               else np.full(n, np.nan))
        dates = df.index

        ret = np.empty(n)
        ret[0] = 0.0
        ret[1:] = close[1:] / close[:-1] - 1.0
        cash_daily = cfg.cash_yield / TRADING_DAYS
        filtered_opens = 0  # premium-sell opens skipped by entry filters

        # ``sleeve_value`` is the compounding book (equity + cash). Realized option
        # P&L is settled into it on every close so it compounds thereafter, exactly
        # as a real account's option cashflows would. ``realized_opt`` is kept only
        # for reporting the raw (un-compounded) option total.
        sleeve_value = cfg.initial_capital
        realized_opt = 0.0
        open_positions: list[OptionPosition] = []
        closed: list = []
        premium_collected = 0.0
        debit_paid = 0.0

        nav_curve = np.empty(n)

        options_on = cfg.model in ("static_cc", "dynamic", "hedge_only", "collar")
        force_full_equity = cfg.model == "buy_hold"

        for i in range(n):
            S = close[i]
            sigma_base = iv[i] / 100.0 if iv[i] == iv[i] and iv[i] > 1.5 else (
                iv[i] if iv[i] == iv[i] else 0.0
            )
            sigma_base *= cfg.pricing_iv_mult  # lift 1x-VXN to TQQQ's ~3x realized vol

            # 1. Equity sleeve compounds by the regime weight (uses today's return).
            if force_full_equity:
                w_eq = 1.0
                regime_state = None
            else:
                regime_state = classify_regime(
                    S, sma[i], atr[i], ivr[i], rsi[i], cfg.regime
                )
                w_eq = regime_state.target_equity_pct
            sleeve_value *= (1.0 + w_eq * ret[i] + (1.0 - w_eq) * cash_daily)

            # 2. Age and reprice open positions, then apply exit rules.
            regime = regime_state.regime if regime_state else MarketRegime.BULL_EXPANSION
            still_open: list[OptionPosition] = []
            for pos in open_positions:
                if i > 0:
                    pos.dte_remaining -= (dates[i] - dates[i - 1]).days
                self._reprice(pos, S, sigma_base if sigma_base > 0 else 0.01)
                if cfg.model == "hedge_only":
                    reason = self._should_close_hedge(pos, regime)
                elif cfg.model == "collar":
                    reason = self._should_close_collar(pos, regime)
                else:
                    reason = self._should_close(pos, regime, ivr[i])
                if reason is not None:
                    pnl = pos.pnl()
                    realized_opt += pnl
                    sleeve_value += pnl  # settle P&L into the compounding book
                    closed.append({
                        "label": pos.label,
                        "action": pos.action.value,
                        "entry_date": pos.entry_date,
                        "exit_date": dates[i],
                        "contracts": pos.contracts,
                        "pnl": pos.pnl(),
                        "reason": reason,
                    })
                else:
                    still_open.append(pos)
            open_positions = still_open

            # 3. Open new positions per the model.
            if options_on and sigma_base > 0 and not force_full_equity:
                if cfg.model == "static_cc":
                    if regime == MarketRegime.BULL_EXPANSION and not any(
                        p.action == OptionAction.SELL_COVERED_CALL for p in open_positions
                    ):
                        allowed, _ = self._entry_allowed(
                            OptionAction.SELL_COVERED_CALL, rsi[i], adx[i])
                        if not allowed:
                            filtered_opens += 1
                        pos = (self._static_cc_position(S, sigma_base, sleeve_value, w_eq, dates[i])
                               if allowed else None)
                        if pos is not None:
                            open_positions.append(pos)
                            premium_collected += -pos.value_entry * 100 * pos.contracts
                elif cfg.model == "hedge_only":
                    if self._hedge_eligible(regime, ivr[i]) and not open_positions:
                        pos = self._open_position(
                            OptionAction.BUY_PUT_DEBIT_SPREAD, S, sigma_base,
                            sleeve_value, w_eq, dates[i],
                            premium_fraction=cfg.hedge_premium_fraction,
                        )
                        if pos is not None:
                            open_positions.append(pos)
                            debit_paid += pos.value_entry * 100 * pos.contracts
                elif cfg.model == "collar":
                    if regime in (MarketRegime.BULL_EXPANSION, MarketRegime.TRANSITION_BAND) \
                            and not open_positions:
                        pos = self._collar_position(S, sigma_base, sleeve_value, w_eq, dates[i])
                        if pos is not None:
                            open_positions.append(pos)
                            net = pos.value_entry * 100 * pos.contracts
                            if net < 0:
                                premium_collected += -net
                            else:
                                debit_paid += net
                else:  # dynamic
                    action = regime_state.option_action
                    if action != OptionAction.IDLE and not any(
                        p.action == action for p in open_positions
                    ):
                        allowed, _ = self._entry_allowed(action, rsi[i], adx[i])
                        if not allowed:
                            filtered_opens += 1
                        pos = (self._open_position(
                            action, S, sigma_base, sleeve_value, w_eq, dates[i]
                        ) if allowed else None)
                        if pos is not None:
                            open_positions.append(pos)
                            if pos.is_credit:
                                premium_collected += -pos.value_entry * 100 * pos.contracts
                            else:
                                debit_paid += pos.value_entry * 100 * pos.contracts

            # 4. Mark NAV. Realized P&L is already in sleeve_value; only add the
            #    mark-to-market of positions still open.
            unrealized = sum(p.pnl() for p in open_positions)
            nav_curve[i] = sleeve_value + unrealized

        end_unrealized = sum(p.pnl() for p in open_positions)
        total_option_pnl = realized_opt + end_unrealized

        equity_curve = pd.Series(nav_curve, index=dates)
        kpis = self._compute_kpis(
            equity_curve, closed, premium_collected, debit_paid, total_option_pnl
        )
        kpis["Entry-Filter Blocks"] = filtered_opens
        return BacktestResult(cfg.model, equity_curve, kpis, closed)

    # -- taxable two-bucket loop ------------------------------------------- #
    def _run_taxable(self, data: pd.DataFrame) -> BacktestResult:
        """Two-bucket (equity + cash) book with cost-basis tracking. Trades only
        on regime changes; realizes gains on equity sales and option closes; taxes
        net short-term gains once a year, carrying losses forward. Everything is
        short-term (fast rotations + <1y options) so a single rate is used."""
        cfg = self.cfg
        df = data.dropna(subset=["Close"]).copy()
        n = len(df)
        close = df["Close"].values.astype(float)
        sma = df["SMA"].values.astype(float)
        atr = df["ATR"].values.astype(float)
        rsi = df["RSI"].values.astype(float)
        iv = df["IV"].values.astype(float)
        ivr = df["IV_Rank"].values.astype(float)
        adx = (df["ADX"].values.astype(float) if "ADX" in df.columns
               else np.full(n, np.nan))
        dates = df.index
        ret = np.empty(n)
        ret[0] = 0.0
        ret[1:] = close[1:] / close[:-1] - 1.0
        cash_daily = cfg.cash_yield / TRADING_DAYS
        rate = cfg.tax_rate
        filtered_opens = 0

        equity_mv = 0.0
        cash_mv = cfg.initial_capital
        equity_basis = 0.0
        loss_carry = 0.0
        realized_ytd = 0.0
        taxes_paid = 0.0
        open_positions: list[OptionPosition] = []
        closed: list = []
        premium_collected = 0.0
        debit_paid = 0.0
        realized_opt = 0.0
        nav_curve = np.empty(n)

        options_on = cfg.model in ("static_cc", "dynamic", "hedge_only")
        force_full_equity = cfg.model == "buy_hold"
        prev_w = None

        def settle_year():
            nonlocal realized_ytd, loss_carry, cash_mv, taxes_paid
            taxable = realized_ytd
            if taxable > 0 and loss_carry > 0:
                off = min(taxable, loss_carry)
                taxable -= off
                loss_carry -= off
            if taxable < 0:
                loss_carry += -taxable
                taxable = 0.0
            t = taxable * rate
            cash_mv -= t
            taxes_paid += t
            realized_ytd = 0.0

        for i in range(n):
            S = close[i]
            sigma_base = iv[i] / 100.0 if iv[i] == iv[i] and iv[i] > 1.5 else (
                iv[i] if iv[i] == iv[i] else 0.0
            )
            sigma_base *= cfg.pricing_iv_mult

            if force_full_equity:
                w_eq = 1.0
                regime_state = None
            else:
                regime_state = classify_regime(S, sma[i], atr[i], ivr[i], rsi[i], cfg.regime)
                w_eq = regime_state.target_equity_pct
            regime = regime_state.regime if regime_state else MarketRegime.BULL_EXPANSION

            # Rebalance only when the target weight actually changes (or day 0).
            if prev_w is None or w_eq != prev_w:
                total = equity_mv + cash_mv
                target = w_eq * total
                if target < equity_mv - 1e-9 and equity_mv > 0:      # sell equity
                    sell = equity_mv - target
                    frac = sell / equity_mv
                    realized_ytd += sell - equity_basis * frac
                    equity_basis *= (1.0 - frac)
                    equity_mv = target
                    cash_mv += sell
                elif target > equity_mv + 1e-9:                      # buy equity
                    buy = min(target - equity_mv, cash_mv)
                    equity_mv += buy
                    equity_basis += buy
                    cash_mv -= buy
                prev_w = w_eq

            # Grow the two buckets; SGOV interest is ordinary income.
            interest = cash_mv * cash_daily
            equity_mv *= (1.0 + ret[i])
            cash_mv += interest
            realized_ytd += interest

            # Age / reprice / close options; realized option P&L is cash + taxable.
            still_open: list[OptionPosition] = []
            for pos in open_positions:
                if i > 0:
                    pos.dte_remaining -= (dates[i] - dates[i - 1]).days
                self._reprice(pos, S, sigma_base if sigma_base > 0 else 0.01)
                reason = (self._should_close_hedge(pos, regime) if cfg.model == "hedge_only"
                          else self._should_close(pos, regime, ivr[i]))
                if reason is not None:
                    pnl = pos.pnl()
                    realized_opt += pnl
                    cash_mv += pnl
                    realized_ytd += pnl
                    closed.append({
                        "label": pos.label, "action": pos.action.value,
                        "entry_date": pos.entry_date, "exit_date": dates[i],
                        "contracts": pos.contracts, "pnl": pnl, "reason": reason,
                    })
                else:
                    still_open.append(pos)
            open_positions = still_open

            # Open new positions per the model (sizing off the whole book).
            if options_on and sigma_base > 0 and not force_full_equity:
                nav = equity_mv + cash_mv
                if cfg.model == "static_cc":
                    if regime == MarketRegime.BULL_EXPANSION and not any(
                        p.action == OptionAction.SELL_COVERED_CALL for p in open_positions
                    ):
                        allowed, _ = self._entry_allowed(
                            OptionAction.SELL_COVERED_CALL, rsi[i], adx[i])
                        if not allowed:
                            filtered_opens += 1
                        pos = (self._static_cc_position(S, sigma_base, nav, w_eq, dates[i])
                               if allowed else None)
                        if pos is not None:
                            open_positions.append(pos)
                            premium_collected += -pos.value_entry * 100 * pos.contracts
                elif cfg.model == "hedge_only":
                    if self._hedge_eligible(regime, ivr[i]) and not open_positions:
                        pos = self._open_position(
                            OptionAction.BUY_PUT_DEBIT_SPREAD, S, sigma_base, nav, w_eq,
                            dates[i], premium_fraction=cfg.hedge_premium_fraction)
                        if pos is not None:
                            open_positions.append(pos)
                            debit_paid += pos.value_entry * 100 * pos.contracts
                else:  # dynamic
                    action = regime_state.option_action
                    if action != OptionAction.IDLE and not any(
                        p.action == action for p in open_positions
                    ):
                        allowed, _ = self._entry_allowed(action, rsi[i], adx[i])
                        if not allowed:
                            filtered_opens += 1
                        pos = (self._open_position(action, S, sigma_base, nav, w_eq, dates[i])
                               if allowed else None)
                        if pos is not None:
                            open_positions.append(pos)
                            if pos.is_credit:
                                premium_collected += -pos.value_entry * 100 * pos.contracts
                            else:
                                debit_paid += pos.value_entry * 100 * pos.contracts

            if i > 0 and dates[i].year != dates[i - 1].year:
                settle_year()

            unrealized = sum(p.pnl() for p in open_positions)
            nav_curve[i] = equity_mv + cash_mv + unrealized

        settle_year()  # final partial year
        nav_curve[-1] = equity_mv + cash_mv + sum(p.pnl() for p in open_positions)
        total_option_pnl = realized_opt + sum(p.pnl() for p in open_positions)

        equity_curve = pd.Series(nav_curve, index=dates)
        kpis = self._compute_kpis(
            equity_curve, closed, premium_collected, debit_paid, total_option_pnl,
            taxes_paid=taxes_paid,
        )
        kpis["Entry-Filter Blocks"] = filtered_opens
        return BacktestResult(cfg.model, equity_curve, kpis, closed)

    # -- metrics ----------------------------------------------------------- #
    def _compute_kpis(
        self, curve: pd.Series, closed, premium_collected, debit_paid, total_option_pnl,
        taxes_paid=None,
    ) -> dict:
        cfg = self.cfg
        vals = curve.values.astype(float)
        n = len(vals)
        initial = cfg.initial_capital
        ending = float(vals[-1])

        years = (curve.index[-1] - curve.index[0]).days / 365.25
        cagr = (ending / initial) ** (1 / years) - 1 if years > 0 and ending > 0 else float("nan")

        # Max drawdown + duration (in calendar days).
        running_peak = np.maximum.accumulate(vals)
        dd = vals / running_peak - 1.0
        mdd = float(dd.min())
        mdd_duration = self._max_drawdown_duration(curve, running_peak)

        daily_ret = np.diff(vals) / vals[:-1]
        rf_daily = cfg.risk_free / TRADING_DAYS
        excess = daily_ret - rf_daily
        std = daily_ret.std(ddof=1) if len(daily_ret) > 1 else 0.0
        sharpe = (excess.mean() / std * math.sqrt(TRADING_DAYS)) if std > 0 else float("nan")
        downside = daily_ret[daily_ret < 0]
        dstd = downside.std(ddof=1) if len(downside) > 1 else 0.0
        sortino = (excess.mean() / dstd * math.sqrt(TRADING_DAYS)) if dstd > 0 else float("nan")
        calmar = (cagr / abs(mdd)) if mdd < 0 and cagr == cagr else float("nan")

        wins = [c for c in closed if c["pnl"] > 0]
        win_rate = (len(wins) / len(closed) * 100.0) if closed else float("nan")

        out = {
            "Initial Capital ($)": initial,
            "Ending Portfolio Value ($)": ending,
            "CAGR (%)": cagr * 100 if cagr == cagr else float("nan"),
            "Max Drawdown (MDD %)": mdd * 100,
            "Max Drawdown Duration (Days)": mdd_duration,
            "Sharpe Ratio (Rf=4.5%)": sharpe,
            "Sortino Ratio": sortino,
            "Calmar Ratio (CAGR / MDD)": calmar,
            "Total Option Premium Collected ($)": premium_collected,
            "Total Option Debit Paid ($)": debit_paid,
            "Total Option P&L ($)": total_option_pnl,
            "Option Win Rate (%)": win_rate,
            "Total Option Trades": len(closed),
        }
        if taxes_paid is not None:
            out["Taxes Paid ($)"] = taxes_paid
        return out

    @staticmethod
    def _max_drawdown_duration(curve: pd.Series, running_peak: np.ndarray) -> int:
        """Longest span (calendar days) between an equity peak and its recovery."""
        idx = curve.index
        vals = curve.values.astype(float)
        peak_start = idx[0]
        longest = 0
        last_peak_val = vals[0]
        for i in range(len(vals)):
            if vals[i] >= last_peak_val:
                last_peak_val = vals[i]
                peak_start = idx[i]
            else:
                span = (idx[i] - peak_start).days
                if span > longest:
                    longest = span
        return int(longest)


def run_model(data: pd.DataFrame, model: str, **cfg_kwargs) -> BacktestResult:
    """Convenience wrapper: build a config for ``model`` and run it."""
    cfg = OverlayConfig(model=model, **cfg_kwargs)
    return OptionsOverlayBacktester(cfg).run(data)
