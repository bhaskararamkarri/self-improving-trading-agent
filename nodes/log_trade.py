"""LOG_TRADE Node: Persists trade decisions, indicators, and market snapshots to SQLite journal."""

from __future__ import annotations

import json
from typing import Dict, Any, List
from datetime import datetime

from config import logger
from graph.state import AgentState
from storage.database import TradeDatabase
from storage.models import TradeRecord, TradeStatus


def log_trade_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node saving trade executions and rejected signals to SQLite database."""
    approved_decisions = state.get("approved_decisions", [])
    rejected_decisions = state.get("rejected_decisions", [])
    snapshots = state.get("market_snapshots", {})

    logger.info(f"--- [NODE: LOG_TRADE] Logging trade records to SQLite ---")
    db = TradeDatabase()
    logged_trade_ids: List[int] = []

    # 1. Log Approved Executions (BUY / SELL)
    for dec in approved_decisions:
        ticker = dec["ticker"]
        action = dec["action"].upper()
        if action == "HOLD":
            continue

        snap = snapshots.get(ticker, {})
        indicators_json = json.dumps(snap.get("indicators", {}))
        market_conditions = snap.get("trend_summary", "")

        trade = TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            ticker=ticker,
            action=action,
            quantity=float(dec.get("quantity", 0)),
            entry_price=float(dec.get("entry_price", 0)),
            stop_loss=float(dec.get("stop_loss", 0)),
            take_profit=float(dec.get("take_profit", 0)),
            confidence=float(dec.get("confidence", 0)),
            reasoning=dec.get("reasoning", ""),
            indicators_json=indicators_json,
            market_conditions=market_conditions,
            status=TradeStatus.OPEN.value if action == "BUY" else TradeStatus.CLOSED.value,
            order_id=dec.get("order_id"),
        )
        trade_id = db.log_trade(trade)
        logged_trade_ids.append(trade_id)

    # 2. Log Rejected Signals for Auditing and Reflection
    for dec in rejected_decisions:
        ticker = dec["ticker"]
        snap = snapshots.get(ticker, {})
        indicators_json = json.dumps(snap.get("indicators", {}))
        market_conditions = snap.get("trend_summary", "")

        trade = TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            ticker=ticker,
            action=dec.get("action", "HOLD"),
            quantity=0,
            entry_price=float(dec.get("entry_price", 0)),
            stop_loss=0,
            take_profit=0,
            confidence=float(dec.get("confidence", 0)),
            reasoning=f"[RISK REJECTED: {dec.get('rejection_reason')}] {dec.get('reasoning', '')}",
            indicators_json=indicators_json,
            market_conditions=market_conditions,
            status=TradeStatus.REJECTED.value,
            exit_reason=dec.get("rejection_reason"),
        )
        trade_id = db.log_trade(trade)
        logged_trade_ids.append(trade_id)

    logger.info(f"Successfully logged {len(logged_trade_ids)} trade records.")
    return {"logged_trades": logged_trade_ids}
