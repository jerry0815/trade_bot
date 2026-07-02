import yfinance as yf
import pandas as pd
import numpy as np

# Global Caches
DATA_CACHE = {}
SIGNAL_CACHE = {}

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

class BaseStrategy:
    def __init__(self, name):
        self.name = name
        self.df = None

    def generate_signals(self, df):
        df = self._add_indicator_logic(df)
        if 'in_market' not in df.columns:
            raise ValueError(f"Strategy '{self.name}' failed to create 'in_market' column.")

        entries = (df['in_market'] == True) & (df['in_market'].shift(1) == False)
        exits = (df['in_market'] == False) & (df['in_market'].shift(1) == True)

        strat_stats = {
            "total_trades": int(entries.sum()),
        }
        return df, strat_stats

    def _add_indicator_logic(self, df):
        raise NotImplementedError("Child strategies must implement _add_indicator_logic()")

    def get_live_stats(self, monitor_ticker="QQQ", leveraged_ticker="TQQQ"):
        # 1. Fetch data
        df = yf.download(monitor_ticker, period="5y", progress=False, auto_adjust=False)
        tqqq = yf.download(leveraged_ticker, period="5y", progress=False, auto_adjust=False)
        vix = yf.download("^VIX", period="5y", progress=False, auto_adjust=False)
        
        for data in [df, tqqq, vix]:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

        # 2. Process data
        self.df = prep_base_indicators(df, vix['Close'])
        self.df = self._add_indicator_logic(self.df)
        
        # 3. Return the base report stats
        return {
            "qqq_price": float(self.df['Close'].iloc[-1].item()),
            "tqqq_price": float(tqqq['Close'].iloc[-1]),
            "action": "BUY/HOLD" if bool(self.df['in_market'].iloc[-1]) else "SELL/CASH"
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

    def get_live_stats(self, monitor_ticker="QQQ", leveraged_ticker="TQQQ"):
        # 1. Get the base data
        stats = super().get_live_stats(monitor_ticker, leveraged_ticker)
        
        # 2. Extract values as scalars
        price = float(self.df['Close'].iloc[-1])
        sma = float(self.df['SMA'].iloc[-1])
        
        # 3. Calculate dynamic bands based on your existing logic
        # (This assumes you have ATR in your df, or a fixed buffer_pct)
        if self.buffer_pct:
            upper_bound = sma * (1 + self.buffer_pct)
            lower_bound = sma * (1 - self.buffer_pct)
        else:
            upper_bound = sma + (float(self.df['ATR'].iloc[-1]) * self.atr_multiplier)
            lower_bound = sma - (float(self.df['ATR'].iloc[-1]) * self.atr_multiplier)
            
        # 4. Determine trend
        if price > upper_bound:
            trend = "BULLISH"
        elif price < lower_bound:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL" # Price is within the bands
        
        stats.update({
            "current_sma": sma,
            "trend": trend
        })
        
        return stats

    def _add_indicator_logic(self, df):
        """
        Overrides the hidden parent logic. Focuses strictly on creating the
        'in_market' column using specialized buffer-band logic.
        Vectorized for performance.
        """
        df = df.copy()

        # df['SMA'] = df['Close'].rolling(window=self.sma_window).mean()
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

        # 2. Shift the signal by 1 day!
        # Today's VIX determines tomorrow's market exposure.
        df['in_market'] = raw_signal.shift(1) == True

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
        df['in_market'] = raw_signal.shift(1) == True
        return df

class RSIMeanReversion(BaseStrategy):
    def __init__(self, name="RSI Mean Reversion", rsi_period=14, buy_thresh=30, sell_thresh=70):
        super().__init__(name)
        self.rsi_period = rsi_period
        self.buy_thresh = buy_thresh
        self.sell_thresh = sell_thresh

    def get_report_fields(self, df):
        fields = super().get_report_fields(df)
        fields["RSI Value"] = f"{df['RSI'].iloc[-1]:.2f}"
        return fields

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
        df['in_market'] = raw_signal.shift(1) == True
        return df


class Backtester:
    """The simulation engine handling money, drawdowns, and data ingestion."""
    def __init__(self, base_ticker="^NDX", start_date="1999-01-01", period_years=25,
                 leverage=3, expense_ratio=0.0095, initial_fund=10000, annual_dca=0, verbose=True):
        self.base_ticker = base_ticker
        self.start_dt = pd.to_datetime(start_date)
        self.end_dt = self.start_dt + pd.DateOffset(years=period_years)
        self.period_years = period_years
        self.leverage = leverage
        self.expense_ratio = expense_ratio
        self.initial_fund = initial_fund
        self.annual_dca = annual_dca
        self.verbose = verbose

    def _get_data(self):
        # Assumes get_cached_signals exists in your global scope
        df = get_cached_signals(self.base_ticker)
        df = df[(df.index >= self.start_dt) & (df.index <= self.end_dt)]
        return df

    def run(self, strategy):
        """Executes the provided strategy and returns the results."""
        df = get_cached_signals(self.base_ticker)

        # 1. Ask the strategy to label the data on the FULL dataset
        df, strat_stats = strategy.generate_signals(df)

        # 2. Slice the dataframe for the test period AFTER signals are generated
        df = df[(df.index >= self.start_dt) & (df.index <= self.end_dt)]

        # 2. Run the math engine
        results = self._run_portfolio_math(df)

        # 3. Calculate universal trade stats directly from the DataFrame
        trade_stats = self._calculate_trade_stats(df)

        # 4. Combine and print (strip old cash_log if strategy still passes it)
        final_results = {**results, **trade_stats, **strat_stats, "strategy": strategy.name}
        if "cash_log" in final_results:
            del final_results["cash_log"]

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
        """Core accounting math for TWR, leverage drag, and drawdowns."""
        portfolio_value = self.initial_fund
        total_principal = self.initial_fund
        current_year = df.index[0].year

        peak_value, min_value = self.initial_fund, self.initial_fund
        max_drawdown, twr_index = 0.0, 1.0

        for row in df.itertuples():
            daily_ret_1x, br = float(row.Daily_Return_1x), float(row.BR)
            if pd.isna(daily_ret_1x): continue

            # Evaluate return based on strategy signal
            if row.in_market:
                daily_drag = (((self.leverage - 1) * br) + self.expense_ratio) / 252
                daily_return = (daily_ret_1x * self.leverage) - daily_drag
            else:
                daily_return = (br * 0.8) / 252

            portfolio_value *= (1 + daily_return)
            twr_index *= (1 + daily_return)

            # DCA Logic
            if self.annual_dca > 0 and row.Index.year > current_year:
                current_year = row.Index.year
                total_principal += self.annual_dca
                portfolio_value += self.annual_dca

            # Drawdowns
            if portfolio_value > peak_value: peak_value = portfolio_value
            if portfolio_value < min_value: min_value = portfolio_value

            drawdown = (portfolio_value - peak_value) / peak_value
            if drawdown < max_drawdown: max_drawdown = drawdown

        return {
            "final_value": portfolio_value,
            "total_invested": total_principal,
            "max_drawdown": max_drawdown * 100,
            "strategy_twr": ((twr_index ** (1 / self.period_years)) - 1) * 100,
            "total_roi": ((portfolio_value - total_principal) / total_principal) * 100,
            "min_value": min_value
        }

    def _print_results(self, res):
        mode_str = f" | DCA: ${self.annual_dca:,.0f}/yr" if self.annual_dca > 0 else " | Lump Sum"
        print(f"--- Running {res['strategy']}: {self.leverage}x {self.base_ticker}{mode_str} ---")

        if self.annual_dca > 0:
            print(f"Total Invested: ${res['total_invested']:,.2f}")
            print(f"Total ROI:      {res['total_roi']:,.2f}%")

        print(f"Final Value:    ${res['final_value']:,.2f}")
        print(f"Lowest Value:   ${res['min_value']:,.2f}")
        print(f"Strategy TWR:   {res['strategy_twr']:,.2f}%")
        print(f"Max Drawdown:   {res['max_drawdown']:.4f}%")

        # Print the new universal stats
        print(f"Total Trades:   {res.get('total_trades', 0)}")
        print(f"Avg Cash Hold:  {res.get('avg_cash_hold', 0):.1f} Trading Days | Total Cash Periods: {res.get('total_cash_periods', 0)}")

        # Print any remaining custom stats returned by the strategy
        skip_keys = {"strategy", "final_value", "total_invested", "max_drawdown", "strategy_twr", "total_roi", "min_value", "total_trades", "avg_cash_hold", "total_cash_periods"}
        for key, value in res.items():
            if key in skip_keys:
                continue
            formatted_key = key.replace("_", " ").title()
            print(f"{formatted_key}:{' ' * (14 - len(formatted_key))}{value}")
        print("\n")

class RollingBacktester:
    """Orchestrates multiple backtests across a rolling window of start dates."""
    def __init__(self, start_dates, base_ticker="^NDX", period_years=25,
                 leverage=3, expense_ratio=0.0095, initial_fund=10000, annual_dca=0):
        self.start_dates = start_dates
        self.base_ticker = base_ticker
        self.period_years = period_years
        self.leverage = leverage
        self.expense_ratio = expense_ratio
        self.initial_fund = initial_fund
        self.annual_dca = annual_dca

    def run(self, strategies):
        """
        Executes a list of Strategy objects across all start dates.
        Returns a formatted DataFrame comparing them.
        """
        results_list = []
        metric_key = "strategy_twr"
        metric_label = "TWR"

        for start_date in self.start_dates:
            date_str = start_date.strftime('%Y-%m-%d')

            # Spin up a silent environment for this specific start date
            env = Backtester(
                base_ticker=self.base_ticker,
                start_date=date_str,
                period_years=self.period_years,
                leverage=self.leverage,
                expense_ratio=self.expense_ratio,
                initial_fund=self.initial_fund,
                annual_dca=self.annual_dca,
                verbose=False
            )

            # Dictionary to hold this row's results
            row_data = {"Start Date": start_date}
            valid_run = True

            # Test every strategy passed in
            for strat in strategies:
                res = env.run(strat)
                if res is None:
                    valid_run = False
                    break  # Skip this date entirely if data is missing

                # Dynamically use the strategy's name for the column headers
                row_data[f"{strat.name} {metric_label} (%)"] = res[metric_key]
                row_data[f"{strat.name} Max DD (%)"] = res["max_drawdown"]
                # RECORD TOTAL TRADES HERE
                row_data[f"{strat.name} Total Trades"] = res.get("total_trades", 0)

            if valid_run:
                results_list.append(row_data)

        return pd.DataFrame(results_list)


def run_experiment_suite(
    configs,
    strategies,
    start_dates,
    period_years=26,
    annual_dca=0,
    base_ticker="^NDX",
    initial_fund=10000,
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
            period_years=period_years,
            leverage=config['leverage'],
            expense_ratio=config['expense'],
            initial_fund=initial_fund,
            annual_dca=annual_dca
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
