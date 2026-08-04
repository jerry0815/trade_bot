# bot.py Config-D Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `bot.py`'s daily report recommend configuration D (dual-signal agreement + ^GSPC trailing stop 8%/60d), keep the two per-index component sections, and add a trailing-stop status block.

**Architecture:** Share the existing trailing-stop overlay by relocating it to `BaseStrategy`, extend `DualSignalAgreement` to carry the stop and expose live stop status, then rewire `bot.py` to source its recommendation and a new status block from a D instance while leaving the component sections and defensive rotation untouched.

**Tech Stack:** Python 3.11, pandas, numpy — same as the rest of the project. No new dependencies. No test framework (project has no suite by established convention; verification is reproduction + live smoke).

**Full design context:** `docs/superpowers/specs/2026-08-03-bot-report-config-d-design.md`

## Global Constraints

- **Signal basis:** the D decision and stop are computed on `^NDX`/`^GSPC` indices (identical to every backtest); component sections still display QQQ/SPY ETF prices. The stop tracks `^GSPC`.
- **Stop parameters are fixed inputs:** `trailing_stop_pct=0.08`, `trailing_stop_cooldown_days=60`, dual-signal `t2_confirmation=False`. No re-selection.
- **Byte-identical when off:** `SMATrendFollowing`'s numbers must be unchanged after the overlay relocation; `DualSignalAgreement()` with the stop unset must reproduce README Table 4's 25.81% Avg TWR.
- **Report-only:** no trade execution, no persisted position state, no order placement.
- **No change** to the defensive-rotation section, `README.md`, or `CHANGELOG.md`.
- **Reuse, don't duplicate** engine primitives; import from `backtest.strat_backtest`.

---

### Task 1: Relocate the trailing-stop overlay to `BaseStrategy` (regression-gated)

Moves `_apply_trailing_stop` so `DualSignalAgreement` can use it too, and adds an optional `price` argument so the stop can track a series other than `df['Close']` (needed because in the live path `df['Close']` is an ETF, not `^GSPC`). `SMATrendFollowing`'s behavior must stay byte-identical (it keeps calling with no `price`, defaulting to `df['Close']`).

**Files:**
- Modify: `backtest/strat_backtest.py` (remove `_apply_trailing_stop` from `SMATrendFollowing` at lines 447-530; add it to `BaseStrategy`, after `get_live_stats` which ends at line 238)

**Interfaces:**
- Produces: `BaseStrategy._apply_trailing_stop(self, df, price=None) -> pd.Series` — the existing overlay, now inherited by all strategies; `price` defaults to `df['Close']`.

- [ ] **Step 1: Cut the method out of `SMATrendFollowing`**

Delete the entire `_apply_trailing_stop` method from `SMATrendFollowing` (currently lines 447-530, the block starting `def _apply_trailing_stop(self, df):` up to and including its `return pd.Series(final, index=df.index)`). Leave the call site at line 443 (`df['in_market'] = self._apply_trailing_stop(df)`) unchanged — it will resolve via inheritance.

- [ ] **Step 2: Paste it into `BaseStrategy` with the `price` parameter**

Insert this method into `BaseStrategy`, immediately after `get_live_stats` ends (line 238), before `class BuyAndHold` (line 240). It is the exact method just removed, with only the signature and the two lines that read the price series changed (marked):

