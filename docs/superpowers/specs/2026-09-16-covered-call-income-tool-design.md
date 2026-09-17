# Design — Covered-Call Income Decision Tool

**Date:** 2026-09-16
**Status:** design approved, spec under review
**Author:** Claude Code (with Jerry)
**Related:** [options/README.md](../../../options/README.md) · [options-overlay.md](../../strategies/options-overlay.md) · [options/_net.py](../../../options/_net.py) · [options/greeks.py](../../../options/greeks.py)

---

## 1. Motivation & goal

Jerry holds shares of **NVDA, PLTR, and TQQQ** as long-term positions and wants to
sell covered calls against them for **cash flow**. The stated objective is
**maximize income safely**: collect reliable premium while keeping the shares
(minimize the chance of assignment / having shares called away), accepting that
this caps upside.

The deliverable is a **live decision tool** — a CLI that pulls current option
chains, applies rules, and surfaces a ranked list of covered-call candidates to
sell *right now*. Jerry places the actual trades; the tool is a decision aid, not
an executor and not personalized financial advice.

### Relationship to the existing options-overlay negative finding

The repo already contains an [options overlay](../../strategies/options-overlay.md)
research engine whose conclusion was that **covered calls hurt a leveraged
trend-follower** ("you're short exactly the fat-right-tail convexity that makes
the strategy work"). That finding is **not in conflict** with this tool, for three
reasons, all of which are in scope to keep straight:

1. That study optimized **total return / Calmar**. This tool optimizes **income
   subject to low assignment risk** — a different objective the user has
   explicitly chosen.
2. That study was about **TQQQ overlaid on a trend-timing system**. This tool
   operates on **buy-and-hold shares** the user holds regardless.
3. That study said nothing about **NVDA or PLTR** as single names, which have
   their own volatility, skew, and earnings dynamics.

The tool's output header will nonetheless carry a one-line pointer to that finding
so the tradeoff (capped upside on a fat-tail asset) stays visible.

## 2. Scope

**In scope (v1):**
- Fetch live option chains for a configured set of held tickers via yfinance.
- Rank fully-covered call candidates by annualized premium yield, filtered by an
  assignment-risk cap (delta) and an earnings blackout.
- Print a per-ticker ranked table to the terminal; optionally save a Markdown
  report.

**Deliberately out of scope (YAGNI for v1):**
- Roll / adjustment automation, multi-leg spreads, cash-secured puts.
- IV-rank timing gate (approach "B" — deferred; see §8).
- Any auto-execution or brokerage connectivity.
- Historical backtesting of the income strategy (the user chose a live tool, not a
  backtest study).

## 3. Architecture

A new self-contained package `covered_calls/`, sibling to `options/`. It reuses
`options/_net.py` (proxy-aware retrying yfinance helper) and `options/greeks.py`
(Black-Scholes delta) rather than duplicating them. It does **not** touch `bot.py`
or any trend-research module.

```
covered_calls/
  __init__.py
  holdings.py       # user's share counts per ticker (config-driven)
  chain_loader.py   # yfinance option chains across a DTE window (via _net.py)
  earnings.py       # next earnings date per ticker → expiration blackout
  screener.py       # PURE core: filter + annualized-yield ranking
  cli.py            # entry point: ranked table per holding, optional --out
tests/
  test_cc_screener.py   # pure-function tests on synthetic chains
  test_cc_earnings.py   # blackout logic
```

### Data flow

```
holdings config ─┐
                 ├─► for each ticker:
chain_loader ────┤       fetch spot + chains (DTE window)
earnings ────────┤       fetch next earnings date
                 └─►  screener.screen(candidates, params) ─► ranked list ─► cli table / report
```

The **network-touching** modules (`chain_loader`, `earnings`) are thin and kept
separate from the **pure** module (`screener`) so the ranking logic is fully
unit-testable with synthetic inputs and no network.

## 4. Selection logic (screener core)

For each held ticker, across every expiration whose DTE falls in the window:

**Filter — a candidate strike is kept only if:**
- `delta ≤ max_delta` (assignment-risk cap; delta ≈ probability of finishing
  in-the-money ≈ assignment probability).
- The expiration does **not** span an earnings date (see §6).
- `bid > 0` (there is a real premium to collect).
- Only OTM calls (`strike > spot`) are considered.

**Compute per surviving candidate:**
- `dte` — calendar days to expiration.
- `pct_otm` = `strike / spot − 1`.
- `premium` = the option **bid** (conservative: what you'd receive selling at bid).
- `delta` — from yfinance if present, else Black-Scholes fallback via
  `options/greeks.py` using the chain's IV.
- `premium_yield` = `premium / spot`.
- `annualized_yield` = `premium_yield × 365 / dte` — the primary ranking metric.
- `contracts` = `floor(shares / 100)` — always fully covered, never naked.
- `total_premium` = `premium × 100 × contracts` — dollar cash flow if filled.

**Rank** all surviving candidates by `annualized_yield`, descending. Return the
top `N` per ticker (default N configurable).

**Metric definition note:** annualized premium yield is deliberately simple and
transparent (premium as a fraction of spot, scaled to a year). It is a comparison
score across strikes/expiries, **not** a return forecast — assignment, share
appreciation given up, and path are not baked in. This is stated in the output.

## 5. Defaults (all CLI-overridable)

| Parameter | Default | Rationale |
|---|---|---|
| Tickers / shares | NVDA, PLTR, TQQQ (counts from `holdings.py`) | user's actual holdings |
| DTE window | 20–45 days | standard income-CC window; enough theta, avoids weeklies' noise |
| `max_delta` | 0.20 | ≈ ≤20% assignment probability — "safe income" bias |
| Earnings blackout | on | NVDA/PLTR gap hard on earnings; avoids assignment-on-gap |
| Top N per ticker | 5 | keep the table scannable |

## 6. Earnings blackout

Fetch each ticker's **next earnings date** via yfinance (`get_earnings_dates` /
`calendar`). Any expiration whose window `[today, expiration]` **contains** the
next earnings date is excluded by default (`--no-earnings-blackout` disables it).
If the earnings date cannot be fetched, the tool **keeps** the affected
expirations but **marks each candidate with an "⚠ earnings unknown" flag** in the
output rather than silently dropping them or silently proceeding as if there is no
earnings risk. This never gives the user false safety (the flag is visible) and
never silently hides income opportunities. A blacked-out expiration (earnings
date *known* to fall inside the window) is dropped as described above.

## 7. Output / UX

- **Terminal:** one ranked table per ticker (top N), columns: expiration, DTE,
  strike, %OTM, delta, bid, premium yield, annualized yield, contracts, total
  premium. Tickers with no qualifying candidates print a clear one-line reason
  (e.g. "no strikes ≤ 0.20Δ in 20–45 DTE" or "all expirations blacked out by
  earnings on 2026-XX-XX").
- **`--out report.md`:** save the same tables as Markdown, matching the repo's
  existing report style.
- **Header caveat (always printed):** delayed yfinance data; decision aid, not
  advice; user places trades; one-line pointer to the options-overlay finding
  (capped upside on fat-tail names).
- The CLI can be surfaced to the user's phone via `SendUserFile` on the saved
  report when run interactively.

## 8. Deferred: IV-rank timing gate (approach B)

Not built in v1, but the architecture leaves room. A later iteration can
accumulate each ticker's ATM implied vol daily (reusing the repo's on-disk cache
pattern) and only surface candidates when IV is rich relative to that name's own
recent history, otherwise recommend waiting. `screener.screen()` will take params
as a struct so an `iv_rank_gate` can be added without reshaping callers.

## 9. Error handling

- Missing chain, or no expirations in the DTE window → skip that ticker with a
  clear message; continue with the others.
- Missing IV on a strike → Black-Scholes delta fallback; if IV is also missing,
  skip that strike (cannot compute assignment risk).
- Network failure → `_net.py` retries; on exhaustion, error for that ticker only,
  not the whole run.
- Zero shares / fewer than 100 shares of a ticker → report "not enough shares to
  cover one contract" and skip.

## 10. Testing

Follows the repo's `tests/` convention (pure functions, mocked network):

- `test_cc_screener.py` — synthetic chain fixtures: delta filter, OTM filter,
  bid>0 filter, annualized-yield computation, ranking order, contract-cap /
  covered-only math, top-N truncation, empty-result reason strings.
- `test_cc_earnings.py` — expiration-spans-earnings blackout logic, including the
  "earnings unknown" branch.
- Network layer (`chain_loader`, `earnings` fetch) is mocked; no live yfinance
  calls in tests.

## 11. Explicit non-goals / honesty guards

- The tool ranks by a **transparent yield metric**, not a return forecast. It does
  not claim covered calls improve total return — the repo's own finding says the
  opposite for total-return objectives. It serves the user's stated *income*
  objective only.
- It never recommends more contracts than shares cover (no naked calls).
- It does not execute, and it is labeled as not constituting financial advice.
