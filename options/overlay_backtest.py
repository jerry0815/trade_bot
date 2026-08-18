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
    model: str = "dynamic"          # buy_hold | trend | static_cc | dynamic
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

    # Sizing caps.
    debit_premium_fraction: float = 0.01  # tail hedge budget as fraction of NAV


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
            contracts = sizer.debit_spread_contracts(nav, net_debit, cfg.debit_premium_fraction)
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

    # -- main loop --------------------------------------------------------- #
    def run(self, data: pd.DataFrame) -> BacktestResult:
        cfg = self.cfg
        df = data.dropna(subset=["Close"]).copy()
        n = len(df)

        close = df["Close"].values.astype(float)
        sma = df["SMA"].values.astype(float)
        atr = df["ATR"].values.astype(float)
        rsi = df["RSI"].values.astype(float)
        iv = df["IV"].values.astype(float)
        ivr = df["IV_Rank"].values.astype(float)
        dates = df.index

        ret = np.empty(n)
        ret[0] = 0.0
        ret[1:] = close[1:] / close[:-1] - 1.0
        cash_daily = cfg.cash_yield / TRADING_DAYS

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

        options_on = cfg.model in ("static_cc", "dynamic")
        force_full_equity = cfg.model == "buy_hold"

        for i in range(n):
            S = close[i]
            sigma_base = iv[i] / 100.0 if iv[i] == iv[i] and iv[i] > 1.5 else (
                iv[i] if iv[i] == iv[i] else 0.0
            )

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
                        pos = self._static_cc_position(S, sigma_base, sleeve_value, w_eq, dates[i])
                        if pos is not None:
                            open_positions.append(pos)
                            premium_collected += -pos.value_entry * 100 * pos.contracts
                else:  # dynamic
                    action = regime_state.option_action
                    if action != OptionAction.IDLE and not any(
                        p.action == action for p in open_positions
                    ):
                        pos = self._open_position(
                            action, S, sigma_base, sleeve_value, w_eq, dates[i]
                        )
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
        return BacktestResult(cfg.model, equity_curve, kpis, closed)

    # -- metrics ----------------------------------------------------------- #
    def _compute_kpis(
        self, curve: pd.Series, closed, premium_collected, debit_paid, total_option_pnl
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

        return {
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
