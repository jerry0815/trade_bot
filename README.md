# TQQQ-Trend-Follower-Bot

### **Project Overview**
This project is an automated trading monitor system designed for long-term investors tracking 3x leveraged ETFs like TQQQ. By utilizing a **200-Day Simple Moving Average (200 SMA)**, the system provides real-time trend assessment to maximize compound growth during bull markets and execute defensive exit strategies before systemic bear markets.

---

### Strategy Logic: Dynamic ATR Protection

The system provides a clear, rule-based approach to market exposure. We move beyond simple "price crossing SMA" signals by adding a dynamic volatility buffer using the **Average True Range (ATR)**.

**The Decision Rules:**

*   **Bullish:** When the price rises **above** the upper buffer:
    `Price > (SMA200 + 2.5 * ATR)`
    *Action: Enter or maintain long positions to capture growth.*

*   **Bearish:** When the price falls **below** the lower buffer:
    `Price < (SMA200 - 2.5 * ATR)`
    *Action: Exit to cash or short-term Treasuries (e.g., SGOV/BIL) to protect capital.*

*   **Neutral:** When the price is **inside** the buffer:
    `(SMA200 - 2.5 * ATR) <= Price <= (SMA200 + 2.5 * ATR)`
    *Action: Hold existing position. This prevents "whipsawing" during indecisive market periods.*

**T+2 Confirmation:** A crossing of the upper or lower buffer doesn't execute immediately. The new signal (bullish or bearish) must persist for **2 consecutive trading days** before the bot changes state. A single day spent outside the buffer that reverts back inside the next day is treated as noise and ignored. This adds a short delay to every entry/exit but filters out one-day spikes that would otherwise trigger a whipsaw trade.

### Key Components

*   **The Trend Anchor (SMA 200):** We utilize the 200-day Simple Moving Average as our "North Star" to filter out market noise and focus on the primary long-term trend.
*   **The Volatility Shield (ATR):** By applying a 2.5x ATR multiplier, we create a "breathing room" buffer that expands during volatile markets and tightens during calm ones, ensuring the strategy adapts to current market conditions.
*   **T+2 Signal Confirmation:** Buy/sell signals must hold for two consecutive trading days before a state change executes, filtering out single-day false signals.
*   **Disciplined Execution:** By automating these calculations, the system removes emotional bias and ensures strict, math-based adherence to your risk parameters.

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

> **With T+2 confirmation, EMA 50/200 overtakes SMA 200 on the S&P 500 signal** — higher average TWR *and* a shallower max drawdown at every leverage tier (e.g. at 1x: 7.88% avg / -33.26% DD for EMA vs 7.49% avg / -34.45% DD for SMA). This reverses the pre-T+2 result, where SMA led on ^GSPC — consistent with the two-day confirmation delay costing SMA more in lost entry/exit timing than it saves in avoided whipsaws, though this comparison isn't a controlled same-window ablation (the window set itself also shifted between the pre- and post-T+2 numbers), so treat the causal read as a plausible hypothesis rather than a proven mechanism. `bot.py` runs the same T+2-confirmed SMA strategy on both its NASDAQ-100 and S&P 500 monitors for consistency — Table 1 continues to support that choice on the NASDAQ-100 signal, while this table shows EMA would historically have done better specifically on the S&P 500 signal.

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

### Table 4: 3x TQQQ — Signal & Parameter Comparison (SMA vs EMA)
*^NDX base, 3x leverage only. Sweeps ATR multiplier, signal source (own ^NDX vs S&P 500), and T+2 confirmation to find the best real-world configuration — Tables 1-3 above only ever show each strategy at its default parameters.*
*Date range: 1986-04-29 to 2000-07-28 (172 rolling windows — confirmed identical for both the own-signal and S&P-500-signal arms of the sweep, matching Table 1's and Table 3's window counts respectively).*

