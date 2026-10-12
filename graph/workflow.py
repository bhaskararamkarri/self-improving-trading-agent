"""LangGraph state machine defining the autonomous trading and self-improvement pipeline."""

from __future__ import annotations

from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, START, END

from graph.state import AgentState
from nodes.fetch_data import fetch_data_node
from nodes.analyze import analyze_node
from nodes.risk_check import risk_check_node
from nodes.execute import execute_node
from nodes.log_trade import log_trade_node
from config import logger


def build_trading_graph() -> Any:
    """Builds and compiles the complete LangGraph trading agent state machine."""
    workflow = StateGraph(AgentState)

    # 1. Add all nodes
    workflow.add_node("fetch_data", fetch_data_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("risk_check", risk_check_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("log_trade", log_trade_node)

    # 2. Add sequential deterministic edges
    workflow.add_edge(START, "fetch_data")
    workflow.add_edge("fetch_data", "analyze")
    workflow.add_edge("analyze", "risk_check")
    workflow.add_edge("risk_check", "execute")
    workflow.add_edge("execute", "log_trade")
    workflow.add_edge("log_trade", END)

    # 3. Compile graph
    app = workflow.compile()
    logger.info("Compiled LangGraph trading workflow successfully.")
    return app


def run_trading_cycle(
    tickers: Optional[list[str]] = None,
    is_backtest: bool = False,
) -> Dict[str, Any]:
    """Executes a single end-to-end trading cycle through the compiled LangGraph workflow."""
    from config import TICKERS
    target_tickers = tickers or TICKERS

    initial_state: AgentState = {
        "tickers": target_tickers,
        "is_backtest": is_backtest,
        "errors": [],
    }

    graph = build_trading_graph()
    final_state = graph.invoke(initial_state)
    return final_state
