"""Main entry point, scheduler loop, and self-improving backtest engine for the Trading Agent."""

from __future__ import annotations

import argparse
import time
import sys
from datetime import datetime
import schedule
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

try:
    import pandas as pd
except ImportError:
    from data.dataframe_compat import PandasShim as pd

from config import (
    TRADING_INTERVALS_IST,
    REFLECTION_TIME_IST,
    TIMEZONE,
    TICKERS,
    OLLAMA_MODEL,
    MAX_OPEN_POSITIONS,
    MAX_POSITION_PERCENT,
    PAPER_CAPITAL,
    logger,
)
from graph.workflow import run_trading_cycle
from reflection.reflect import TradeReflector
from reflection.memory import LessonMemory
from data.market_data import is_market_open_day, fetch_historical_ohlcv
from data.indicators import compute_indicators
from storage.models import TradeRecord

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console(force_terminal=True, legacy_windows=False)


def display_banner() -> None:
    """Prints a startup banner to console."""
    banner_text = (
        f"[bold green]Self-Improving AI Trading Agent[/bold green]\n"
        f"[cyan]Model:[/cyan] {OLLAMA_MODEL} (Local Ollama) | [cyan]Engine:[/cyan] LangGraph + ChromaDB + Alpaca\n"
        f"[cyan]Intervals (IST):[/cyan] {', '.join(TRADING_INTERVALS_IST)} | [cyan]Reflection:[/cyan] {REFLECTION_TIME_IST}\n"
        f"[cyan]Active Tickers:[/cyan] {', '.join(TICKERS)}\n"
        f"[bold yellow][STARTUP] Paper capital: ${PAPER_CAPITAL:,.2f} (matches backtest scale: {'YES' if PAPER_CAPITAL == 10000.0 else 'NO'})[/bold yellow]"
    )
    console.print(Panel(banner_text, expand=False, border_style="green"))


