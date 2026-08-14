# VT Reconstruction — Validation vs Real VT (2026-08-12)

**Question.** README Table 9 reconstructs a pre-2008 "VT" history and splices it
onto real VT from 2008-07. Two worries: (a) does a market-cap index bake in
*today's* US-heavy weights and misrepresent an era when Japan/Europe were far
larger (Japan alone was ~40% of developed-market cap at its 1989 peak; the US
barely ~30%)? and (b) how *close* is the reconstruction to real VT where we can
actually check?

**Answers.** (a) No — MSCI World is **continuously market-cap weighted**, so it
already carries that time-varying US weight; it is *not* a static-weight series.
(b) The proxy Table 9 actually uses — **MSCI World + an emerging-markets sleeve**
— tracks real VT closely over their 2008–2026 overlap: **0.95 daily-return
correlation, monthly R² 0.98, a near-zero −0.12%/yr CAGR gap, and a 0.8pp mean
annual gap**. Adding the EM sleeve was the single biggest improvement, cutting
the annual gap from 2.1pp (World-only) and the CAGR gap from +0.32% to ~0.

Reproduce with `python backtest/validate_vt_reconstruction.py`.

## Method

The Table 9 proxy blends a developed-world index with an EM sleeve at EM's
market-cap share (0% → ~12%, `EM_WEIGHT_BY_YEAR` in `generate_vt_table.py`):

    proxy_ret(t) = (1 − w_EM) · MSCI_World_ret(t) + w_EM · EM_ret(t)
    MSCI World = ^990100-USD-STRD (1985+)   EM = EEM (USD, 2003-04+)

This note also builds an independent cross-check — an explicit **dynamic
US+EAFE** blend, annually re-weighted by US market-cap share
(`US_WEIGHT_BY_YEAR`, ≈0.57 in 2001 → ~0.74 by the mid-2020s):

    blend_ret(t) = w_US(year)·SP500_ret(t) + (1 − w_US(year))·EAFE_ret(t)
    US = ^GSPC     ex-US dev = EFA (MSCI EAFE ETF, USD, 2001+)

All series are daily **price** returns (ex-dividend, raw Close), matching
Tables 1–3.

Why EFA/EEM and not the MSCI indices, and why only 2001–2003+: the MSCI EAFE and
EM indices have **no history on Yahoo** (live quote only), and FX pairs are
unavailable before ~2003, so no USD ex-US series can be built back to 1985 from
this data source. That data wall is why Table 9 uses MSCI World — the one
developed-world series reaching 1985 — for the deep past, with the EM sleeve
switched on only once EEM data begins (EM was ~1% of the world in the late
1980s, so its earlier absence is a small error).

## Results

| Comparison (A vs B) | Overlap (days) | Daily-ret corr | Ann. tracking err | Cumulative A vs B | Gap |
| :--- | :--- | ---: | ---: | ---: | ---: |
| Dynamic blend vs **MSCI World** (pre-VT) | 2001-08→2008-06 (1718) | 0.748 | 11.44% | 32% vs 29% | +3pp |
| Dynamic blend vs **MSCI World** (full) | 2001-08→2026-08 (6269) | 0.901 | 8.40% | 409% vs 359% | +50pp |
| Dynamic blend vs **real VT** | 2008-06→2026-08 (4560) | 0.972 | 4.82% | 276% vs 228% | +49pp |
| **MSCI World** vs **real VT** (old, World-only proxy) | 2008-06→2026-08 (4553) | 0.940 | 7.33% | 256% vs 237% | +18pp |
| **MSCI World + EM** vs **real VT** (Table 9 proxy leg) | 2008-06→2026-08 (4553) | 0.954 | 6.36% | 231% vs 237% | **−7pp** |
| US-only (S&P 500) vs **real VT** (contrast) | 2008-06→2026-08 (4560) | 0.951 | 6.36% | 508% vs 228% | +280pp |

### What this shows

1. **The EM sleeve closes most of the residual gap.** Adding emerging markets to
   the developed-world proxy tightens the fit to real VT on every axis: the mean
   annual return gap falls **2.1pp → 0.8pp**, the CAGR gap **+0.32% → −0.12%/yr**,
   the cumulative gap **+18pp → −7pp**, and daily correlation rises
   **0.940 → 0.954** (monthly R² 0.973 → 0.983). EM was the single largest
   composition difference between VT and a developed-only proxy — the source of
   the worst single-year miss (2009, EM +79%) — so restoring it is the highest-
   value fidelity fix available. The proxy now sits *marginally under* VT (−7pp)
   rather than over, because at a fixed ~12% EM weight the EM drag over 2008–2026
   slightly outweighs the small-cap sleeve VT still holds that the proxy lacks.

2. **The dynamic international weighting is what matters — and the index supplies
   it.** US-only overstates real VT by **+280pp** over 18 years (508% vs 228%),
   despite a high 0.95 daily correlation. The MSCI World + EM proxy's gap is
   **−7pp**. Assuming a static US-heavy weight (as skipping the reconstruction
   would) is off by *orders of magnitude* on cumulative return; the market-cap
   weighting closes almost all of it. **MSCI World is a dynamic-weight series,
   not a static one.**

3. **The explicit dynamic US+EAFE blend corroborates the method.** The annually
   re-weighted blend tracks real VT at 0.97 correlation. It runs ~+49pp hot vs VT
   because it omits emerging markets and small caps and carries a slightly higher
   US tilt — a composition difference, not a weighting error (and exactly why the
   EM sleeve, not a reweighting, is the fix that matters).

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
- The `US_WEIGHT_BY_YEAR` and `EM_WEIGHT_BY_YEAR` schedules are approximate
  market-cap paths, not vendor weight files. The tracking checks are robust to
  modest weight error because the component returns are highly correlated.
- **The EM sleeve only helps from 2003** (EEM's inception); before then it is 0.
  This is why the Table 9 EM enhancement moves only the 2003–2008 portion of the
  pre-splice proxy, lifting the table's cells by ~0.2–1.0pp (those years were an
  EM boom). EM's absence before 2003 is a small error because EM was a tiny
  share of world market cap then.

## Data-recovered US weight (secondary corroboration)

A per-year least-squares fit of `World ≈ w·US + (1−w)·EAFE` (w clipped to
[0,1]) recovers the effective US weight embedded in MSCI World straight from
returns. It is **noisy year to year** — the same closing-time offset destabilises
single-year fits — but it stays in a **~0.5–0.75 band and never approaches 1.0**,
i.e. MSCI World consistently carries a large, non-trivial international weight
rather than behaving like a US-only index. Full yearly table in
`backtest/vt_reconstruction_validation_output.md`.

## Bottom line

The Table 9 reconstruction — **MSCI World + an EM sleeve**, spliced onto real VT
— tracks real VT closely over the window where a check is possible: **0.95
daily correlation, monthly R² 0.98, −0.12%/yr CAGR gap, 0.8pp mean annual gap,
−7pp cumulative over 18 years**. Adding emerging markets was the single biggest
fidelity gain (annual gap 2.1pp → 0.8pp). The market-cap weighting captures the
time-varying US/international split that a static or US-only assumption would get
wrong by *hundreds* of percentage points (+280pp). The one bias that remains —
no global **small caps** (no long history available) — is small and disclosed in
the Table 9 caveats.
