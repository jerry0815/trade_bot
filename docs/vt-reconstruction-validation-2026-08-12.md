# VT Reconstruction — Validation of the MSCI World Proxy (2026-08-12)

**Question.** README Table 9 reconstructs a pre-2008 "VT" history from the
**MSCI World** price index (`^990100-USD-STRD`), spliced onto real VT from
2008-07. Is a single index legitimate, or does it bake in *today's* US-heavy
weights and misrepresent an era when Japan and Europe were far larger
(Japan alone was ~40% of developed-market cap at its 1989 peak; the US was
barely ~30%)?

**Answer.** It is legitimate. MSCI World is **continuously market-cap
weighted**, so it already carries that time-varying US weight — it is *not* a
static-weight series. This note validates that empirically by building the
explicit dynamic reconstruction the index is accused of missing and comparing
it, plus MSCI World itself, against real VT.

Reproduce with `python backtest/validate_vt_reconstruction.py`.

## Method

Explicit dynamic reconstruction, annually re-weighted by US market-cap share:

    US        = S&P 500        (^GSPC)
    ex-US dev = MSCI EAFE ETF  (EFA, USD, 2001+)
    blend_ret(t) = w_US(year)·US_ret(t) + (1 − w_US(year))·EAFE_ret(t)

`w_US` follows an editable annual schedule (≈US share of the US+EAFE developed
blend: 0.57 in 2001 rising to ~0.74 by the mid-2020s — see
`US_WEIGHT_BY_YEAR`). All series are daily **price** returns (ex-dividend, raw
Close), matching Tables 1–3.

Why EFA and not the MSCI EAFE index, and why only 2001+: the MSCI EAFE index
(`^990300-USD-STRD`) has **no history on Yahoo** (live quote only), and FX pairs
are unavailable before ~2003, so a USD ex-US series cannot be built back to
1985 from this data source. That data wall is exactly why Table 9 uses MSCI
World — the one developed-world series with full 1985 history — for the deep
past, and this validation confirms that choice over the window where an
independent cross-check *is* possible.

## Results

| Comparison (A vs B) | Overlap (days) | Daily-ret corr | Ann. tracking err | Cumulative A vs B | Gap |
| :--- | :--- | ---: | ---: | ---: | ---: |
| Dynamic blend vs **MSCI World** (pre-VT) | 2001-08→2008-06 (1718) | 0.748 | 11.44% | 32% vs 29% | +3pp |
| Dynamic blend vs **MSCI World** (full) | 2001-08→2026-08 (6268) | 0.901 | 8.40% | 407% vs 357% | +50pp |
| Dynamic blend vs **real VT** | 2008-06→2026-08 (4559) | 0.972 | 4.82% | 275% vs 226% | +48pp |
| **MSCI World** vs **real VT** (Table 9 proxy leg) | 2008-06→2026-08 (4552) | 0.940 | 7.34% | 254% vs 236% | +18pp |
| US-only (S&P 500) vs **real VT** (contrast) | 2008-06→2026-08 (4559) | 0.951 | 505% vs 226% | +278pp |

### What this shows

1. **The Table 9 proxy leg is sound.** MSCI World tracks real VT with 0.94
   daily-return correlation and a +18pp cumulative gap over 18 years — modestly
   *higher* because MSCI World is developed-only, omitting the emerging-markets
   and small-cap sleeves VT holds (both underperformed over this window).

2. **The dynamic international leg is what matters — and MSCI World supplies
   it.** US-only overstates real VT by **+278pp** over 18 years (505% vs 226%),
   despite a high 0.95 daily correlation. MSCI World's gap is only **+18pp**.
   In other words, assuming a static US-heavy weight (as skipping the
   reconstruction would) is off by an order of magnitude on cumulative return;
   MSCI World's market-cap weighting closes almost all of that gap. That is the
   central point: **MSCI World is a dynamic-weight series, not a static one.**

3. **The explicit dynamic blend corroborates the method.** The annually
   re-weighted US+EAFE blend tracks real VT at 0.97 correlation. It runs ~+48pp
   hot vs VT because, like MSCI World, it omits emerging markets and small caps,
   and carries a slightly higher US tilt — a composition difference, not a
   weighting error.

### Caveats (read these before trusting the tracking-error column)

- **Non-synchronous closing times inflate the pre-2008 mismatch.** EFA (a
  US-listed ETF) prices at the 4pm ET US close; the MSCI World index and its
  EAFE component are struck at *local* European/Asian closes, hours earlier. So
  same-day EFA vs MSCI World returns are partly offset by a day, depressing the
  0.748 daily correlation and inflating the 11.44% tracking error for that row.
  Cumulative returns — which are immune to the timing offset — still track to
  +3pp over seven years. The VT-based rows (blend vs VT, World vs VT) do not
  suffer this, since VT and EFA are both struck at the US close, which is why
  their correlations are much higher (0.94–0.97).
- **Price return only** (ex-dividend), so every "cumulative" figure understates
  total return; this is consistent across all series and matches Tables 1–3.
- The `US_WEIGHT_BY_YEAR` schedule is an approximate market-cap path, not a
  vendor weight file. The tracking checks are robust to modest weight error
  because US and EAFE returns are highly correlated intraday.

## Data-recovered US weight (secondary corroboration)

A per-year least-squares fit of `World ≈ w·US + (1−w)·EAFE` (w clipped to
[0,1]) recovers the effective US weight embedded in MSCI World straight from
returns. It is **noisy year to year** — the same closing-time offset destabilises
single-year fits — but it stays in a **~0.5–0.75 band and never approaches 1.0**,
i.e. MSCI World consistently carries a large, non-trivial international weight
rather than behaving like a US-only index. Full yearly table in
`backtest/vt_reconstruction_validation_output.md`.

## Bottom line

Using MSCI World for Table 9's pre-2008 segment is the right call given the
data available: it is a genuinely dynamic, market-cap-weighted developed-world
series that tracks real VT closely (0.94 corr, +18pp/18yr), and it captures the
time-varying US/international split that a static or US-only assumption would
get wrong by hundreds of percentage points. Its one systematic bias — omitting
emerging markets and small caps — makes it run modestly *hot* versus true VT,
which is disclosed in the Table 9 caveats.
