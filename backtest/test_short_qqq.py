import numpy as np
import pandas as pd
from strat_backtest import Backtester

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

if __name__ == "__main__":
    test_inverse_leverage_init()
    test_short_math()
    test_default_cash_math()