```python
    def _apply_trailing_stop(self, df, price=None):
        """
        Walks the already-computed (execution-day) in_market column day by
        day. Tracks the running peak Close since the most recent entry;
        forces an exit the day Close falls trailing_stop_pct below that
        peak, regardless of the trend signal. After a stop-triggered exit,
        forces in_market False for the next trailing_stop_cooldown_days
        trading days even if the trend signal says in-market again; normal
        trend-driven logic resumes once the cooldown elapses.

        price: optional Series to track the stop against (peak + breach).
        Defaults to df['Close']. DualSignalAgreement passes ^GSPC explicitly
        so the stop tracks the validated reference even when df['Close'] is
        an ETF (the live path) rather than the ^GSPC signal (the backtest).

        Lookahead-free by construction: in_market[i] is already the
        EXECUTION-day column, and _run_portfolio_math sells an exit day at
        TODAY'S OPEN, so the decision for day i may only use information
        available before day i's open -- i.e. close[i-1], never close[i].
        All three reads below (peak init on a fresh entry, the running peak
        update, and the breach comparison) use the SAME lagged close series.

        Precedence: when a trend-signal exit and a stop breach would both
        apply on the same day, the trend-signal exit wins (the `not desired`
        branch is checked first) and does NOT start a cooldown -- only a
        stop-triggered exit does.
        """
        trend_in_market = df['in_market'].to_numpy()
        close = (df['Close'] if price is None else price).to_numpy()  # CHANGED
        close_lagged = np.roll(close, 1)
        if len(close_lagged):
            close_lagged[0] = close[0]
        n = len(df)
        final = np.zeros(n, dtype=bool)

        was_in = False
        peak = 0.0
        cooldown = 0

        for i in range(n):
            if cooldown > 0:
                final[i] = False
                cooldown -= 1
                was_in = False
                continue

            desired = trend_in_market[i]
            if not desired:
                final[i] = False
                was_in = False
                continue

            if not was_in:
                peak = close_lagged[i]
                was_in = True
                final[i] = True
                continue

            peak = max(peak, close_lagged[i])
            if close_lagged[i] < peak * (1 - self.trailing_stop_pct):
                final[i] = False
                was_in = False
                cooldown = self.trailing_stop_cooldown_days
            else:
                final[i] = True

        return pd.Series(final, index=df.index)
```

- [ ] **Step 3: Verify `SMATrendFollowing` reproduces its published single-window numbers**

Run:
```bash
python -c "
import sys; sys.path.insert(0,'.'); import warnings; warnings.filterwarnings('ignore')
from backtest.strat_backtest import SMATrendFollowing, Backtester
for kw,exp in [(dict(),'baseline'),(dict(trailing_stop_pct=0.08,trailing_stop_cooldown_days=60),'8/60')]:
    s=SMATrendFollowing(sma_window=200,atr_multiplier=2.5,t2_confirmation=True,**kw)
    r=Backtester(base_ticker='^NDX',signal_ticker='^GSPC',start_date='1999-01-01',period_years=26,leverage=3,expense_ratio=0.0095,initial_fund=10000,verbose=False).run(s)
    print(exp, round(r['strategy_twr'],2), round(r['max_drawdown'],2), len(r['trade_log']))
"
```
Expected: two lines, no traceback, both with real numbers. The `8/60` line must show a shallower (less negative) max drawdown than `baseline` — confirming the relocated overlay still fires. If either errors with `AttributeError: _apply_trailing_stop`, the method was not correctly placed in `BaseStrategy`.

- [ ] **Step 4: Commit**

```bash
git add backtest/strat_backtest.py
git commit -m "refactor: relocate _apply_trailing_stop to BaseStrategy with optional price series"
```

---

### Task 2: Add the trailing-stop overlay to `DualSignalAgreement`

Give `DualSignalAgreement` the same opt-in stop params `SMATrendFollowing` has, applied against `^GSPC`. Preserve the pre-stop trend signal in a separate column so the live status helper (Task 3) can re-walk it.

**Files:**
- Modify: `backtest/strat_backtest.py` (`DualSignalAgreement.__init__` at lines 539-546; `_add_indicator_logic` at lines 556-583)

**Interfaces:**
- Consumes: `BaseStrategy._apply_trailing_stop(df, price=)` from Task 1; `get_cached_signals` (already imported and used in this class).
- Produces: `DualSignalAgreement(..., trailing_stop_pct=None, trailing_stop_cooldown_days=60)`; after `_add_indicator_logic`, `df['in_market']` is post-stop and `df['trend_in_market']` is the pre-stop dual-signal column.

