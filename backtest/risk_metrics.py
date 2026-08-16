"""
Risk-adjusted performance ratios for a backtested equity curve.

All three ratios reward return per unit of *risk*, but each defines risk
differently:

  - Sharpe  — return per unit of total volatility (up-swings and down-swings
              both count as "risk").
  - Sortino — return per unit of *downside* volatility only (up-swings are
              not penalised). Higher than Sharpe for a strategy whose big
              moves are mostly upward.
  - Calmar  — annualised return per unit of worst peak-to-trough drawdown.
              The pain-focused ratio: how much you earn for the deepest hole
              you had to sit through.

Convention notes:
  - Daily returns are annualised with sqrt(252) (Sharpe/Sortino) or 252
    (mean), the standard trading-day count also used by the backtester's
    TWR annualisation.
  - Excess return is measured over a per-day risk-free rate. Pass the
    model's own cash yield (idle cash earns BR*0.8 in this simulator) for an
    internally consistent number, or 0.0 for the raw/absolute variant.
  - Sortino's downside deviation divides the sum of squared *negative*
    excess returns by the total period count N (the "target downside
    deviation" definition), not by the count of down-days. This keeps it on
    the same scale as the ordinary standard deviation so Sortino >= Sharpe
    holds as expected.
"""
import numpy as np

TRADING_DAYS = 252


def daily_returns_from_equity(equity):
    """Convert an equity curve (array of portfolio values) into simple daily
    returns. Length is len(equity) - 1."""
    equity = np.asarray(equity, dtype=float)
    return equity[1:] / equity[:-1] - 1.0


def sharpe_ratio(daily_returns, rf_daily=0.0, periods=TRADING_DAYS):
    """Annualised Sharpe ratio from a daily return series.

    rf_daily may be a scalar or a per-day array aligned to daily_returns.
    """
    r = np.asarray(daily_returns, dtype=float)
    excess = r - rf_daily
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return (excess.mean() / sd) * np.sqrt(periods)


def sortino_ratio(daily_returns, rf_daily=0.0, periods=TRADING_DAYS):
    """Annualised Sortino ratio — like Sharpe but the denominator is the
    downside deviation (target = rf), so upside volatility isn't penalised."""
    r = np.asarray(daily_returns, dtype=float)
    excess = r - rf_daily
    downside = np.minimum(excess, 0.0)
    # Target downside deviation: divide by N (all periods), not by down-day count.
    downside_dev = np.sqrt(np.mean(downside ** 2))
    if downside_dev == 0 or np.isnan(downside_dev):
        return float("nan")
    return (excess.mean() / downside_dev) * np.sqrt(periods)


def calmar_ratio(annual_return_pct, max_drawdown_pct):
    """Calmar ratio = annualised return / |max drawdown|.

    Both inputs are in percent (e.g. 11.1 and -44.8), matching the fields the
    backtester already returns (strategy_twr and max_drawdown). Returns a
    pure ratio.
    """
    dd = abs(max_drawdown_pct)
    if dd == 0:
        return float("nan")
    return annual_return_pct / dd


def annualised_return_from_equity(equity, n_days=None, periods=TRADING_DAYS):
    """Time-weighted annualised return (as a percent) from an equity curve.
    Mirrors the backtester's ``strategy_twr`` formula so numbers reconcile.

    Annualises over the number of return *periods* (len(equity) - 1), which
    equals the backtester's daily-return row count when the equity curve is
    built by prepending the starting value to a per-day return series."""
    equity = np.asarray(equity, dtype=float)
    total_growth = equity[-1] / equity[0]
    n = (len(equity) - 1) if n_days is None else n_days
    return ((total_growth ** (periods / n)) - 1.0) * 100.0


def max_drawdown_from_equity(equity):
    """Worst peak-to-trough drawdown (as a negative percent) from an equity curve."""
    equity = np.asarray(equity, dtype=float)
    running_peak = np.maximum.accumulate(equity)
    drawdowns = (equity - running_peak) / running_peak
    return float(drawdowns.min() * 100.0)


def risk_report(equity, rf_daily=0.0, periods=TRADING_DAYS):
    """Compute all three ratios (plus the supporting stats) from an equity curve.

    Returns a dict with sharpe, sortino, calmar, annual_return_pct,
    max_drawdown_pct, and daily-return mean/vol for reference.
    """
    r = daily_returns_from_equity(equity)
    ann_ret = annualised_return_from_equity(equity, periods=periods)
    max_dd = max_drawdown_from_equity(equity)
    return {
        "sharpe": sharpe_ratio(r, rf_daily, periods),
        "sortino": sortino_ratio(r, rf_daily, periods),
        "calmar": calmar_ratio(ann_ret, max_dd),
        "annual_return_pct": ann_ret,
        "max_drawdown_pct": max_dd,
        "ann_volatility_pct": r.std(ddof=1) * np.sqrt(periods) * 100.0,
        "n_days": len(equity),
    }
