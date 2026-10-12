"""FETCH_DATA Node: Downloads historical OHLCV data and computes technical indicators."""

from __future__ import annotations

from typing import Dict, Any, List
from datetime import datetime

from config import logger, TICKERS
from graph.state import AgentState
from data.market_data import get_market_snapshot
from data.indicators import compute_indicators
from storage.models import MarketSnapshot


def fetch_data_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node to fetch market data and calculate indicators for target tickers."""
    tickers: List[str] = state.get("tickers") or TICKERS
    logger.info(f"--- [NODE: FETCH_DATA] Processing {len(tickers)} tickers ---")

    market_snapshots: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = list(state.get("errors", []))

    for ticker in tickers:
        try:
            snapshot = get_market_snapshot(ticker=ticker)
            if snapshot:
                market_snapshots[ticker] = snapshot.to_dict()
                logger.info(f"  ✓ {ticker}: Price=${snapshot.current_price:.2f} | RSI={snapshot.indicators.rsi_14:.1f} | MACD Hist={snapshot.indicators.macd_hist:+.2f}")
            else:
                msg = f"Failed to generate market snapshot for {ticker}"
                logger.warning(msg)
                errors.append(msg)
        except Exception as e:
            err_msg = f"Exception fetching data for {ticker}: {str(e)}"
            logger.error(err_msg)
            errors.append(err_msg)

    return {
        "market_snapshots": market_snapshots,
        "errors": errors,
        "timestamp": datetime.utcnow().isoformat(),
    }
