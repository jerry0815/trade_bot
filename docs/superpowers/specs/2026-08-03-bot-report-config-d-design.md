# bot.py Config-D Reporting — Design Spec (2026-08-03)

## Goal

Change `bot.py`'s daily Discord report so its **recommended action** reflects
configuration **D** — dual-signal agreement (^NDX and ^GSPC both bullish, no
T+2) plus a ^GSPC trailing stop (8%, 60-day cooldown) — while keeping the two
per-index component sections it already shows, and adding one new
trailing-stop status block.

Chosen scope (user decision): **replace the recommendation with D, keep the
component signals visible, add a stop-status block.** Not a full report
rewrite, not a purely-additive section.

## Background

- Full validation of D lives in `docs/combined-system-comparison-2026-08-03.md`
  and the finding chain it links. D was chosen for its drawdown protection
  (mean Max DD -64.77% vs. -84.59% for dual-signal alone; -48.73% vs. -69.96%
  out-of-sample) accepting a return cost vs. dual-signal-no-stop.
- `bot.py` today runs `SMATrendFollowing(sma_window=200, t2_confirmation=True)`
  on QQQ/SPY/TQQQ ETFs, renders a PRIMARY (S&P 500) and SECONDARY (NASDAQ)
  signal section, and takes RECOMMENDED ACTION from the S&P section's action.
- The trailing-stop overlay currently exists only on `SMATrendFollowing`
  (`_apply_trailing_stop`, verified lookahead-free).

## Key decisions

1. **Signal basis: indices for the decision, ETFs for display.** The D
   decision and the stop are computed on ^NDX/^GSPC — identical to every
   backtest. The component sections keep displaying QQQ/SPY prices/bands as
   they do now. `DualSignalAgreement._add_indicator_logic` already fetches
   ^NDX/^GSPC internally, so this needs no ticker plumbing.

2. **Stop tracks ^GSPC** — the validated choice (single-ticker, first-breach,
   8%, 60d).

3. **Statefulness accepted as recompute-from-history.** `bot.py` runs
   statelessly once per day; peak-since-entry is recomputed each run from the
   available history. Safe because the longest measured hold is ~3.2 years and
   the stop's peak resets on each entry; the fetch window must comfortably
   exceed that. Documented as an assumption in code, not persisted state.

## Components

### 1. Engine: share the stop overlay (`backtest/strat_backtest.py`)

- **Relocate** `_apply_trailing_stop` from `SMATrendFollowing` to
  `BaseStrategy`, byte-identical. It reads only `df['in_market']`,
  `df['Close']`, `self.trailing_stop_pct`, `self.trailing_stop_cooldown_days`.
  Regression gate: `SMATrendFollowing`'s rolling numbers must reproduce
  exactly (baseline Avg TWR 21.77% / Worst DD -83.40%, and the published
  (8%,60d) row 23.43% / -64.78%).
- **Add** `trailing_stop_pct` / `trailing_stop_cooldown_days` to
  `DualSignalAgreement.__init__` (default `None`/off; byte-identical to
  current behavior when off — the existing README Table 4 numbers must be
  unchanged when the params are unset), applied in its `_add_indicator_logic`
  after the dual-signal `in_market` column is built.

### 2. Engine: live stop status (`DualSignalAgreement.get_live_stats` override)

Returns the existing base fields plus a `trailing_stop` sub-dict. Interface:

```
trailing_stop = {
  "state": "holding" | "triggered" | "cooldown" | "inactive",
  "peak": float | None,           # ^GSPC peak since current entry
  "current": float | None,        # latest ^GSPC close
  "drop_pct": float | None,       # (current - peak)/peak * 100, <= 0
  "distance_pct": float | None,   # how much further drop until -8% trigger
  "cooldown_left": int | None,    # trading days remaining, when state==cooldown
}
```

- Derived by re-running the same peak/cooldown walk the overlay uses over the
  fetched ^GSPC history, then reading the final day's state. A dedicated
  `_trailing_stop_status(df)` helper computes this so `_apply_trailing_stop`
  itself stays untouched (protecting the regression gate above).
- `state` mapping: in a position and stop not fired today → `holding`; stop
  fired on the latest day → `triggered`; in the post-fire cooldown window →
  `cooldown`; in cash for any other reason → `inactive`.

### 3. Report: `bot.py`

- `bot.py` now holds **two** strategy instances: the existing
  `SMATrendFollowing` (used only to render the two per-index component
  sections, unchanged) and a new D instance (used only for the recommendation
  and stop status). D is instantiated as:
  `DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
  trailing_stop_pct=0.08, trailing_stop_cooldown_days=60)`, and
  `D.get_live_stats(...)` is called once; only its `action` and `trailing_stop`
  fields are consumed (its per-ticker price fields are ignored, since the
  component sections supply display prices).
- **Component sections unchanged**: keep the existing per-index
  `get_live_stats` calls (via the SMA strategy) that render the NASDAQ and
  S&P 500 trend/bands/duration blocks exactly as today. These are display of
  each index's own trend — the inputs to dual-signal agreement.
- **RECOMMENDED ACTION** now comes from D's combined verdict (both indices
  bullish AND stop not fired), replacing the S&P-only action.
- **New Trailing-Stop Status block**, rendered from the `trailing_stop`
  sub-dict, with jargon-free status wording:

```
🛑 TRAILING STOP (S&P 500, 8% / 60d)
• Peak since entry: 5,540.20 | Current: 5,502.10
• Drop from peak: -0.69% (trigger at -8.00%, 7.31% to go)
• Status: Holding
```
Status line values by state:
  - holding  → `Holding`
  - triggered → `SELL — S&P fell 8% from peak`
  - cooldown → `In cash — stop cooldown, {cooldown_left} trading days until re-entry allowed`
  - inactive → `In cash — no position`
When `state` is `cooldown`/`inactive`, the peak/drop lines show `n/a` (no
position, nothing tracked).

- **Signal-change alert** flips to track D's action changing vs. the prior day
  (a new state, including a stop-triggered exit), instead of either raw index
  trend flipping.

## Explicitly out of scope

- No change to trade execution — `bot.py` reports; it does not trade. No order
  placement, no persisted position state.
- No change to the defensive-rotation section.
- No change to `README.md` tables or `CHANGELOG.md` (the finding docs already
  carry the analysis).
- No parameter re-selection — 8%/60d and dual-signal-no-T+2 are fixed inputs
  from the completed investigation.
- No commission/tax modeling (a report, not a backtest).

## Testing

No project test suite exists (established convention). Verify by:
1. **Regression:** re-run `backtest/trailing_stop_region_validate.py` (or the
   baseline rows of any rolling script) and confirm `SMATrendFollowing`'s
   numbers are unchanged after the `_apply_trailing_stop` relocation, and that
   `DualSignalAgreement` with the stop off reproduces README Table 4's 25.81%.
2. **Live smoke:** run `python bot.py` with no `DISCORD_WEBHOOK` set → prints
   the report to stdout. Confirm the new recommendation, the component
   sections, and the stop-status block all render with live data and no
   traceback, across whatever state today happens to be.
