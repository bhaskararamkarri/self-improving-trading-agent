import sqlite3
import pandas as pd
from rich.console import Console
from rich.table import Table
import os

def run_diagnostics():
    console = Console()
    db_path = os.path.join(os.path.dirname(__file__), "trading_agent.db")
    if not os.path.exists(db_path):
        console.print("[red]No trading_agent.db found.[/red]")
        return
        
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql("SELECT * FROM trades WHERE status='CLOSED'", conn)
    except sqlite3.OperationalError:
        console.print("[red]trades table does not exist yet.[/red]")
        return
    finally:
        conn.close()

    if df.empty:
        console.print("[yellow]No closed trades to analyze.[/yellow]")
        return

    # Calculate risk_dollars and R-multiple
    # If risk_dollars is missing, fallback to capital * 1%
    capital = 10000.0
    risk_dollars_budget = capital * 0.01

    def calc_r_multiple(row):
        return row['pnl_amount'] / risk_dollars_budget

    df['r_multiple'] = df.apply(calc_r_multiple, axis=1)

    total_trades = len(df)
    wins = df[df['pnl_amount'] > 0]
    losses = df[df['pnl_amount'] <= 0]
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    
    avg_win = wins['pnl_amount'].mean() if len(wins) > 0 else 0
    avg_loss = losses['pnl_amount'].mean() if len(losses) > 0 else 0
    expectancy = df['pnl_amount'].mean()
    
    # R-multiple stats
    avg_r_win = wins['r_multiple'].mean() if len(wins) > 0 else 0
    avg_r_loss = losses['r_multiple'].mean() if len(losses) > 0 else 0
    avg_r = df['r_multiple'].mean()

    # Exit reason distribution & R-multiple by exit reason
    exit_reasons = df['exit_reason'].value_counts()
    
    console.print(f"\n[bold cyan]=== TRADE DIAGNOSTICS REPORT ({total_trades} Trades) ===[/bold cyan]")
    
    summary_table = Table(title="Overall Metrics", style="yellow")
    summary_table.add_column("Metric", style="bold white")
    summary_table.add_column("Value", style="cyan")
    
    summary_table.add_row("Overall Win Rate", f"{win_rate*100:.1f}%")
    summary_table.add_row("Average Win", f"${avg_win:.2f} ({avg_r_win:+.2f}R)")
    summary_table.add_row("Average Loss", f"${avg_loss:.2f} ({avg_r_loss:+.2f}R)")
    summary_table.add_row("Expectancy per Trade", f"${expectancy:.2f} ({avg_r:+.2f}R)")
    console.print(summary_table)

    exit_table = Table(title="Exit Reason Distribution & Performance", style="magenta")
    exit_table.add_column("Exit Reason", style="bold white")
    exit_table.add_column("Count", justify="right")
    exit_table.add_column("% of Total", justify="right")
    exit_table.add_column("Avg R-Multiple", justify="right", style="cyan")
    exit_table.add_column("Avg PnL$", justify="right", style="green")

    for reason, count in exit_reasons.items():
        subset = df[df['exit_reason'] == reason]
        pct = (count / total_trades) * 100
        avg_rm = subset['r_multiple'].mean()
        avg_pnl = subset['pnl_amount'].mean()
        exit_table.add_row(
            str(reason),
            str(count),
            f"{pct:.1f}%",
            f"{avg_rm:+.2f}R",
            f"${avg_pnl:+.2f}"
        )
        
    console.print(exit_table)
    
if __name__ == "__main__":
    run_diagnostics()
