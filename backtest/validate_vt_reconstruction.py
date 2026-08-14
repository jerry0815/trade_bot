"""
Validates the Table 9 VT reconstruction (backtest/generate_vt_table.py).

Table 9 uses the MSCI World price index (^990100-USD-STRD) as the pre-2008
developed-equity proxy, spliced onto real VT. A fair question is whether a
*static* index misrepresents history — the US share of world equities has moved
enormously (Japan's 1989 bubble made the US barely ~30% of developed-market cap;
today it is ~70%). This script shows it does NOT, because MSCI World is
continuously market-cap weighted and therefore already carries that time-varying
US weight.

It does so by building the EXPLICIT dynamic reconstruction the static index is
accused of missing — an annually re-weighted, market-cap blend of

    US        = S&P 500              (^GSPC)
    ex-US dev = MSCI EAFE ETF        (EFA, USD)

— and checking, over the windows where the data exists, that:

  1. blend  ≈ MSCI World      (2001–2008, the pre-VT overlap)  -> justifies
     using MSCI World for the deep-history splice segment.
  2. blend  ≈ real VT         (2008–present)                   -> the dynamic
     US+EAFE method tracks the thing we are reconstructing.
  3. MSCI World ≈ real VT     (2008–present)                   -> the actual
     proxy leg used in Table 9 tracks real VT.

EAFE has no pre-2001 history on Yahoo (only a live quote) and FX is unavailable
before ~2003, so the explicit blend cannot itself be pushed back to 1985 — which
is exactly why Table 9 uses MSCI World there. Run:

    python backtest/validate_vt_reconstruction.py

Writes a report to backtest/vt_reconstruction_validation_output.md.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import numpy as np
import pandas as pd
from backtest.strat_backtest import get_cached_data

OUTPUT_PATH = REPO_ROOT / "backtest" / "vt_reconstruction_validation_output.md"

US_TICKER    = "^GSPC"             # US large cap
EAFE_TICKER  = "EFA"              # MSCI EAFE ETF (developed ex-US, USD, 2001+)
WORLD_TICKER = "^990100-USD-STRD"  # MSCI World price index (1985+)
EM_TICKER    = "EEM"              # MSCI EM ETF (USD, 2003-04+)
VT_TICKER    = "VT"               # real Vanguard Total World (2008+)
EM_WEIGHT    = 0.12               # EM sleeve weight (Table 9's mature-era value)

# Approximate US share of the US+EAFE developed blend, by year. These are the
# "market-cap weighting adjusted year by year" the reconstruction calls for —
# roughly the US share of developed-market cap (rising as US mega-caps came to
# dominate; lower earlier when Japan/Europe were relatively larger). Editable;
# the tracking checks below are robust to modest weight error because US and
# EAFE returns are highly correlated.
US_WEIGHT_BY_YEAR = {
    2001: 0.57, 2002: 0.56, 2003: 0.55, 2004: 0.54, 2005: 0.53, 2006: 0.51,
    2007: 0.49, 2008: 0.50, 2009: 0.51, 2010: 0.52, 2011: 0.54, 2012: 0.55,
    2013: 0.57, 2014: 0.59, 2015: 0.61, 2016: 0.62, 2017: 0.63, 2018: 0.65,
    2019: 0.67, 2020: 0.68, 2021: 0.70, 2022: 0.71, 2023: 0.72, 2024: 0.73,
    2025: 0.74, 2026: 0.74,
}
_DEFAULT_W = 0.74  # for any year beyond the table


def daily_returns(ticker):
    s = get_cached_data(ticker)["Close"].astype(float)
    return s.pct_change().dropna()


def build_dynamic_blend(us_ret, eafe_ret):
    """Annually re-weighted market-cap blend of US and EAFE daily returns."""
    j = pd.concat({"us": us_ret, "eafe": eafe_ret}, axis=1).dropna()
    w_us = j.index.to_series().dt.year.map(
        lambda y: US_WEIGHT_BY_YEAR.get(y, _DEFAULT_W)
    ).values
    blend = w_us * j["us"].values + (1.0 - w_us) * j["eafe"].values
    return pd.Series(blend, index=j.index, name="blend")


def _cmp(a, b, lo=None, hi=None):
    j = pd.concat({"a": a, "b": b}, axis=1).dropna()
    if lo is not None:
        j = j[j.index >= pd.Timestamp(lo)]
    if hi is not None:
        j = j[j.index <= pd.Timestamp(hi)]
    if len(j) < 20:
        return None
    corr = j["a"].corr(j["b"])
    te = (j["a"] - j["b"]).std() * np.sqrt(252) * 100          # ann. tracking error
    cum_a = (1 + j["a"]).prod() - 1
    cum_b = (1 + j["b"]).prod() - 1
    return {
        "n": len(j), "start": j.index[0].date(), "end": j.index[-1].date(),
        "corr": corr, "te": te, "cum_a": cum_a * 100, "cum_b": cum_b * 100,
        "cum_gap": (cum_a - cum_b) * 100,
    }


def _row(label, r):
    if r is None:
        return f"| {label} | insufficient overlap | | | | |"
    return (f"| {label} | {r['start']}→{r['end']} ({r['n']}) | {r['corr']:.3f} | "
            f"{r['te']:.2f}% | {r['cum_a']:.0f}% vs {r['cum_b']:.0f}% | {r['cum_gap']:+.0f}pp |")


def main():
    us    = daily_returns(US_TICKER)
    eafe  = daily_returns(EAFE_TICKER)
    world = daily_returns(WORLD_TICKER)
    em    = daily_returns(EM_TICKER)
    vt    = daily_returns(VT_TICKER)
    blend = build_dynamic_blend(us, eafe)

    # EM-enhanced proxy = MSCI World + EM sleeve — the actual Table 9 pre-2008
    # construction (backtest/generate_vt_table.py), evaluated here on the VT
    # overlap at its mature-era EM weight.
    we = pd.concat({"w": world, "e": em}, axis=1).dropna()
    world_em = (1 - EM_WEIGHT) * we["w"] + EM_WEIGHT * we["e"]

    lines = ["# VT reconstruction validation", "",
             "Dynamic US(S&P 500)+EAFE(EFA) market-cap blend vs the MSCI World proxy "
             "and real VT. Daily price returns (ex-dividend), blend re-weighted to "
             "annual US market-cap share (see `US_WEIGHT_BY_YEAR`).", "",
             "| Comparison (A vs B) | Overlap (days) | Daily-ret corr | Ann. tracking err | Cumulative A vs B | Gap |",
             "| :--- | :--- | ---: | ---: | ---: | ---: |",
             _row("Dynamic blend vs **MSCI World** (pre-VT)", _cmp(blend, world, hi="2008-06-30")),
             _row("Dynamic blend vs **MSCI World** (full)",   _cmp(blend, world)),
             _row("Dynamic blend vs **real VT**",             _cmp(blend, vt)),
             _row("**MSCI World** vs **real VT** (old proxy leg)", _cmp(world, vt)),
             _row("**MSCI World + EM** vs **real VT** (Table 9 proxy leg)", _cmp(world_em, vt)),
             _row("US-only (S&P 500) vs **real VT** (contrast)", _cmp(us, vt)),
             ""]

    # US-weight drift, recovered from data: constrained yearly fit of
    # world_ret ≈ w*us_ret + (1-w)*eafe_ret, w in [0,1]. Corroborates that the
    # weight embedded in MSCI World rises over time (market-cap dynamics), and
    # that our hand-set schedule is in the right neighbourhood.
    j = pd.concat({"us": us, "eafe": eafe, "world": world}, axis=1).dropna()
    lines += ["## Effective US weight embedded in MSCI World (recovered from data)",
              "*Yearly least-squares fit of World ≈ w·US + (1−w)·EAFE, w clipped to [0,1]. "
              "Compared to the hand-set market-cap schedule used in the blend.*", "",
              "| Year | Fitted US weight | Schedule US weight |",
              "| ---: | ---: | ---: |"]
    for y, g in j.groupby(j.index.year):
        d = (g["us"] - g["eafe"]).values
        t = (g["world"] - g["eafe"]).values
        denom = float(d @ d)
        w = float(np.clip((d @ t) / denom, 0, 1)) if denom > 0 else float("nan")
        lines.append(f"| {y} | {w:.2f} | {US_WEIGHT_BY_YEAR.get(y, _DEFAULT_W):.2f} |")

    report = "\n".join(lines)
    print(report)
    OUTPUT_PATH.write_text(report, encoding="utf-8")
    print(f"\nWritten to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
