# Dual-Signal Agreement — Noise Filter (Layer 2)

[← Back to README](../../README.md) · Related: [Methodology](methodology.md) · [Core Trend Signal](core-trend-signal.md) · [Trailing Stop](trailing-stop.md)

A single band crossing of the [core trend signal](core-trend-signal.md) can be a one-day head-fake. Two ways to filter that noise were tested:

*   **T+2 confirmation** — a new signal must persist **2 consecutive trading days** before acting (temporal persistence). Used in the single-signal setups and Tables 1–3.
*   **Dual-signal agreement** — flip state only when **both** the NASDAQ-100 (^NDX) *and* the S&P 500 (^GSPC) independently agree; if they disagree, hold the prior position (cross-index persistence).

`bot.py` uses **dual-signal agreement** as its noise filter — not T+2, since stacking both is redundant (see Table 4 below). It still trades ^NDX (TQQQ) exposure; the S&P is a second confirming vote, not a separate position.

---

## Backtest Results

Rolling 26-year methodology per [Methodology](methodology.md).

### Table 4: 3x ^NDX (TQQQ) — Signal Source Comparison (NDX vs S&P 500 vs Dual-Signal Agreement), with Trailing-Stop Overlay
*^NDX base, 3x leverage, SMA 200 (ATR x2.5 — `bot.py`'s current default) only. Compares three ways to generate the trend signal — NDX's own trend, the S&P 500's trend, and a "dual-signal agreement" hybrid that only acts when both trends agree — each with and without T+2 confirmation. The last two rows add an opt-in ^GSPC trailing stop (8% below peak since entry, 60-day re-entry cooldown) to the two most relevant setups.*
*Date range: 1986-04-29 to 2000-07-28 (172 rolling windows).*

> **Dual-signal agreement (no T+2) wins on every return metric, with the fewest trades of any setup here:** Avg TWR 25.81%, Med TWR 26.68%, 9 trades — vs. 23.53%/23.56% Avg TWR and 12-15 trades for the single-signal setups. Its worst-case drawdown (-84.95%) isn't the shallowest in this table (NDX-own with no T+2 is -81.38%), so it's not a strict win on every axis, but it's the strongest combination of return and trade efficiency tested.
>
> **Adding T+2 confirmation to the dual-signal hybrid makes it worse, not better** (25.81% -> 24.16% Avg TWR, drawdown also slightly deeper, -84.95% -> -85.50%) — cross-signal agreement and T+2 are both noise-filtering mechanisms aimed at the same problem (false signals/whipsaws), so stacking both appears partly redundant: each adds entry/exit delay without a matching benefit once the other is already filtering. The same direction held for both single-signal setups too: T+2 lowered Avg TWR for NDX-own (23.53% -> 23.33%) and, more sharply, for the S&P signal (23.56% -> 21.77%).
>
> **The trailing-stop overlay (last two rows) buys the lowest drawdown in the table** — Worst DD -64.78% vs. -83% to -85% for every no-stop setup — for roughly double the trading (9-11 -> 18 trades) and a near-flat return effect (S&P+T+2 22% -> 23%; dual-signal 26% -> 25%). Its full validation — out-of-sample generalization, parameter stability, execution-cost, and event-relative behavior — is covered in the [Trailing Stop](trailing-stop.md) doc, which is why it is presented here as an overlay on the two most relevant setups rather than swept across all six.

| Setup | Avg TWR | Med TWR | Worst TWR | Worst DD | Worst DD vs Init | Avg Trades |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| NDX own signal | 23.53% | 24.25% | 10.53% | -81.38% | -81.38% | 15 |
| NDX own signal [T+2] | 23.33% | 24.25% | 11.21% | -84.99% | -84.75% | 13 |
| S&P 500 signal | 23.56% | 23.95% | 12.04% | -83.79% | -83.79% | 12 |
| S&P 500 signal [T+2] | 21.77% | 22.13% | 8.31% | -83.40% | -83.40% | 11 |
| **Dual-signal agreement** | **25.81%** | **26.68%** | 11.68% | -84.95% | -84.95% | **9** |
| Dual-signal agreement [T+2] | 24.16% | 25.24% | 9.41% | -85.50% | -85.27% | 9 |
| S&P 500 signal [T+2] + Trailing Stop 8%/60d | 23.43% | 23.92% | 12.30% | **-64.78%** | -54.76% | 18 |
| Dual-signal agreement + Trailing Stop 8%/60d | 24.59% | 25.36% | 12.92% | **-64.78%** | -54.75% | 18 |

> **Caveats, and how this table differs from the version it replaced:** this run is a single ATR value (2.5, `bot.py`'s current default) and SMA only — unlike the version of this table it replaced, it does not sweep ATR or test EMA (that data is preserved in `CHANGELOG.md`'s history if needed). It has also had lighter review than the core trend tables: `DualSignalAgreement` (`backtest/strat_backtest.py`) is new code, verified by hand-tracing its logic, confirming ^NDX's trading calendar is a strict subset of ^GSPC's (no date-alignment gaps), and cross-validating this table's NDX-own and S&P-signal rows against [Table 1](core-trend-signal.md) and [Table 3](core-trend-signal.md)'s already-published, independently-reviewed numbers (both matched exactly) — but the dual-signal logic itself has not been through the same multi-round adversarial review the core findings have. The usual overlapping-window caveat also applies: 172 monthly-stepped windows share nearly all their history with their neighbors, so this is much less independent evidence than "172" suggests, and this is a single run — not itself checked for parameter stability or out-of-sample generalization the way earlier findings were.

---

## Further reading

- [Trailing stop on the dual-signal setup (2026-08-03)](../trailing-stop-dual-signal-2026-08-03.md)
- [Dual-breach trailing stop variant (2026-08-03)](../trailing-stop-dual-breach-2026-08-03.md)