- [ ] **Step 1: Extend `__init__`**

Replace `DualSignalAgreement.__init__` (lines 539-546) with:

```python
    def __init__(self, sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
                 trailing_stop_pct=None, trailing_stop_cooldown_days=60):
        name = f"Dual-Signal Agreement (ATR x{atr_multiplier})"
        if t2_confirmation:
            name += " [T+2]"
        if trailing_stop_pct:
            name += (f" [Trailing Stop {trailing_stop_pct*100:.1f}%, "
                     f"cooldown {trailing_stop_cooldown_days}d]")
        super().__init__(name=name)
        self.sma_window = sma_window
        self.atr_multiplier = atr_multiplier
        self.t2_confirmation = t2_confirmation
        self.trailing_stop_pct = trailing_stop_pct
        self.trailing_stop_cooldown_days = trailing_stop_cooldown_days
```

- [ ] **Step 2: Apply the stop in `_add_indicator_logic`**

At the end of `DualSignalAgreement._add_indicator_logic`, replace the final two lines (582-583):

```python
        df['in_market'] = raw_signal.shift(1).fillna(initial_state_val).astype(bool)
        return df
```

with:

```python
        df['in_market'] = raw_signal.shift(1).fillna(initial_state_val).astype(bool)
        if self.trailing_stop_pct:
            # Preserve the pre-stop dual-signal column so the live status
            # helper can re-walk it; track the stop against ^GSPC (the
            # validated reference), reindexed to this df's calendar.
            df['trend_in_market'] = df['in_market'].copy()
            gspc_close = get_cached_signals("^GSPC")["Close"].reindex(df.index).ffill()
            df['in_market'] = self._apply_trailing_stop(df, price=gspc_close)
        return df
```

- [ ] **Step 3: Verify stop-off is byte-identical and stop-on reproduces D**

Run (this is a short 12-window slice for speed, not the full 172):
```bash
python -c "
import sys; sys.path.insert(0,'.'); import warnings; warnings.filterwarnings('ignore')
from backtest.strat_backtest import DualSignalAgreement, Backtester
off=DualSignalAgreement(atr_multiplier=2.5,t2_confirmation=False)
on =DualSignalAgreement(atr_multiplier=2.5,t2_confirmation=False,trailing_stop_pct=0.08,trailing_stop_cooldown_days=60)
for s,tag in [(off,'off'),(on,'on 8/60')]:
    r=Backtester(base_ticker='^NDX',signal_ticker='^GSPC',start_date='1999-01-01',period_years=26,leverage=3,expense_ratio=0.0095,initial_fund=10000,verbose=False).run(s)
    print(tag, round(r['strategy_twr'],2), round(r['max_drawdown'],2), len(r['trade_log']))
"
```
Expected: no traceback; the `on 8/60` line shows a shallower (less negative) max drawdown than `off`, and more trades. (Exact TWR depends on the single window; the drawdown-improves-and-trades-increase direction is the check that the overlay is wired in.)

- [ ] **Step 4: Verify the full-aggregate D numbers still reproduce**

Run the committed comparison script and confirm row D is unchanged from `docs/combined-system-comparison-2026-08-03.md`:
```bash
python backtest/combined_system_comparison.py
```
Expected: in the rolling table, row D (`Dual-signal + GSPC stop 8/60`) shows Avg TWR ~24.59% and Mean Max DD ~-64.77%, and row C (`Dual-signal (no T+2)`) shows ~25.81% (byte-identical-when-off gate). If D shifted materially, the ^GSPC price wiring differs from the analysis script's `signal_ticker='^GSPC'` path — investigate before proceeding.

- [ ] **Step 5: Commit**

```bash
git add backtest/strat_backtest.py
git commit -m "feat: add opt-in ^GSPC trailing stop to DualSignalAgreement"
```

---

### Task 3: Expose live trailing-stop status

Add a helper that reports the stop's current state for the live report, and surface it through a `get_live_stats` override on `DualSignalAgreement`.