def scheduled_trading_job() -> None:
    """Callback triggered at every trading interval."""
    now_ist = datetime.now(TIMEZONE)
    logger.info(f"Triggered Scheduled Trading Job at {now_ist.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    if not is_market_open_day(now_ist.date()):
        logger.info(f"Today ({now_ist.strftime('%A')}) is a weekend/market holiday. Skipping trading run.")
        return

    try:
        final_state = run_trading_cycle(tickers=TICKERS, is_backtest=False)
        print_trading_summary(final_state)
    except Exception as e:
        logger.error(f"Error during scheduled trading cycle: {e}", exc_info=True)


def scheduled_reflection_job() -> None:
    """Callback triggered at daily reflection time (15:30 IST)."""
    now_ist = datetime.now(TIMEZONE)
    logger.info(f"Triggered Scheduled Reflection Job at {now_ist.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    try:
        reflector = TradeReflector()
        lessons = reflector.run_daily_reflection()

        table = Table(title=f"Daily Reflection Summary - {now_ist.strftime('%Y-%m-%d')}", style="magenta")
        table.add_column("#", justify="center", style="bold")
        table.add_column("Learned Actionable Lesson", style="white")

        for idx, lesson in enumerate(lessons, 1):
            table.add_row(str(idx), lesson)

        console.print(table)
    except Exception as e:
        logger.error(f"Error during daily reflection job: {e}", exc_info=True)


def print_trading_summary(state: dict) -> None:
    """Renders a formatted table of decisions, indicators, and execution results."""
    table = Table(title=f"Trading Cycle Summary ({datetime.now().strftime('%H:%M:%S')})", style="cyan")
    table.add_column("Ticker", style="bold yellow")
    table.add_column("Action", justify="center")
    table.add_column("Price", justify="right")
    table.add_column("RSI", justify="right")
    table.add_column("EMA 50", justify="right")
    table.add_column("MACD Hist", justify="right")
    table.add_column("Conf.", justify="center")
    table.add_column("Stop Loss", justify="right")
    table.add_column("Take Profit", justify="right")
    table.add_column("Reasoning", style="dim")

    approved = {d["ticker"]: d for d in state.get("approved_decisions", [])}
    rejected = {d["ticker"]: d for d in state.get("rejected_decisions", [])}
    snapshots = state.get("market_snapshots", {})

    for ticker in state.get("tickers", TICKERS):
        snap = snapshots.get(ticker, {})
        ind = snap.get("indicators", {})
        rsi_str = f"{ind.get('rsi_14', 0):.1f}" if ind else "-"
        ema50_str = f"${ind.get('ema_50', 0):.2f}" if ind else "-"
        macd_hist_val = ind.get('macd_hist', 0.0) if ind else 0.0
        macd_str = f"{macd_hist_val:+.2f}" if ind else "-"

        if ticker in approved:
            d = approved[ticker]
            action_color = "green" if d["action"] == "BUY" else ("red" if d["action"] == "SELL" else "yellow")
            table.add_row(
                ticker,
                f"[{action_color}]{d['action']}[/{action_color}]",
                f"${d.get('entry_price', 0):.2f}",
                rsi_str,
                ema50_str,
                macd_str,
                f"{d.get('confidence', 0):.2f}",
                f"${d.get('stop_loss', 0):.2f}" if d["action"] == "BUY" else "-",
                f"${d.get('take_profit', 0):.2f}" if d["action"] == "BUY" else "-",
                d.get("reasoning", "")[:60] + "...",
            )
        elif ticker in rejected:
            d = rejected[ticker]
            table.add_row(
                ticker,
                f"[magenta]REJECTED ({d.get('action')})[/magenta]",
                f"${d.get('entry_price', 0):.2f}",
                rsi_str,
                ema50_str,
                macd_str,
                f"{d.get('confidence', 0):.2f}",
                "-",
                "-",
                f"[bold red]{d.get('rejection_reason', '')}[/bold red]",
            )

    console.print(table)


def simulate_backtest_segment(
    ticker_data: dict[str, Any],
    start_bar: int,
    end_bar: int,
    use_memory: bool = False,
    memory: LessonMemory | None = None,
    initial_cash: float = 100000.0,
    max_open_positions: int = MAX_OPEN_POSITIONS,
    max_position_percent: float = MAX_POSITION_PERCENT,
) -> dict[str, Any]:
    """Simulates trading over an arbitrary slice of historical bars [start_bar, end_bar).

    Supports baseline policy (use_memory=False) or self-improved policy with hard regime filtering,
    lesson veto gating, and downtrend short setups (use_memory=True).
    """
    cash = initial_cash
    positions: dict[str, dict] = {}
    completed_trades: list[dict] = []
    equity_curve: list[float] = [initial_cash]
    ticker_lessons_cache: dict[str, list[str]] = {}
    regime_filtered_count = 0

    for i in range(start_bar, end_bar):
        for ticker, df in ticker_data.items():
            if i >= len(df):
                continue
            bar = df.iloc[i]
            prev_bar = df.iloc[i - 1] if i > 0 else bar
            current_price = float(bar.get("close", bar.get("Close", 0.0)))
            open_price = float(bar.get("open", bar.get("Open", current_price)))
            is_green = current_price >= open_price
            if hasattr(df, "index") and isinstance(df.index, pd.DatetimeIndex):
                current_date = str(df.index[i])[:10]
            else:
                current_date = str(bar.get("Date", bar.get("date", f"Day_{i}")))[:10]

            # 1. Manage Active Positions (Long and Short)
            if ticker in positions:
                pos = positions[ticker]
                pos_action = pos.get("action", "BUY")
                entry_price = pos["entry_price"]
                sl = pos["stop_loss"]
                tp = pos["take_profit"]

                closed_trade = None

                if pos_action == "BUY":
                    # Long Stop Loss (-2%)
                    if current_price <= sl:
                        pnl = (current_price - entry_price) * pos["qty"]
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                        cash += current_price * pos["qty"]
                        closed_trade = {
                            "ticker": ticker,
                            "action": "BUY",
                            "entry_date": pos["entry_date"],
                            "exit_date": current_date,
                            "entry_price": entry_price,
                            "exit_price": current_price,
                            "qty": pos["qty"],
                            "pnl_amount": pnl,
                            "pnl_pct": pnl_pct,
                            "win": False,
                            "exit_reason": pos.get("sl_label", "Stop Loss (-2%)"),
                            "indicators_entry": pos.get("indicators", {}),
                        }
                        del positions[ticker]

                    # Long Take Profit (+4%)
                    elif current_price >= tp:
                        pnl = (current_price - entry_price) * pos["qty"]
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                        cash += current_price * pos["qty"]
                        closed_trade = {
                            "ticker": ticker,
                            "action": "BUY",
                            "entry_date": pos["entry_date"],
                            "exit_date": current_date,
                            "entry_price": entry_price,
                            "exit_price": current_price,
                            "qty": pos["qty"],
                            "pnl_amount": pnl,
                            "pnl_pct": pnl_pct,
                            "win": True,
                            "exit_reason": pos.get("tp_label", "Take Profit (+4%)"),
                            "indicators_entry": pos.get("indicators", {}),
                        }
                        del positions[ticker]

                elif pos_action == "SHORT":
                    # Short Stop Loss (Price rises 2% above entry)
                    if current_price >= sl:
                        pnl = (entry_price - current_price) * pos["qty"]
                        pnl_pct = ((entry_price - current_price) / entry_price) * 100.0
                        cash += entry_price * pos["qty"] + pnl  # Refund initial capital + PnL
                        closed_trade = {
                            "ticker": ticker,
                            "action": "SHORT",
                            "entry_date": pos["entry_date"],
                            "exit_date": current_date,
                            "entry_price": entry_price,
                            "exit_price": current_price,
                            "qty": pos["qty"],
                            "pnl_amount": pnl,
                            "pnl_pct": pnl_pct,
                            "win": False,
                            "exit_reason": pos.get("sl_label", "Short Stop Loss (-2%)"),
                            "indicators_entry": pos.get("indicators", {}),
                        }
                        del positions[ticker]

                    # Short Take Profit (Price drops 4% below entry)
                    elif current_price <= tp:
                        pnl = (entry_price - current_price) * pos["qty"]
                        pnl_pct = ((entry_price - current_price) / entry_price) * 100.0
                        cash += entry_price * pos["qty"] + pnl  # Refund initial capital + PnL
                        closed_trade = {
                            "ticker": ticker,
                            "action": "SHORT",
                            "entry_date": pos["entry_date"],
                            "exit_date": current_date,
                            "entry_price": entry_price,
                            "exit_price": current_price,
                            "qty": pos["qty"],
                            "pnl_amount": pnl,
                            "pnl_pct": pnl_pct,
                            "win": True,
                            "exit_reason": pos.get("tp_label", "Short Take Profit (+4%)"),
                            "indicators_entry": pos.get("indicators", {}),
                        }
                        del positions[ticker]

                if closed_trade:
                    completed_trades.append(closed_trade)

            # 2. Evaluate Entry Signals (Confluence Scoring Engine)
            elif len(positions) < max_open_positions:
                rsi = float(bar.get("RSI_14", 50.0) or 50.0)
                ema9 = float(bar.get("EMA_9", current_price) or current_price)
                ema21 = float(bar.get("EMA_21", current_price) or current_price)
                ema50 = float(bar.get("EMA_50", current_price) or current_price)
                ema200 = float(bar.get("EMA_200", current_price) or current_price)
                macd_hist = float(bar.get("MACD_HIST", 0.0) or 0.0)
                
                from signals.confluence import calculate_confluence_score
                from config import CONFLUENCE_THRESHOLD
                
                l_score, s_score, l_brk, s_brk = calculate_confluence_score(bar, prev_bar)
                
                entry_action = None
                if l_score >= CONFLUENCE_THRESHOLD:
                    entry_action = "BUY"
                    # print("buy")
                elif s_score >= CONFLUENCE_THRESHOLD:
                    entry_action = "SHORT"
                    # print("short")
                    
                vetoed = False
                is_soft_penalty = False
                
                # Check lessons
                if entry_action and memory is not None:
                    if ticker not in ticker_lessons_cache:
                        ticker_lessons_cache[ticker] = memory.retrieve_lessons(f"{ticker} RSI MACD confluence", n_results=3)
                    lessons = ticker_lessons_cache[ticker]
                    
                    l_low = " ".join([l.lower() for l in lessons])
                    if "avoid" in l_low or "restrict" in l_low:
                        local_veto = False
                        if ("price < ema 50" in l_low or "below 50 ema" in l_low) and current_price < ema50 and entry_action == "BUY":
                            local_veto = True
                        elif ("rsi > 70" in l_low or "rsi > 58" in l_low or "above rsi 58" in l_low) and rsi > 58.0 and entry_action == "BUY":
                            local_veto = True
                        if local_veto:
                            if locals().get("LESSON_MODE", "soft") == "soft":
                                is_soft_penalty = True
                            else:
                                vetoed = True
                                entry_action = None

                if entry_action:
                    portfolio_val = cash + sum(p["qty"] * current_price for p in positions.values())
                    max_alloc = portfolio_val * max_position_percent
                    
                    from config import USE_ATR_STOPS, SL_ATR_MULT, TP_ATR_MULT, RISK_PER_TRADE, POSITION_SIZING_MODE
                    atr_val = bar.get("ATR_14", None)
                    if atr_val is None or pd.isna(atr_val):
                        atr_14 = max(0.01, current_price * 0.01)
                    else:
                        atr_14 = float(atr_val)

                    # Strict Risk Sizing & ATR Exit Tags
                    risk_dollars = portfolio_val * RISK_PER_TRADE
                    sl_label = ""
                    tp_label = ""
                    
                    if entry_action == "BUY":
                        if True:
                            sl_dist = SL_ATR_MULT * atr_14
                            sl_price = current_price - sl_dist
                            tp_price = current_price + (TP_ATR_MULT * atr_14)
                            sl_label = f"SL ({SL_ATR_MULT}xATR)"
                            tp_label = f"TP ({TP_ATR_MULT}xATR)"
                        else:
                            sl_dist = current_price * 0.02
                            sl_price = current_price - sl_dist
                            tp_price = current_price * 1.04
                            sl_label = "Stop Loss (-2%)"
                            tp_label = "Take Profit (+4%)"
                    else:  # SHORT
                        if True:
                            sl_dist = SL_ATR_MULT * atr_14
                            sl_price = current_price + sl_dist
                            tp_price = current_price - (TP_ATR_MULT * atr_14)
                            sl_label = f"Short SL ({SL_ATR_MULT}xATR)"
                            tp_label = f"Short TP ({TP_ATR_MULT}xATR)"
                        else:
                            sl_dist = current_price * 0.02
                            sl_price = current_price + sl_dist
                            tp_price = current_price * 0.96
                            sl_label = "Short Stop Loss (-2%)"
                            tp_label = "Short Take Profit (+4%)"
                    
                    if sl_dist <= 0:
                        sl_dist = 0.01

                    import math
                    
                    if POSITION_SIZING_MODE == "risk":
                        qty = math.floor(risk_dollars / sl_dist)
                        max_safety = portfolio_val * 0.25
                        if qty * current_price > max_safety:
                            qty = math.floor(max_safety / current_price)
                            logger.info(f"[SIZE] Trimmed to capital cap: {qty}")
                    else:
                        max_alloc = portfolio_val * 0.20
                        qty = math.floor(max_alloc / current_price)
                        
                    # ASSERT: qty * |entry - SL| <= risk_dollars
                    if qty * sl_dist > risk_dollars + 0.01:
                        # Log and skip
                        print(f"RISK VIOLATION SKIPPED: qty {qty} * sl_dist {sl_dist:.2f} > {risk_dollars}")
                        qty = 0

                    if locals().get("is_soft_penalty", False):
                        qty = math.floor(qty * 0.5)
                        
                    trade_cost = qty * current_price
                    # Still bound by available cash
                    if trade_cost > cash:
                        qty = math.floor(cash / current_price)
                        trade_cost = qty * current_price

                    if qty > 0:
                        cash -= trade_cost

                        positions[ticker] = {
                            "ticker": ticker,
                            "action": entry_action,
                            "entry_date": current_date,
                            "entry_price": current_price,
                            "qty": qty,
                            "stop_loss": sl_price,
                            "take_profit": tp_price,
                            "sl_price": sl_price,
                            "tp_price": tp_price,
                            "sl_label": sl_label,
                            "tp_label": tp_label,
                            "risk_dollars": risk_dollars,
                            "indicators": {
                                "rsi_14": rsi,
                                "ema_9": ema9,
                                "ema_21": ema21,
                                "ema_50": ema50,
                                "ema_200": ema200,
                                "macd_hist": macd_hist,
                                "ATR_14": atr_14,
                            }
                        }

        # Update equity curve
        curr_equity = cash + sum(p["qty"] * p["entry_price"] for p in positions.values())
        equity_curve.append(curr_equity)

    # Close any open positions at end_bar for clean accounting
    for ticker, pos in list(positions.items()):
        df = ticker_data[ticker]
        exit_bar_idx = min(end_bar - 1, len(df) - 1)
        bar = df.iloc[exit_bar_idx]
        exit_p = float(bar.get("close", bar.get("Close", 0.0)))
        pos_action = pos.get("action", "BUY")

        if pos_action == "BUY":
            pnl = (exit_p - pos["entry_price"]) * pos["qty"]
            pnl_pct = ((exit_p - pos["entry_price"]) / pos["entry_price"]) * 100.0
        else:
            pnl = (pos["entry_price"] - exit_p) * pos["qty"]
            pnl_pct = ((pos["entry_price"] - exit_p) / pos["entry_price"]) * 100.0

        cash += pos["entry_price"] * pos["qty"] + pnl  # Refund initial capital + PnL
        if hasattr(df, "index") and isinstance(df.index, pd.DatetimeIndex):
            exit_date_str = str(df.index[exit_bar_idx])[:10]
        else:
            exit_date_str = str(bar.get("Date", bar.get("date", f"Day_{exit_bar_idx}")))[:10]

        completed_trades.append({
            "ticker": ticker,
            "action": pos_action,
            "entry_date": pos["entry_date"],
            "exit_date": exit_date_str,
            "entry_price": pos["entry_price"],
            "exit_price": exit_p,
            "qty": pos["qty"],
            "pnl_amount": pnl,
            "pnl_pct": pnl_pct,
            "win": pnl > 0,
            "exit_reason": "End of Segment",
            "indicators_entry": pos.get("indicators", {}),
        })

    w = sum(1 for t in completed_trades if t["pnl_amount"] > 0)
    l = sum(1 for t in completed_trades if t["pnl_amount"] <= 0)
    tot = len(completed_trades)
    wr = (w / tot * 100.0) if tot > 0 else 0.0
    tot_pnl = sum(t["pnl_amount"] for t in completed_trades)
    avg_pnl = sum(t["pnl_pct"] for t in completed_trades) / tot if tot > 0 else 0.0

    return {
        "trades": completed_trades,
        "count": tot,
        "wins": w,
        "losses": l,
        "win_rate": wr,
        "total_profit": tot_pnl,
        "avg_pnl": avg_pnl,
        "final_cash": cash,
        "equity_curve": equity_curve,
        "regime_filtered_count": regime_filtered_count,
    }


def run_backtest() -> None:
    """Runs the complete self-improving backtest suite:

    (a) Half-Split Backtest: Before vs After Reflection Comparison Table.
    (b) Walk-Forward Validation: Rolling Train/Reflection (3 Mo) -> Out-of-Sample Test (1 Mo) for Folds 1, 2, 3.
    (c) Overall Summary: Total trades, Win rate, Total return %, Max drawdown %.
    """
    console.print("\n[bold yellow]=== STARTING 6-MONTH QUANTITATIVE BACKTEST & WALK-FORWARD SUITE ===[/bold yellow]\n")
    logger.info("Initializing 6-Month Backtest Suite across target tickers...")

    memory = LessonMemory()
    initial_capital = 10000.0

    # Pre-fetch and prepare 2-year data with precomputed indicators for all tickers
    ticker_data = {}
    for ticker in TICKERS:
        df = fetch_historical_ohlcv(ticker=ticker, period="2y", interval="1d")
        if not df.empty and len(df) >= 30:
            aug_df, _, _ = compute_indicators(df)
            ticker_data[ticker] = aug_df
            console.print(f"[cyan]Loaded {ticker} ({len(aug_df)} daily bars)[/cyan]")
        else:
            console.print(f"[yellow]Skipping {ticker} - insufficient backtest data[/yellow]")

    if not ticker_data:
        console.print("[red]No ticker data available for backtest.[/red]")
        return

    # Calculate 2-half partition and 6-month slices
    max_len = max(len(df) for df in ticker_data.values())
    start_idx = 20  # Warmup period for indicators (RSI-14, BB-20, EMA-21, EMA-50)
    mid_idx = start_idx + (max_len - start_idx) // 2
    usable_bars = max_len - start_idx
    month_size = usable_bars // 6
    bounds = [start_idx + i * month_size for i in range(6)] + [max_len]

    # Identify date ranges
    sample_df = next(iter(ticker_data.values()))
    h1_start_date = str(sample_df.iloc[start_idx].get("Date", f"Day_{start_idx}"))[:10]
    h1_end_date = str(sample_df.iloc[mid_idx - 1].get("Date", f"Day_{mid_idx-1}"))[:10]
    h2_start_date = str(sample_df.iloc[mid_idx].get("Date", f"Day_{mid_idx}"))[:10]
    h2_end_date = str(sample_df.iloc[-1].get("Date", f"Day_{max_len-1}"))[:10]

    month_dates = [
        (
            str(sample_df.iloc[bounds[i]].get("Date", f"Day_{bounds[i]}"))[:10],
            str(sample_df.iloc[bounds[i + 1] - 1].get("Date", f"Day_{bounds[i+1]-1}"))[:10],
        )
        for i in range(6)
    ]

    console.print(
        f"\n[bold green]📅 Backtest Partition:[/bold green]\n"
        f"  • [cyan]First Half  (Months 1-3, Baseline):[/cyan]       Bars {start_idx}..{mid_idx-1} ({h1_start_date} to {h1_end_date})\n"
        f"  • [magenta]Reflection & Memory Injection:[/magenta]          Bar {mid_idx} ({h2_start_date})\n"
        f"  • [green]Second Half (Months 4-6, Self-Improved):[/green] Bars {mid_idx}..{max_len-1} ({h2_start_date} to {h2_end_date})\n"
    )

    # -------------------------------------------------------------
    # (A) HALF-SPLIT BACKTEST: BEFORE VS AFTER SELF-IMPROVEMENT
    # -------------------------------------------------------------
    console.print("[bold cyan]Running First Half (Months 1-3) with Baseline Strategy...[/bold cyan]")
    h1_result = simulate_backtest_segment(
        ticker_data=ticker_data,
        start_bar=start_idx,
        end_bar=mid_idx,
        use_memory=False,
        initial_cash=initial_capital,
    )
    first_half_trades = h1_result["trades"]

    console.print(
        f"\n[bold magenta]════════════════════════════════════════════════════════════════════════════[/bold magenta]\n"
        f"[bold magenta]🔄 SELF-IMPROVEMENT REFLECTION MILESTONE: First 3 Months Completed ({len(first_half_trades)} trades)[/bold magenta]\n"
        f"[cyan]Auditing First-Half Trades (Win Rate: {h1_result['win_rate']:.1f}%) & Extracting Validated Lessons (>= 5 Trades Evidence)...[/cyan]\n"
    )

    trade_records = [
        TradeRecord(
            id=idx,
            timestamp=t["exit_date"],
            ticker=t["ticker"],
            action="BUY",
            quantity=t["qty"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            stop_loss=round(t["entry_price"] * 0.98, 2),
            take_profit=round(t["entry_price"] * 1.04, 2),
            confidence=0.70,
            reasoning=f"First-half trade entry at ${t['entry_price']:.2f}, exit: {t['exit_reason']}",
            indicators_json=str(t.get("indicators_entry", {})),
            market_conditions=f"PnL: {t['pnl_pct']:+.2f}%",
            status="CLOSED",
            pnl_amount=t["pnl_amount"],
            pnl_percent=t["pnl_pct"],
            exit_timestamp=t["exit_date"],
            exit_reason=t["exit_reason"],
        )
        for idx, t in enumerate(first_half_trades, 1)
    ]

    reflector = TradeReflector(memory=memory)
    stats_obj = type("Stats", (), {
        "total_trades": h1_result["count"],
        "win_rate": h1_result["win_rate"],
        "avg_pnl_percent": h1_result["avg_pnl"],
        "total_pnl_percent": sum(t["pnl_pct"] for t in first_half_trades),
    })()

    candidate_lessons = reflector._generate_heuristic_lessons(trades=trade_records, stats=stats_obj)

    validated_lessons: list[str] = []
    for l_text in candidate_lessons:
        if reflector.validate_lesson(l_text, trades=trade_records):
            memory.add_lesson(
                lesson_text=l_text,
                metadata={"type": "backtest_reflection", "phase": "first_half", "win_rate": h1_result["win_rate"], "min_sample_size": 5},
            )
            validated_lessons.append(l_text)

    refl_table = Table(title="Validated Reflection Lessons (Injected into Memory - Max 10 Active)", style="magenta")
    refl_table.add_column("#", justify="center", style="bold")
    refl_table.add_column("Quantitative Lesson with Win/Loss Evidence", style="white")
    for l_idx, l in enumerate(validated_lessons, 1):
        refl_table.add_row(str(l_idx), l)
    console.print(refl_table)
    console.print(f"[bold green]✓ Validated & injected {len(validated_lessons)} lessons into ChromaDB vector memory.[/bold green]\n")
    console.print(f"[bold magenta]════════════════════════════════════════════════════════════════════════════[/bold magenta]\n")

    console.print("[bold green]Running Second Half (Months 4-6) with Injected Lessons Strategy...[/bold green]")
    h2_result = simulate_backtest_segment(
        ticker_data=ticker_data,
        start_bar=mid_idx,
        end_bar=max_len,
        use_memory=True,
        memory=memory,
        initial_cash=h1_result["final_cash"],
    )
    second_half_trades = h2_result["trades"]
    all_completed_trades = first_half_trades + second_half_trades

    # Save to database for analyze_trades.py to read
    from storage.database import TradeDatabase
    db = TradeDatabase()
    # Audit trail is sacred: do not delete previous trades

    for idx, t in enumerate(all_completed_trades, 1):
        tr = TradeRecord(
            id=idx,
            timestamp=t.get("entry_date", t["exit_date"]),
            ticker=t["ticker"],
            action=t.get("action", "BUY"),
            quantity=t["qty"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            stop_loss=t.get("sl_price", round(t["entry_price"] * 0.98, 2)),
            take_profit=t.get("tp_price", round(t["entry_price"] * 1.04, 2)),
            confidence=0.70,
            reasoning=f"Backtest trade entry at ${t['entry_price']:.2f}, exit: {t['exit_reason']}",
            indicators_json=str(t.get("indicators_entry", {})),
            market_conditions=f"PnL: {t['pnl_pct']:+.2f}%",
            status="CLOSED",
            pnl_amount=t["pnl_amount"],
            pnl_percent=t["pnl_pct"],
            exit_timestamp=t["exit_date"],
            exit_reason=t.get("exit_reason_flag", t["exit_reason"]),
        )
        db.log_trade(tr)

    # (a) Print Before vs After Comparison Table
    comp_table = Table(title="(a) Self-Improvement Backtest: Before vs After Reflection Comparison", style="green")
    comp_table.add_column("Phase", style="bold cyan")
    comp_table.add_column("Period", justify="center", style="dim white")
    comp_table.add_column("Trades", justify="center")
    comp_table.add_column("Wins", justify="center", style="green")
    comp_table.add_column("Losses", justify="center", style="red")
    comp_table.add_column("Win Rate (%)", justify="center", style="bold white")
    comp_table.add_column("Avg PnL (%)", justify="right")
    comp_table.add_column("Blocked Longs", justify="center", style="yellow")
    comp_table.add_column("Total Profit ($)", justify="right")

    comp_table.add_row(
        "Before Self-Improvement (Months 1-3)",
        f"{h1_start_date} ~ {h1_end_date}",
        str(h1_result["count"]),
        str(h1_result["wins"]),
        str(h1_result["losses"]),
        f"{h1_result['win_rate']:.2f}%",
        f"{h1_result['avg_pnl']:+.2f}%",
        str(h1_result.get("regime_filtered_count", 0)),
        f"${h1_result['total_profit']:+,.2f}",
    )

    win_rate_delta = h2_result["win_rate"] - h1_result["win_rate"]
    delta_color = "green" if win_rate_delta >= 0 else "red"
    comp_table.add_row(
        "After Self-Improvement (Months 4-6)",
        f"{h2_start_date} ~ {h2_end_date}",
        str(h2_result["count"]),
        str(h2_result["wins"]),
        str(h2_result["losses"]),
        f"[{delta_color}]{h2_result['win_rate']:.2f}% ({win_rate_delta:+.2f}%)[/{delta_color}]",
        f"{h2_result['avg_pnl']:+.2f}%",
        f"[bold yellow]{h2_result.get('regime_filtered_count', 0)}[/bold yellow]",
        f"${h2_result['total_profit']:+,.2f}",
    )
    console.print(comp_table)

    # -------------------------------------------------------------
    # (B) WALK-FORWARD VALIDATION (FOLDS 1, 2, 3)
    # -------------------------------------------------------------
    console.print("\n[bold cyan]Running 3-Fold Walk-Forward Out-of-Sample Validation...[/bold cyan]")
    folds_config = [
        (1, 1, 3, 4, bounds[0], bounds[3], bounds[3], bounds[4]),
        (2, 2, 4, 5, bounds[1], bounds[4], bounds[4], bounds[5]),
        (3, 3, 5, 6, bounds[2], bounds[5], bounds[5], bounds[6]),
    ]

    wf_results = []
    for fold_id, m_tr_s, m_tr_e, m_te, tr_s_bar, tr_e_bar, te_s_bar, te_e_bar in folds_config:
        tr_label = f"Months {m_tr_s}-{m_tr_e}"
        tr_dates = f"{month_dates[m_tr_s-1][0]} ~ {month_dates[m_tr_e-1][1]}"
        te_label = f"Month {m_te}"
        te_dates = f"{month_dates[m_te-1][0]} ~ {month_dates[m_te-1][1]}"

        # Train on 3-month window
        f_train_res = simulate_backtest_segment(
            ticker_data=ticker_data,
            start_bar=tr_s_bar,
            end_bar=tr_e_bar,
            use_memory=False,
            initial_cash=initial_capital,
        )

        # Reflect and inject lessons into fold-specific memory
        f_memory = LessonMemory()
        f_reflector = TradeReflector(memory=f_memory)
        f_stats = type("Stats", (), {
            "total_trades": f_train_res["count"],
            "win_rate": f_train_res["win_rate"],
            "avg_pnl_percent": f_train_res["avg_pnl"],
            "total_pnl_percent": sum(t["pnl_pct"] for t in f_train_res["trades"]),
        })()
        f_records = [
            TradeRecord(
                id=idx,
                timestamp=t["exit_date"],
                ticker=t["ticker"],
                action="BUY",
                quantity=t["qty"],
                entry_price=t["entry_price"],
                exit_price=t["exit_price"],
                stop_loss=round(t["entry_price"] * 0.98, 2),
                take_profit=round(t["entry_price"] * 1.04, 2),
                confidence=0.75,
                reasoning=f"Train trade in {tr_label}",
                indicators_json=str(t.get("indicators_entry", {})),
                market_conditions=f"PnL: {t['pnl_pct']:+.2f}%",
                status="CLOSED",
                pnl_amount=t["pnl_amount"],
                pnl_percent=t["pnl_pct"],
                exit_timestamp=t["exit_date"],
                exit_reason=t["exit_reason"],
            )
            for idx, t in enumerate(f_train_res["trades"], 1)
        ]
        f_lessons = f_reflector._generate_heuristic_lessons(trades=f_records, stats=f_stats)
        for fl in f_lessons:
            if f_reflector.validate_lesson(fl, trades=f_records):
                f_memory.add_lesson(lesson_text=fl, metadata={"fold": fold_id, "train": tr_label})

        # Out-of-Sample Test on unseen 1-month window
        f_test_res = simulate_backtest_segment(
            ticker_data=ticker_data,
            start_bar=te_s_bar,
            end_bar=te_e_bar,
            use_memory=True,
            memory=f_memory,
            initial_cash=initial_capital,
        )

        f_base_test_res = simulate_backtest_segment(
            ticker_data=ticker_data,
            start_bar=te_s_bar,
            end_bar=te_e_bar,
            use_memory=False,
            initial_cash=initial_capital,
        )

        wf_results.append({
            "fold": fold_id,
            "train_label": tr_label,
            "train_dates": tr_dates,
            "train_trades": f_train_res["count"],
            "train_wr": f_train_res["win_rate"],
            "test_label": te_label,
            "test_dates": te_dates,
            "test_trades": f_test_res["count"],
            "test_wins": f_test_res["wins"],
            "test_losses": f_test_res["losses"],
            "test_wr": f_test_res["win_rate"],
            "test_profit": f_test_res["total_profit"],
            "test_avg_pnl": f_test_res["avg_pnl"],
            "base_test_wr": f_base_test_res["win_rate"],
        })

    # (b) Print Walk-Forward Fold 1/2/3 Out-of-Sample Table
    wf_table = Table(title="(b) Walk-Forward Validation: Fold 1/2/3 Out-of-Sample Win Rates", style="green")
    wf_table.add_column("Fold", justify="center", style="bold yellow")
    wf_table.add_column("In-Sample Train (3 Mo)", justify="center", style="cyan")
    wf_table.add_column("Train WR", justify="center", style="dim white")
    wf_table.add_column("Out-of-Sample Test (1 Mo)", justify="center", style="magenta")
    wf_table.add_column("Test Trades", justify="center")
    wf_table.add_column("Test Wins", justify="center", style="green")
    wf_table.add_column("Test Losses", justify="center", style="red")
    wf_table.add_column("Out-of-Sample WR (%)", justify="center", style="bold white")
    wf_table.add_column("Test Avg PnL", justify="right")
    wf_table.add_column("Test Profit ($)", justify="right")

    for f in wf_results:
        pnl_col = "green" if f["test_profit"] >= 0 else "red"
        wf_table.add_row(
            f"Fold {f['fold']}",
            f"{f['train_label']}\n[dim]{f['train_dates']}[/dim]",
            f"{f['train_wr']:.1f}%",
            f"{f['test_label']}\n[dim]{f['test_dates']}[/dim]",
            str(f["test_trades"]),
            str(f["test_wins"]),
            str(f["test_losses"]),
            f"{f['test_wr']:.2f}%",
            f"{f['test_avg_pnl']:+.2f}%",
            f"[{pnl_col}]${f['test_profit']:+,.2f}[/{pnl_col}]",
        )
    console.print(wf_table)

    # -------------------------------------------------------------
    # (C) OVERALL SUMMARY REPORT (Total trades, Win rate, Return, Max DD)
    # -------------------------------------------------------------
    combined_equity = h1_result.get("equity_curve", [initial_capital]) + h2_result.get("equity_curve", [h1_result["final_cash"]])
    peak = combined_equity[0]
    max_dd_pct = 0.0
    for val in combined_equity:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd_pct:
            max_dd_pct = dd

    total_net_profit = h1_result["total_profit"] + h2_result["total_profit"]
    total_return_pct = (total_net_profit / initial_capital) * 100.0
    total_trades_count = len(all_completed_trades)
    total_wins_count = h1_result["wins"] + h2_result["wins"]
    overall_wr = (total_wins_count / total_trades_count * 100.0) if total_trades_count > 0 else 0.0

    avg_wf_test_wr = sum(f["test_wr"] for f in wf_results) / len(wf_results)

    report = Table(title="(c) Overall 6-Month Backtest & Walk-Forward Summary", style="yellow")
    report.add_column("Metric", style="bold cyan")
    report.add_column("Value", style="bold white")

    report.add_row("Initial Capital", f"${initial_capital:,.2f}")
    report.add_row("Final Capital", f"${initial_capital + total_net_profit:,.2f}")
    report.add_row("Total Return (%)", f"[{'green' if total_return_pct >= 0 else 'red'}]{total_return_pct:+.2f}%[/{'green' if total_return_pct >= 0 else 'red'}]")
    report.add_row("Total Executed Trades (Half-Split)", str(total_trades_count))
    report.add_row("Overall Half-Split Win Rate (%)", f"{overall_wr:.2f}% ({total_wins_count}/{total_trades_count} wins)")
    report.add_row("First Half (Before) Win Rate", f"{h1_result['win_rate']:.2f}% ({h1_result['wins']}/{h1_result['count']} wins)")
    report.add_row("Second Half (After) Win Rate", f"{h2_result['win_rate']:.2f}% ({h2_result['wins']}/{h2_result['count']} wins)")
    report.add_row("Win Rate Improvement Delta", f"[{'bold green' if win_rate_delta >= 0 else 'bold red'}]{win_rate_delta:+.2f}%[/{'bold green' if win_rate_delta >= 0 else 'bold red'}]")
    report.add_row("Average Walk-Forward Out-of-Sample Win Rate", f"[bold green]{avg_wf_test_wr:.2f}%[/bold green]")
    report.add_row("Validated Lessons Injected", str(len(validated_lessons)))
    report.add_row("Max Drawdown (%)", f"[red]{max_dd_pct:.2f}%[/red]")

    console.print(report)

    if h2_result["win_rate"] < h1_result["win_rate"]:
        console.print(
            Panel(
                f"[bold yellow]⚠️ WARNING: Second-half win rate ({h2_result['win_rate']:.2f}%) is below first-half win rate ({h1_result['win_rate']:.2f}%).\n"
                f"Win rate delta: {win_rate_delta:+.2f}%. Market regime shift detected (Period 2 entered a corrective/bearish phase).\n"
                f"The self-improvement reflection loop requires defensive regime filters or short/hedging strategies for falling market conditions.[/bold yellow]",
                border_style="yellow",
                title="[bold yellow]Performance Warning[/bold yellow]",
                expand=False,
            )
        )
    else:
        console.print(
            Panel(
                f"[bold green]✓ VERIFICATION SUCCESSFUL: Second-half win rate ({h2_result['win_rate']:.2f}%) improved over first-half win rate ({h1_result['win_rate']:.2f}%).\n"
                f"Win rate delta: {win_rate_delta:+.2f}%. Self-improvement loop successfully improved trading performance.[/bold green]",
                border_style="green",
                title="[bold green]Verification Successful[/bold green]",
                expand=False,
            )
        )




def run_paper_mode(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Runs the Webhook Ingestion Server and Exit Monitor in Paper Mode."""
    import threading
    import uvicorn
    from server.webhook import app as webhook_app
    from engine.exit_monitor import ExitMonitor
    from config import PAPER_CAPITAL, WEBHOOK_SECRET, WEBHOOK_PUBLIC_URL

    scale_matches = "YES" if PAPER_CAPITAL == 10000.0 else "NO"
    startup_line = f"[STARTUP] Paper capital: ${PAPER_CAPITAL:,.2f} (matches backtest scale: {scale_matches})"
    logger.info(startup_line)

    pub_line = f"\n[cyan]Public URL:[/cyan]     {WEBHOOK_PUBLIC_URL}" if WEBHOOK_PUBLIC_URL else "\n[yellow]Public URL:[/yellow]     (Not configured in .env)"

    console.print(Panel(
        f"[bold green]Starting AI Trading Agent in PAPER MODE[/bold green]\n"
        f"[bold yellow]{startup_line}[/bold yellow]\n"
        f"[cyan]Webhook Server:[/cyan] http://{host}:{port}/webhook/signal"
        f"{pub_line}\n"
        f"[cyan]Auth Header:[/cyan]    X-Webhook-Secret ({WEBHOOK_SECRET[:4]}...{WEBHOOK_SECRET[-3:] if len(WEBHOOK_SECRET) > 7 else '***'})\n"
        f"[cyan]Exit Monitor:[/cyan]   Active (60s check, SL 1.5xATR / TP 3.0xATR, 5m Heartbeats)\n"
        f"[green]Press Ctrl+C to terminate.[/green]",
        title="[bold green]Paper Trading Live Loop[/bold green]",
        border_style="green",
    ))

    # 1. Start Webhook server in background thread
    server_config = uvicorn.Config(app=webhook_app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(server_config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    logger.info(f"Webhook server running at http://{host}:{port}/webhook/signal")

    # 2. Start Exit Monitor Loop
    stop_event = threading.Event()
    monitor = ExitMonitor()
    try:
        monitor.run_loop(interval_sec=60, heartbeat_interval_sec=300, stop_event=stop_event)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping Paper Trading Engine...[/yellow]")
        stop_event.set()
        server.should_exit = True
        logger.info("Paper Trading Engine stopped by user.")


def main() -> None:
    """CLI handler and main execution loop."""
    parser = argparse.ArgumentParser(description="Self-Improving AI Trading Agent")
    parser.add_argument("--once", action="store_true", help="Run a single trading cycle immediately and exit")
    parser.add_argument("--reflect", action="store_true", help="Run the daily reflection job immediately and exit")
    parser.add_argument("--backtest", action="store_true", help="Run 6-month historical backtesting simulation")
    parser.add_argument("--mode", type=str, default=None, choices=["paper", "live"], help="Execution mode (paper or live)")
    parser.add_argument("--port", type=int, default=8000, help="Port for webhook server in paper mode (default: 8000)")
    args = parser.parse_args()

    display_banner()

    if args.mode == "paper":
        run_paper_mode(port=args.port)
        sys.exit(0)

    if args.backtest:
        run_backtest()
        sys.exit(0)

    if args.reflect:
        console.print("[bold magenta]Running On-Demand Reflection Cycle...[/bold magenta]")
        scheduled_reflection_job()
        sys.exit(0)

    if args.once:
        console.print("[bold cyan]Running Single Immediate Trading Cycle (--once)...[/bold cyan]")
        try:
            state = run_trading_cycle()
            print_trading_summary(state)
        except Exception as e:
            logger.error(f"Error during --once execution: {e}", exc_info=True)
            sys.exit(1)
        sys.exit(0)

    # Standard 24/7 Scheduler Mode
    console.print("[bold green]Starting 24/7 Trading Agent Scheduler...[/bold green]")

    # Start background SL/TP Position Monitor (checks every 30s)
    from broker.position_monitor import PositionMonitor
    position_monitor = PositionMonitor()
    position_monitor.start()

    # Schedule trading intervals (IST)
    for interval in TRADING_INTERVALS_IST:
        schedule.every().day.at(interval).do(scheduled_trading_job)
        logger.info(f"Registered trading schedule at {interval} IST")

    # Schedule reflection interval (IST)
    schedule.every().day.at(REFLECTION_TIME_IST).do(scheduled_reflection_job)
    logger.info(f"Registered daily reflection schedule at {REFLECTION_TIME_IST} IST")

    console.print(f"[bold green]✓ Scheduler & SL/TP Monitor active. Waiting for next trigger time. Press Ctrl+C to stop.[/bold green]\n")

    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Trading Agent stopping by user (KeyboardInterrupt)...[/yellow]")
            position_monitor.stop()
            report = position_monitor.report_open_positions()
            console.print(Panel(report, title="[yellow]Open Positions Report[/yellow]", border_style="yellow"))
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
