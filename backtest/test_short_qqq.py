# backtest/test_short_qqq.py
import pandas as pd
import numpy as np
from strat_backtest import Backtester

def test_inverse_leverage_init():
    bt = Backtester(initial_fund=10000, leverage=3)
    # Should default to 0.0
    assert not hasattr(bt, 'inverse_leverage') or getattr(bt, 'inverse_leverage') == 0.0
    
    bt_short = Backtester(initial_fund=10000, leverage=3, inverse_leverage=-1.0)
    assert getattr(bt_short, 'inverse_leverage') == -1.0
    print("test_inverse_leverage_init PASSED")

if __name__ == "__main__":
    test_inverse_leverage_init()