**Files:**
- Modify: `backtest/strat_backtest.py` (add `_trailing_stop_status` to `BaseStrategy` after `_apply_trailing_stop`; add `get_live_stats` override to `DualSignalAgreement`)

**Interfaces:**
- Consumes: `df['trend_in_market']` and the `^GSPC` price series (Task 2); `BaseStrategy.get_live_stats` (base implementation, lines 183-238).
- Produces: `stats["trailing_stop"]` dict with keys `state` (`"holding"|"triggered"|"cooldown"|"inactive"`), `peak`, `current`, `drop_pct`, `distance_pct`, `cooldown_left`.

- [ ] **Step 1: Add `_trailing_stop_status` to `BaseStrategy`**

Insert immediately after the `_apply_trailing_stop` method added in Task 1:

```python
    def _trailing_stop_status(self, df, price=None):
        """Current stop state for live reporting. Re-walks the same peak/
        cooldown logic as _apply_trailing_stop over df['trend_in_market']
        (the pre-stop signal) and reads the final day. Separate walk by
        design, so _apply_trailing_stop stays untouched (its numbers are a
        regression gate). Returns a dict; all price fields are None when
        there is no live position to protect."""
        inactive = {"state": "inactive", "peak": None, "current": None,
                    "drop_pct": None, "distance_pct": None, "cooldown_left": None}
        if not getattr(self, "trailing_stop_pct", None) or "trend_in_market" not in df:
            return inactive
        trend = df["trend_in_market"].to_numpy()
        series = (df["Close"] if price is None else price)
        close = series.to_numpy()
        lag = np.roll(close, 1)
        if len(lag):
            lag[0] = close[0]
        n = len(df)
        pct = self.trailing_stop_pct
        was_in = False
        peak = 0.0
        cooldown = 0
        state = "inactive"
        cur_peak = None
        cur_cd = None
        for i in range(n):
            if cooldown > 0:
                cooldown -= 1
                was_in = False
                state, cur_peak, cur_cd = "cooldown", None, cooldown
                continue
            if not trend[i]:
                was_in = False
                state, cur_peak, cur_cd = "inactive", None, None
                continue
            if not was_in:
                peak = lag[i]
                was_in = True
                state, cur_peak, cur_cd = "holding", peak, None
                continue
            peak = max(peak, lag[i])
            if lag[i] < peak * (1 - pct):
                was_in = False
                cooldown = self.trailing_stop_cooldown_days
                state, cur_peak, cur_cd = "triggered", peak, self.trailing_stop_cooldown_days
            else:
                state, cur_peak, cur_cd = "holding", peak, None
        if state in ("cooldown", "inactive"):
            return {"state": state, "peak": None, "current": None,
                    "drop_pct": None, "distance_pct": None, "cooldown_left": cur_cd}
        current = float(close[-1])
        drop_pct = (current - cur_peak) / cur_peak * 100.0
        distance_pct = drop_pct - (-pct * 100.0)
        return {"state": state, "peak": float(cur_peak), "current": current,
                "drop_pct": drop_pct, "distance_pct": distance_pct, "cooldown_left": None}
```

- [ ] **Step 2: Add the `get_live_stats` override to `DualSignalAgreement`**

Insert as a new method inside `DualSignalAgreement` (e.g. directly after `_add_indicator_logic`):

```python
    def get_live_stats(self, monitor_ticker="QQQ", leveraged_ticker="TQQQ", data=None):
        stats = super().get_live_stats(monitor_ticker, leveraged_ticker, data=data)
        # self.df now carries in_market (post-stop) and, when the stop is on,
        # trend_in_market (pre-stop). action in `stats` already reflects the
        # post-stop column, i.e. D's verdict.
        gspc_close = get_cached_signals("^GSPC")["Close"].reindex(self.df.index).ffill()
        stats["trailing_stop"] = self._trailing_stop_status(self.df, price=gspc_close)
        return stats
```

