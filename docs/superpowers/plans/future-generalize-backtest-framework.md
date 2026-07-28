# Generalizing the Backtest Framework for Arbitrary Strategies — Implementation Plan

> **STATUS: FUTURE PHASE — DO NOT EXECUTE.** This plan was requested as a
> plan only. Do not dispatch implementers against it until the user
> explicitly asks to start this phase. It is written at a lower level of
> granularity than an execution-ready SDD plan (no bite-sized TDD steps)
> because its purpose right now is scoping and sequencing, not dispatch.
> When the user is ready to build it, re-derive an execution-ready plan
> per the writing-plans skill from whichever phase they pick.

**Goal:** Turn the TQQQ-specific SMA/ATR bot into a reusable backtesting
framework where adding a new strategy, a new ticker universe, or a new
report doesn't require touching the engine or duplicating logic — while
keeping the current bot (`bot.py` + `strat_backtest.py`) working
unmodified in behavior throughout.

**Why now:** The 2026-07-27 optimization audit
(`docs/optimization-analysis-2026-07-27.md`, section 3, "Reusability: the
engine is coupled to one strategy's shape") found three concrete coupling
points that block reuse: presentation logic mixed into `Backtester`,
strategy-specific fields read ad-hoc by `bot.py`, and a hardcoded
defensive-asset universe. This plan addresses each with evidence-backed
file:line references rather than a from-scratch redesign.

**Architecture:** Incremental refactor in 5 phases, each independently
shippable and each preserving current behavior (verified by the test
suite added in Phase 0). Phases are ordered so later phases build on
interfaces the earlier phases establish — do not reorder without checking
dependencies noted per phase.

**Tech Stack:** No new dependencies required for Phases 0-3. Phase 4
(config-driven strategy registry) may add `pyyaml` if YAML configs are
preferred over Python dicts — a decision to make at that phase, not now.

## Global Constraints (apply to every phase)

- **Behavior parity:** at the end of every phase, `python bot.py` (dry
  run, no webhook) must produce output equivalent to today's, and
  `backtest/generate_readme_tables.py`'s numbers for a fixed date range
  must be byte-for-byte identical to a pre-phase baseline run. This is the
  regression gate — capture the baseline before Phase 1 starts.
- **No engine rewrite:** `Backtester._run_portfolio_math` is
  well-tested-by-history (see optimization report §1) and should be
  *wrapped/extended*, not rewritten, in every phase below.
- **One strategy family stays canonical:** `SMATrendFollowing` remains the
  reference implementation every new interface is validated against —
  don't design an abstraction whose first real consumer is a strategy that
  doesn't exist yet.

---

## Phase 0: Establish the regression safety net

Must land before any refactor phase — without it, "behavior parity" above
is unverifiable.

- Add `tests/test_strat_backtest.py` per optimization report §1: unit
  tests for `SMATrendFollowing._add_indicator_logic` (including T+2),
  `_run_portfolio_math` (synthetic data, hand-computed expected TWR/DD/tax),
  and `_calculate_trade_stats`.
- Add one golden-master test: run `Backtester` for a fixed short date range
  (e.g. `2018-01-01` to `2019-01-01`, `^NDX`, `leverage=3`) against live
  cached data, snapshot `final_value`/`strategy_twr`/`max_drawdown` to a
  checked-in fixture file, assert future runs match within float tolerance.
  This is what later phases diff against for parity.
- Pin `requirements.txt` per optimization report §5 (`yfinance>=0.2.40` or
  the version confirmed working in this environment) and add
  `pytest>=8` — untracked test infra shouldn't rely on a globally
  installed pytest.

**Exit criteria:** `pytest` runs green in CI-equivalent conditions (no
network required except the one golden-master test, which should be
marked so it can be skipped offline).

---

## Phase 1: Separate computation from presentation

**Coupling point (optimization report §3):** `Backtester._print_results`
(`backtest/strat_backtest.py:616-659`) mixes formatting into the class
that owns the money math; `RollingBacktester.run()` builds result
DataFrames with `f"{strat.name} TWR (%)"`-style wide columns
(`backtest/strat_backtest.py:715-717`) that every consumer (README
script, notebook, future dashboards) has to independently know how to
parse.

- Extract `_print_results` into a standalone `reporting.py` module
  function, e.g. `print_backtest_result(result: dict, strategy_name: str,
  leverage: int, base_ticker: str, ...)`. `Backtester.run()` keeps calling
  it when `verbose=True`, but the formatting logic is no longer a method
  on the money-math class.
- Add a **long-format** result option alongside (not replacing) the
  existing wide-format DataFrame from `RollingBacktester.run()`: one row
  per (start_date, strategy, metric, value) rather than one column per
  strategy-metric pair. This is what `generate_readme_tables.py`-style
  consumers should switch to in Phase 4 — wide format stays for backward
  compatibility with the notebook.
- No change to `_run_portfolio_math` itself.

**Exit criteria:** Golden-master test from Phase 0 still passes bit-for-bit;
`bot.py` and `generate_readme_tables.py` unchanged and still working
(they don't touch `_print_results` today, so this phase should be a
no-op for them — confirms the extraction was clean).

---

## Phase 2: Formal strategy report-field interface

**Coupling point (optimization report §3):** `bot.py`'s
`format_signal_section` (`bot.py:36-53`) reads `stats.get('upper_bound',
0.0)`, `stats.get('trend', 'N/A')` — fields only `SMATrendFollowing`
populates (`backtest/strat_backtest.py:286-293`). A new strategy run live
today would report blank/zero for every strategy-specific field, silently,
because `.get(..., default)` swallows the absence.

- Add `BaseStrategy.get_report_fields(self) -> dict` (default: `{}`,
  documented as "strategy-specific fields for the live report; keys become
  template placeholders"). `SMATrendFollowing` overrides it to return
  `{"trend": ..., "upper_bound": ..., "lower_bound": ...}` — the same
  values it computes today, just surfaced through an explicit hook instead
  of being bolted onto the base `get_live_stats` return dict.
- Change `bot.py`'s `format_signal_section` to fail loudly (not silently
  default) when a strategy doesn't provide an expected field for the
  *currently configured* strategy — since `bot.py` only ever runs
  `SMATrendFollowing` today, this should never trigger, but it converts a
  silent-wrong-report failure mode into a fail-fast one for whoever adds
  the next live strategy.
- Fix the `qqq_price`/`.item()` naming issues from optimization report §4
  as part of this phase, since you're already touching this exact code
  path (`backtest/strat_backtest.py:233`).

**Exit criteria:** `bot.py`'s Discord message output byte-for-byte
identical to pre-phase baseline for the current strategy config.

---

## Phase 3: Generalize the defensive-rotation component

**Coupling point (optimization report §3):**
`get_current_defensive_rotation` (`backtest/strat_backtest.py:118-150`)
hardcodes `["KMLM", "TLT", "GLD", "SHY"]` and `126`-day momentum as
literals in the function body.

- Turn it into a small configurable helper: `get_current_defensive_rotation(data,
  tickers=("KMLM", "TLT", "GLD", "SHY"), momentum_days=126)` — same
  defaults, now parameters. `bot.py`'s call site
  (`bot.py:27`) stays unchanged (defaults preserve current behavior).
- Delete or rewrite `show_recent_signals.py` per optimization report §2 —
  once the rotation logic is parameterized and imported rather than
  reimplemented, this script's only reason to exist (a historical "what
  would the bot have held" view) can call the real function directly.

**Exit criteria:** `bot.py`'s defensive-allocation section of the Discord
message unchanged for the current 4-asset/126-day config.

---

## Phase 4: Config-driven experiment runner

This is the phase that actually delivers "backtest other strategies
without writing a new script" — Phases 1-3 are the interface work that
makes it safe.

- Design a small declarative experiment spec (Python dataclass is enough;
  don't reach for YAML/JSON until a second, non-Python consumer actually
  needs it — YAGNI per this project's own stated conventions):
  ```python
  @dataclass
  class ExperimentSpec:
      name: str
      base_ticker: str
      signal_ticker: str | None
      strategies: list[BaseStrategy]
      leverage_configs: list[dict]
      period_years: int
      annual_dca: float
      apply_tax: bool
  ```
- Generalize `backtest/generate_readme_tables.py` into
  `backtest/run_suite.py`, which takes a list of `ExperimentSpec` and
  produces the same long-format output Phase 1 introduced, for arbitrary
  strategies/tickers — the three README tables become three
  `ExperimentSpec` instances passed to one runner, not three near-duplicate
  functions (`run_table()` currently hardcodes NDX/GSPC/cross-signal by
  name).
- `generate_readme_tables.py` becomes a thin wrapper: define the 3 specs,
  call `run_suite.run(specs)`, format for README. This keeps the
  README-specific formatting (bold-best-per-tier, the specific markdown
  table shape) out of the reusable runner.

**Exit criteria:** Re-running the README table generation through the new
`run_suite.py` path produces numbers matching the Phase 0 golden master
and the pre-refactor `generate_readme_tables.py` output for the same date
range.

---

## Phase 5 (optional, lower priority): Packaging & script organization

Only worth doing once Phases 0-4 land and the project actually has a
second strategy or ticker universe in active use — don't do this
speculatively.

- Move one-off analysis scripts (anything like `show_recent_signals.py`)
  into a `scripts/` directory, separate from the reusable `backtest/`
  package.
- Consider `pyproject.toml` + `python -m backtest.run_suite --spec
  configs/ndx_gspc.py` as a CLI entry point once there are enough specs to
  make ad-hoc script-editing painful.

---

## Sequencing notes for whoever picks this up

- Phases 0→1→2→3→4 have a strict dependency order as written (each phase's
  exit criteria depends on the previous phase's interface existing).
  Phase 5 can slot in anytime after Phase 4 or be dropped entirely.
- Every phase's exit criteria is a parity check, not a new-feature check —
  this plan deliberately defers "add a second strategy for real" to
  whatever prompted this work in the first place; Phases 0-4 just make
  that future addition cheap instead of a re-plumbing exercise.
- Re-run the optimization audit's §3 coupling points against the codebase
  before starting, in case the codebase moved since 2026-07-27.
