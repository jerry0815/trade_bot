import time
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Capital Gains Tax Rates (US defaults)
# Long-term: position held > 365 calendar days
# Short-term: position held <= 365 calendar days
# Set apply_tax=True on Backtester to enable post-tax simulation.
# ---------------------------------------------------------------------------
TAX_LONG_TERM_RATE  = 0.15   # 15% on gains held > 365 days
TAX_SHORT_TERM_RATE = 0.25   # 25% on gains held <= 365 days

# Global Caches
DATA_CACHE = {}
SIGNAL_CACHE = {}

# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

def _download_with_retry(tickers, period="5y", max_retries=5):
    """Download yfinance data with exponential back-off retry.

    Returns a non-empty DataFrame or raises RuntimeError after all retries.
    """
    backoff = 15  # seconds between attempts
    data = pd.DataFrame()
    for attempt in range(1, max_retries + 1):
        try:
            data = yf.download(tickers, period=period, progress=False, auto_adjust=False, threads=False)
            if not data.empty:
                return data
        except Exception as e:
            print(f"[yf.download] Exception during download: {e}")
            data = pd.DataFrame()

        if attempt < max_retries:
            print(
                f"[yf.download] Empty response or error for '{tickers}' "
                f"(attempt {attempt}/{max_retries}). Retrying in {backoff}s..."
            )
            time.sleep(backoff)
            backoff *= 2  # exponential back-off
    raise RuntimeError(
        f"[yf.download] Failed to download '{tickers}' after {max_retries} attempts. "
        "yfinance may be rate-limiting this runner."
    )

