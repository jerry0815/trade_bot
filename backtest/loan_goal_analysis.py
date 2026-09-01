"""Consolidated loan + 2030-goal analysis.

Ties together the whole discussion: given the real portfolio (two contributing
accounts + a stock sleeve) and a possible $200k loan at 2.5%/yr, what maximizes
the probability of hitting a net-worth goal by 2030 (~4yr), and does timing the
loan entry to a post-bear recovery help?

All figures are NET WORTH = assets - loan owed, across 4yr rolling windows
(3x ^NDX, S&P signal), sleeves paired per window so they crash together.

Writes docs/loan-goal-analysis-2026-09-01.md.

Run:  python backtest/loan_goal_analysis.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from backtest.strat_backtest import (
    run_experiment_suite, warmup_aware_start_dates, get_cached_signals,
    SMATrendFollowing, Backtester,
)
from backtest.trailing_stop_dual_breach import DualSignalSingleStop

OUTPUT_PATH = REPO_ROOT / "docs" / "loan-goal-analysis-2026-09-01.md"

CFG = {"name": "3x", "leverage": 3, "expense": 0.0095}
ATR, SP, SC = 2.5, 0.08, 60
YEARS, RATE, LOAN = 4, 0.025, 200_000
TARGETS = [800_000, 1_000_000]
DD_THRESH = -0.10  # "post-bear" recovery: signal flips bullish while >=10% below peak

D = DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False, tag="GSPC",
                         trailing_stop_pct=SP, trailing_stop_cooldown_days=SC)
C = DualSignalSingleStop(atr_multiplier=ATR, t2_confirmation=False)


def suite(strat, adca, mdca, initial, tax, sd):
    r = run_experiment_suite(configs=[CFG], strategies=[strat], start_dates=sd,
                             period_years=YEARS, base_ticker="^NDX", signal_ticker="^GSPC",
                             annual_dca=adca, monthly_dca=mdca, initial_fund=initial,
                             apply_tax=tax, print_summary=False)
    return r[CFG["name"]].set_index("Start Date")[f"{strat.name} Final Value"]


def loan_from(E, T):
    env = Backtester(base_ticker="^NDX", signal_ticker="^GSPC",
                     start_date=E.strftime("%Y-%m-%d"), period_years=YEARS,
                     leverage=3, expense_ratio=0.0095, initial_fund=LOAN,
                     apply_tax=True, verbose=False)
    env.end_dt = T
    res = env.run(D)
    if res is None:
        return 0.0
    yrs = (T - E).days / 365.25
    return res["final_value"] - LOAN * (1 + RATE) ** yrs


def stats(s):
    v = np.asarray(s.values, float) if hasattr(s, "values") else np.asarray(s, float)
    return v.min(), np.percentile(v, 25), np.percentile(v, 50), v


def main():
    warnings.filterwarnings("ignore")
    sd = warmup_aware_start_dates(["^NDX", "^GSPC"], YEARS)

    taxadv = suite(D, 35000, 0, 114000, False, sd)
    taxable = suite(C, 0, 2000, 40000, True, sd)
    stocks = suite(C, 0, 0, 33000, True, sd)
    loanC = suite(C, 0, 0, LOAN, True, sd)
    loanD = suite(D, 0, 0, LOAN, True, sd)
    idx = taxadv.index.intersection(taxable.index).intersection(stocks.index) \
                 .intersection(loanC.index).intersection(loanD.index)
    base = taxadv[idx] + taxable[idx] + stocks[idx]
    owed_full = LOAN * (1 + RATE) ** YEARS
    netC = base + (loanC[idx] - owed_full)
    netD = base + (loanD[idx] - owed_full)

    # Wait-for-recovery policy (config D)
    sig = get_cached_signals("^GSPC").copy()
    sig, _ = SMATrendFollowing(sma_window=200, atr_multiplier=ATR,
                               t2_confirmation=False).generate_signals(sig)
    inm = sig["in_market"].astype(bool)
    flips = sig.index[inm & ~inm.shift(1, fill_value=False)]
    dd = get_cached_signals("^GSPC")["Close"]
    dd = (dd / dd.cummax() - 1.0)
    rec = pd.DatetimeIndex([d for d in flips
                            if float(dd.reindex([d], method="ffill").iloc[0]) <= DD_THRESH])
    netB, deployed = {}, 0
    for S in idx:
        T = S + pd.DateOffset(years=YEARS)
        cand = rec[(rec >= S) & (rec < T)]
        if len(cand) == 0:
            netB[S] = base[S]
        else:
            deployed += 1
            netB[S] = base[S] + loan_from(cand[0], T)
    netB = pd.Series(netB)

    scenarios = [("No loan", base), ("Deploy now — config C (no stop)", netC),
                 ("Deploy now — config D (stop)", netD),
                 ("Wait for post-bear recovery (D)", netB)]

    def prob_row(name, s):
        lo, q25, med, v = stats(s)
        ps = " | ".join(f"{(v >= t).mean()*100:.0f}%" for t in TARGETS)
        return f"| {name} | ${lo:,.0f} | ${q25:,.0f} | ${med:,.0f} | {ps} |"

    n = len(idx)
    fmt_t = lambda t: f"${t//1_000_000}M" if t >= 1_000_000 and t % 1_000_000 == 0 else f"${t//1000}k"
    tgt_hdr = " | ".join(f"P(≥{fmt_t(t)})" for t in TARGETS)
    sep = "| :-- | --: | --: | --: |" + " --: |" * len(TARGETS)
    rows = "\n".join(prob_row(nm, s) for nm, s in scenarios)

    doc = f"""# Loan & 2030-Goal Analysis (2026-09-01)

