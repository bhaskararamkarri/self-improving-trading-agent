import sqlite3
import pandas as pd
import subprocess
import re
from rich.console import Console
from rich.table import Table

console = Console()

def set_config(atr_mult: float, trend_filter: bool):
    with open("config.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    content = re.sub(r'SL_ATR_MULT: float = .*', f'SL_ATR_MULT: float = float(os.getenv("SL_ATR_MULT", "{atr_mult}"))', content)
    content = re.sub(r'TREND_FILTER: bool = .*', f'TREND_FILTER: bool = os.getenv("TREND_FILTER", "{"true" if trend_filter else "false"}").lower() == "true"', content)
    
    with open("config.py", "w", encoding="utf-8") as f:
        f.write(content)

def run_backtest_and_get_stats(atr_mult: float, trend_filter: bool):
    console.print(f"[cyan]Running backtest for SL_ATR_MULT={atr_mult}, TREND_FILTER={trend_filter}...[/cyan]")
    # Run backtest
    result = subprocess.run(["python", "main.py", "--backtest"], capture_output=True, text=True, encoding='utf-8')
    
    # Query DB for stats
    conn = sqlite3.connect("trading_agent.db")
    df = pd.read_sql("SELECT * FROM trades WHERE status='CLOSED' ORDER BY exit_timestamp", conn)
    conn.close()
    
    if df.empty:
        return {"trades": 0, "wr": "0%", "avg_r": 0.0, "expectancy": 0.0, "max_dd": "0%", "total_pnl": 0.0, "output": result.stdout}
        
    capital = 10000.0
    risk_dollars_budget = capital * 0.01
    
    total_trades = len(df)
    wins = df[df['pnl_amount'] > 0]
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    
    df['r_multiple'] = df['pnl_amount'] / risk_dollars_budget
    avg_r = df['r_multiple'].mean()
    expectancy = df['pnl_amount'].mean()
    total_pnl = df['pnl_amount'].sum()
    
    # Max DD proxy
    df['cumulative_pnl'] = df['pnl_amount'].cumsum()
    df['equity'] = capital + df['cumulative_pnl']
    df['peak'] = df['equity'].cummax()
    df['drawdown'] = (df['equity'] - df['peak']) / df['peak']
    max_dd = abs(df['drawdown'].min()) * 100
    
    return {
        "trades": total_trades,
        "wr": f"{win_rate*100:.1f}%",
        "avg_r": f"{avg_r:+.2f}R",
        "expectancy": f"${expectancy:.2f}",
        "max_dd": f"{max_dd:.2f}%",
        "total_pnl": f"${total_pnl:.2f}",
        "output": result.stdout
    }

def main():
    combos = [
        (1.0, False),
        (1.5, False),
        (1.0, True),
        (1.5, True)
    ]
    
    results = []
    
    for atr, trend in combos:
        set_config(atr, trend)
        stats = run_backtest_and_get_stats(atr, trend)
        stats['combo'] = f"ATR={atr}, TREND={trend}"
        stats['atr'] = atr
        stats['trend'] = trend
        results.append(stats)
        
    # Print Table
    table = Table(title="=== PART 3: Trend Filter + Parameter Grid Backtest ===", style="bold cyan")
    table.add_column("Combo", style="white")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Avg R", justify="right")
    table.add_column("Expectancy$", justify="right")
    table.add_column("Max DD%", justify="right", style="red")
    table.add_column("Total PnL$", justify="right", style="green")
    
    for r in results:
        table.add_row(
            r['combo'],
            str(r['trades']),
            r['wr'],
            r['avg_r'],
            r['expectancy'],
            r['max_dd'],
            r['total_pnl']
        )
        
    console.print(table)
    
    # Determine best combo based on Total PnL (or a mix)
    best = sorted(results, key=lambda x: float(x['total_pnl'].replace('$', '')), reverse=True)[0]
    console.print(f"\n[bold green]BEST COMBO IDENTIFIED: {best['combo']} with {best['total_pnl']} PnL[/bold green]")
    
    # Walk-forward for best combo is just the output from that run!
    console.print(f"\n[bold magenta]=== Walk-Forward Validation (Best Combo) ===[/bold magenta]")
    wf_match = re.search(r'(b\)\s*Walk-Forward Validation: Fold 1/2/3 Out-of-Sample Win Rates.*?)(?=\(c\)\s*Overall)', best['output'], re.DOTALL)
    if wf_match:
        try:
            print(wf_match.group(1))
        except UnicodeEncodeError:
            with open("wf_best.txt", "w", encoding="utf-8") as f:
                f.write(wf_match.group(1))
            print("Walk-forward table saved to wf_best.txt due to encoding issues in terminal.")

if __name__ == "__main__":
    main()
