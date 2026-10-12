"""Shared state schema for LangGraph agent workflow."""

from __future__ import annotations

from typing import TypedDict, List, Dict, Any, Optional
from storage.models import MarketSnapshot, TradeDecision


class AgentState(TypedDict, total=False):
    """LangGraph state passed between decision and execution nodes."""
    tickers: List[str]
    timestamp: str
    is_backtest: bool
    market_snapshots: Dict[str, Dict[str, Any]]
    past_lessons: List[str]
    raw_decisions: List[Dict[str, Any]]
    approved_decisions: List[Dict[str, Any]]
    rejected_decisions: List[Dict[str, Any]]
    account_info: Dict[str, Any]
    open_positions: List[Dict[str, Any]]
    execution_results: List[Dict[str, Any]]
    logged_trades: List[int]
    errors: List[str]