- [ ] **Step 3: Smoke-test the status dict against live data**

Run:
```bash
python -c "
import sys; sys.path.insert(0,'.'); import warnings; warnings.filterwarnings('ignore')
from backtest.strat_backtest import DualSignalAgreement, _download_with_retry
d=DualSignalAgreement(sma_window=200,atr_multiplier=2.5,t2_confirmation=False,trailing_stop_pct=0.08,trailing_stop_cooldown_days=60)
data=_download_with_retry('QQQ TQQQ SPY ^VIX')
s=d.get_live_stats('SPY','TQQQ',data=data)
print('action:', s['action'])
print('trailing_stop:', s['trailing_stop'])
"
```
Expected: no traceback; `action` is `BUY/HOLD` or `SELL/CASH`; `trailing_stop` is a dict whose `state` is one of the four labels. If `state=='holding'`, `peak`/`current` are floats and `distance_pct` is positive (cushion remaining); if `state` is `cooldown`, `cooldown_left` is an int 0-60; if `inactive`, all price fields are `None`.

- [ ] **Step 4: Commit**

```bash
git add backtest/strat_backtest.py
git commit -m "feat: expose live trailing-stop status on DualSignalAgreement"
```

---

### Task 4: Rewire `bot.py` to report config D

Point the recommendation at D, add the stop-status block, keep the component sections and defensive rotation.

**Files:**
- Modify: `bot.py` (`generate_market_report` lines 11-81; `run_bot` lines 83-96)

**Interfaces:**
- Consumes: `DualSignalAgreement(...).get_live_stats(...)` returning `action` + `trailing_stop` (Task 3); the existing `SMATrendFollowing` component-section rendering (unchanged).

- [ ] **Step 1: Import and instantiate D in `run_bot`**

In `bot.py`, update the import line (line 9) to add `DualSignalAgreement`:

```python
from backtest.strat_backtest import SMATrendFollowing, DualSignalAgreement, _download_with_retry, get_current_defensive_rotation
```

Replace `run_bot`'s strategy construction (line 86) so both instances exist:

```python
    strat = SMATrendFollowing(sma_window=200, t2_confirmation=True)
    strat_d = DualSignalAgreement(sma_window=200, atr_multiplier=2.5, t2_confirmation=False,
                                  trailing_stop_pct=0.08, trailing_stop_cooldown_days=60)
    message = generate_market_report(strat, strat_d)
```

- [ ] **Step 2: Thread `strat_d` into `generate_market_report` and compute D's verdict**

Change the signature (line 11) to `def generate_market_report(strategy, strategy_d, monitor_ticker="QQQ", leveraged_ticker="TQQQ", sp500_ticker="SPY"):`.

After the existing `stats_sp500`/`stats_ndx`/`def_rot` are computed (after line 27), add:

```python
    # D's combined verdict (dual-signal agreement + ^GSPC trailing stop).
    # Signals computed on ^NDX/^GSPC internally; monitor ticker only supplies
    # the base price fields, which we don't use here.
    stats_d = strategy_d.get_live_stats(sp500_ticker, leveraged_ticker, data=shared_data)
    ts = stats_d["trailing_stop"]
```

- [ ] **Step 3: Switch the change alert to D**

Replace the change-alert lines (30-32):

```python
    signal_changed = stats_sp500["trend_changed"] or stats_ndx["trend_changed"]
    change_alert = "🔄 **Signal Change Detected!**" if signal_changed else "✅ Status: No change in signal."
```

with:

```python
    # A change is D's recommended action being new as of today (a fresh entry,
    # or an exit including a stop-triggered one). days_in_current_state == 1
    # means today is the first day of the current state.
    signal_changed = stats_d["days_in_current_state"] == 1
    change_alert = "🔄 **Signal Change Detected!**" if signal_changed else "✅ Status: No change in signal."
```

(The RECOMMENDED ACTION line is switched to D in Step 4, where the message
tail is rebuilt — do not edit it here, to avoid a double-edit.)