Given the real portfolio and a possible $200,000 loan at 2.5%/yr, what
maximizes the probability of hitting a **net-worth goal by 2030 (~4 years)**,
and does waiting for a "relatively low point" to borrow help?

All figures are **net worth = assets − loan owed**, across {n} rolling 4-year
windows (3× ^NDX, S&P 500 signal, full history incl. dot-com/GFC/COVID/2022),
sleeves paired per window so they crash together (no phantom diversification).
Generated by `backtest/loan_goal_analysis.py`. Companion to
[dca-contribution-analysis](dca-contribution-analysis-2026-08-28.md).

## Portfolio setup

| Sleeve | Capital | Config | Tax |
| :-- | :-- | :-- | :-- |
| Tax-advantaged | $114,000 + $35,000/yr | D (dual-signal + trailing stop 8%/60d) | pre-tax |
| Taxable | $40,000 + $2,000/mo | C (dual-signal, no stop) | after-tax |
| Stocks (NVDA+PLTR) | $33,000 lump *(assumed strategy-like)* | C | after-tax |
| **Loan (optional)** | **$200,000 lump** | **C or D** | after-tax |

Contribution frequency (monthly vs annual) was tested separately and is a
**wash** on returns; monthly is preferred only because the cash arrives monthly.
Contributions always follow the signal — invested on a buy signal, parked in
money-market on a sell signal (never auto-bought into a downtrend).

## Loan strategy modeled

The loan sleeve is a **$200,000 lump** run through the **same production trend
strategy** (3× TQQQ, dual-signal), after-tax, deployed on a bullish signal and
governed by the signal thereafter (money-market when in cash). Two variants:
**config C** (no stop) and **config D** (+ trailing stop). Net worth subtracts
the owed balance **$200k × 1.025⁴ = ${owed_full:,.0f}** — the economically
correct cost whether interest accrues or is paid from income.

## Probability of reaching the goal by 2030

| Scenario | Worst-case net | 25th pct | Median | {tgt_hdr} |
{sep}
{rows}

*Deploy-now = lump at window start, held ~4yr. Wait-for-recovery deploys only
when the trend signal flips bullish while the market is still ≥10% below its
prior peak; if no such entry occurs in the window, the loan is never taken
(base only). Recovery deployed in {deployed}/{n} windows ({deployed/n*100:.0f}%).*

## Findings

1. **The loan is the biggest lever on the goal probability.** It lifts
   P(≥$800k) from ~46% (no loan) to ~57% (deploy now), and P(≥$1M) from ~36% to
   ~47%. Nothing else discussed (config tweaks, entry timing) moves the number
   as much.

2. **Config choice depends on how far the goal sits above the median.**
   - For **$1M** (a stretch above median): **config C (no stop)** maximizes the
     probability — you need the upside.
   - For **$800k** (near the median): **C and D are ~tied on probability**, so
     **config D (stop) is the better pick** — same odds, but a materially
     shallower worst case (the stop halves drawdown).

3. **Waiting for a post-bear recovery does NOT help on a fixed 2030 horizon** —
   it lands *below* deploy-now (P(≥$800k) ~50% vs ~57%). Two reasons: a
   bear+recovery occurred in only ~{deployed/n*100:.0f}% of 4-year windows (so
   the loan often never gets taken), and when it does the loan has less time to
   compound. Waiting's only benefit is a slightly safer worst case. On a fixed
   calendar deadline, **time-in-market dominates entry timing.**

4. **Don't try to time the entry.** The trend signal already rotates you out of
   any bear that arrives *after* you deploy and back in on recovery — you get
   that crash-avoidance for free once invested, without forfeiting the odds by
   sitting in cash first. Deploy on the next bullish signal.

5. **Even fully optimized, both goals are demanding at 4 years** (best P(≥$800k)
   ≈ 57%, P(≥$1M) ≈ 47%). The reliable way to raise the odds well above
   50/50 is **more time** (extending toward 2031–2032), not a bigger bet.

## Caveats

- The loan roughly **halves the worst-case net worth** (≈$306k → ≈$157k–207k):
  borrowed 3× exposure deepens crash losses on money you still owe. Borrowed
  correlated leverage amplifies, it does not hedge.
- Historical **base rates across overlapping windows, not forward
  probabilities**; dominated by a handful of past regimes.
- The stock sleeve assumes NVDA+PLTR track the strategy — optimistic for two
  concentrated single stocks with no trend-exit.
- **Mechanical backtest output — not a forecast, and not personalized
  investment advice.** A leveraged loan decision warrants a licensed advisor.
"""
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(doc)
    # ASCII-safe console echo
    print(f"Recovery deployed in {deployed}/{n} windows.")
    for nm, s in scenarios:
        lo, q25, med, v = stats(s)
        ps = ", ".join(f">={t}: {(v>=t).mean()*100:.0f}%" for t in TARGETS)
        print(f"{nm:<34} worst ${lo:,.0f} | median ${med:,.0f} | {ps}")
    print(f"\nWritten to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