> **Best Practice: SMA 200, ATR x3.0, Signal = Own (^NDX), T+2 = Off — Avg TWR 24.53%, Worst DD -83.08%, Avg Trades 12.** Picked mechanically: highest Avg TWR among the 33 variants remaining after excluding the 11 deepest-drawdown variants (25% — a screen that, in this run, happened not to change the winner: all 11 excluded rows were low-performing EMA variants that were never in contention for best Avg TWR anyway) out of all 44 combinations tested — not a subjective call.
>
> **This is a backtested historical result, not `bot.py`'s current live behavior.** Adopting it requires two changes to `bot.py`, not one: (a) retuning the strategy's constructor kwargs from `atr_multiplier=2.5, t2_confirmation=True` (its current live defaults) to `atr_multiplier=3.0, t2_confirmation=False`, **and** (b) switching the primary signal source `bot.py` actually acts on. `bot.py`'s `RECOMMENDED ACTION` (`bot.py:78`) is driven entirely by `stats_sp500` — the S&P 500 signal — not the NASDAQ-100/own signal this pick assumes. (b) is the materially bigger change: it means retargeting which index the bot trend-follows, not just retuning two parameters.
>
> **How this compares to what `bot.py` actually runs live:** in this table's own terms, `bot.py`'s live configuration is the **`x2.5 | S&P 500 (^GSPC) | On`** row below — Avg TWR 21.77%, Worst DD -83.40%, Avg Trades 11 (this exactly matches Table 3's SMA row, since Table 3 is this same configuration run at its default ATR). The Best Practice pick beats that real baseline by **+2.76pp Avg TWR** (24.53% vs. 21.77%) with essentially flat drawdown (-83.08% vs. -83.40%, 0.32pp shallower). Note this is *not* the `x2.5 | Own (^NDX) | On` row (23.33%) — that row already assumes the signal-source switch in (b) above and understates the real gap, since `bot.py` does not currently run on the own-signal.
>
> **Caveat: this is a single-history, 44-combination grid search over ~172 heavily-overlapping rolling windows, not 172 independent samples** — each window shares most of its 26 years with its neighbors, so the sweep has far less independent evidence behind it than 172 suggests. The winner isn't a clean, isolated peak either: along the Own/Off ATR sweep alone, Avg TWR runs 16.46% (x1.5) -> 22.05% (x2.0) -> 23.53% (x2.5) -> 24.53% (x3.0) -> 23.40% (x3.5) — a large, non-monotonic swing between adjacent parameter values, which is a classic sign of noise rather than a smooth, robust optimum. Read "ATR x3.0" as the parameter that happened to perform best in this particular historical sample, not as a proven "true" optimal band.

#### SMA — ATR & Signal Sweep (3x Leverage)

| ATR | Signal | T+2 | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **x3.0** | **Own (^NDX)** | **Off** | **24.53%** | **25.38%** | **11.46%** | **-83.08%** | **12** |
| x1.5 | S&P 500 (^GSPC) | On | 24.41% | 24.69% | 11.02% | -81.38% | 17 |
| x2.5 | S&P 500 (^GSPC) | Off | 23.56% | 23.95% | 12.04% | -83.79% | 12 |
| x2.5 | Own (^NDX) | Off | 23.53% | 24.25% | 10.53% | -81.38% | 15 |
| x2.0 | S&P 500 (^GSPC) | Off | 23.51% | 23.21% | 11.72% | -83.79% | 16 |
| x3.0 | S&P 500 (^GSPC) | Off | 23.46% | 23.59% | 9.79% | -84.97% | 10 |
| x1.5 | S&P 500 (^GSPC) | Off | 23.46% | 23.62% | 13.21% | -86.93% | 22 |
| x3.5 | Own (^NDX) | Off | 23.40% | 24.35% | 9.72% | -84.77% | 11 |
| x2.5 | Own (^NDX) | On | 23.33% | 24.25% | 11.21% | -84.99% | 13 |
| x3.0 | Own (^NDX) | On | 23.29% | 24.27% | 8.77% | -85.93% | 11 |
| x3.5 | Own (^NDX) | On | 22.87% | 24.10% | 8.23% | -88.76% | 9 |
| x2.0 | Own (^NDX) | Off | 22.05% | 22.66% | 9.88% | -80.07% | 17 |
| x2.0 | Own (^NDX) | On | 21.93% | 23.21% | 8.25% | -85.53% | 16 |
| x2.5 | S&P 500 (^GSPC) | On | 21.77% | 22.13% | 8.31% | -83.40% | 11 |
| x2.0 | S&P 500 (^GSPC) | On | 21.74% | 22.41% | 8.98% | -83.40% | 13 |
| x1.5 | Own (^NDX) | On | 21.42% | 22.55% | 9.58% | -84.50% | 19 |
| x3.5 | S&P 500 (^GSPC) | Off | 21.01% | 21.29% | 7.27% | -87.82% | 10 |
| x3.0 | S&P 500 (^GSPC) | On | 20.62% | 20.92% | 6.72% | -87.95% | 10 |
| x3.5 | S&P 500 (^GSPC) | On | 20.08% | 21.07% | 3.11% | -91.55% | 9 |
| x1.5 | Own (^NDX) | Off | 16.46% | 16.77% | 7.74% | -91.01% | 23 |

#### EMA — ATR & Signal Sweep (3x Leverage)

| ATR | Signal | T+2 | Avg TWR | Med TWR | Worst TWR | Worst DD | Avg Trades |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| None | Own (^NDX) | On | 23.83% | 25.77% | 10.74% | -90.36% | 13 |
| None | Own (^NDX) | Off | 23.52% | 25.05% | 10.81% | -90.41% | 13 |
| None | S&P 500 (^GSPC) | Off | 22.93% | 23.50% | 9.02% | -88.61% | 12 |
| x2.0 | Own (^NDX) | Off | 22.87% | 23.01% | 10.40% | -92.71% | 5 |
| None | S&P 500 (^GSPC) | On | 22.41% | 22.94% | 8.81% | -87.26% | 12 |
| x2.0 | S&P 500 (^GSPC) | Off | 22.29% | 22.67% | 6.91% | -96.26% | 5 |
| x1.5 | Own (^NDX) | On | 21.97% | 21.93% | 9.27% | -93.59% | 6 |
| x1.5 | Own (^NDX) | Off | 21.92% | 21.95% | 8.76% | -93.69% | 6 |
| x2.0 | Own (^NDX) | On | 21.71% | 21.75% | 9.17% | -93.86% | 5 |
| x2.0 | S&P 500 (^GSPC) | On | 21.04% | 21.16% | 5.93% | -96.26% | 5 |
| x1.5 | S&P 500 (^GSPC) | On | 20.27% | 22.45% | 3.87% | -95.52% | 5 |
| x1.5 | S&P 500 (^GSPC) | Off | 19.99% | 22.00% | 4.37% | -95.52% | 5 |
| x3.0 | Own (^NDX) | Off | 17.47% | 17.37% | 4.12% | -98.48% | 4 |
| x3.0 | Own (^NDX) | On | 17.46% | 17.25% | 3.99% | -98.46% | 4 |
| x2.5 | Own (^NDX) | On | 17.37% | 17.32% | 5.09% | -98.50% | 4 |
| x3.5 | Own (^NDX) | Off | 17.21% | 16.80% | 3.83% | -98.39% | 4 |
| x2.5 | S&P 500 (^GSPC) | On | 15.72% | 14.91% | 2.26% | -98.60% | 4 |
| x2.5 | S&P 500 (^GSPC) | Off | 15.46% | 14.71% | 1.67% | -98.65% | 4 |
| x3.0 | S&P 500 (^GSPC) | Off | 14.89% | 14.07% | 1.92% | -98.71% | 4 |
| x3.5 | Own (^NDX) | On | 14.88% | 14.61% | 2.16% | -98.74% | 4 |
| x2.5 | Own (^NDX) | Off | 14.85% | 14.80% | 2.93% | -99.14% | 5 |
| x3.0 | S&P 500 (^GSPC) | On | 13.40% | 12.60% | 0.56% | -99.02% | 4 |
| x3.5 | S&P 500 (^GSPC) | Off | 7.41% | 6.69% | -5.24% | -99.74% | 4 |
| x3.5 | S&P 500 (^GSPC) | On | 6.49% | 5.87% | -5.71% | -99.78% | 4 |

> **(1) ATR does not help EMA at 3x — it only hurts.** Every one of the 20 ATR-bearing EMA rows has a
> deeper worst drawdown than all four ATR-free ("None") rows: the shallowest ATR-row drawdown is -92.71%
> (x2.0, Own, Off), worse than even the *worst* None-row drawdown of -90.41% (Off) — let alone the best,
> -87.26% (S&P, On). No ATR row beats the best None row's 23.83% Avg TWR either (the top ATR row reaches
> only 22.87%). ATR also collapses average trade count from 12-13 down to 4-6, indicating the dead-zone
> mostly suppresses EMA crossovers entirely rather than filtering noise productively. Part of this is
> likely a scale-calibration problem rather than proof that ATR dead-zones never work: the multiplier is
> applied to a structurally much smaller-amplitude quantity for EMA (the fast/slow EMA spread) than for
> SMA (price minus a single smoothed line), so the same numeric multiplier (x1.5-x3.5) acts as a far more
> aggressive filter on EMA's spread than on SMA's price-vs-SMA gap — this result says the specific
> multiplier scale used here is miscalibrated for EMA, not that ATR dead-zones are categorically
> unworkable for EMA-style crossovers. It's also not a fair "ATR helps SMA" comparison in reverse: every
> one of the 20 SMA variants uses some ATR multiplier, so this sweep has no ATR-free SMA baseline to
> confirm ATR actually improves on a no-ATR SMA control — only that ATR is present in the winning SMA row.
>
> **(2) The S&P 500 signal does not robustly help either family at 3x — it's mixed for SMA and a clear
> loss for EMA.** This is a different question from Tables 2-3 (which compared EMA vs. SMA *on* the GSPC
> signal/asset) — here both strategies stay on ^NDX and only the trend-signal source changes. For SMA,
> S&P 500 wins only 4 of the 10 matched ATR/T+2 pairs, concentrated at looser ATR (x1.5/Off: 23.46% vs.
> 16.46% Own; x1.5/On: 24.41% vs. 21.42% Own; x2.0/Off: 23.51% vs. 22.05% Own; x2.5/Off: 23.56% vs. 23.53%
> Own, a virtual tie) — Own (^NDX) wins the other 6, especially at ATR >= 3.0 with T+2 On (x3.0/On: 23.29%
> Own vs. 20.62% S&P). For EMA, Own signal wins 11 of 12 matched pairs, often by wide margins at higher
> ATR (x3.5/Off: 17.21% Own vs. 7.41% S&P) — S&P only wins once, narrowly (x2.5/Off: 15.46% vs. 14.85%).
>
> **(3) T+2 confirmation is a net negative for SMA at 3x and a coin flip for EMA — no single setting wins
> across the board.** For SMA, T+2 raises Avg TWR in only 2 of 10 matched ATR/signal pairs — both at the
> tightest ATR band (x1.5/Own: +4.96pp, 16.46% -> 21.42%; x1.5/S&P: +0.95pp, 23.46% -> 24.41%) — and lowers
> it in the other 8, up to -2.84pp (x3.0/S&P: 23.46% Off vs. 20.62% On). The Best Practice pick itself runs
> T+2=Off. For EMA, T+2 helps in 5 of 12 pairs (e.g. x2.5/Own: +2.52pp, 14.85% -> 17.37%) and hurts in the
> other 7 (e.g. x3.5/Own: -2.33pp, 17.21% -> 14.88%) — Tables 1-3's **SMA** rows all run `bot.py`'s T+2-on
> configuration, but their EMA rows do not: `EMACrossover` had no `t2_confirmation` parameter at all before
> this effort added it, so every EMA row in Tables 1-3 was already implicitly T+2 off (Table 1's EMA row
> and Table 3's EMA row match this table's `None | Own (^NDX) | Off` and `None | S&P 500 (^GSPC) | Off`
> rows exactly). This sweep shows that at 3x, T+2's real-world value depends heavily on the ATR band and
> signal source it's paired with, not a universal improvement — true for SMA, and (once EMA's actual
> baseline is accounted for) for EMA too.

---

### **Changelog**

See [CHANGELOG.md](CHANGELOG.md) for a full history of changes with dates.

---

### **Strategy Research & Theoretical Basis**
This bot implements a **Trend-Following Strategy** enhanced with a **Triple-Filter System** to mitigate "Whipsaw" (false signals). This methodology is supported by key quantitative finance principles:

1. **Trend-Filtering for Leveraged ETFs:** Leveraged ETFs are subject to *Volatility Decay*. Research (e.g., Meb Faber) suggests that 200-day trend filters effectively "clip the left tail" of risk, preventing catastrophic drawdowns during secular bear markets.
2. **The Triple-Filter Mechanism:**
    * **SMA 200:** Identifies the long-term regime (Bull vs. Bear).
    * **ATR (Average True Range) Filter:** Dynamically adjusts the "No-Trade Zone" based on current market volatility, preventing the bot from overreacting to minor noise in stable markets.
    * **T+2 Confirmation:** Requires a signal to persist for two consecutive trading days before acting, filtering out one-day spikes that would otherwise trigger a whipsaw trade.
3. **Core Objective:** To improve **Risk-Adjusted Returns** by preserving capital during systemic failures rather than attempting to time minor market tops.

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
