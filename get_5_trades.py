import sqlite3
import pandas as pd
import json

def test_5_trades():
    conn = sqlite3.connect("trading_agent.db")
    df = pd.read_sql("SELECT ticker, action, entry_price, stop_loss, take_profit, exit_reason, indicators_json, quantity FROM trades WHERE status='CLOSED' LIMIT 5", conn)
    
    print(f"\n--- 5 SAMPLE TRADES (ATR EXITS & SIZING) ---")
    for idx, row in df.iterrows():
        entry = row['entry_price']
        
        # Calculate ATR based on recorded SL distance and ATR_MULT=1.0 or 1.5 (using 1.0 for the first run)
        sl_dist = abs(entry - row['stop_loss'])
        atr = sl_dist / 1.0 # Assuming grid run 1 is ATR=1.0
        
        fixed_sl = round(entry * 0.98 if row['action'] == 'BUY' else entry * 1.02, 2)
        fixed_tp = round(entry * 1.04 if row['action'] == 'BUY' else entry * 0.96, 2)
        
        print(f"Trade {idx+1}: {row['ticker']} {row['action']} (Qty: {row['quantity']})")
        print(f"  Entry: ${entry:.2f} | Implied ATR14 @ Entry: ${atr:.2f}")
        print(f"  Computed SL: ${row['stop_loss']:.2f} | Computed TP: ${row['take_profit']:.2f}")
        print(f"  (For comparison, Fixed 2% SL would be: ${fixed_sl:.2f}, TP: ${fixed_tp:.2f})")
        print(f"  Label Recorded: {row['exit_reason']}")
        print()

if __name__ == "__main__":
    test_5_trades()
