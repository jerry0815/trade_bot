"""Covered-call *income* simulator — max premium while keeping the shares.

This is a **different objective** from the ``overlay_backtest`` study. There the
question was whether an options overlay improves *total return* on a leveraged
trend sleeve (answer: no — covered calls were the worst overlay because they
short the fat-right tail the trend system needs). Here the shares are held
regardless (NVDA / PLTR / TQQQ long-term holds) and the goal is **cash flow per
unit of upside given up**, so the engine biases toward low-delta / far-OTM
calls and reports keep-rate and total-return drag as first-class KPIs.

Semantics (event-driven daily loop, per the design)
----------------------------------------------------
* **Open** (when flat, ``IV_Rank ≥ ivr_gate``, and — if ``earnings_rule="skip"``
  — no earnings date falls on/before the prospective expiry): sell
  ``covered_call_contracts(shares)`` calls, strike from
  :meth:`GreeksEngine.get_strike_for_delta` at the proxy IV with the call-skew
  override. Premium is booked as a cash credit.
* **Manage**: buy-to-close at ``profit_target`` of max profit; else close at the
  current mark once ``DTE ≤ min_dte_exit`` (the 21-DTE roll); else settle at
  intrinsic ``max(S-K,0)`` on expiry. Options are **cash-settled at intrinsic —
  the shares are always retained** (same convention as ``overlay_backtest``). A
  cycle whose short call is ITM at close increments ``assigned_cycles`` — the
  cycle where the shares *would* have been called away and their upside capped.
  (With ``dte ≥ min_dte_exit`` the 21-DTE roll always pre-empts a literal
  expiry, so ITM-at-close is what makes the keep-rate meaningful.)
* **NAV** = ``shares × price + cash``, where ``cash`` accrues ``cash_yield``
  daily and reflects premium in / buybacks + intrinsic out. The buy & hold
  baseline holds the identical shares + starting cash with no options.

Backtest-grade ranking signal, **not tradeable P&L**: no bid/ask, commissions,
early assignment or borrow are modeled, and the IV is a realized-vol proxy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd

from .greeks import GreeksEngine, CALL_SKEW_MULT
from .position_sizer import covered_call_contracts, CONTRACT_MULTIPLIER
from .realized_iv import build_iv_frame, vrp_mult_for

TRADING_DAYS = 252


@dataclass
class CCConfig:
    """Parameters for one covered-call income run."""

    ticker: str = "NVDA"
    shares: int | None = None          # None => derived from initial_capital
    delta: float = 0.15                 # target |Δ| of the short call
    dte: int = 30                       # days to expiry at open
    ivr_gate: float = 0.0               # only open when IV_Rank >= this
    earnings_rule: str = "ignore"       # "ignore" | "skip"
    profit_target: float = 0.50         # buy-to-close at this fraction of max profit
    min_dte_exit: int = 21              # force-close at/under this DTE (the roll)
    vrp_mult: float | None = None       # None => per-ticker default
    call_skew_mult: float = CALL_SKEW_MULT
    risk_free: float = 0.045
    cash_yield: float = 0.045
    initial_capital: float = 100_000.0

    def resolved_vrp(self) -> float:
        return vrp_mult_for(self.ticker) if self.vrp_mult is None else self.vrp_mult


@dataclass
class CCResult:
    """Output of :func:`run_cc_income`."""

    config: CCConfig
    equity_curve: pd.Series
    buyhold_curve: pd.Series
    cash_curve: pd.Series
    closed_trades: list[dict]
    premium_collected: float
    option_pnl: float
    assigned_cycles: int
    cycles: int
    shares: int
    kpis: dict = field(default_factory=dict)


def run_cc_income(
    price_df: pd.DataFrame,
    iv_df: pd.DataFrame,
    earnings_dates,
    cfg: CCConfig,
) -> CCResult:
    """Simulate the covered-call income strategy over ``price_df``.

    ``price_df`` needs a ``Close`` column indexed by date; ``iv_df`` needs
    ``IV`` (decimal) and ``IV_Rank`` columns (e.g. from
    :func:`options.realized_iv.build_iv_frame`). ``earnings_dates`` is an
    iterable of Timestamps (used only when ``cfg.earnings_rule == "skip"``).
    """
    close = price_df["Close"].astype(float)
    dates = close.index
    iv = iv_df["IV"].reindex(dates).ffill()
    ivr = iv_df["IV_Rank"].reindex(dates).ffill()

    earnings = sorted(pd.to_datetime(list(earnings_dates))) if earnings_dates is not None else []

    first_price = float(close.iloc[0])
    shares = cfg.shares
    if shares is None:
        lots = int(cfg.initial_capital / first_price) // CONTRACT_MULTIPLIER
        shares = max(CONTRACT_MULTIPLIER, lots * CONTRACT_MULTIPLIER)
    shares = int(shares)
    max_contracts = shares // CONTRACT_MULTIPLIER

    initial_cash = cfg.initial_capital - shares * first_price
    daily_factor = 1.0 + cfg.cash_yield / TRADING_DAYS

    cash = initial_cash
    bh_cash = initial_cash
    r = cfg.risk_free
    skew = cfg.call_skew_mult

    open_pos: dict | None = None
    closed: list[dict] = []
    premium_collected = 0.0
    option_pnl = 0.0
    assigned_cycles = 0
    cycles = 0

    nav = np.empty(len(dates), dtype=float)
    bh_nav = np.empty(len(dates), dtype=float)
    cash_series = np.empty(len(dates), dtype=float)

    def call_mark(S: float, K: float, sigma: float, t_years: float) -> float:
        adj = sigma * skew
        return GreeksEngine.calculate_greeks(S, K, t_years, r, adj, "call")["price"]

    def close_trade(pos: dict, exit_price: float, date, reason: str, assigned: bool):
        nonlocal cash, option_pnl, assigned_cycles, cycles
        pnl = (pos["entry_premium"] - exit_price) * CONTRACT_MULTIPLIER * pos["contracts"]
        cash -= exit_price * CONTRACT_MULTIPLIER * pos["contracts"]
        option_pnl += pnl
        cycles += 1
        if assigned:
            assigned_cycles += 1
        closed.append({
            "entry_date": pos["entry_date"],
            "exit_date": date,
            "strike": pos["strike"],
            "contracts": pos["contracts"],
            "entry_premium": pos["entry_premium"],
            "exit_price": exit_price,
            "pnl": pnl,
            "reason": reason,
            "assigned": assigned,
        })

    for i, date in enumerate(dates):
        S = float(close.iloc[i])
        cash *= daily_factor
        bh_cash *= daily_factor

        if open_pos is not None:
            K = open_pos["strike"]
            expiry = open_pos["expiry"]
            sigma_now = float(iv.iloc[i]) if not math.isnan(iv.iloc[i]) else open_pos["entry_sigma"]
            dte_left = (expiry - date).days
            is_last = i == len(dates) - 1

            # A cycle is "assigned" (its short call went ITM, capping the shares)
            # when the underlying is above the strike at close — whatever the
            # close reason. With dte >= min_dte_exit the 21-DTE roll always
            # pre-empts a literal expiry, so measuring ITM at the close is what
            # makes the keep-rate a meaningful "shares kept uncapped" KPI.
            itm = S > K
            if dte_left <= 0:
                intrinsic = max(S - K, 0.0)
                close_trade(open_pos, intrinsic, date, "expiry", assigned=itm)
                open_pos = None
            else:
                t_years = max(dte_left, 0) / 365.0
                mark = call_mark(S, K, sigma_now, t_years)
                unreal_profit = open_pos["entry_premium"] - mark
                cross_earnings = (
                    cfg.earnings_rule == "skip"
                    and any(date < e <= expiry for e in earnings)
                )
                if unreal_profit >= cfg.profit_target * open_pos["entry_premium"]:
                    close_trade(open_pos, mark, date, "profit_target", assigned=itm)
                    open_pos = None
                elif cross_earnings:
                    close_trade(open_pos, mark, date, "earnings", assigned=itm)
                    open_pos = None
                elif dte_left <= cfg.min_dte_exit:
                    close_trade(open_pos, mark, date, "roll_21dte", assigned=itm)
                    open_pos = None
                elif is_last:
                    close_trade(open_pos, mark, date, "final_settle", assigned=itm)
                    open_pos = None
        else:
            base_sigma = float(iv.iloc[i]) if i < len(iv) else float("nan")
            gate_ok = (not math.isnan(ivr.iloc[i])) and ivr.iloc[i] >= cfg.ivr_gate
            if gate_ok and not math.isnan(base_sigma) and base_sigma > 0 and max_contracts >= 1:
                expiry = date + timedelta(days=cfg.dte)
                cross_earnings = (
                    cfg.earnings_rule == "skip"
                    and any(date < e <= expiry for e in earnings)
                )
                if not cross_earnings:
                    contracts = covered_call_contracts(shares)
                    # Collateral invariant: never sell more than shares // 100 calls.
                    assert contracts <= max_contracts, (
                        f"collateral breach: {contracts} calls > {max_contracts} lots"
                    )
                    if contracts >= 1:
                        K, greeks = GreeksEngine.get_strike_for_delta(
                            S, cfg.dte / 365.0, r, base_sigma, cfg.delta, "call",
                            call_skew_mult=skew,
                        )
                        premium = greeks["price"]
                        cash += premium * CONTRACT_MULTIPLIER * contracts
                        premium_collected += premium * CONTRACT_MULTIPLIER * contracts
                        open_pos = {
                            "strike": K,
                            "entry_premium": premium,
                            "entry_sigma": base_sigma,
                            "contracts": contracts,
                            "expiry": expiry,
                            "entry_date": date,
                        }

        nav[i] = shares * S + cash
        bh_nav[i] = shares * S + bh_cash
        cash_series[i] = cash

    equity_curve = pd.Series(nav, index=dates)
    buyhold_curve = pd.Series(bh_nav, index=dates)
    cash_curve = pd.Series(cash_series, index=dates)
    kpis = _compute_kpis(
        equity_curve, buyhold_curve, closed, premium_collected, option_pnl,
        assigned_cycles, cycles, shares, close, cfg,
    )
    return CCResult(
        config=cfg,
        equity_curve=equity_curve,
        buyhold_curve=buyhold_curve,
        cash_curve=cash_curve,
        closed_trades=closed,
        premium_collected=premium_collected,
        option_pnl=option_pnl,
        assigned_cycles=assigned_cycles,
        cycles=cycles,
        shares=shares,
        kpis=kpis,
    )


def _cagr(curve: pd.Series) -> float:
    vals = curve.values.astype(float)
    initial, ending = float(vals[0]), float(vals[-1])
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    if years <= 0 or initial <= 0 or ending <= 0:
        return float("nan")
    return (ending / initial) ** (1 / years) - 1


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


def _compute_kpis(
    curve: pd.Series,
    buyhold: pd.Series,
    closed: list[dict],
    premium_collected: float,
    option_pnl: float,
    assigned_cycles: int,
    cycles: int,
    shares: int,
    close: pd.Series,
    cfg: CCConfig,
) -> dict:
    """KPI dict mirroring ``overlay_backtest._compute_kpis`` plus income metrics."""
    vals = curve.values.astype(float)
    initial = float(vals[0])
    ending = float(vals[-1])
    years = (curve.index[-1] - curve.index[0]).days / 365.25

    cagr = _cagr(curve)
    bh_cagr = _cagr(buyhold)

    running_peak = np.maximum.accumulate(vals)
    dd = vals / running_peak - 1.0
    mdd = float(dd.min())
    mdd_duration = _max_drawdown_duration(curve, running_peak)

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

    avg_position_value = float((shares * close.astype(float)).mean())
    premium_yield = (
        premium_collected / avg_position_value / years
        if avg_position_value > 0 and years > 0 else float("nan")
    )
    keep_rate = (1.0 - assigned_cycles / cycles) if cycles > 0 else 1.0
    drag = (bh_cagr - cagr) if (bh_cagr == bh_cagr and cagr == cagr) else float("nan")

    return {
        "Initial Capital ($)": initial,
        "Ending Portfolio Value ($)": ending,
        "Buy & Hold Ending Value ($)": float(buyhold.values[-1]),
        "CAGR (%)": cagr * 100 if cagr == cagr else float("nan"),
        "Buy & Hold CAGR (%)": bh_cagr * 100 if bh_cagr == bh_cagr else float("nan"),
        "Total-Return Drag (pp/yr)": drag * 100 if drag == drag else float("nan"),
        "Annualized Premium Yield (%)": premium_yield * 100 if premium_yield == premium_yield else float("nan"),
        "Keep Rate (%)": keep_rate * 100,
        "Assigned Cycles": assigned_cycles,
        "Total Cycles": cycles,
        "Max Drawdown (MDD %)": mdd * 100,
        "Max Drawdown Duration (Days)": mdd_duration,
        "Sharpe Ratio (Rf=4.5%)": sharpe,
        "Sortino Ratio": sortino,
        "Calmar Ratio (CAGR / MDD)": calmar,
        "Total Option Premium Collected ($)": premium_collected,
        "Total Option P&L ($)": option_pnl,
        "Option Win Rate (%)": win_rate,
        "Total Option Trades": len(closed),
    }


def load_earnings_dates(ticker: str, start: str = "2018-01-01", end: str | None = None) -> list:
    """Earnings dates for ``ticker``: yfinance first, synthetic-quarterly fallback.

    Tries ``yf.Ticker(ticker).get_earnings_dates``; on empty/failure (or no
    network) falls back to a synthesized ~quarterly cadence (every 91 days) from
    a per-ticker anchor. The synthetic cadence is an **approximation** used only
    to gate ``earnings_rule="skip"`` in the backtest. Returns a sorted list of
    Timestamps within ``[start, end]``.
    """
    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end) if end is not None else pd.Timestamp.today().normalize()

    try:  # pragma: no cover - network path, exercised only on a live runner
        import yfinance as yf

        from ._net import make_session

        session = make_session()
        tk = yf.Ticker(ticker, session=session) if session is not None else yf.Ticker(ticker)
        raw = tk.get_earnings_dates(limit=60)
        if raw is not None and len(raw) > 0:
            idx = pd.to_datetime(raw.index).tz_localize(None)
            dates = sorted(d for d in idx if start_ts <= d <= end_ts)
            if dates:
                return dates
    except Exception:
        pass

    return synthetic_earnings_dates(ticker, start_ts, end_ts)


# Per-ticker anchor for the synthetic quarterly cadence (a recent real report
# date, rounded); the exact day matters little — only that a ~quarterly block is
# excluded when earnings_rule="skip".
_EARNINGS_ANCHOR = {
    "NVDA": pd.Timestamp("2020-02-19"),
    "PLTR": pd.Timestamp("2021-02-16"),
    "TQQQ": pd.Timestamp("2020-01-28"),  # TQQQ has no earnings; use NDX-ish cadence
}


def synthetic_earnings_dates(ticker: str, start_ts, end_ts, period_days: int = 91) -> list:
    """Quarterly cadence (~91 days) spanning ``[start_ts, end_ts]`` from an anchor."""
    anchor = _EARNINGS_ANCHOR.get(ticker.upper(), pd.Timestamp("2020-02-01"))
    # Walk the anchor back to before the window, then forward through it.
    d = anchor
    while d > start_ts:
        d -= timedelta(days=period_days)
    out = []
    while d <= end_ts:
        if d >= start_ts:
            out.append(d)
        d += timedelta(days=period_days)
    return out
