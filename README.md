# TQQQ-Trend-Follower-Bot

### **Project Overview**
This project is an automated trading monitor system designed for long-term investors tracking 3x leveraged ETFs like TQQQ. It layers a **200-Day SMA + ATR trend signal**, **dual-signal agreement** (the NASDAQ-100 and S&P 500 must concur), and a **trailing stop** for crash protection into a single daily recommendation — aiming to compound through bull markets while exiting defensively before systemic drawdowns. See [How It Works](#how-it-works) for the mechanics.

---

### How It Works

`bot.py` produces one daily recommendation by stacking three layers, each fixing a weakness of the layer before it. The Discord report shows the underlying signals for transparency, but the headline **recommended action** is the combined verdict of all three.

#### Layer 1 — The core trend signal (SMA 200 + ATR buffer)

Each index's trend is classified against a 200-day Simple Moving Average with a volatility buffer sized by **Average True Range (ATR)** — "breathing room" that widens in volatile markets and tightens in calm ones, so the strategy adapts instead of reacting to every minor wiggle:

*   **Bullish** — price above the upper buffer: `Price > SMA200 + 2.5 * ATR` → enter or hold to capture growth.
*   **Bearish** — price below the lower buffer: `Price < SMA200 - 2.5 * ATR` → exit to cash or short-term Treasuries (e.g. SGOV/BIL) to protect capital.
*   **Neutral** — price inside the buffer → hold the current position (prevents "whipsawing" during indecisive markets).

#### Layer 2 — A noise filter: dual-signal agreement

A single band crossing can be a one-day head-fake. Two ways to filter that noise were tested:

*   **T+2 confirmation** — a new signal must persist **2 consecutive trading days** before acting (temporal persistence). Used in the single-signal setups and Tables 1–3.
*   **Dual-signal agreement** — flip state only when **both** the NASDAQ-100 (^NDX) *and* the S&P 500 (^GSPC) independently agree; if they disagree, hold the prior position (cross-index persistence).

`bot.py` uses **dual-signal agreement** as its noise filter — not T+2, since stacking both is redundant (see Table 4). It still trades ^NDX (TQQQ) exposure; the S&P is a second confirming vote, not a separate position.

#### Layer 3 — The trailing stop (crash protection)

The trend signal is deliberately slow, so a sharp crash can inflict heavy damage before it confirms a bearish turn. The trailing stop is a faster safety net on top:

*   While in a position, track the **running peak of the (unleveraged) S&P 500 price** since entry.
*   The day the S&P closes **8% below that peak**, exit immediately — bypassing the dual-signal delay entirely.
*   After a stop-triggered exit, block re-entry for a **60-trading-day cooldown**, so a still-elevated trend signal doesn't buy straight back into a falling market.

It tracks the *unleveraged* S&P price, not the 3x equity curve — the leveraged curve swings ~3× as hard and would trip the stop constantly. The stop is opt-in; `bot.py` runs it at 8% / 60d.

```mermaid
stateDiagram-v2
    [*] --> InCash
    InCash --> InPosition: both indices agree bullish
    InPosition --> InPosition: track S&P peak since entry
    InPosition --> Cooldown: S&P falls 8% below peak (stop fires)
    InPosition --> InCash: trend turns bearish (normal exit)
    Cooldown --> InCash: 60 trading days elapse
```

The **recommended action** is "in the market" only when both indices agree bullish **and** the trailing stop has not fired. Full validation of the trailing stop — out-of-sample generalization, parameter stability, execution cost, and crash-event behavior — lives in the [`docs/`](docs/) finding chain (`docs/trailing-stop-*`, `docs/combined-system-comparison-2026-08-03.md`).

---

### Backtesting Methodology

All results below are produced by rolling 26-year backtests stepped forward **monthly** from the earliest available data through the latest valid start date (2000-07). This eliminates timing luck and exposes strategies to every major market regime — the Dot-com crash, 2008 Financial Crisis, COVID crash, and the 2022 rate-shock bear market.

**Key engine features:**
- **Next-day open execution** — orders execute at the following day's open, not the signal day's close
- **Accurate TWR annualisation** — computed from actual trading days, not configured period years
- **Historical borrow rates** — leverage drag uses era-accurate interest rates (4%–9% depending on decade)
- **Cash yield** — idle cash earns 80% of the prevailing borrow rate (money-market proxy)
- **Parallel computation** — all rolling windows run concurrently via `ThreadPoolExecutor`

**Backtest Parameters:**
- Rolling period: **26 years** per window
- Initial investment: **$10,000 lump sum** (no DCA)
- Tax: **not applied** (pre-tax returns)

---

## Backtest Results

- **Tables 1–3** — strategy comparison (SMA 200 vs EMA 50/200 vs Buy & Hold vs VIX/RSI) across signal sources and leverage tiers.
- **Table 4** — signal-source comparison (NDX vs S&P 500 vs dual-signal agreement), plus the trailing-stop overlay on the two most relevant setups.
- **Table 5** — drawdown by crash event, per strategy.

### Table 1: NASDAQ-100 (^NDX) — Lump Sum Performance
*Date range: 1986-04-29 to 2000-07-28 (172 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 3.10% | 3.84% | -9.09% | -99.98% | 1 |
| **3x** | **SMA 200 (ATR x2.5, T+2)** | **23.33%** | **24.25%** | **11.21%** | **-84.99%** | **13** |
| **3x** | EMA 50/200 | 23.52% | 25.05% | 10.81% | -90.41% | 13 |
| **3x** | VIX < 25 | -1.84% | -1.10% | -10.36% | -99.85% | 124 |
| **3x** | RSI 30/70 | -5.70% | -5.81% | -12.73% | -99.85% | 22 |
| | | | | | | |
| **2x** | Buy & Hold | 11.17% | 11.83% | 1.54% | -98.95% | 1 |
| **2x** | **SMA 200 (ATR x2.5, T+2)** | **20.57%** | **21.16%** | **11.42%** | **-66.80%** | **13** |
| **2x** | EMA 50/200 | 21.04% | 21.72% | 11.57% | -73.90% | 13 |
| **2x** | VIX < 25 | 3.48% | 4.20% | -3.20% | -98.17% | 124 |
| **2x** | RSI 30/70 | 1.75% | 1.81% | -2.76% | -96.66% | 22 |
| | | | | | | |
| **1x** | Buy & Hold | 11.65% | 12.06% | 6.12% | -82.99% | 1 |
| **1x** | **SMA 200 (ATR x2.5, T+2)** | **13.89%** | **14.10%** | **8.70%** | **-35.77%** | **13** |
| **1x** | EMA 50/200 | 14.31% | 14.56% | 8.99% | -39.94% | 13 |
| **1x** | VIX < 25 | 5.52% | 6.03% | 1.55% | -83.44% | 124 |
| **1x** | RSI 30/70 | 4.86% | 4.86% | 3.28% | -74.40% | 22 |

> **Bold = best risk-adjusted result per leverage tier.** With T+2 confirmation, SMA 200 (ATR x2.5) runs essentially neck-and-neck with EMA 50/200 on average TWR at every tier (within ~0.5pp) and consistently posts a shallower max drawdown (-84.99% vs -90.41% at 3x, -66.80% vs -73.90% at 2x, -35.77% vs -39.94% at 1x). The worst-case floor, though, is mixed: SMA has the better floor at 3x (11.21% vs EMA's 10.81%), but EMA has a modestly higher floor at 2x (11.57% vs 11.42%) and 1x (8.99% vs 8.70%). The consistently lower drawdown across all three tiers is what keeps SMA the preferred strategy for leveraged exposure.

---

### Table 2: S&P 500 (^GSPC) — Lump Sum Performance
*Date range: 1985-07-31 to 2000-07-28 (181 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 2.75% | 3.34% | -2.54% | -98.86% | 1 |
| **3x** | SMA 200 (ATR x2.5, T+2) | 10.97% | 11.33% | 5.50% | -82.28% | 11 |
| **3x** | **EMA 50/200** | **11.60%** | **11.88%** | **6.73%** | **-79.40%** | **12** |
| **3x** | VIX < 25 | 0.64% | 0.88% | -2.94% | -95.46% | 123 |
| **3x** | RSI 30/70 | 3.95% | 4.52% | 0.08% | -95.10% | 23 |
| | | | | | | |
| **2x** | Buy & Hold | 6.37% | 6.70% | 3.38% | -91.49% | 1 |
| **2x** | SMA 200 (ATR x2.5, T+2) | 9.81% | 10.02% | 6.43% | -63.45% | 11 |
| **2x** | **EMA 50/200** | **10.40%** | **10.50%** | **7.44%** | **-59.38%** | **12** |
| **2x** | VIX < 25 | 2.65% | 2.87% | 0.06% | -83.34% | 123 |
| **2x** | RSI 30/70 | 6.01% | 6.03% | 4.06% | -81.45% | 23 |
| | | | | | | |
| **1x** | Buy & Hold | 6.99% | 7.08% | 5.33% | -56.90% | 1 |
| **1x** | SMA 200 (ATR x2.5, T+2) | 7.49% | 7.66% | 5.48% | -34.45% | 11 |
| **1x** | **EMA 50/200** | **7.88%** | **8.08%** | **6.02%** | **-33.26%** | **12** |
| **1x** | VIX < 25 | 3.85% | 4.03% | 2.23% | -46.92% | 123 |
| **1x** | RSI 30/70 | 5.78% | 5.80% | 4.94% | -52.65% | 23 |

> **With T+2 confirmation, EMA 50/200 overtakes SMA 200 on the S&P 500 signal** — higher average TWR *and* a shallower max drawdown at every leverage tier (e.g. at 1x: 7.88% avg / -33.26% DD for EMA vs 7.49% avg / -34.45% DD for SMA). This reverses the pre-T+2 result, where SMA led on ^GSPC — consistent with the two-day confirmation delay costing SMA more in lost entry/exit timing than it saves in avoided whipsaws, though this comparison isn't a controlled same-window ablation (the window set itself also shifted between the pre- and post-T+2 numbers), so treat the causal read as a plausible hypothesis rather than a proven mechanism. `bot.py` displays each index's T+2-confirmed SMA trend as a component monitor (its headline recommendation now layers dual-signal agreement + a trailing stop on top — see [How It Works](#how-it-works) and Table 4) — Table 1 continues to support the SMA choice on the NASDAQ-100 signal, while this table shows EMA would historically have done better specifically on the S&P 500 signal.

---

### Table 3: NASDAQ-100 Returns + S&P 500 Signal — Lump Sum Performance
*Trade ^NDX (TQQQ) exposure but use ^GSPC (S&P 500) trend to determine in/out.*
*Date range: 1986-04-29 to 2000-07-28 (172 rolling windows)*

| Leverage | Strategy | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **3x** | Buy & Hold | 3.10% | 3.84% | -9.09% | -99.98% | 1 |
| **3x** | SMA 200 (ATR x2.5, T+2) | 21.77% | 22.13% | 8.31% | -83.40% | 11 |
| **3x** | **EMA 50/200** | **22.93%** | **23.50%** | **9.02%** | **-88.61%** | **12** |
| **3x** | VIX < 25 | -1.84% | -1.10% | -10.36% | -99.85% | 124 |
| **3x** | RSI 30/70 | 3.74% | 3.64% | -0.89% | -99.39% | 23 |
| | | | | | | |
| **2x** | Buy & Hold | 11.17% | 11.83% | 1.54% | -98.95% | 1 |
| **2x** | SMA 200 (ATR x2.5, T+2) | 19.33% | 19.75% | 9.41% | -64.11% | 11 |
| **2x** | **EMA 50/200** | **20.41%** | **20.96%** | **10.12%** | **-70.83%** | **12** |
| **2x** | VIX < 25 | 3.48% | 4.20% | -3.20% | -98.17% | 124 |
| **2x** | RSI 30/70 | 8.17% | 8.01% | 5.52% | -92.72% | 23 |
| | | | | | | |
| **1x** | Buy & Hold | 11.65% | 12.06% | 6.12% | -82.99% | 1 |
| **1x** | SMA 200 (ATR x2.5, T+2) | 13.21% | 13.74% | 7.68% | -35.77% | 11 |
| **1x** | **EMA 50/200** | **13.89%** | **14.47%** | **8.17%** | **-40.11%** | **12** |
| **1x** | VIX < 25 | 5.52% | 6.03% | 1.55% | -83.44% | 124 |
| **1x** | RSI 30/70 | 7.99% | 7.88% | 6.60% | -64.15% | 23 |

> **vs. Table 1 (NDX own signal) and Table 2 (^GSPC own signal):** Table 3 inherits the same GSPC-signal
> dynamic seen in Table 2 — EMA 50/200 leads on average TWR, median TWR, and worst-case return at every
> leverage tier (e.g. at 1x: 13.89% vs SMA's 13.21% avg TWR). Drawdown, though, tells a different story
> than Table 2: SMA 200 (ATR x2.5) posts the shallower max drawdown at every tier (-83.40% vs -88.61% at
> 3x, -64.11% vs -70.83% at 2x, -35.77% vs -40.11% at 1x) — a consistent split by metric rather than the
> across-the-board EMA sweep seen in Table 2. This is the same returns-vs-drawdown trade-off Table 1
> shows, except here EMA's return edge is larger and extends to the worst-case floor at every tier too
> (not just some, as in Table 1), so EMA keeps the bold as the stronger overall pick on this signal —
> SMA remains the lower-drawdown alternative for anyone weighting capital preservation more heavily.

---

### Table 4: 3x TQQQ — Signal Source Comparison (NDX vs S&P 500 vs Dual-Signal Agreement), with Trailing-Stop Overlay
*^NDX base, 3x leverage, SMA 200 (ATR x2.5 — `bot.py`'s current default) only. Compares three ways to generate the trend signal — NDX's own trend, the S&P 500's trend, and a "dual-signal agreement" hybrid that only acts when both trends agree — each with and without T+2 confirmation. The last two rows add an opt-in ^GSPC trailing stop (8% below peak since entry, 60-day re-entry cooldown) to the two most relevant setups.*
*Date range: 1986-04-29 to 2000-07-28 (172 rolling windows).*

> **Dual-signal agreement (no T+2) wins on every return metric, with the fewest trades of any setup here:** Avg TWR 25.81%, Med TWR 26.68%, 9 trades — vs. 23.53%/23.56% Avg TWR and 12-15 trades for the single-signal setups. Its worst-case drawdown (-84.95%) isn't the shallowest in this table (NDX-own with no T+2 is -81.38%), so it's not a strict win on every axis, but it's the strongest combination of return and trade efficiency tested.
>
> **Adding T+2 confirmation to the dual-signal hybrid makes it worse, not better** (25.81% -> 24.16% Avg TWR, drawdown also slightly deeper, -84.95% -> -85.50%) — cross-signal agreement and T+2 are both noise-filtering mechanisms aimed at the same problem (false signals/whipsaws), so stacking both appears partly redundant: each adds entry/exit delay without a matching benefit once the other is already filtering. The same direction held for both single-signal setups too: T+2 lowered Avg TWR for NDX-own (23.53% -> 23.33%) and, more sharply, for the S&P signal (23.56% -> 21.77%).
>
> **The trailing-stop overlay (last two rows) buys the lowest drawdown in the table** — Worst DD -64.78% vs. -83% to -85% for every no-stop setup — for roughly double the trading (9-11 -> 18 trades) and a near-flat return effect (S&P+T+2 22% -> 23%; dual-signal 26% -> 25%). Its full validation — out-of-sample generalization, parameter stability, execution-cost, and event-relative behavior — lives in the `docs/trailing-stop-*` and `docs/combined-system-comparison-2026-08-03.md` finding chain, which is why it is presented here as an overlay on the two most relevant setups rather than swept across all six.

| Setup | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | ---: | ---: | ---: | ---: | ---: |
| NDX own signal | 23.53% | 24.25% | 10.53% | -81.38% | 15 |
| NDX own signal [T+2] | 23.33% | 24.25% | 11.21% | -84.99% | 13 |
| S&P 500 signal | 23.56% | 23.95% | 12.04% | -83.79% | 12 |
| S&P 500 signal [T+2] | 21.77% | 22.13% | 8.31% | -83.40% | 11 |
| **Dual-signal agreement** | **25.81%** | **26.68%** | 11.68% | -84.95% | **9** |
| Dual-signal agreement [T+2] | 24.16% | 25.24% | 9.41% | -85.50% | 9 |
| S&P 500 signal [T+2] + Trailing Stop 8%/60d | 23.43% | 23.92% | 12.30% | **-64.78%** | 18 |
| Dual-signal agreement + Trailing Stop 8%/60d | 24.59% | 25.36% | 12.92% | **-64.78%** | 18 |

> **Caveats, and how this table differs from the version it replaced:** this run is a single ATR value (2.5, `bot.py`'s current default) and SMA only — unlike the version of this table it replaced, it does not sweep ATR or test EMA (that data is preserved in `CHANGELOG.md`'s history if needed). It has also had lighter review than the rest of this README: `DualSignalAgreement` (`backtest/strat_backtest.py`) is new code, verified by hand-tracing its logic, confirming ^NDX's trading calendar is a strict subset of ^GSPC's (no date-alignment gaps), and cross-validating this table's NDX-own and S&P-signal rows against Table 1 and Table 3's already-published, independently-reviewed numbers (both matched exactly) — but the dual-signal logic itself has not been through the same multi-round adversarial review the rest of this README's findings have. The usual overlapping-window caveat also applies: 172 monthly-stepped windows share nearly all their history with their neighbors, so this is much less independent evidence than "172" suggests, and this is a single run — not itself checked for parameter stability or out-of-sample generalization the way earlier findings in this README were.

---

### Table 5: 3x TQQQ — Drawdown by Crash Event (Event-Relative Peak-to-Trough)
*^NDX base, 3x leverage, S&P 500 signal. Each cell is the equity decline from just before the event to the local trough within the event window — a direct read of how the Table 4 setups weathered the five worst crashes in the sample. Less negative = better protected. Generated by `backtest/crash_event_drawdown.py`.*

> **The trailing stop is the single largest drawdown reducer in every crash**, and it helps all five with none worsened: Black Monday -66% -> -20%, dot-com -83% -> -51%, COVID -70% -> -43%. **Buy & Hold at 3x is ruinous** — the dot-com crash took it to -99.95% (near-total wipeout), the floor the trend rules improve on. The two stopped setups are nearly identical (the ^GSPC stop dominates the crash profile regardless of entry rule; only 2008 differs), and dual-signal without a stop is slightly *worse* than the S&P signal in 2008/2022 — the higher-return, higher-drawdown trade the stop then closes.

| Setup | Black Monday 1987 | Dot-com crash | 2008 GFC | COVID crash | 2022 rate-shock bear |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Buy & Hold (3x) | -83.66% | -99.95% | -94.57% | -69.96% | -80.15% |
| S&P 500 signal [T+2] (baseline) | -65.91% | -83.25% | -31.77% | -69.61% | -51.69% |
| S&P 500 signal [T+2] + Trailing Stop 8%/60d | **-19.55%** | **-51.11%** | **-17.95%** | **-42.69%** | **-38.06%** |
| Dual-signal agreement | -65.91% | -83.65% | -43.69% | -69.96% | -53.33% |
| Dual-signal agreement + Trailing Stop 8%/60d | -19.55% | -51.11% | -23.88% | -42.69% | -38.06% |

---

### **Changelog**

See [CHANGELOG.md](CHANGELOG.md) for a full history of changes with dates.

---

### **Strategy Research & Theoretical Basis**
The bot implements a **trend-following strategy** for leveraged ETFs, grounded in a few quantitative-finance principles (the mechanics themselves are in [How It Works](#how-it-works)):

1. **Trend-filtering for leveraged ETFs:** Leveraged ETFs suffer from *volatility decay*. Research (e.g. Meb Faber) shows that 200-day trend filters effectively "clip the left tail" of risk, preventing catastrophic drawdowns during secular bear markets.
2. **Layered noise-and-crash filtering:** the ATR buffer, dual-signal agreement, and trailing stop each target a distinct failure mode — minor noise, single-signal head-fakes, and fast crashes respectively — rather than leaning on one filter to do everything.
3. **Core objective:** improve **risk-adjusted returns** by preserving capital during systemic failures rather than trying to time minor market tops.

---

### **System Architecture**
* **Automation:** Powered by **GitHub Actions**, which runs the script automatically after market close.
* **Data Engine:** Uses `yfinance` to fetch reliable, real-time market data.
* **Notification:** Integrated with **Discord Webhooks** for instant, actionable trading recommendations.

---

### **Getting Started**
1. **Clone/Fork** this repository.
2. **Configure Secrets:** Navigate to `Settings` > `Secrets and variables` > `Actions` and add your `DISCORD_WEBHOOK` URL.
3. **Dependencies:** Install the required libraries
4. **Automation:** The workflow file `.github/workflows/daily_check.yml` is pre-configured to run automatically every trading day.

### **Risk Disclaimer**
This project is for educational and monitoring purposes only. Leveraged ETFs (such as TQQQ) are highly volatile instruments. The 200 SMA strategy is designed to mitigate long-term systemic risk but may face "whipsaw" losses during sideways or consolidating markets. Please assess your risk tolerance before executing real-world trades based on these signals.
