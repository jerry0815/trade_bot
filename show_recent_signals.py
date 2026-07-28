import pandas as pd
import numpy as np
from backtest.strat_backtest import SMATrendFollowing, get_cached_data

def show_recent_holdings():
    # 1. Get Base Signal (QQQ / ^NDX)
    strat = SMATrendFollowing(sma_window=200, t2_confirmation=True)
    base_df = get_cached_data("^NDX").copy()
    
    base_df['High_Low'] = base_df['High'] - base_df['Low']
    base_df['High_Close'] = np.abs(base_df['High'] - base_df['Close'].shift())
    base_df['Low_Close'] = np.abs(base_df['Low'] - base_df['Close'].shift())
    base_df['True_Range'] = base_df[['High_Low', 'High_Close', 'Low_Close']].max(axis=1)
    
    # Calculate the signal series directly using the strategy
    sig_df = strat.generate_signals(base_df)[0]
    
    # 2. Get Defensive Rotation Winners
    tickers = ["KMLM", "RYMTX", "TLT", "VUSTX", "GLD", "SHY"]
    for t in tickers:
        get_cached_data(t)
    
    prices = pd.DataFrame(index=base_df.index)
    for t in tickers:
        df = get_cached_data(t)
        if not df.empty:
            prices[t] = df['Close']
        else:
            prices[t] = np.nan
            
    # Combine histories
    kmlm = prices['KMLM'].fillna(prices['RYMTX'])
    tlt = prices['TLT'].fillna(prices['VUSTX'])
    gld = prices['GLD']
    shy = prices['SHY'] # Cash fallback
    
    # 6-month momentum (approx 126 days)
    mom_df = pd.DataFrame({
        'KMLM': kmlm.pct_change(126), 
        'TLT': tlt.pct_change(126), 
        'GLD': gld.pct_change(126), 
        'SHY': shy.pct_change(126)
    })
    
    # Pick the one with the highest momentum, shift by 1 to prevent lookahead
    best_asset = mom_df.idxmax(axis=1).shift(1).fillna('SHY')
    
    # 3. Combine to find what we held each day
    results = pd.DataFrame(index=base_df.index)
    
    # We use in_market from the strategy output
    # True = Long, False = Defensive
    results['in_market'] = sig_df['in_market']
    
    results['Defensive_Winner'] = best_asset
    
    # Filter to entire history
    recent = results.copy()
    
    # Find periods where Position == -1
    # We want to print contiguous blocks of holding the same asset
    current_holding = None
    start_date = None
    
    print("=== Portfolio Holdings (1999 - Present) ===")
    
    for date, row in recent.iterrows():
        # What are we holding today?
        if row['in_market']:
            holding = "TQQQ (Long Equities)"
        else:
            holding = f"DEFENSIVE -> {row['Defensive_Winner']}"
            
        if holding != current_holding:
            if current_holding is not None:
                # Print the completed block
                end_date = date - pd.Timedelta(days=1)
                # handle if end_date isn't in index, just use string repr
                print(f"{start_date.strftime('%Y-%m-%d')} to {date.strftime('%Y-%m-%d')} : Held {current_holding}")
            current_holding = holding
            start_date = date
            
    if current_holding is not None:
        print(f"{start_date.strftime('%Y-%m-%d')} to PRESENT     : Held {current_holding}")

if __name__ == "__main__":
    show_recent_holdings()
