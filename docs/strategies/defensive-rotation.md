# Defensive Rotation (dynamic momentum for the out-of-market sleeve)

[← Back to README](../../README.md) · Related: [Core Trend Signal](core-trend-signal.md) · [Trailing Stop](trailing-stop.md) · [Methodology](methodology.md)

The trend strategy sits **out of TQQQ ~30–36% of the time** (transitions and bears). Rather than earn cash there, `bot.py` computes the **126-day (6-month) momentum** of four defensive assets and suggests holding the **strongest** one:

| Asset | Role |
|---|---|
| **KMLM** | Managed futures — crisis-alpha / trend-following across commodities, FX, rates |
| **TLT** | 20+ yr Treasuries — deflationary / flight-to-safety bear hedge |
| **GLD** | Gold — inflation / currency-debasement hedge |
| **SHY** | 1–3 yr Treasuries — the cash-like floor (wins when nothing else has momentum) |

Because SHY is in the set, the rotation **defaults to ~cash** when every risk asset has negative momentum.

> **Status: live display feature; evaluated with proxies but *not* adopted as a
> production default.** `bot.py`'s `get_current_defensive_rotation()` shows the
> winner in the daily report, but the [headline strategy numbers](methodology.md)
> model "out of market" as **cash**. The proxy backtest below (reproduce with
> `python -m backtest.defensive_rotation_backtest`) shows a modest, *return-only*
> benefit that does not clearly justify integrating it as a default — see the sober
> conclusion.

---

## Backtest Results

The real ETFs are short-lived (KMLM from **Dec 2020**), so each is spliced onto a
longer proxy, **validated by daily-return correlation vs the real ETF**:

| Asset | Proxy | Proxy from | Corr vs real |
|---|---|---|---:|
| TLT | VUSTX | 1986 | 0.98 |
| GLD | GC=F (gold futures) | 2000 | 0.89 |
| SHY | VFISX | 1991 | 0.81 |
| **KMLM** | **RYMTX** | **2007** | **0.54** ⚠️ |

Applied only during the production rule's out-of-market days, best-momentum asset vs
**holding SGOV** (real 0–3 mo T-bills, spliced onto VFISX for history) — the benchmark
you'd actually park in. On the reconstructed-TQQQ production path. *Read the
difference, not the window-specific levels.*

| Window | out = hold SGOV | out = rotation | Δ CAGR | Δ Sharpe | Δ MaxDD |
| :--- | :--- | :--- | ---: | ---: | ---: |
| 3-asset (TLT/GLD/SHY), 2000–2026 | 15.9% / −60.4% / 0.46 | 19.0% / −61.9% / 0.52 | **+3.1** | +0.06 | −1.5 (worse) |
| 4-asset incl KMLM, 2007–2026 | 23.0% / −50.2% / 0.61 | 29.1% / −47.8% / 0.71 | **+6.1** | +0.10 | +2.4 |

*(CAGR% / MaxDD% / Sharpe.)* Holding SGOV came out ~identical to a flat-4.5% cash
assumption (15.9% and 23.0% vs 15.9% / 23.5%) — the out-of-market periods weren't
concentrated in the zero-rate years (2022's long out-period had *rising* rates), so
T-bills averaged close to cash. A short real-ETF window (2021–2026, incl. real KMLM)
showed a bigger +10pp gap, but that is essentially one out-period (2022) — treat it as
a data point, not a trend.

## Conclusion — a modest return tailwind, not a crisis hedge

- **The rotation reliably adds a little return** (~+3 to +6pp CAGR, +0.06–0.10
  Sharpe) across windows, **vs actually holding SGOV**. Defensive momentum has a mild
  positive expectancy — holding whichever of bonds/gold/managed-futures is trending
  beats parking in T-bills.
- **The drawdown / "crisis-alpha" benefit does *not* hold up.** Over the longer
  windows the max drawdown is ~neutral, and the 2008 drawdown was slightly *worse*
  with rotation than with SGOV. The eye-catching −49% → −41% drawdown cut was a
  **short-sample artifact of 2022**, where the *real* KMLM had a banner year — not a
  robust property (2008 didn't repeat it).
- **The managed-futures leg is on weak evidence.** RYMTX tracks KMLM at only 0.54
  daily-return correlation, and the whole 4-asset case leans on managed futures, so
  its long-run contribution is genuinely uncertain.

**Net:** kept as a live suggestion (a small return sweetener while parked in cash),
and it means the cash-modeled headline numbers slightly *understate* returns. But it
is **not** the drawdown hedge the short window implied, so it is not integrated as a
production default and the headline strategy stands on the trend rule + trailing stop.

## Caveats

- Momentum modeled with daily rebalancing; a real monthly implementation trades less.
- Single continuous path (26-year rolling isn't possible — gold/managed-futures proxies
  don't reach back far enough); the reconstructed-TQQQ leg drives the in-market return.
- `show_recent_signals.py` carries a drifted *duplicate* of the rotation ticker list —
  consolidate onto `get_current_defensive_rotation()` (noted in the
  [optimization analysis](../optimization-analysis-2026-07-27.md)).

## Further reading

- [`backtest/defensive_rotation_backtest.py`](../../backtest/defensive_rotation_backtest.py) — the proxy-spliced, validated backtest.
- [`bot.py`](../../bot.py) `get_current_defensive_rotation()` — the live logic.
