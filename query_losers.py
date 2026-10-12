import sqlite3
import pandas as pd

def investigate_risk():
    conn = sqlite3.connect("trading_agent.db")
    df = pd.read_sql("SELECT ticker, action, entry_price, exit_price, quantity, stop_loss, take_profit, pnl_amount, exit_reason FROM trades WHERE status='CLOSED'", conn)
    
    losers = df[df['pnl_amount'] < 0].copy()
    
    # Calculate expected risk_dollars based on entry and SL
    # PnL = (exit - entry) * qty for BUY, (entry - exit) * qty for SHORT
    
    print(f"Total Losers: {len(losers)}")
    print(losers[['ticker', 'action', 'entry_price', 'exit_price', 'stop_loss', 'quantity', 'pnl_amount', 'exit_reason']])
    
if __name__ == "__main__":
    investigate_risk()
