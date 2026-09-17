# Covered-Call Income Decision Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live CLI that ranks fully-covered call candidates for held tickers (NVDA, PLTR, TQQQ) by annualized premium yield, filtered by assignment-risk (delta) and an earnings blackout.

**Architecture:** A self-contained `covered_calls/` package (sibling to `options/`). Network-touching modules (`chain_loader`, `earnings`) are thin and separate from the pure ranking core (`screener`), so all ranking logic is unit-testable with synthetic inputs and no network. Reuses `options/_net.py` (proxy-aware session) and `options/greeks.py` (Black-Scholes delta fallback).

**Tech Stack:** Python 3, yfinance (via `options/_net.py`), scipy (via `options/greeks.py`), pandas, pytest.

## Global Constraints

- Never recommend more contracts than shares cover: `contracts = shares // 100` (no naked calls).
- Ranking metric is `annualized_yield = (bid / spot) * (365 / dte)` — a transparent comparison score, **not** a return forecast.
- Delta is the assignment-risk proxy; use yfinance-provided delta when present, else Black-Scholes fallback via `options.greeks.GreeksEngine`.
- Default risk-free rate `r = 0.045` (matches the repo's `cash_yield` default).
- Pure modules (`holdings`, `screener`) do no network I/O; network modules (`chain_loader`, `earnings`) are mocked in tests. No live yfinance calls in the test suite.
- Follow the repo's existing style: `from __future__ import annotations`, dataclasses, module docstrings, `python -m pytest tests/ -q` green before each commit.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1: Package skeleton + holdings config

**Files:**
- Create: `covered_calls/__init__.py`
- Create: `covered_calls/holdings.py`
- Test: `tests/test_cc_holdings.py`

**Interfaces:**
- Produces: `Holding` (dataclass: `ticker: str`, `shares: int`); `DEFAULT_HOLDINGS: list[Holding]`; `covered_contracts(shares: int) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cc_holdings.py
from covered_calls.holdings import Holding, DEFAULT_HOLDINGS, covered_contracts


def test_covered_contracts_floors_to_lots_of_100():
    assert covered_contracts(0) == 0
    assert covered_contracts(99) == 0
    assert covered_contracts(100) == 1
    assert covered_contracts(250) == 2


def test_default_holdings_cover_the_three_tickers():
    tickers = {h.ticker for h in DEFAULT_HOLDINGS}
    assert tickers == {"NVDA", "PLTR", "TQQQ"}
    assert all(isinstance(h.shares, int) and h.shares >= 0 for h in DEFAULT_HOLDINGS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cc_holdings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'covered_calls'`

- [ ] **Step 3: Write minimal implementation**

```python
# covered_calls/__init__.py
"""Covered-call income decision tool (live yfinance-backed screener)."""
```

```python
# covered_calls/holdings.py
"""User's held share counts and the covered-contract cap.

Edit ``DEFAULT_HOLDINGS`` with your real share counts. ``covered_contracts``
enforces the no-naked-calls rule: you can only sell one call per 100 shares.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Holding:
    ticker: str
    shares: int


# EDIT these share counts to your real holdings.
DEFAULT_HOLDINGS: list[Holding] = [
    Holding("NVDA", 0),
    Holding("PLTR", 0),
    Holding("TQQQ", 0),
]


def covered_contracts(shares: int) -> int:
    """Max fully-covered calls sellable against ``shares`` (1 per 100)."""
    return shares // 100
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cc_holdings.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add covered_calls/__init__.py covered_calls/holdings.py tests/test_cc_holdings.py
git commit -m "feat(cc): holdings config + covered-contract cap

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Screener data models + yield / delta primitives

**Files:**
- Create: `covered_calls/screener.py`
- Test: `tests/test_cc_screener.py`

**Interfaces:**
- Consumes: `options.greeks.GreeksEngine.calculate_greeks(S, K, T, r, sigma, option_type) -> dict` (uses `["delta"]`).
- Produces:
  - `ScreenParams` (dataclass: `dte_min: int = 20`, `dte_max: int = 45`, `max_delta: float = 0.20`, `top_n: int = 5`, `risk_free: float = 0.045`).
  - `RawOption` (dataclass: `expiration: date`, `dte: int`, `strike: float`, `bid: float`, `iv: float | None`, `delta: float | None`).
  - `annualized_yield(bid: float, spot: float, dte: int) -> float`.
  - `resolve_delta(spot: float, strike: float, dte: int, iv: float | None, given_delta: float | None, r: float) -> float | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cc_screener.py
from datetime import date

import pytest

from covered_calls.screener import (
    ScreenParams,
    RawOption,
    annualized_yield,
    resolve_delta,
)


def test_annualized_yield_scales_premium_to_a_year():
    # $2 premium on a $100 stock over ~36.5 days -> 2% * 10 = 20%
    assert annualized_yield(bid=2.0, spot=100.0, dte=36) == pytest.approx(0.2028, abs=1e-3)


def test_annualized_yield_zero_dte_is_zero():
    assert annualized_yield(bid=2.0, spot=100.0, dte=0) == 0.0


def test_resolve_delta_prefers_given_delta():
    assert resolve_delta(100, 110, 30, iv=0.4, given_delta=0.18, r=0.045) == 0.18


def test_resolve_delta_falls_back_to_black_scholes():
    d = resolve_delta(100, 110, 30, iv=0.40, given_delta=None, r=0.045)
    assert d is not None and 0.0 < d < 0.5  # OTM call, well under 0.5


def test_resolve_delta_none_when_no_delta_and_no_iv():
    assert resolve_delta(100, 110, 30, iv=None, given_delta=None, r=0.045) is None


def test_screen_params_defaults():
    p = ScreenParams()
    assert (p.dte_min, p.dte_max, p.max_delta, p.top_n, p.risk_free) == (20, 45, 0.20, 5, 0.045)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cc_screener.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'covered_calls.screener'`

- [ ] **Step 3: Write minimal implementation**

```python
# covered_calls/screener.py
"""Pure covered-call ranking core: no network I/O.

Consumes normalized option rows (``RawOption``) plus spot/shares/earnings context
and returns a ranked list of covered-call ``Candidate`` rows. Delta is the
assignment-risk proxy (~probability of finishing in-the-money); when the chain
does not carry a delta we fall back to Black-Scholes via ``options.greeks``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from options.greeks import GreeksEngine


@dataclass(frozen=True)
class ScreenParams:
    dte_min: int = 20
    dte_max: int = 45
    max_delta: float = 0.20
    top_n: int = 5
    risk_free: float = 0.045


@dataclass(frozen=True)
class RawOption:
    expiration: date
    dte: int
    strike: float
    bid: float
    iv: float | None
    delta: float | None


def annualized_yield(bid: float, spot: float, dte: int) -> float:
    """Premium as a fraction of spot, scaled to a year. 0 if dte<=0 or spot<=0."""
    if dte <= 0 or spot <= 0:
        return 0.0
    return (bid / spot) * (365.0 / dte)


def resolve_delta(
    spot: float,
    strike: float,
    dte: int,
    iv: float | None,
    given_delta: float | None,
    r: float,
) -> float | None:
    """Return the chain's delta if present, else a Black-Scholes call delta.

    Returns ``None`` when neither a delta nor an IV is available (cannot assess
    assignment risk, so the strike must be skipped by the caller).
    """
    if given_delta is not None:
        return given_delta
    if iv is None or iv <= 0 or dte <= 0:
        return None
    greeks = GreeksEngine.calculate_greeks(spot, strike, dte / 365.0, r, iv, "call")
    return greeks["delta"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cc_screener.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add covered_calls/screener.py tests/test_cc_screener.py
git commit -m "feat(cc): screener data models + yield/delta primitives

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: The screen() filter + rank pipeline

**Files:**
- Modify: `covered_calls/screener.py`
- Test: `tests/test_cc_screener.py` (add cases)

**Interfaces:**
- Consumes: `RawOption`, `ScreenParams`, `annualized_yield`, `resolve_delta` (Task 2); `covered_calls.holdings.covered_contracts` (Task 1).
- Produces:
  - `Candidate` (dataclass: `ticker: str`, `expiration: date`, `dte: int`, `strike: float`, `pct_otm: float`, `delta: float`, `bid: float`, `premium_yield: float`, `annualized_yield: float`, `contracts: int`, `total_premium: float`, `earnings_flag: bool`).
  - `ScreenResult` (dataclass: `candidates: list[Candidate]`, `reason: str | None`).
  - `screen(ticker: str, spot: float, shares: int, options: list[RawOption], params: ScreenParams, today: date, earnings_date: date | None, earnings_known: bool) -> ScreenResult`.

**Filter rules (in order):**
1. `contracts = covered_contracts(shares)`; if `0` → `ScreenResult([], "not enough shares to cover one contract")`.
2. Per option keep only if: `dte_min <= dte <= dte_max`; `strike > spot` (OTM); `bid > 0`; a resolvable `delta <= max_delta`.
3. Earnings: if `earnings_known and earnings_date is not None and today <= earnings_date <= expiration` → **drop** (blackout). If `not earnings_known` → keep but set `earnings_flag=True`.
4. Rank surviving candidates by `annualized_yield` descending; truncate to `top_n`.
5. If nothing survives → reason string explaining why (no strikes in window / all below delta / all blacked out).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cc_screener.py
from covered_calls.screener import Candidate, ScreenResult, screen

TODAY = date(2026, 9, 16)


def _opt(strike, bid, dte, delta, iv=0.5):
    return RawOption(
        expiration=date.fromordinal(TODAY.toordinal() + dte),
        dte=dte, strike=strike, bid=bid, iv=iv, delta=delta,
    )


def test_screen_ranks_by_annualized_yield_and_caps_contracts():
    opts = [
        _opt(strike=110, bid=1.0, dte=30, delta=0.15),   # ann ~0.11
        _opt(strike=115, bid=2.0, dte=30, delta=0.10),   # ann ~0.24  (best)
    ]
    res = screen("NVDA", spot=100, shares=250, options=opts,
                 params=ScreenParams(), today=TODAY,
                 earnings_date=None, earnings_known=True)
    assert res.reason is None
    assert [c.strike for c in res.candidates] == [115, 110]  # best first
    assert res.candidates[0].contracts == 2                  # 250 // 100
    assert res.candidates[0].total_premium == pytest.approx(2.0 * 100 * 2)


def test_screen_drops_in_the_money_and_high_delta_and_zero_bid():
    opts = [
        _opt(strike=95, bid=6.0, dte=30, delta=0.7),    # ITM -> drop
        _opt(strike=110, bid=1.0, dte=30, delta=0.35),  # delta > max -> drop
        _opt(strike=112, bid=0.0, dte=30, delta=0.15),  # zero bid -> drop
    ]
    res = screen("NVDA", spot=100, shares=100, options=opts,
                 params=ScreenParams(), today=TODAY,
                 earnings_date=None, earnings_known=True)
    assert res.candidates == []
    assert res.reason is not None


def test_screen_drops_dte_outside_window():
    opts = [_opt(strike=110, bid=1.0, dte=10, delta=0.15),   # too near
            _opt(strike=110, bid=1.0, dte=60, delta=0.15)]   # too far
    res = screen("NVDA", spot=100, shares=100, options=opts,
                 params=ScreenParams(), today=TODAY,
                 earnings_date=None, earnings_known=True)
    assert res.candidates == []


def test_screen_earnings_blackout_drops_spanning_expiration():
    opts = [_opt(strike=110, bid=1.0, dte=30, delta=0.15)]
    earnings = date.fromordinal(TODAY.toordinal() + 20)  # inside [today, exp]
    res = screen("NVDA", spot=100, shares=100, options=opts,
                 params=ScreenParams(), today=TODAY,
                 earnings_date=earnings, earnings_known=True)
    assert res.candidates == []
    assert "earnings" in res.reason.lower()


def test_screen_flags_when_earnings_unknown():
    opts = [_opt(strike=110, bid=1.0, dte=30, delta=0.15)]
    res = screen("NVDA", spot=100, shares=100, options=opts,
                 params=ScreenParams(), today=TODAY,
                 earnings_date=None, earnings_known=False)
    assert len(res.candidates) == 1
    assert res.candidates[0].earnings_flag is True


def test_screen_not_enough_shares():
    res = screen("NVDA", spot=100, shares=50, options=[],
                 params=ScreenParams(), today=TODAY,
                 earnings_date=None, earnings_known=True)
    assert res.candidates == []
    assert "cover" in res.reason.lower()


def test_screen_truncates_to_top_n():
    opts = [_opt(strike=100 + i, bid=1.0 + i * 0.1, dte=30, delta=0.15) for i in range(1, 9)]
    res = screen("NVDA", spot=100, shares=100, options=opts,
                 params=ScreenParams(top_n=3), today=TODAY,
                 earnings_date=None, earnings_known=True)
    assert len(res.candidates) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cc_screener.py -v`
Expected: FAIL — `ImportError: cannot import name 'Candidate'`

- [ ] **Step 3: Write minimal implementation**

Append to `covered_calls/screener.py`:

```python
from covered_calls.holdings import covered_contracts


@dataclass(frozen=True)
class Candidate:
    ticker: str
    expiration: date
    dte: int
    strike: float
    pct_otm: float
    delta: float
    bid: float
    premium_yield: float
    annualized_yield: float
    contracts: int
    total_premium: float
    earnings_flag: bool


@dataclass(frozen=True)
class ScreenResult:
    candidates: list[Candidate]
    reason: str | None


def screen(
    ticker: str,
    spot: float,
    shares: int,
    options: list[RawOption],
    params: ScreenParams,
    today: date,
    earnings_date: date | None,
    earnings_known: bool,
) -> ScreenResult:
    contracts = covered_contracts(shares)
    if contracts == 0:
        return ScreenResult([], "not enough shares to cover one contract")

    kept: list[Candidate] = []
    for o in options:
        if not (params.dte_min <= o.dte <= params.dte_max):
            continue
        if o.strike <= spot:            # OTM calls only
            continue
        if o.bid <= 0:
            continue
        delta = resolve_delta(spot, o.strike, o.dte, o.iv, o.delta, params.risk_free)
        if delta is None or delta > params.max_delta:
            continue
        if earnings_known and earnings_date is not None and today <= earnings_date <= o.expiration:
            continue                    # earnings blackout
        py = o.bid / spot
        kept.append(Candidate(
            ticker=ticker,
            expiration=o.expiration,
            dte=o.dte,
            strike=o.strike,
            pct_otm=o.strike / spot - 1.0,
            delta=delta,
            bid=o.bid,
            premium_yield=py,
            annualized_yield=annualized_yield(o.bid, spot, o.dte),
            contracts=contracts,
            total_premium=o.bid * 100 * contracts,
            earnings_flag=not earnings_known,
        ))

    kept.sort(key=lambda c: c.annualized_yield, reverse=True)
    kept = kept[: params.top_n]
    if not kept:
        return ScreenResult([], _empty_reason(options, params, earnings_known))
    return ScreenResult(kept, None)


def _empty_reason(options: list[RawOption], params: ScreenParams, earnings_known: bool) -> str:
    if not options:
        return f"no option chain in the {params.dte_min}-{params.dte_max} DTE window"
    if earnings_known:
        return (
            f"no strikes <= {params.max_delta:.2f}Δ in the "
            f"{params.dte_min}-{params.dte_max} DTE window (or all blacked out by earnings)"
        )
    return f"no strikes <= {params.max_delta:.2f}Δ in the {params.dte_min}-{params.dte_max} DTE window"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cc_screener.py -v`
Expected: PASS (all Task 2 + Task 3 tests)

- [ ] **Step 5: Commit**

```bash
git add covered_calls/screener.py tests/test_cc_screener.py
git commit -m "feat(cc): screen() filter + annualized-yield ranking pipeline

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Live option-chain loader (yfinance)

**Files:**
- Create: `covered_calls/chain_loader.py`
- Test: `tests/test_cc_chain_loader.py`

**Interfaces:**
- Consumes: `options._net.make_session()`; `covered_calls.screener.RawOption`, `ScreenParams`.
- Produces:
  - `load_chain(ticker: str, params: ScreenParams, today: date, ticker_factory=None) -> tuple[float, list[RawOption]]` — returns `(spot, options)`. `ticker_factory` defaults to a yfinance-backed factory and is injectable for tests.
  - `_spot_from_ticker(tk) -> float` and `_rows_from_chain(df, expiration, today, option_type='call') -> list[RawOption]` helpers.

**Notes for the implementer:**
- A yfinance `Ticker` exposes `.options` (tuple of `'YYYY-MM-DD'` expiry strings), `.option_chain(expiry)` (namedtuple with `.calls` DataFrame), and `.fast_info['lastPrice']` / `.history(period='1d')` for spot. The `.calls` DataFrame columns include `strike`, `bid`, `impliedVolatility`, and (sometimes) `delta` — treat `delta` as optional (yfinance usually omits it; fall back happens in the screener).
- Build the yfinance `Ticker` with the proxy-aware session: `yf.Ticker(ticker, session=make_session())`.
- Convert each expiry string to a `date`; `dte = (expiration - today).days`. Only load expiries with `params.dte_min <= dte <= params.dte_max` (avoid fetching every chain).
- `impliedVolatility` in yfinance is already a decimal (0.5 == 50%); pass through as `iv`. Missing/NaN → `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cc_chain_loader.py
from datetime import date
from types import SimpleNamespace

import pandas as pd

from covered_calls.chain_loader import load_chain
from covered_calls.screener import ScreenParams

TODAY = date(2026, 9, 16)


class _FakeTicker:
    """Minimal stand-in for yfinance.Ticker."""

    def __init__(self, ticker, session=None):
        self._exps = ["2026-09-25", "2026-10-16", "2026-12-18"]  # 9d, 30d, 93d

    @property
    def options(self):
        return tuple(self._exps)

    def option_chain(self, expiry):
        calls = pd.DataFrame({
            "strike": [110.0, 120.0],
            "bid": [2.0, 1.0],
            "impliedVolatility": [0.5, 0.45],
        })
        return SimpleNamespace(calls=calls, puts=pd.DataFrame())

    def history(self, period="1d"):
        return pd.DataFrame({"Close": [100.0]})


def test_load_chain_returns_spot_and_windowed_rows():
    spot, opts = load_chain("NVDA", ScreenParams(), TODAY, ticker_factory=_FakeTicker)
    assert spot == 100.0
    # only the 30-day expiry (2026-10-16) is inside 20-45 DTE
    assert {o.expiration for o in opts} == {date(2026, 10, 16)}
    assert {o.strike for o in opts} == {110.0, 120.0}
    assert all(o.iv is not None and o.delta is None for o in opts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cc_chain_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'covered_calls.chain_loader'`

- [ ] **Step 3: Write minimal implementation**

```python
# covered_calls/chain_loader.py
"""Live option-chain loader (yfinance, proxy-aware).

Thin network layer: turns a ticker into a spot price and a list of ``RawOption``
rows within the DTE window. Injectable ``ticker_factory`` keeps it testable
without hitting the network.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd

from options._net import make_session
from covered_calls.screener import RawOption, ScreenParams


def _default_ticker_factory(ticker: str):
    import yfinance as yf

    return yf.Ticker(ticker, session=make_session())


def _spot_from_ticker(tk) -> float:
    hist = tk.history(period="1d")
    if hist is None or hist.empty or "Close" not in hist:
        raise RuntimeError("no spot price available")
    return float(hist["Close"].iloc[-1])


def _cell(row, key):
    val = row.get(key)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _rows_from_chain(calls: pd.DataFrame, expiration: date, today: date) -> list[RawOption]:
    dte = (expiration - today).days
    rows: list[RawOption] = []
    for _, r in calls.iterrows():
        strike = _cell(r, "strike")
        bid = _cell(r, "bid")
        if strike is None or bid is None:
            continue
        rows.append(RawOption(
            expiration=expiration,
            dte=dte,
            strike=strike,
            bid=bid,
            iv=_cell(r, "impliedVolatility"),
            delta=_cell(r, "delta"),
        ))
    return rows


def load_chain(
    ticker: str,
    params: ScreenParams,
    today: date,
    ticker_factory=_default_ticker_factory,
) -> tuple[float, list[RawOption]]:
    tk = ticker_factory(ticker)
    spot = _spot_from_ticker(tk)
    options: list[RawOption] = []
    for exp_str in tk.options:
        expiration = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (expiration - today).days
        if not (params.dte_min <= dte <= params.dte_max):
            continue
        chain = tk.option_chain(exp_str)
        options.extend(_rows_from_chain(chain.calls, expiration, today))
    return spot, options
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cc_chain_loader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add covered_calls/chain_loader.py tests/test_cc_chain_loader.py
git commit -m "feat(cc): live yfinance option-chain loader (DTE-windowed)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Earnings-date lookup + blackout inputs

**Files:**
- Create: `covered_calls/earnings.py`
- Test: `tests/test_cc_earnings.py`

**Interfaces:**
- Consumes: `options._net.make_session()`.
- Produces: `next_earnings_date(ticker: str, today: date, ticker_factory=None) -> tuple[date | None, bool]` — returns `(earnings_date, known)`. `known=False` (and date `None`) when the lookup fails or returns nothing, so the caller flags rather than assumes safety.

**Notes for the implementer:**
- yfinance `Ticker.get_earnings_dates(limit=12)` returns a DataFrame indexed by tz-aware `Timestamp` (mix of past and upcoming). Pick the earliest index date `>= today`. Wrap the whole thing in `try/except Exception` → `(None, False)` — the API is flaky.
- Normalize the tz-aware `Timestamp` to a plain `date` (`.date()`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cc_earnings.py
from datetime import date

import pandas as pd

from covered_calls.earnings import next_earnings_date

TODAY = date(2026, 9, 16)


class _TickerWithEarnings:
    def __init__(self, ticker, session=None):
        pass

    def get_earnings_dates(self, limit=12):
        idx = pd.to_datetime(["2026-08-01", "2026-11-05", "2027-02-04"])
        return pd.DataFrame({"EPS Estimate": [1, 2, 3]}, index=idx)


class _TickerNoEarnings:
    def __init__(self, ticker, session=None):
        pass

    def get_earnings_dates(self, limit=12):
        raise RuntimeError("nope")


def test_next_earnings_date_picks_first_future_date():
    d, known = next_earnings_date("NVDA", TODAY, ticker_factory=_TickerWithEarnings)
    assert known is True
    assert d == date(2026, 11, 5)


def test_next_earnings_date_unknown_on_failure():
    d, known = next_earnings_date("NVDA", TODAY, ticker_factory=_TickerNoEarnings)
    assert d is None and known is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cc_earnings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'covered_calls.earnings'`

- [ ] **Step 3: Write minimal implementation**

```python
# covered_calls/earnings.py
"""Next-earnings-date lookup for the expiration blackout.

Returns ``(date, known)``. On any failure ``known`` is False so the caller flags
the candidates ("earnings unknown") instead of silently assuming no earnings risk.
"""

from __future__ import annotations

from datetime import date

from options._net import make_session


def _default_ticker_factory(ticker: str):
    import yfinance as yf

    return yf.Ticker(ticker, session=make_session())


def next_earnings_date(
    ticker: str,
    today: date,
    ticker_factory=_default_ticker_factory,
) -> tuple[date | None, bool]:
    try:
        tk = ticker_factory(ticker)
        df = tk.get_earnings_dates(limit=12)
        if df is None or len(df) == 0:
            return None, False
        future = sorted(ts.date() for ts in df.index if ts.date() >= today)
        if not future:
            return None, False
        return future[0], True
    except Exception:
        return None, False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cc_earnings.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add covered_calls/earnings.py tests/test_cc_earnings.py
git commit -m "feat(cc): next-earnings-date lookup for expiration blackout

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: CLI — wire loaders + screener, format tables, caveats

**Files:**
- Create: `covered_calls/cli.py`
- Test: `tests/test_cc_cli.py`

**Interfaces:**
- Consumes: `holdings.DEFAULT_HOLDINGS`/`Holding`, `chain_loader.load_chain`, `earnings.next_earnings_date`, `screener.{screen, ScreenParams, ScreenResult, Candidate}`.
- Produces:
  - `format_result(res: ScreenResult, ticker: str) -> str` — pure; renders one ticker's table or its empty-reason line.
  - `HEADER_CAVEAT: str` — the always-printed disclaimer.
  - `run(holdings, params, today, load_chain=..., next_earnings_date=...) -> str` — assembles the full report string; loaders injectable for tests.
  - `main(argv=None) -> int` — argparse entry point (`--dte-min --dte-max --max-delta --top-n --no-earnings-blackout --out PATH`).

**Notes:**
- `HEADER_CAVEAT` must state: delayed yfinance data; decision aid, not financial advice; you place the trades; and one line — "capped upside on fat-tail names; see docs/strategies/options-overlay.md".
- `--no-earnings-blackout` makes `run` pass `earnings_known=True, earnings_date=None` for every ticker (i.e. never blacks out).
- Table columns: `Exp | DTE | Strike | %OTM | Δ | Bid | Yield | Ann.Yield | Ctr | $Prem`. Percentages formatted to 1 dp, `earnings_flag` rows get a trailing `⚠`.
- `main` prints the report; with `--out PATH` also writes it. Keep a module `if __name__ == "__main__": raise SystemExit(main())`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cc_cli.py
from datetime import date

from covered_calls.cli import format_result, run, HEADER_CAVEAT
from covered_calls.holdings import Holding
from covered_calls.screener import ScreenParams, ScreenResult, Candidate

TODAY = date(2026, 9, 16)


def _cand(**kw):
    base = dict(
        ticker="NVDA", expiration=date(2026, 10, 16), dte=30, strike=120.0,
        pct_otm=0.2, delta=0.12, bid=1.5, premium_yield=0.015,
        annualized_yield=0.18, contracts=2, total_premium=300.0, earnings_flag=False,
    )
    base.update(kw)
    return Candidate(**base)


def test_format_result_renders_table_rows():
    res = ScreenResult([_cand()], None)
    out = format_result(res, "NVDA")
    assert "NVDA" in out and "120" in out and "18.0%" in out


def test_format_result_renders_empty_reason():
    res = ScreenResult([], "not enough shares to cover one contract")
    out = format_result(res, "PLTR")
    assert "PLTR" in out and "not enough shares" in out


def test_run_assembles_report_with_caveat_and_injected_loaders():
    def fake_load_chain(ticker, params, today, **kw):
        return 100.0, []  # empty chain -> empty reason path

    def fake_earnings(ticker, today, **kw):
        return None, True

    report = run(
        [Holding("NVDA", 200)], ScreenParams(), TODAY,
        load_chain=fake_load_chain, next_earnings_date=fake_earnings,
    )
    assert HEADER_CAVEAT.splitlines()[0] in report
    assert "NVDA" in report
    assert "options-overlay" in report  # the finding pointer is present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cc_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'covered_calls.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# covered_calls/cli.py
"""CLI: rank covered-call candidates for held tickers and print/save a report.

Decision aid only. Not financial advice; you place the trades.
"""

from __future__ import annotations

import argparse
from datetime import date

from covered_calls.holdings import DEFAULT_HOLDINGS, Holding
from covered_calls.screener import ScreenParams, ScreenResult, screen
from covered_calls import chain_loader, earnings as earnings_mod

HEADER_CAVEAT = (
    "Covered-call income screener - DECISION AID, NOT FINANCIAL ADVICE.\n"
    "Data is delayed (yfinance); you place the trades. Covered-only (<= shares/100).\n"
    "Capped upside on fat-tail names; see docs/strategies/options-overlay.md.\n"
)

_COLS = "  {exp:<10} {dte:>3} {strike:>8} {otm:>6} {delta:>5} {bid:>6} {yld:>6} {ann:>8} {ctr:>3} {prem:>9}"
_HEAD = _COLS.format(
    exp="Exp", dte="DTE", strike="Strike", otm="%OTM", delta="Δ",
    bid="Bid", yld="Yield", ann="Ann.Yld", ctr="Ctr", prem="$Prem",
)


def format_result(res: ScreenResult, ticker: str) -> str:
    lines = [f"== {ticker} =="]
    if not res.candidates:
        lines.append(f"  (no candidates: {res.reason})")
        return "\n".join(lines)
    lines.append(_HEAD)
    for c in res.candidates:
        flag = " ⚠" if c.earnings_flag else ""
        lines.append(_COLS.format(
            exp=c.expiration.isoformat(), dte=c.dte, strike=f"{c.strike:.2f}",
            otm=f"{c.pct_otm * 100:.1f}%", delta=f"{c.delta:.2f}", bid=f"{c.bid:.2f}",
            yld=f"{c.premium_yield * 100:.1f}%", ann=f"{c.annualized_yield * 100:.1f}%",
            ctr=c.contracts, prem=f"${c.total_premium:,.0f}",
        ) + flag)
    return "\n".join(lines)


def run(
    holdings: list[Holding],
    params: ScreenParams,
    today: date,
    load_chain=chain_loader.load_chain,
    next_earnings_date=earnings_mod.next_earnings_date,
    earnings_blackout: bool = True,
) -> str:
    blocks = [HEADER_CAVEAT]
    for h in holdings:
        try:
            spot, options = load_chain(h.ticker, params, today)
        except Exception as e:  # noqa: BLE001 - report per-ticker, keep going
            blocks.append(f"== {h.ticker} ==\n  (data error: {e})")
            continue
        if earnings_blackout:
            edate, eknown = next_earnings_date(h.ticker, today)
        else:
            edate, eknown = None, True
        res = screen(h.ticker, spot, h.shares, options, params, today, edate, eknown)
        blocks.append(format_result(res, h.ticker))
    return "\n\n".join(blocks)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Covered-call income screener")
    p.add_argument("--dte-min", type=int, default=20)
    p.add_argument("--dte-max", type=int, default=45)
    p.add_argument("--max-delta", type=float, default=0.20)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--no-earnings-blackout", action="store_true")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args(argv)

    params = ScreenParams(
        dte_min=args.dte_min, dte_max=args.dte_max,
        max_delta=args.max_delta, top_n=args.top_n,
    )
    report = run(
        DEFAULT_HOLDINGS, params, date.today(),
        earnings_blackout=not args.no_earnings_blackout,
    )
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cc_cli.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite + a live smoke check**

Run: `python -m pytest tests/ -q`
Expected: all green.

Run (live, needs unthrottled egress; may print data errors under a rate-limited proxy — that is acceptable): `python -m covered_calls.cli --top-n 3`
Expected: header caveat + one block per ticker (a table, an empty-reason line, or a per-ticker data-error line). With `DEFAULT_HOLDINGS` shares at 0, every block should say "not enough shares to cover one contract" — confirming the covered-only guard end to end.

- [ ] **Step 6: Commit**

```bash
git add covered_calls/cli.py tests/test_cc_cli.py
git commit -m "feat(cc): CLI wiring, table formatting, and disclaimers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Package README + docs pointer

**Files:**
- Create: `covered_calls/README.md`
- Modify: `README.md` (add a one-line pointer under the tools/strategy list)

**Interfaces:** none (docs only).

- [ ] **Step 1: Write `covered_calls/README.md`**

Cover: purpose (income-first covered-call screener, distinct from the total-return options-overlay negative finding), the module table (holdings/chain_loader/earnings/screener/cli), the selection rules and defaults (DTE 20-45, max-delta 0.20, earnings blackout), how to edit `holdings.py` share counts, run commands (`python -m covered_calls.cli`, `--out report.md`, `python -m pytest tests/ -q`), and the caveats (delayed data, not advice, covered-only, yield is a comparison metric not a forecast). Link to [docs/strategies/options-overlay.md](../docs/strategies/options-overlay.md) and the design spec.

- [ ] **Step 2: Add the pointer to the top-level `README.md`**

Add one bullet linking to `covered_calls/README.md`, described as "income-first covered-call screener (live yfinance decision tool)".

- [ ] **Step 3: Commit**

```bash
git add covered_calls/README.md README.md
git commit -m "docs(cc): package README + top-level pointer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §3 package layout → Tasks 1-7 create exactly the listed modules. ✓
- §4 selection logic (OTM, bid>0, delta filter, annualized yield, contract cap, ranking) → Task 3. ✓
- §4 delta yfinance-else-BS fallback → Task 2 `resolve_delta`. ✓
- §5 defaults (DTE 20-45, max_delta 0.20, top_n 5, blackout on) → Task 2 `ScreenParams` + Task 6 argparse. ✓
- §6 earnings blackout incl. "unknown → flag not drop" → Task 5 (`known` flag) + Task 3 (`earnings_flag`) + Task 6 (⚠ rendering). ✓
- §7 output (per-ticker table, empty reasons, `--out`, header caveat + finding pointer) → Task 6. ✓
- §9 error handling (skip ticker on failure, BS fallback, skip strike on no IV, <100 shares message) → Task 3 (reasons) + Task 4 (per-cell None) + Task 6 (per-ticker try/except). ✓
- §10 testing (pure screener/earnings tests, mocked network) → Tasks 2-6 all TDD with injectable factories. ✓
- §11 honesty guards (no naked calls, not advice, yield-not-forecast) → Global Constraints + Task 6 `HEADER_CAVEAT`. ✓
- §8 deferred IV-rank gate → intentionally not implemented; `ScreenParams` struct leaves room. ✓

**Placeholder scan:** No TBD/TODO; every code step has concrete code. ✓

**Type consistency:** `RawOption`, `Candidate`, `ScreenParams`, `ScreenResult` fields and `screen()` / `load_chain()` / `next_earnings_date()` signatures match across Tasks 2-6. `ticker_factory` / `load_chain` / `next_earnings_date` injection points are consistent. ✓
