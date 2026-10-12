import os
import subprocess
import sqlite3
import pandas as pd

def run_grid():
    with open("config.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    thresholds = [3, 4]
    
    results = []
    
    for thresh in thresholds:
        print(f"Running backtest for CONFLUENCE_THRESHOLD={thresh}...")
        
        import re
        content = re.sub(r'CONFLUENCE_THRESHOLD: int = .*', f'CONFLUENCE_THRESHOLD: int = {thresh}', content)
        
        with open("config.py", "w", encoding="utf-8") as f:
            f.write(content)
            
        subprocess.run(["python", "main.py", "--backtest"])
        
        conn = sqlite3.connect("trading_agent.db")
        df = pd.read_sql("SELECT * FROM trades", conn)
        
        if len(df) == 0:
            results.append((thresh, 0, 0.0, 0.0, 0.0, 0.0, 0.0))
            continue
            
        trades_count = len(df)
        wins = len(df[df['pnl_amount'] > 0])
        wr = wins / trades_count if trades_count > 0 else 0
        total_pnl = df['pnl_amount'].sum()
        
        # Calculate R-multiples (Assuming 1% risk of $10,000 = $100 budget per trade)
        df['r_multiple'] = df['pnl_amount'] / 100.0
        avg_r = df['r_multiple'].mean()
        expectancy = total_pnl / trades_count if trades_count > 0 else 0
        
        results.append((thresh, trades_count, wr, avg_r, expectancy, 0.0, total_pnl))
        
        # Breakdown by ticker
        for ticker in df['ticker'].unique():
            ticker_df = df[df['ticker'] == ticker]
            ticker_trades = len(ticker_df)
            ticker_wins = len(ticker_df[ticker_df['pnl_amount'] > 0])
            ticker_wr = ticker_wins / ticker_trades if ticker_trades > 0 else 0
            ticker_pnl = ticker_df['pnl_amount'].sum()
            ticker_exp = ticker_pnl / ticker_trades if ticker_trades > 0 else 0
            print(f"Thresh {thresh} | Ticker {ticker} | Trades: {ticker_trades} | WR: {ticker_wr*100:.1f}% | Exp: ${ticker_exp:.2f}")

        conn.close()
        
    print("\\n            === PART 1: Confluence Engine Grid ===             ")
    print("+-----------------------------------------------------------------+")
    print("| Thresh | Trades | Win Rate |  Avg R | Expectancy | Total PnL$ |")
    print("|--------+--------+----------+--------+------------+------------|")
    for r in results:
        thresh, trades, wr, avg_r, exp, dd, pnl = r
        print(f"|    {thresh}   |     {trades:2d} |    {wr*100:5.1f}% | {avg_r:+.2f}R |     ${exp:+.2f} |   ${pnl:+.2f} |")
    print("+-----------------------------------------------------------------+")

if __name__ == "__main__":
    run_grid()
