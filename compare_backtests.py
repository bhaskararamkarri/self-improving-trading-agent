import subprocess
import re
from rich.console import Console
from rich.table import Table

console = Console()

def set_config(use_atr: bool, lesson_mode: str):
    with open("config.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # Replace USE_ATR_STOPS
    content = re.sub(r'USE_ATR_STOPS: bool = .*', f'USE_ATR_STOPS: bool = {"True" if use_atr else "False"}', content)
    # Replace LESSON_MODE
    content = re.sub(r'LESSON_MODE: str = os\.getenv\("LESSON_MODE", ".*"\)', f'LESSON_MODE: str = os.getenv("LESSON_MODE", "{lesson_mode}")', content)
    
    with open("config.py", "w", encoding="utf-8") as f:
        f.write(content)
        
def run_backtest(label):
    console.print(f"[cyan]Running backtest for {label}...[/cyan]")
    # Run backtest, suppressing heavy output but capturing the final table somehow, or just parsing standard output
    result = subprocess.run(["python", "main.py", "--backtest"], capture_output=True, text=True, encoding='utf-8')
    
    # Extract stats from output
    output = result.stdout
    stats = {}
    
    # Simple regex parsing from the overall summary table
    total_trades_m = re.search(r'Total Executed Trades \(Half-Split\)\s*│\s*(\d+)', output)
    stats['total_trades'] = total_trades_m.group(1) if total_trades_m else "N/A"
    
    wr_m = re.search(r'Overall Half-Split Win Rate \(%\)\s*│\s*([0-9.]+% .*)', output)
    stats['win_rate'] = wr_m.group(1) if wr_m else "N/A"
    
    # Expectancy is not in the default summary, I'll calculate it from WR and avg PnL if needed, but wait!
    # "Compare metrics: total trades, WR, avg win/loss, EXPECTANCY, max drawdown, total PnL."
    # Since I just ran analyze_trades.py previously, I can also run it!
    # analyze_trades reads from trading_agent.db! main.py populates trading_agent.db now!
    stats['output'] = output
    return stats

def run_analysis():
    result = subprocess.run(["python", "analyze_trades.py"], capture_output=True, text=True, encoding='utf-8')
    output = result.stdout
    stats = {}
    
    tr_m = re.search(r'TRADE DIAGNOSTICS REPORT \((\d+) Trades\)', output)
    stats['total_trades'] = tr_m.group(1) if tr_m else "N/A"
    
    wr_m = re.search(r'Overall Win Rate\s*\|\s*([0-9.]+%)', output)
    stats['win_rate'] = wr_m.group(1) if wr_m else "N/A"
    
    aw_m = re.search(r'Average Win\s*\|\s*\$([0-9.-]+)', output)
    stats['avg_win'] = aw_m.group(1) if aw_m else "N/A"
    
    al_m = re.search(r'Average Loss\s*\|\s*\$([0-9.-]+)', output)
    stats['avg_loss'] = al_m.group(1) if al_m else "N/A"
    
    ex_m = re.search(r'Expectancy per Trade\s*\|\s*\$([0-9.-]+)', output)
    stats['expectancy'] = ex_m.group(1) if ex_m else "N/A"
    
    md_m = re.search(r'Max Consecutive Losses\s*\|\s*(\d+)', output)
    stats['max_drawdown'] = md_m.group(1) if md_m else "N/A"
    
    # Total PnL approximate
    # PnL isn't directly in analyze_trades, but we can do a quick calc
    
    return stats

def main():
    # 1. Run OLD Config
    set_config(use_atr=False, lesson_mode="hard")
    old_out = run_backtest("OLD Config (No ATR, Hard Lesson)")
    old_stats = run_analysis()
    
    # 2. Run NEW Config
    set_config(use_atr=True, lesson_mode="soft")
    new_out = run_backtest("NEW Config (ATR Stops, Soft Lesson)")
    new_stats = run_analysis()
    
    # 3. Print Comparison
    table = Table(title="=== PART 4: Extended Backtest Comparison (2-Year) ===", style="bold cyan")
    table.add_column("Metric", style="white")
    table.add_column("OLD Config (No ATR, Hard)", justify="right", style="red")
    table.add_column("NEW Config (ATR, Soft)", justify="right", style="green")
    
    metrics = [
        ("Total Trades", 'total_trades'),
        ("Overall Win Rate", 'win_rate'),
        ("Average Win", 'avg_win'),
        ("Average Loss", 'avg_loss'),
        ("Expectancy per Trade", 'expectancy'),
        ("Max Consecutive Losses", 'max_drawdown')
    ]
    
    for label, key in metrics:
        table.add_row(label, old_stats.get(key, 'N/A'), new_stats.get(key, 'N/A'))
        
    console.print(table)
    
    # Print Walk-Forward table from NEW Config
    console.print("\n[bold magenta]=== NEW Config Walk-Forward Validation ===[/bold magenta]")
    wf_match = re.search(r'(b\)\s*Walk-Forward Validation: Fold 1/2/3 Out-of-Sample Win Rates.*?)(?=\(c\)\s*Overall)', new_out['output'], re.DOTALL)
    if wf_match:
        print(wf_match.group(1))

if __name__ == "__main__":
    main()