- [ ] **Step 4: Add the trailing-stop status block**

Add this helper inside `generate_market_report` (near `format_signal_section`):

```python
    def format_trailing_stop(ts):
        header = "🛑 **TRAILING STOP (S&P 500, 8% / 60d)**"
        if ts["state"] in ("holding", "triggered"):
            price_lines = (
                f"• Peak since entry: {ts['peak']:.2f} | Current: {ts['current']:.2f}\n"
                f"• Drop from peak: {ts['drop_pct']:.2f}% "
                f"(trigger at -8.00%, {ts['distance_pct']:.2f}% to go)\n"
            )
        else:
            price_lines = "• Peak since entry: n/a | Current: n/a\n"
        status = {
            "holding":   "Holding",
            "triggered": "SELL — S&P fell 8% from peak",
            "cooldown":  f"In cash — stop cooldown, {ts['cooldown_left']} trading days until re-entry allowed",
            "inactive":  "In cash — no position",
        }[ts["state"]]
        return f"{header}\n{price_lines}• Status: {status}"
```

Insert its output into the `message` f-string, between the ASSET ALLOCATION block and the RECOMMENDED ACTION separator (after the `{def_msg}` line at line 76). Add before the final `--------------------------` / RECOMMENDED ACTION:

```python
        f"--------------------------\n"
        f"{format_trailing_stop(ts)}\n"
        f"--------------------------\n"
        f"🚩 **RECOMMENDED ACTION:** {stats_d['action']}"
```

(i.e. replace the existing trailing `--------------------------\n🚩 ...` tail at lines 77-78 with the block above.)

- [ ] **Step 5: Live smoke test the full report**

Run with no webhook so it prints to stdout:
```bash
python bot.py
```
Expected: no traceback; the report prints with the two component sections (NASDAQ + S&P 500), the ASSET ALLOCATION + defensive rotation, a new `🛑 TRAILING STOP` block whose Status line is one of Holding / SELL — … / In cash — …, and a `RECOMMENDED ACTION` of `BUY/HOLD` or `SELL/CASH`. Sanity-check the block internally: if Status is `Holding`, the "% to go" value should be positive and roughly equal `8.00 - |drop|`.

- [ ] **Step 6: Commit**

```bash
git add bot.py
git commit -m "feat: report config D (dual-signal + trailing stop) in the daily report"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = spec Component 1 (relocate overlay; the optional `price` param is the spec's "stop tracks ^GSPC" intent made robust for the live ETF path). Task 2 = spec Component 1 (dual-signal gains the stop) + the byte-identical-when-off constraint. Task 3 = spec Component 2 (`trailing_stop` status sub-dict, exact key set matches the spec's interface block). Task 4 = spec Component 3 (recommendation → D, component sections unchanged, new status block with the agreed Holding/SELL/In cash wording, change alert → D). Out-of-scope items (execution, defensive rotation, README/CHANGELOG, re-selection, tax) are absent from every task.
- **Placeholder scan:** every step has runnable code or an exact command with a stated expected result. No TODO/TBD.
- **Type/name consistency:** `_apply_trailing_stop(self, df, price=None)` defined in Task 1 is called with `price=gspc_close` in Task 2 and (via `_trailing_stop_status`) Task 3. `trend_in_market` is written in Task 2 Step 2 and read in Task 3 Step 1. The `trailing_stop` dict keys (`state`, `peak`, `current`, `drop_pct`, `distance_pct`, `cooldown_left`) are produced in Task 3 and consumed by `format_trailing_stop` in Task 4. `stats_d["action"]` / `stats_d["days_in_current_state"]` come from the base `get_live_stats` (unchanged). `strat_d` is the name used in both `run_bot` and `generate_market_report`.
- **Statefulness caveat** (spec Key Decision 3) is encoded as the `reindex(df.index)` over the fetched window plus the docstring notes; no persisted state is introduced, matching the report-only constraint.
