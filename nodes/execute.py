"""EXECUTE Node: Executes approved orders and monitors open positions for SL/TP triggers."""

from __future__ import annotations

from typing import Dict, Any, List
from datetime import datetime

from config import logger, STOP_LOSS_PERCENT, TAKE_PROFIT_PERCENT
from graph.state import AgentState
from broker.alpaca_client import AlpacaBrokerClient, is_us_market_open
from storage.database import TradeDatabase
from storage.models import TradeStatus


def execute_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node executing approved trading signals and checking SL/TP on active positions."""
    approved_decisions = state.get("approved_decisions", [])
    snapshots = state.get("market_snapshots", {})
    is_backtest = state.get("is_backtest", False)
    logger.info(f"--- [NODE: EXECUTE] Processing {len(approved_decisions)} approved decisions ---")

    broker = AlpacaBrokerClient()
    db = TradeDatabase()
    execution_results: List[Dict[str, Any]] = []

    # US Market Hours Gate: Only applies to live/paper execution, NOT backtests
    if not is_backtest:
        is_open, market_msg = is_us_market_open()
        if not is_open:
            logger.warning(market_msg)
            for decision in approved_decisions:
                execution_results.append({
                    "ticker": decision["ticker"],
                    "action": decision["action"],
                    "status": "skipped",
                    "reason": market_msg,
                })
            return {"execution_results": execution_results}

    # 1. First, monitor existing open trades in SQLite for Stop-Loss or Take-Profit hits
    open_db_trades = db.get_open_trades()
    for open_trade in open_db_trades:
        ticker = open_trade.ticker
        if ticker in snapshots:
            curr_price = float(snapshots[ticker]["current_price"])
            entry_price = float(open_trade.entry_price)
            sl_price = float(open_trade.stop_loss)
            tp_price = float(open_trade.take_profit)

            # Check if Stop-Loss or Take-Profit is hit
            if open_trade.action == "BUY":
                if curr_price <= sl_price:
                    logger.warning(f"🚨 STOP-LOSS TRIGGERED on {ticker}: Current ${curr_price:.2f} <= SL ${sl_price:.2f}")
                    broker.close_position(ticker=ticker, current_price=curr_price)
                    closed_record = db.update_closed_trade(
                        trade_id=open_trade.id,
                        exit_price=curr_price,
                        exit_reason="Stop Loss Triggered (-2%)",
                    )
                    execution_results.append({
                        "ticker": ticker,
                        "action": "CLOSE_SL",
                        "exit_price": curr_price,
                        "pnl_percent": closed_record.pnl_percent if closed_record else -2.0,
                    })
                elif curr_price >= tp_price:
                    logger.info(f"🎯 TAKE-PROFIT TRIGGERED on {ticker}: Current ${curr_price:.2f} >= TP ${tp_price:.2f}")
                    broker.close_position(ticker=ticker, current_price=curr_price)
                    closed_record = db.update_closed_trade(
                        trade_id=open_trade.id,
                        exit_price=curr_price,
                        exit_reason="Take Profit Triggered (+4%)",
                    )
                    execution_results.append({
                        "ticker": ticker,
                        "action": "CLOSE_TP",
                        "exit_price": curr_price,
                        "pnl_percent": closed_record.pnl_percent if closed_record else 4.0,
                    })

    # 2. Execute new approved decisions
    for decision in approved_decisions:
        ticker = decision["ticker"]
        action = decision["action"].upper()
        qty = float(decision.get("quantity", 0))
        price = float(decision.get("entry_price", 0))
        sl = float(decision.get("stop_loss", 0))
        tp = float(decision.get("take_profit", 0))

        if action == "HOLD":
            execution_results.append({"ticker": ticker, "action": "HOLD", "status": "no_order"})
            continue

        # Symbol routing check: Indian vs US Equities
        if ticker.upper().endswith(".NS") or ticker.upper().endswith(".BO"):
            logger.error(f"❌ Indian broker executor not configured — NSE trade skipped: {ticker}")
            execution_results.append({
                "ticker": ticker,
                "action": action,
                "status": "skipped",
                "reason": f"Indian broker executor not configured — NSE trade skipped: {ticker}",
            })
            continue

        logger.info(f"[Alpaca Route] Routing {ticker} order to Alpaca executor")

        try:
            if action == "BUY" and qty > 0:
                order_res = broker.submit_order(
                    ticker=ticker,
                    qty=qty,
                    side="buy",
                    current_price=price,
                    stop_loss_price=sl,
                    take_profit_price=tp,
                    is_backtest=is_backtest,
                )
                decision["order_id"] = order_res.get("order_id")
                execution_results.append({
                    "ticker": ticker,
                    "action": "BUY",
                    "qty": qty,
                    "price": price,
                    "order_response": order_res,
                })

            elif action == "SELL":
                order_res = broker.submit_order(
                    ticker=ticker,
                    qty=qty,
                    side="sell",
                    current_price=price,
                    is_backtest=is_backtest,
                )
                # Close matching open trade in database
                open_trades = db.get_open_trades(ticker=ticker)
                for ot in open_trades:
                    db.update_closed_trade(
                        trade_id=ot.id,
                        exit_price=price,
                        exit_reason="Signal SELL",
                    )
                execution_results.append({
                    "ticker": ticker,
                    "action": "SELL",
                    "qty": qty,
                    "price": price,
                    "order_response": order_res,
                })

        except Exception as e:
            logger.error(f"Error executing order for {ticker}: {e}")
            execution_results.append({
                "ticker": ticker,
                "action": action,
                "status": "error",
                "error": str(e),
            })

    return {"execution_results": execution_results}
