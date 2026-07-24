import numpy as np
import pandas as pd
from strat_backtest import Backtester, RollingBacktester

def test_inverse_leverage_init():
    bt = Backtester(initial_fund=10000, leverage=3)
    # Should default to 0.0
    assert bt.inverse_leverage == 0.0
    
    bt_short = Backtester(initial_fund=10000, leverage=3, inverse_leverage=-1.0)
    assert bt_short.inverse_leverage == -1.0
    print("test_inverse_leverage_init PASSED")

def test_short_math():
    # Construct a dummy dataframe for testing exact compounding
    dates = pd.date_range("2020-01-01", periods=4)
    # Day 0: Long (ret=1%)
    # Day 1: Exit Long at open, enter Short at open. (overnight long = 0.5%, open2close short = -1%)
    # Day 2: Short (ret=-2%)
    # Day 3: Exit Short at open, enter Long at open. (overnight short = -0.5%, open2close long = 2%)
    
    df = pd.DataFrame({
        'in_market': [True, False, False, True],
        'BR': [0.0, 0.0, 0.0, 0.0],
        'Daily_Return_1x': [0.01, -0.01, -0.02, 0.02],
        'Open2Close': [0.01, -0.01, -0.02, 0.02],
        'Overnight_Return': [0.0, 0.005, 0.0, -0.005]
    }, index=dates)
    
    bt = Backtester(leverage=1, inverse_leverage=-1, expense_ratio=0.0)
    res = bt._run_portfolio_math(df)
    
    expected_final = 10000.0 * 1.01 * 1.01505 * 1.02 * 1.0251
    assert np.isclose(res['final_value'], expected_final), f"Expected {expected_final}, got {res['final_value']}"
    print("test_short_math PASSED")

def test_default_cash_math():
    dates = pd.date_range("2020-01-01", periods=4)
    df = pd.DataFrame({
        'in_market': [True, False, False, True],
        'BR': [0.0, 0.0, 0.0, 0.0],
        'Daily_Return_1x': [0.01, -0.01, -0.02, 0.02],
        'Open2Close': [0.01, -0.01, -0.02, 0.02],
        'Overnight_Return': [0.0, 0.005, 0.0, -0.005]
    }, index=dates)
    
    bt = Backtester(leverage=1, inverse_leverage=0.0, expense_ratio=0.0)
    res = bt._run_portfolio_math(df)
    
    expected_final = 10000.0 * 1.01 * 1.005 * 1.0 * 1.02
    assert np.isclose(res['final_value'], expected_final), f"Expected {expected_final}, got {res['final_value']}"
    print("test_default_cash_math PASSED")

def test_rolling_inverse():
    rbt = RollingBacktester(start_dates=[], inverse_leverage=-1.0)
    assert getattr(rbt, 'inverse_leverage') == -1.0
    print("test_rolling_inverse PASSED")

def test_current_defensive_rotation():
    from strat_backtest import get_current_defensive_rotation
    
    # Create a mock multi-index dataframe as returned by yfinance
    # 127 days so we have exactly 126 days of momentum (iloc[-1] / iloc[-127] -> wait, it's iloc[-1] / iloc[-126] - 1)
    dates = pd.date_range("2023-01-01", periods=130)
    
    # GLD goes up 20%
    gld_prices = np.linspace(100, 120, 130)
    # TLT goes down 10%
    tlt_prices = np.linspace(100, 90, 130)
    
    # Construct MultiIndex
    columns = pd.MultiIndex.from_tuples([('Close', 'GLD'), ('Close', 'TLT'), ('Close', 'KMLM'), ('Close', 'SHY')])
    data = pd.DataFrame(index=dates, columns=columns)
    
    data[('Close', 'GLD')] = gld_prices
    data[('Close', 'TLT')] = tlt_prices
    data[('Close', 'KMLM')] = np.nan # KMLM missing data
    data[('Close', 'SHY')] = 100.0 # SHY flat
    
    res = get_current_defensive_rotation(data)
    
    assert res['winner'] == 'GLD'
    assert res['momentums']['GLD'] > 0.15 # Approx 20% over 130 days, 126 days should be ~19%
    assert res['momentums']['TLT'] < -0.05
    assert res['momentums']['KMLM'] == 0.0
    assert res['momentums']['SHY'] == 0.0
    
    print("test_current_defensive_rotation PASSED")

if __name__ == "__main__":
    test_inverse_leverage_init()
    test_short_math()
    test_default_cash_math()
    test_rolling_inverse()
    test_current_defensive_rotation()



