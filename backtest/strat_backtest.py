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
        data = yf.download(tickers, period=period, progress=False, auto_adjust=False)
        if not data.empty:
            return data
        if attempt < max_retries:
            print(
                f"[yf.download] Empty response for '{tickers}' "
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

class BuyAndHold(BaseStrategy):
    def __init__(self):
        super().__init__(name="Buy & Hold")

    def _add_indicator_logic(self, df):
        df = df.copy()
        df['in_market'] = True
        return df

class SMATrendFollowing(BaseStrategy):
    def __init__(self, sma_window=200, buffer_pct=None, atr_multiplier=2.5):
        # We handle naming and initialization cleanly
        name = f"SMA {sma_window} - " + (f"Static {buffer_pct*100}% Buffer" if buffer_pct else f"ATR Buffer (x{atr_multiplier})")
        super().__init__(name=name)
        self.sma_window = sma_window
        self.buffer_pct = buffer_pct
        self.atr_multiplier = atr_multiplier

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
                return "BULLISH", sma
            elif price < lower_bound:
                return "BEARISH", sma
            return "NEUTRAL", sma

        current_trend, current_sma = _get_trend_for_day(-1)
        previous_trend, _ = _get_trend_for_day(-2)
        
        stats.update({
            "current_sma": current_sma,
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
        buy_signal = df['Close'] > upper_bound
        sell_signal = df['Close'] < lower_bound

        # # --- THE 3-DAY CONFIRMATION RULE ---
        # buy_signal = buy_signal.rolling(window=3).min() == 1
        # sell_signal = sell_signal.rolling(window=3).min() == 1

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

        return df

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
    def __init__(self, name="EMA 50/200 Cross", fast_period=50, slow_period=200):
        super().__init__(name)
        self.fast = fast_period
        self.slow = slow_period

    def _add_indicator_logic(self, df):
        df = df.copy()

        fast_ema = df['Close'].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df['Close'].ewm(span=self.slow, adjust=False).mean()

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
