# 3x TQQQ Signal & Parameter Comparison (README Table 4) — Design

## Goal

Answer, with data: for a 3x-leveraged NASDAQ-100 position (TQQQ), which
combination of {strategy type, signal source, ATR buffer, T+2
confirmation} performs best as real-world practice? Publish the answer as
a new Table 4 in README.md, alongside the existing Tables 1-3.

## Background

Tables 1-3 already compare 5 strategies (Buy & Hold, SMA+ATR, EMA
crossover, VIX filter, RSI) at 3 leverage tiers on 2 signal sources, but
each strategy only appears with its default parameters (SMA fixed at ATR
x2.5, EMA at fixed 50/200 spans, no T+2 on EMA). This table instead holds
leverage fixed at 3x and strategy family fixed to {SMA, EMA} — the two
strategies that already lead at least one of Tables 1-3 — and sweeps the
parameters that plausibly matter for real-world use.

## Combination Space

**SMA (`SMATrendFollowing`) — 20 variants:**
- ATR multiplier: 1.5, 2.0, 2.5, 3.0, 3.5
- Signal source: own (`^NDX`) or S&P 500 (`^GSPC`)
- T+2 confirmation: on or off

**EMA (`EMACrossover`) — 24 variants:**
- ATR multiplier: `None` (pure crossover, today's default behavior), 1.5,
  2.0, 2.5, 3.0, 3.5
- Signal source: own (`^NDX`) or S&P 500 (`^GSPC`)
- T+2 confirmation: on or off

All 44 variants run as 3x-leverage, `^NDX`-base rolling 26-year
backtests (same warmup-aware, monthly-stepped methodology as Tables
1-3), producing Avg/Med/Worst TWR, Worst DD, and Avg Trades per variant.

## `EMACrossover` Engine Changes

Two new, independently-optional constructor parameters:

```python
class EMACrossover(BaseStrategy):
    def __init__(self, name="EMA 50/200 Cross", fast_period=50, slow_period=200,
                 t2_confirmation=False, atr_multiplier=None):
        if atr_multiplier:
            name += f" (ATR x{atr_multiplier})"
        if t2_confirmation:
            name += " [T+2]"
        super().__init__(name)
        self.fast = fast_period
        self.slow = slow_period
        self.t2_confirmation = t2_confirmation
        self.atr_multiplier = atr_multiplier

    def _add_indicator_logic(self, df):
        df = df.copy()
        fast_ema = df['Close'].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df['Close'].ewm(span=self.slow, adjust=False).mean()

        if self.atr_multiplier or self.t2_confirmation:
            if self.atr_multiplier:
                spread = fast_ema - slow_ema
                buy_signal = spread > (df['ATR'] * self.atr_multiplier)
                sell_signal = spread < -(df['ATR'] * self.atr_multiplier)
            else:
                buy_signal = fast_ema > slow_ema
                sell_signal = fast_ema <= slow_ema

            if self.t2_confirmation:
                buy_signal = buy_signal.rolling(window=2).min() == 1
                sell_signal = sell_signal.rolling(window=2).min() == 1

            state = pd.Series(np.nan, index=df.index)
            state.loc[buy_signal] = 1.0
            state.loc[sell_signal] = 0.0
            initial_state_val = 1.0 if fast_ema.iloc[0] > slow_ema.iloc[0] else 0.0
            raw_signal = state.ffill().fillna(initial_state_val)
            df['in_market'] = raw_signal.shift(1).fillna(initial_state_val).astype(bool)
        else:
            # Byte-identical to today's behavior — no ATR, no T+2.
            raw_signal = fast_ema > slow_ema
            shifted = raw_signal.shift(1)
            df['in_market'] = np.where(shifted.isna(), False, shifted).astype(bool)

        return df
```

**Critical invariant:** when `atr_multiplier=None` and `t2_confirmation=False`
(today's only usage, in Tables 1-3 and `bot.py` if ever used), the code
takes the exact original branch — same operations, same order, same
output. This must be verified with a regression check (see Testing)
before any table numbers are trusted, since Tables 1-3's EMA rows must
not shift.

**Why the state-machine path for both knobs:** a naive
`raw_signal.rolling(2).min()==1` on the plain crossover boolean would
require 2 days to confirm entry but only 1 to fall out of confirmation
on exit (asymmetric). Treating "fast above slow (by more than the ATR
band, if set)" and "fast below slow (by more than the band)" as
independent buy/sell events — each optionally 2-day-confirmed — then
forward-filling state, mirrors `SMATrendFollowing`'s already-correct
pattern and gives genuinely symmetric confirmation on both sides.

**ATR dead-zone semantics:** `buy` requires the fast/slow spread to
exceed `ATR × multiplier` on the *high* side; `sell` requires it to fall
below `-ATR × multiplier` on the low side. Between those two thresholds,
state holds (neutral zone) — directly analogous to `SMATrendFollowing`'s
price-vs-SMA band, just applied to the EMA spread.

## Shared Helper Extraction

`backtest/generate_readme_tables.py` currently defines `monthly_start_dates()`
(warmup-aware start-date generation) and `summarize()` (per-strategy
Avg/Med/Worst TWR + independent Worst DD) as module-local functions. Both
are needed again by the new comparison script. Promote them into
`backtest/strat_backtest.py` as shared, generically-useful utilities:

- `warmup_aware_start_dates(tickers, period_years)` — same body as today's
  `monthly_start_dates`, renamed for clarity now that it's a shared,
  public function (not a private helper name specific to one script).
- `summarize_rolling_results(df_res, strategies, metric_label="TWR")` —
  same body as today's `summarize`.

`generate_readme_tables.py` is updated to import and call these instead
of defining its own copies — a mechanical extraction, not a behavior
change. This must be verified by regenerating Tables 1-3 and confirming
byte-identical output to the current committed numbers (see Testing).

## New Script: `backtest/generate_signal_comparison.py`

Builds the 44 `(strategy_instance, label)` pairs described above,
runs each through `RollingBacktester` at `leverage=3, base_ticker="^NDX"`
with the appropriate `signal_ticker`, using `warmup_aware_start_dates`
for the window set and `summarize_rolling_results` for the metrics.
Emits two markdown tables (SMA sweep, EMA sweep) plus the ranking-rule
computation, to stdout and to a gitignored
`backtest/signal_comparison_output.md` scratch file — same
generate-then-hand-transcribe pattern as `generate_readme_tables.py`.

## Ranking Rule ("Best Real-World Practice")

1. Across all 44 variants, compute each one's Worst DD.
2. Exclude the worst quartile by Worst DD (the 11 variants — 25% of
   44 — with the deepest drawdowns) as "outlier drawdown."
3. Among the remaining 33, pick the single variant with the highest Avg
   TWR. That is the published "Best Practice" pick.
4. State the pick's full parameter combination (strategy, signal,
   ATR/None, T+2 on/off) and its Avg TWR / Worst DD / Avg Trades
   explicitly in the README callout — no vague "the top strategy," name
   the exact configuration.

