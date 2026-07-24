# Short QQQ Strategy Design

## Overview
The goal is to modify the existing strategy backtesting engine to support taking a short position (e.g., -1x or -3x inverse leverage) when the strategy triggers a "sell" signal, instead of moving to cash or a defensive proxy.

## Architecture & Components

### 1. `Backtester` Initialization
- **New Parameter**: `inverse_leverage` (float, default `0.0`).
- **Behavior**:
  - `0.0`: The engine continues to operate exactly as it does currently (moves to cash or defensive proxy during sell signals).
  - `< 0.0` (e.g., `-1.0` for 1x short, `-3.0` for 3x short): The engine will calculate returns based on shorting the asset during "sell" signals.

### 2. Math Engine Updates (`_run_portfolio_math`)
The vectorized transition masks and return arrays will be updated to correctly model exact daily compounding on transition days.

- **Short Drag Calculation**:
  - Drag for short positions will be calculated similarly to long positions, but taking the absolute value of the inverse leverage into account for borrowing costs.
  - `inverse_leverage_drag = (((abs(self.inverse_leverage) - 1) * br_arr) + self.expense_ratio) / 252`

- **Hold Days (Short)**:
  - When `in_market` is False and `inverse_leverage` is set, the daily return will be `(ret_arr * self.inverse_leverage) - inverse_leverage_drag`.

- **Transition Day Exact Compounding**:
  - **ENTRY Day** (Flipping from Short to Long): We exit the short position at the open, and enter the long position at the open.
    - `short_overnight = (ovn_arr * self.inverse_leverage) - inverse_leverage_drag`
    - `long_open2close = (o2c_arr * self.leverage) - leverage_drag`
    - `daily_ret_arr[entering_mask] = (1 + short_overnight) * (1 + long_open2close) - 1`
  - **EXIT Day** (Flipping from Long to Short): We exit the long position at the open, and enter the short position at the open.
    - `long_overnight = (ovn_arr * self.leverage) - leverage_drag`
    - `short_open2close = (o2c_arr * self.inverse_leverage) - inverse_leverage_drag`
    - `daily_ret_arr[exiting_mask] = (1 + long_overnight) * (1 + short_open2close) - 1`

### 3. `RollingBacktester` Updates
- Pass the `inverse_leverage` parameter through `RollingBacktester`'s initialization down to the individual `Backtester` instances.

### 4. Backwards Compatibility
- If `inverse_leverage` is left at its default `0.0`, the system will use the existing cash/defensive proxy logic without any changes to historical test results.

## Out of Scope
- Separate attribution of Long vs. Short trades in the `trade_log`. The log will simply treat the period between an Entry and Exit as a "trade" (which currently aligns with being in the Long state), while the Short state will just be reflected in the overall `portfolio_value` and `strategy_twr`. If detailed short-trade attribution is needed, it will be added in a future update.