def get_cached_data(ticker="^NDX"):
    """Fetches raw data once and caches it."""
    if ticker not in DATA_CACHE:
        # Download from 1985 to ensure all indicators are fully warmed up
        df = yf.download(ticker, start="1985-01-01", progress=False, auto_adjust=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        DATA_CACHE[ticker] = df
    return DATA_CACHE[ticker].copy()

def prep_base_indicators(df, vix_series, sma_window=200):
    """Applies VIX alignment, base indicators, ATR, and Borrow Rates to a dataframe."""

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.copy()

    # Align VIX
    df['VIX'] = vix_series
    df['VIX'] = df['VIX'].ffill()

    # 1. Base Indicators
    df['SMA'] = df['Close'].rolling(window=sma_window).mean()
    df['Daily_Return_1x'] = df['Close'].pct_change()

    # 2. Vectorized True Range
    df['Prev_Close'] = df['Close'].shift(1)
    df['HL'] = df['High'] - df['Low']
    df['HC'] = (df['High'] - df['Prev_Close']).abs()
    df['LC'] = (df['Low'] - df['Prev_Close']).abs()
    df['True_Range'] = df[['HL', 'HC', 'LC']].max(axis=1)
    df.loc[df['Prev_Close'].isna(), 'True_Range'] = df['HL']

    df['ATR'] = df['True_Range'].rolling(window=14).mean()

    # 3. Pre-compute Historic Borrow Rates
    years = df.index.year
    conditions = [
        years < 1990, years < 2000, years < 2008,
        years < 2016, years < 2022, years >= 2022
    ]
    choices = [0.09, 0.055, 0.04, 0.005, 0.015, 0.05]
    df['BR'] = np.select(conditions, choices, default=0.05)

    # 4. Next-day open execution columns
    # Open2Close: return earned when entering at today's open and holding to close
    # Overnight_Return: gap return from prior close to today's open (used on exit day)
    df['Open2Close']       = (df['Close'] - df['Open'])          / df['Open']
    df['Overnight_Return'] = (df['Open']  - df['Close'].shift(1)) / df['Close'].shift(1)

    return df

def get_cached_signals(ticker="^NDX", sma_window=200):
    """Calculates all indicators and borrow rates for the entire history once."""
    cache_key = (ticker, sma_window)

    if cache_key not in SIGNAL_CACHE:
        df = get_cached_data(ticker)
        vix_df = get_cached_data("^VIX")

        # Use our new shared helper function
        SIGNAL_CACHE[cache_key] = prep_base_indicators(df, vix_df['Close'], sma_window)

    return SIGNAL_CACHE[cache_key].copy()

def get_current_defensive_rotation(data):
    """
    Calculates the live 126-day momentum for KMLM, TLT, GLD, and SHY.
    Returns a dictionary of the momentums and the current winner.
    `data` should be a MultiIndex DataFrame from yfinance containing these tickers.
    """
    tickers = ["KMLM", "TLT", "GLD", "SHY"]
    momentums = {}
    
    for t in tickers:
        if isinstance(data.columns, pd.MultiIndex):
            # Try to get the close price for this ticker
            if t in data.columns.get_level_values(1):
                close_series = data.xs(t, axis=1, level=1)['Close'].dropna()
                if len(close_series) >= 126:
                    mom = (close_series.iloc[-1] / close_series.iloc[-126]) - 1
                    momentums[t] = float(mom)
                else:
                    momentums[t] = 0.0
            else:
                momentums[t] = 0.0
        else:
            momentums[t] = 0.0
            
    # Determine winner
    winner = "SHY"
    if momentums:
        winner = max(momentums, key=momentums.get)
        
    return {
        "momentums": momentums,
        "winner": winner
    }

def cache_clear():
    """
    Clears all in-memory data and signal caches.

    Call this whenever you change indicator parameters that are NOT part of the
    cache key (e.g., ATR period in prep_base_indicators, borrow rate table),
    or to force a fresh yfinance download after market close.

    Example:
        cache_clear()
        get_cached_signals('^NDX', sma_window=200)  # re-downloads + recomputes
    """
    DATA_CACHE.clear()
    SIGNAL_CACHE.clear()

class BaseStrategy:
    def __init__(self, name):
        self.name = name
        self.df = None

    def generate_signals(self, df):
        df = self._add_indicator_logic(df)
        if 'in_market' not in df.columns:
            raise ValueError(f"Strategy '{self.name}' failed to create 'in_market' column.")
        # trade counts are derived from the sliced test-period df inside Backtester,
        # not from the full history here — avoids the off-period double-count bug.
        return df, {}

    def _add_indicator_logic(self, df):
        raise NotImplementedError("Child strategies must implement _add_indicator_logic()")

    def get_live_stats(self, monitor_ticker="QQQ", leveraged_ticker="TQQQ", data=None):
        # 1. Use caller-supplied data (shared download) or fetch fresh with retry logic.
        if data is None:
            tickers = f"{monitor_ticker} {leveraged_ticker} ^VIX"
            data = _download_with_retry(tickers)

        # If multiple tickers were requested, yfinance returns a MultiIndex DataFrame (Price, Ticker)
        # We need to extract the 'Close', 'High', 'Low' etc. for each ticker
        if isinstance(data.columns, pd.MultiIndex):
            # df is for monitor_ticker
            df           = data.xs(monitor_ticker,   axis=1, level=1).dropna(subset=['Close']).copy()
            # leveraged_df is for leveraged_ticker
            leveraged_df = data.xs(leveraged_ticker, axis=1, level=1).dropna(subset=['Close']).copy()
            # vix is for ^VIX
            vix          = data.xs("^VIX",           axis=1, level=1).dropna(subset=['Close']).copy()
        else:
            # Fallback if only one ticker was somehow fetched
            df           = data.dropna(subset=['Close']).copy()
            leveraged_df = data.dropna(subset=['Close']).copy()
            vix          = data.dropna(subset=['Close']).copy()

        # Guard: ensure each ticker's slice actually has rows before proceeding
        missing = []
        if df.empty:           missing.append(monitor_ticker)
        if leveraged_df.empty: missing.append(leveraged_ticker)
        if vix.empty:          missing.append("^VIX")
        if missing:
            raise RuntimeError(
                f"[get_live_stats] Data is empty for: {missing}. "
                "This is likely a yfinance rate-limit issue — re-run the action or add a delay."
            )

        # 2. Process data
        self.df = prep_base_indicators(df, vix['Close'])
        self.df = self._add_indicator_logic(self.df)

        # 3. Count consecutive trading days in the current state (hold or cash streak)
        in_market_vals = self.df['in_market'].values
        current_state  = bool(in_market_vals[-1])
        streak = 0
        for v in reversed(in_market_vals):
            if bool(v) == current_state:
                streak += 1
            else:
                break
        # Derive the calendar date the current streak started
        state_since = self.df.index[-streak] if streak <= len(self.df) else self.df.index[0]

        # 4. Return the base report stats
        return {
            "qqq_price"      : float(self.df['Close'].iloc[-1].item()),
            "leveraged_price": float(leveraged_df['Close'].iloc[-1]),
            "action"               : "BUY/HOLD" if current_state else "SELL/CASH",
            "days_in_current_state": int(streak),
            "state_since"          : state_since.strftime("%Y-%m-%d"),
        }

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
        close = (df['Close'] if price is None else price).to_numpy()
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

class BuyAndHold(BaseStrategy):
    def __init__(self):
        super().__init__(name="Buy & Hold")

    def _add_indicator_logic(self, df):
        df = df.copy()
        df['in_market'] = True
        return df

class SMATrendFollowing(BaseStrategy):
    def __init__(self, sma_window=200, buffer_pct=None, atr_multiplier=2.5, t2_confirmation=False,
                 vix_threshold=None, atr_spike_multiplier=None, atr_spike_lookback=60,
                 sma_slope_lookback=None, trailing_stop_pct=None, trailing_stop_cooldown_days=20):
        # We handle naming and initialization cleanly
        name = f"SMA {sma_window} - " + (f"Static {buffer_pct*100}% Buffer" if buffer_pct else f"ATR Buffer (x{atr_multiplier})")
        if t2_confirmation:
            name += " [T+2]"
        if vix_threshold:
            name += f" [VIX>{vix_threshold} bypass]"
        if atr_spike_multiplier:
            name += f" [ATR-spike x{atr_spike_multiplier} bypass]"
        if sma_slope_lookback:
            name += f" [SMA-slope {sma_slope_lookback}d re-entry filter]"
        if trailing_stop_pct:
            # One decimal place, not zero: at .0f two distinct stops (e.g. 0.075
            # and 0.08) would render to the same string and silently collide in
            # RollingBacktester's strategy-name-keyed columns.
            name += f" [Trailing Stop {trailing_stop_pct*100:.1f}%, cooldown {trailing_stop_cooldown_days}d]"
        super().__init__(name=name)
        self.sma_window = sma_window
        self.buffer_pct = buffer_pct
        self.atr_multiplier = atr_multiplier
        self.t2_confirmation = t2_confirmation
        # When set, T+2 confirmation is bypassed (signal acts same-day) on any
        # day the VIX close is above this threshold — the idea being that in a
        # genuine fast/severe selloff the directional signal isn't ambiguous,
        # so the 2-day confirmation delay costs more than it filters. Has no
        # effect unless t2_confirmation=True (nothing to bypass otherwise).
        # VIX data only exists from 1990 onward (see strat_backtest.py's
        # ^VIX cache) — for any date before that, df['VIX'] is NaN and the
        # comparison below is always False, so the bypass silently never
        # fires for pre-1990 history rather than erroring.
        self.vix_threshold = vix_threshold
        # Same bypass idea as vix_threshold, but keyed to realized volatility
        # computed from price data (ATR as a % of Close, relative to its own
        # trailing average) instead of the VIX index — this has full
        # historical coverage back to the start of the data (no 1990 floor),
        # so it can react to pre-VIX events like Black Monday 1987. Also has
        # no effect unless t2_confirmation=True. If both vix_threshold and
        # atr_spike_multiplier are set, either condition can trigger the
        # bypass on a given day (logical OR).
        self.atr_spike_multiplier = atr_spike_multiplier
        self.atr_spike_lookback = atr_spike_lookback
        # When set, a re-entry (buy) signal only fires if the SMA itself has
        # risen over the last N days — filters out re-entries during a bear-
        # market rally where price briefly pokes above the ATR band while the
        # underlying 200-day trend is still declining (dot-com's repeated
        # whipsaw losses being the motivating case). Only affects entries,
        # not exits — a declining SMA shouldn't make the strategy slower to
        # get OUT, only slower to get back IN on an unconfirmed reversal.
        self.sma_slope_lookback = sma_slope_lookback
        # When set, exits the position the day the signal-ticker's Close
        # falls trailing_stop_pct below its own running peak since the most
        # recent entry — independent of what the SMA/ATR trend signal says.
        # Measured against the unleveraged signal-ticker price (same series
        # the entry/exit band already watches), not the leveraged equity
        # curve: a given % threshold then means the same underlying move
        # regardless of leverage tier, instead of needing separate tuning
        # per leverage config. Acts immediately (bypasses t2_confirmation
        # unconditionally) — the whole point is reacting faster than the
        # slow trend signal, so gating it behind the same delay it exists
        # to route around would defeat the purpose. After a stop-triggered
        # exit, re-entry is blocked for trailing_stop_cooldown_days trading
        # days regardless of the trend signal, then normal signal-driven
        # entry logic resumes unmodified. A normal trend-signal-driven exit
        # does NOT start a cooldown — only a trailing-stop-triggered one
        # does. cooldown_days only matters when trailing_stop_pct is set.
        self.trailing_stop_pct = trailing_stop_pct
        self.trailing_stop_cooldown_days = trailing_stop_cooldown_days

    def get_live_stats(self, monitor_ticker="QQQ", leveraged_ticker="TQQQ", data=None):
        # 1. Get the base data (pass shared pre-downloaded data if provided)
        stats = super().get_live_stats(monitor_ticker, leveraged_ticker, data=data)
        
        def _get_trend_for_day(idx):
            price = float(self.df['Close'].iloc[idx])
            sma = float(self.df['SMA'].iloc[idx])
            
            if self.buffer_pct:
                upper_bound = sma * (1 + self.buffer_pct)
                lower_bound = sma * (1 - self.buffer_pct)
            else:
                atr = float(self.df['ATR'].iloc[idx])
                upper_bound = sma + (atr * self.atr_multiplier)
                lower_bound = sma - (atr * self.atr_multiplier)
                
            if price > upper_bound:
                return "BULLISH", sma, upper_bound, lower_bound
            elif price < lower_bound:
                return "BEARISH", sma, upper_bound, lower_bound
            return "NEUTRAL", sma, upper_bound, lower_bound

        current_trend, current_sma, upper, lower = _get_trend_for_day(-1)
        previous_trend, _, _, _ = _get_trend_for_day(-2)
        
        stats.update({
            "current_sma": current_sma,
            "upper_bound": upper,
            "lower_bound": lower,
            "trend": current_trend,
            "previous_trend": previous_trend,
            "trend_changed": current_trend != previous_trend
        })
        
        return stats

    def _add_indicator_logic(self, df):
        """
        Overrides the hidden parent logic. Focuses strictly on creating the
        'in_market' column using specialized buffer-band logic.
        Vectorized for performance.
        """
        df = df.copy()

        # Always recompute SMA for this strategy's own window.
        # The cached df has SMA=200; if sma_window differs this would silently use the wrong line.
        df['SMA'] = df['Close'].rolling(window=self.sma_window).mean()
        # 1. Calculate bounds universally for the entire dataframe at once
        if self.buffer_pct:
            upper_bound = df['SMA'] * (1 + self.buffer_pct)
            lower_bound = df['SMA'] * (1 - self.buffer_pct)
        else:
            upper_bound = df['SMA'] + (df['ATR'] * self.atr_multiplier)
            lower_bound = df['SMA'] - (df['ATR'] * self.atr_multiplier)

        # 2. Identify the exact days the price breaks the bounds
        buy_signal_raw = df['Close'] > upper_bound
        sell_signal_raw = df['Close'] < lower_bound

        if self.sma_slope_lookback:
            # A rising SMA is required for a re-entry to count at all — this
            # gates buy_signal_raw itself, before T+2/volatility-bypass logic
            # ever sees it, so a filtered-out re-entry can't be confirmed or
            # bypassed into an actual entry either.
            sma_rising = df['SMA'] > df['SMA'].shift(self.sma_slope_lookback)
            buy_signal_raw = buy_signal_raw & sma_rising.fillna(False)

        if self.t2_confirmation:
            buy_signal_confirmed = buy_signal_raw.rolling(window=2).min() == 1
            sell_signal_confirmed = sell_signal_raw.rolling(window=2).min() == 1

            high_vol = None
            if self.vix_threshold:
                high_vol = df['VIX'] > self.vix_threshold
            if self.atr_spike_multiplier:
                atr_pct = df['ATR'] / df['Close']
                atr_pct_baseline = atr_pct.rolling(window=self.atr_spike_lookback, min_periods=20).mean()
                atr_spike = atr_pct > (atr_pct_baseline * self.atr_spike_multiplier)
                high_vol = atr_spike if high_vol is None else (high_vol | atr_spike)

            if high_vol is not None:
                # High-volatility days (by whichever measure(s) are enabled)
                # act on the raw (same-day) signal; everything else still
                # requires the normal 2-day confirmation.
                high_vol = high_vol.fillna(False)
                buy_signal = pd.Series(
                    np.where(high_vol, buy_signal_raw, buy_signal_confirmed), index=df.index
                ).astype(bool)
                sell_signal = pd.Series(
                    np.where(high_vol, sell_signal_raw, sell_signal_confirmed), index=df.index
                ).astype(bool)
            else:
                # Original path — byte-identical to pre-change behavior when
                # neither bypass is configured.
                buy_signal = buy_signal_confirmed
                sell_signal = sell_signal_confirmed
        else:
            buy_signal = buy_signal_raw
            sell_signal = sell_signal_raw

        # 3. Create a state tracker using np.nan (float) to avoid object dtype warnings
        state = pd.Series(np.nan, index=df.index)

        # 4. Map our signals to 1.0 (True) and 0.0 (False)
        state.loc[buy_signal] = 1.0
        state.loc[sell_signal] = 0.0

        # 5. Calculate initial state as a 1.0 or 0.0
        initial_state_bool = df['Close'].iloc[0] >= lower_bound.iloc[0]
        initial_state_val = 1.0 if initial_state_bool else 0.0

        # 6. Forward fill the numeric state
        raw_signal = state.ffill().fillna(initial_state_val)

        # 7. Shift the signal by 1 day and strictly cast to bool
        df['in_market'] = raw_signal.shift(1).fillna(initial_state_val).astype(bool)

        # 8. Trailing-stop overlay (opt-in). Must run AFTER the vectorized
        # state machine above, not fused into it: the trailing stop's peak
        # tracking depends on when THIS overlay itself last opened a
        # position, which depends on its own prior output — inherently
        # sequential, unlike the band/T+2/bypass logic above.
        if self.trailing_stop_pct:
            df['in_market'] = self._apply_trailing_stop(df)

        return df

class DualSignalAgreement(BaseStrategy):
    """Requires ^NDX and ^GSPC's independent SMA+ATR trend signals to agree
    before flipping state — an alternative to T+2's temporal-persistence
    filter that instead requires cross-signal confirmation. If the two
    signals disagree, or either sits in its own neutral zone, holds the
    prior state (mirrors the existing neutral-zone hold behavior)."""

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

    def _trend_state(self, ticker):
        sig_df = get_cached_signals(ticker, self.sma_window)
        upper = sig_df['SMA'] + sig_df['ATR'] * self.atr_multiplier
        lower = sig_df['SMA'] - sig_df['ATR'] * self.atr_multiplier
        bullish = sig_df['Close'] > upper
        bearish = sig_df['Close'] < lower
        return bullish, bearish

    def _add_indicator_logic(self, df):
        df = df.copy()
        ndx_bull, ndx_bear = self._trend_state("^NDX")
        gspc_bull, gspc_bear = self._trend_state("^GSPC")

        # Align both tickers' independently-computed signals onto this call's
        # date index — ^NDX and ^GSPC don't necessarily share an identical
        # trading calendar. ffill carries the last known state across any
        # gap; fillna(False) covers a leading gap ffill can't fill.
        ndx_bull = ndx_bull.reindex(df.index).ffill().fillna(False)
        ndx_bear = ndx_bear.reindex(df.index).ffill().fillna(False)
        gspc_bull = gspc_bull.reindex(df.index).ffill().fillna(False)
        gspc_bear = gspc_bear.reindex(df.index).ffill().fillna(False)

        buy_signal = ndx_bull & gspc_bull
        sell_signal = ndx_bear & gspc_bear

        if self.t2_confirmation:
            buy_signal = buy_signal.rolling(window=2).min() == 1
            sell_signal = sell_signal.rolling(window=2).min() == 1

        state = pd.Series(np.nan, index=df.index)
        state.loc[buy_signal] = 1.0
        state.loc[sell_signal] = 0.0
        initial_state_val = 1.0 if bool(ndx_bull.iloc[0] and gspc_bull.iloc[0]) else 0.0
        raw_signal = state.ffill().fillna(initial_state_val)
        df['in_market'] = raw_signal.shift(1).fillna(initial_state_val).astype(bool)
        if self.trailing_stop_pct:
            # Preserve the pre-stop dual-signal column so the live status
            # helper can re-walk it; track the stop against ^GSPC (the
            # validated reference), reindexed to this df's calendar.
            df['trend_in_market'] = df['in_market'].copy()
            gspc_close = get_cached_signals("^GSPC")["Close"].reindex(df.index).ffill()
            df['in_market'] = self._apply_trailing_stop(df, price=gspc_close)
        return df

    def get_live_stats(self, monitor_ticker="QQQ", leveraged_ticker="TQQQ", data=None):
        stats = super().get_live_stats(monitor_ticker, leveraged_ticker, data=data)
        # self.df now carries in_market (post-stop) and, when the stop is on,
        # trend_in_market (pre-stop). action in `stats` already reflects the
        # post-stop column, i.e. D's verdict.
        gspc_close = get_cached_signals("^GSPC")["Close"].reindex(self.df.index).ffill()
        stats["trailing_stop"] = self._trailing_stop_status(self.df, price=gspc_close)
        return stats

class VolatilityFilter(BaseStrategy):
    def __init__(self, name="VIX Filter (<25)", vix_threshold=25):
        super().__init__(name)
        self.vix_threshold = vix_threshold

    def _add_indicator_logic(self, df):
        df = df.copy()

        # 1. Generate the signal based on today's closing VIX
        raw_signal = df['VIX'] < self.vix_threshold

        # 2. Shift by 1 day — today's VIX determines tomorrow's exposure.
        #    fillna(False) ensures the first row doesn't flip in on stale NaN.
        shifted = raw_signal.shift(1)
        df['in_market'] = np.where(shifted.isna(), False, shifted).astype(bool)

        return df

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
            # Enhanced path: ATR dead-zone and/or T+2 confirmation requested.
            # Treat "fast above slow (by more than the ATR band, if set)"
            # and "fast below slow (by more than the band)" as independent
            # buy/sell events, each optionally 2-day-confirmed, then
            # forward-fill state — mirrors SMATrendFollowing's pattern and
            # gives symmetric confirmation on both entry and exit (a naive
            # rolling-min on the raw crossover boolean would confirm entry
            # over 2 days but exit after just 1).
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
            # Original path — byte-identical to pre-change behavior when
            # neither knob is set. Do not merge this with the branch above;
            # this exact duplication is what guarantees Tables 1-3's
            # already-published EMA numbers cannot shift.
            raw_signal = fast_ema > slow_ema
            shifted = raw_signal.shift(1)
            df['in_market'] = np.where(shifted.isna(), False, shifted).astype(bool)
        return df

class RSIMeanReversion(BaseStrategy):
    def __init__(self, name="RSI Mean Reversion", rsi_period=14, buy_thresh=30, sell_thresh=70):
        super().__init__(name)
        self.rsi_period = rsi_period
        self.buy_thresh = buy_thresh
        self.sell_thresh = sell_thresh


    def _add_indicator_logic(self, df):
        df = df.copy()

        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/self.rsi_period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/self.rsi_period, adjust=False).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        buy_signal = df['RSI'] < self.buy_thresh
        sell_signal = df['RSI'] > self.sell_thresh

        df['signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, np.nan))
        df['signal'] = df['signal'].ffill().fillna(-1)

        raw_signal = df['signal'] == 1
        shifted = raw_signal.shift(1)
        df['in_market'] = np.where(shifted.isna(), False, shifted).astype(bool)
        return df


class Backtester:
    """The simulation engine handling money, drawdowns, and data ingestion."""
    def __init__(self, base_ticker="^NDX", start_date="1999-01-01", period_years=25,
                 leverage=3, expense_ratio=0.0095, initial_fund=10000, annual_dca=0,
                 apply_tax=False, verbose=True, signal_ticker=None):
        self.base_ticker   = base_ticker
        # signal_ticker: ticker used to generate strategy signals (in_market).
        # If None or same as base_ticker, standard single-ticker mode.
        # If different (e.g. base="^NDX", signal="^GSPC"), the strategy reads
        # ^GSPC price/indicators for signal generation but portfolio returns
        # are computed from ^NDX daily moves — i.e. "trade TQQQ on SP500 signal".
        self.signal_ticker = signal_ticker if signal_ticker else base_ticker
        self.start_dt      = pd.to_datetime(start_date)
        self.end_dt        = self.start_dt + pd.DateOffset(years=period_years)
        self.period_years  = period_years
        self.leverage      = leverage
        self.expense_ratio = expense_ratio
        self.initial_fund  = initial_fund
        self.annual_dca    = annual_dca
        self.apply_tax     = apply_tax
        self.verbose       = verbose

    def run(self, strategy):
        """Executes the provided strategy and returns the results."""
        # 1. Generate signals on the signal ticker (full history for warm-up)
        df = get_cached_signals(self.signal_ticker)
        df, strat_stats = strategy.generate_signals(df)

        # 2. Cross-signal mode: overlay return columns from the tradeable ticker.
        #    in_market stays from signal_ticker; Daily_Return_1x / Open2Close /
        #    Overnight_Return are replaced with base_ticker's actual daily moves.
        if self.signal_ticker != self.base_ticker:
            df_ret = get_cached_signals(self.base_ticker)
            for col in ['Daily_Return_1x', 'Open2Close', 'Overnight_Return']:
                df[col] = df_ret[col]
            # Drop dates where the return ticker has no data (e.g. different
            # listing history between ^GSPC and ^NDX)
            df = df.dropna(subset=['Daily_Return_1x'])

        # 3. Slice for the test period AFTER signals are generated on full history
        df = df[(df.index >= self.start_dt) & (df.index <= self.end_dt)]
        if df.empty:
            return None

        # Reject windows where real data doesn't cover the full requested
        # period (e.g. nominal start_date predates the ticker's actual
        # history). Without this, a window silently truncates instead of
        # being rejected, corrupting rolling-window statistics with
        # shorter, non-comparable periods mixed in as if they were full.
        actual_span_days = (df.index.max() - df.index.min()).days
        requested_span_days = (self.end_dt - self.start_dt).days
        if actual_span_days < requested_span_days * 0.98:
            return None

        # 4. Run the math engine
        results = self._run_portfolio_math(df)

        # 5. Calculate universal trade stats directly from the DataFrame
        trade_stats = self._calculate_trade_stats(df)

        # 6. Combine all results and print
        final_results = {**results, **trade_stats, **strat_stats, "strategy": strategy.name}

        if self.verbose:
            self._print_results(final_results)

        return final_results

    def _calculate_trade_stats(self, df):
        """Calculates trades and cash duration strictly from the in_market column."""
        # Calculate total trades (flips from False to True)
        trades = (df['in_market'] & ~df['in_market'].shift(1, fill_value=False)).sum()

        # Calculate cash periods and durations
        is_cash = ~df['in_market']
        blocks = is_cash.ne(is_cash.shift()).cumsum()
        cash_durations = blocks[is_cash].value_counts()

        total_cash_periods = len(cash_durations)
        avg_cash_hold = cash_durations.mean() if not cash_durations.empty else 0.0

        return {
            "total_trades": int(trades),
            "avg_cash_hold": float(avg_cash_hold),
            "total_cash_periods": int(total_cash_periods)
        }

    def _run_portfolio_math(self, df):
        """
        Core accounting math for TWR, leverage drag, and drawdowns.

        Execution model (next-day open):
        - ENTRY day  (in_market flips False→True): enters at today's open,
          earns Open2Close return at leverage.
        - HOLD days  (in_market stays True):  earns full close-to-close return.
        - EXIT day   (in_market flips True→False): sells at today's open,
          captures overnight gap at leverage; then tax is applied (if enabled).
        - CASH days  (in_market stays False): earns money-market rate (BR×0.8).

        Tax model (when apply_tax=True):
        - On each exit, realised gain = portfolio_value_after_exit - cost_basis
        - Hold duration determines rate: TAX_LONG_TERM_RATE (>365d) or
          TAX_SHORT_TERM_RATE (<=365d).  Only positive gains are taxed.
        - Tax drag is reflected in both final_value AND twr_index (after-tax TWR).

        Performance: all daily returns are pre-vectorised into a NumPy array
        before the loop. The scalar loop only handles state that depends on the
        running portfolio value: DCA injections, tax deductions, drawdown.
        """
        # --- Pre-extract columns to NumPy (eliminates per-row attribute lookups) ---
        n         = len(df)
        dates     = df.index
        in_mkt    = df['in_market'].values.astype(bool)
        br_arr    = df['BR'].values.astype(float)
        ret_arr   = np.nan_to_num(df['Daily_Return_1x'].values.astype(float))
        o2c_arr   = np.nan_to_num(df['Open2Close'].values.astype(float))
        ovn_arr   = np.nan_to_num(df['Overnight_Return'].values.astype(float))
        years_arr = dates.year

        # --- Vectorised transition masks ---
        prev_mkt     = np.empty(n, dtype=bool)
        prev_mkt[0]  = False
        prev_mkt[1:] = in_mkt[:-1]
        entering_mask = in_mkt  & ~prev_mkt   # False→True flip
        exiting_mask  = ~in_mkt & prev_mkt    # True→False flip

        # --- Pre-compute the full daily_return array in one vectorised pass ---
        leverage_drag = (((self.leverage - 1) * br_arr) + self.expense_ratio) / 252
        cash_ret      = (br_arr * 0.8) / 252

        # Default: leveraged close-to-close when in market, cash when out
        daily_ret_arr = np.where(in_mkt,
                                 ret_arr * self.leverage - leverage_drag,
                                 cash_ret)
        # Entry days: only earn open→close (entered at open, missed overnight gap)
        daily_ret_arr[entering_mask] = (o2c_arr[entering_mask] * self.leverage
                                        - leverage_drag[entering_mask])
        # Exit days: sell at open, capture only overnight gap at leverage
        daily_ret_arr[exiting_mask]  = (ovn_arr[exiting_mask] * self.leverage
                                        - leverage_drag[exiting_mask])

        # --- Scalar loop: only handles running-value-dependent state ---
        portfolio_value = self.initial_fund
        total_principal = self.initial_fund
        current_year    = int(years_arr[0])
        peak_value      = self.initial_fund
        min_value       = self.initial_fund
        max_drawdown    = 0.0
        twr_index       = 1.0

        total_tax_paid = 0.0
        trade_log      = []
        entry_idx      = -1       # array index of last entry (-1 = no open position)
        cost_basis_val = 0.0
        portfolio_values = np.empty(n)  # daily equity curve, for drawdown-episode analysis

        for i in range(n):
            # Capture cost basis BEFORE applying today's return (entry day only)
            if entering_mask[i]:
                entry_idx      = i
                cost_basis_val = portfolio_value

            # Apply pre-computed return (fast: array read + multiply, no branches)
            dr              = daily_ret_arr[i]
            portfolio_value *= (1 + dr)
            twr_index       *= (1 + dr)

            # Tax + trade log on exit (fires ~once per trade, not every row)
            if exiting_mask[i] and entry_idx >= 0:
                hold_days     = (dates[i] - dates[entry_idx]).days
                gross_ret_pct = (portfolio_value - cost_basis_val) / cost_basis_val * 100
                trade_record  = {
                    "entry_date"    : dates[entry_idx],
                    "exit_date"     : dates[i],
                    "hold_days"     : hold_days,
                    "gross_ret_pct" : gross_ret_pct,
                    "tax_paid"      : 0.0,
                    "tax_type"      : "",
                }
                if self.apply_tax:
                    gain = portfolio_value - cost_basis_val
                    if gain > 0:
                        rate     = TAX_LONG_TERM_RATE if hold_days > 365 else TAX_SHORT_TERM_RATE
                        tax      = gain * rate
                        total_tax_paid  += tax
                        portfolio_value -= tax
                        twr_index       *= portfolio_value / (portfolio_value + tax)
                        trade_record["tax_paid"] = tax
                        trade_record["tax_type"] = "Long-term" if hold_days > 365 else "Short-term"
                trade_log.append(trade_record)
                entry_idx = -1

            # DCA: inject cash once per year (fires ~once per year, not every row)
            if self.annual_dca > 0 and years_arr[i] > current_year:
                current_year    = int(years_arr[i])
                total_principal += self.annual_dca
                portfolio_value += self.annual_dca

            # Drawdown tracking
            if portfolio_value > peak_value: peak_value = portfolio_value
            if portfolio_value < min_value:  min_value  = portfolio_value
            drawdown = (portfolio_value - peak_value) / peak_value
            if drawdown < max_drawdown: max_drawdown = drawdown

            portfolio_values[i] = portfolio_value

        result = {
            "final_value"    : portfolio_value,
            "total_invested" : total_principal,
            "max_drawdown"   : max_drawdown * 100,
            # Use actual trading days for annualisation — more accurate than
            # configured period_years when data has gaps or partial years.
            "strategy_twr"   : ((twr_index ** (252 / len(df))) - 1) * 100,
            "total_roi"      : ((portfolio_value - total_principal) / total_principal) * 100,
            "min_value"      : min_value,
            "trade_log"      : trade_log,
            # Daily equity curve, for drawdown-episode analysis (peak-to-trough
            # periods) that the single max_drawdown scalar above can't show.
            "equity_curve"   : pd.Series(portfolio_values, index=dates),
        }
        if self.apply_tax:
            result["total_tax_paid"] = total_tax_paid
        return result


    def _print_results(self, res):
        tax_str  = " | Tax-Aware (After-Tax TWR)" if self.apply_tax else ""
        mode_str = f" | DCA: ${self.annual_dca:,.0f}/yr" if self.annual_dca > 0 else " | Lump Sum"
        print(f"--- Running {res['strategy']}: {self.leverage}x {self.base_ticker}{mode_str}{tax_str} ---")

        if self.annual_dca > 0:
            print(f"Total Invested: ${res['total_invested']:,.2f}")
            print(f"Total ROI:      {res['total_roi']:,.2f}%")

        print(f"Final Value:    ${res['final_value']:,.2f}")
        print(f"Lowest Value:   ${res['min_value']:,.2f}")
        print(f"Strategy TWR:   {res['strategy_twr']:,.2f}%" +
              (" (after-tax)" if self.apply_tax else ""))
        print(f"Max Drawdown:   {res['max_drawdown']:.4f}%")

        if self.apply_tax and "total_tax_paid" in res:
            print(f"Tax Paid:       ${res['total_tax_paid']:,.2f}")

        # Print the new universal stats
        print(f"Total Trades:   {res.get('total_trades', 0)}")
        print(f"Avg Cash Hold:  {res.get('avg_cash_hold', 0):.1f} Trading Days | Total Cash Periods: {res.get('total_cash_periods', 0)}")

        # --- Per-trade log ---
        trade_log = res.get("trade_log", [])
        if trade_log:
            print(f"\n  {'#':<4} {'Entry':<12} {'Exit':<12} {'Hold Days':<11} {'Return':>8}  {'Tax Info'}")
            print(f"  {'-'*4} {'-'*11} {'-'*11} {'-'*10} {'-'*8}  {'-'*26}")
            for i, t in enumerate(trade_log, 1):
                tax_info = ""
                if self.apply_tax and t.get("tax_paid", 0) > 0:
                    tax_info = f"{t['tax_type']}, Tax: ${t['tax_paid']:,.0f}"
                print(f"  {i:<4} {str(t['entry_date'])[:10]:<12} {str(t['exit_date'])[:10]:<12} "
                      f"{t['hold_days']:<11} {t['gross_ret_pct']:>+7.1f}%  {tax_info}")

        # Print any remaining custom stats returned by the strategy
        skip_keys = {"strategy", "final_value", "total_invested", "max_drawdown", "strategy_twr",
                     "total_roi", "min_value", "total_trades", "avg_cash_hold", "total_cash_periods",
                     "total_tax_paid", "trade_log"}
        for key, value in res.items():
            if key in skip_keys:
                continue
            formatted_key = key.replace("_", " ").title()
            print(f"{formatted_key}:{' ' * (14 - len(formatted_key))}{value}")
        print("\n")

class RollingBacktester:
    """Orchestrates multiple backtests across a rolling window of start dates."""
    def __init__(self, start_dates, base_ticker="^NDX", period_years=25,
                 leverage=3, expense_ratio=0.0095, initial_fund=10000, annual_dca=0,
                 apply_tax=False, metric_key="strategy_twr", metric_label="TWR",
                 signal_ticker=None):
        self.start_dates   = start_dates
        self.base_ticker   = base_ticker
        self.signal_ticker = signal_ticker if signal_ticker else base_ticker
        self.period_years  = period_years
        self.leverage      = leverage
        self.expense_ratio = expense_ratio
        self.initial_fund  = initial_fund
        self.annual_dca    = annual_dca
        self.apply_tax     = apply_tax
        self.metric_key    = metric_key
        self.metric_label  = metric_label

    def run(self, strategies):
        """
        Executes a list of Strategy objects across all start dates in parallel.
        Returns a formatted DataFrame comparing them.

        Thread safety: both caches are pre-warmed before launching threads so
        all workers only read (no concurrent downloads). Each Backtester and
        each strategy call operates on its own data copy.
        """
        metric_key   = self.metric_key
        metric_label = self.metric_label

        # Pre-warm both caches before parallel workers start
        get_cached_signals(self.signal_ticker)
        if self.signal_ticker != self.base_ticker:
            get_cached_signals(self.base_ticker)

        def _run_single(start_date):
            date_str = start_date.strftime('%Y-%m-%d')
            env = Backtester(
                base_ticker   = self.base_ticker,
                signal_ticker = self.signal_ticker,
                start_date    = date_str,
                period_years  = self.period_years,
                leverage      = self.leverage,
                expense_ratio = self.expense_ratio,
                initial_fund  = self.initial_fund,
                annual_dca    = self.annual_dca,
                apply_tax     = self.apply_tax,
                verbose       = False,
            )
            row_data = {"Start Date": start_date}
            for strat in strategies:
                res = env.run(strat)
                if res is None:
                    return None  # Missing data — skip this date
                row_data[f"{strat.name} {metric_label} (%)"] = res[metric_key]
                row_data[f"{strat.name} Max DD (%)"]          = res["max_drawdown"]
                row_data[f"{strat.name} Total Trades"]        = res.get("total_trades", 0)
            return row_data

        workers = min(8, len(self.start_dates))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures      = [pool.submit(_run_single, d) for d in self.start_dates]
            raw          = [f.result() for f in futures]
            results_list = [r for r in raw if r is not None]

        return pd.DataFrame(results_list)


def run_experiment_suite(
    configs,
    strategies,
    start_dates,
    period_years=26,
    annual_dca=0,
    base_ticker="^NDX",
    signal_ticker=None,
    initial_fund=10000,
    apply_tax=False,
    print_summary=True
):
    """
    Takes a list of leverage configs and strategies, runs them all through
    the RollingBacktester, and optionally prints a statistical summary.
    Returns a dictionary mapping config names to their result DataFrames.
    """
    all_rolling_results = {}

    # 1. Execution Loop
    for config in configs:
        if print_summary:
            print(f"🚀 RUNNING MONTHLY ROLLING BACKTEST: {config['name']}...")

        orchestrator = RollingBacktester(
            start_dates=start_dates,
            base_ticker=base_ticker,
            signal_ticker=signal_ticker,
            period_years=period_years,
            leverage=config['leverage'],
            expense_ratio=config['expense'],
            initial_fund=initial_fund,
            annual_dca=annual_dca,
            apply_tax=apply_tax
        )

        df_result = orchestrator.run(strategies)
        all_rolling_results[config['name']] = df_result

    # 2. Summary Printing
    if print_summary:
        metric_label = "TWR"
        print(f"\n{'='*75}\n📊 SUMMARY STATISTICS ({metric_label} & Drawdowns)\n{'='*75}")

        for config_name, df_res in all_rolling_results.items():
            if df_res.empty:
                print(f"--- {config_name} ---\nNo valid data.\n")
                continue

            print(f"--- {config_name} ---")
            for strat in strategies:
                # Define column headers dynamically
                ret_col = f"{strat.name} {metric_label} (%)"
                dd_col = f"{strat.name} Max DD (%)"
                trades_col = f"{strat.name} Total Trades"

                if ret_col in df_res.columns and dd_col in df_res.columns:
                    avg_val = df_res[ret_col].mean()
                    med_val = df_res[ret_col].median()

                    # Calculate average trades per period
                    avg_trades = df_res[trades_col].mean() if trades_col in df_res.columns else 0

                    worst_ret_idx = df_res[ret_col].idxmin()
                    worst_dd_idx = df_res[dd_col].idxmin()

                    worst_val = df_res.loc[worst_ret_idx, ret_col]
                    worst_dd = df_res.loc[worst_dd_idx, dd_col]

                    worst_ret_date = str(df_res.loc[worst_ret_idx, 'Start Date'])[:10]
                    worst_dd_date = str(df_res.loc[worst_dd_idx, 'Start Date'])[:10]

                    print(f"[{strat.name}]")
                    print(f"  {metric_label:<9} -> Avg: {avg_val:>8.2f}% | Med: {med_val:>8.2f}%")
                    print(f"               Worst: {worst_val:>8.2f}% (Started: {worst_ret_date})")
                    print(f"  Max DD:   {worst_dd:>8.2f}% (Started: {worst_dd_date})")
                    print(f"  Trades:   Avg {avg_trades:.1f} per period\n")

    return all_rolling_results


def warmup_aware_start_dates(tickers, period_years):
    """Generate monthly rolling-window start dates, warmup-aware per ticker.

    The earliest usable start date is the latest of the given tickers'
    real data start dates, plus a 210-calendar-day offset (~200 trading
    days) so the 200-day SMA/EMA indicators are fully warmed up before
    the window begins. `tickers` should include every ticker actually
    used by the backtest (both base and signal ticker for cross-signal
    setups) since the window can't start until *all* of them have data.
    """
    warmup_start = max(get_cached_data(t).index[0] for t in tickers) + pd.DateOffset(days=210)
    end_date = pd.Timestamp.today() - pd.DateOffset(years=period_years)
    return pd.date_range(start=warmup_start, end=end_date, freq=pd.DateOffset(months=1))


def summarize_rolling_results(df_res, strategies, metric_label="TWR"):
    """Summarizes a RollingBacktester result DataFrame into per-strategy stats."""
    rows = []
    for strat in strategies:
        ret_col = f"{strat.name} {metric_label} (%)"
        dd_col = f"{strat.name} Max DD (%)"
        trades_col = f"{strat.name} Total Trades"
        if ret_col not in df_res.columns:
            continue
        rows.append({
            "Strategy": strat.name,
            "Avg TWR": df_res[ret_col].mean(),
            "Med TWR": df_res[ret_col].median(),
            "Worst TWR": df_res[ret_col].min(),
            # Worst DD must be the deepest drawdown observed across ALL windows
            # for this strategy — independent of which window had the worst
            # TWR. Matches this same file's print-summary convention above.
            "Worst DD": df_res[dd_col].min(),
            "Avg Trades": df_res[trades_col].mean(),
        })
    return rows