This rule is mechanical and reproducible from the output table alone —
no separate judgment call required at publish time.

## Output: README.md Table 4

New section following Table 3, same house style (bold winning cells,
blockquote commentary below). Structure:

- One-sentence framing: what's being compared and why (3x leverage,
  which strategies, why EMA now has ATR/T+2 options it didn't have
  before).
- Bolded one-line "Best Practice" callout per the ranking rule above.
- Sub-table "SMA — ATR & Signal Sweep" (20 rows: ATR × signal × T+2).
- Sub-table "EMA — ATR & Signal Sweep" (24 rows: ATR(incl. None) ×
  signal × T+2).
- Blockquote commentary: does ATR help EMA at all (comparing the `None`
  rows to the ATR rows)? Does S&P 500 signal help either family at 3x?
  Does T+2 help or hurt at 3x specifically (leverage-dependent, since
  Tables 1-3 only tested T+2's effect implicitly via the one config bot.py
  runs)?

CHANGELOG entry documenting: the `EMACrossover` engine additions, the
shared-helper extraction, the new script, and the published finding.

## Testing

No project-wide test suite exists yet (documented, separate gap). For
this change specifically, two focused regression checks are required
before any Table 4 numbers are trusted:

1. **EMA behavior-preservation check:** run `EMACrossover()` (defaults,
   no ATR, no T+2) against a fixed date range before and after the
   engine change; assert identical `in_market` series and identical
   `Backtester.run()` result dict. This directly protects Tables 1-3's
   already-published EMA numbers.
2. **Shared-helper extraction check:** regenerate Tables 1-3 via
   `generate_readme_tables.py` after the `monthly_start_dates`/`summarize`
   extraction; assert output is byte-identical to
   `backtest/readme_tables_output.md`'s current committed content (or,
   if regenerating from live data isn't practical to diff byte-for-byte
   due to today's date moving the window range forward, assert the
   window counts/date ranges and every existing strategy's numbers are
   unchanged — only structurally verify, not literally re-run against
   frozen historical data unless the delta is explained by calendar
   drift alone).

## Out of Scope

- Extending T+2/ATR to VIX filter or RSI strategies (not part of this
  request).
- Testing leverage tiers other than 3x for this comparison.
- Building a general strategy-registry/config-driven runner (that's the
  separate, not-yet-started `future-generalize-backtest-framework.md`
  plan) — this stays a purpose-built script following the existing
  `generate_readme_tables.py` pattern.
