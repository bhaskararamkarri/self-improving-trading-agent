"""Data models and schemas for trading agent state, execution, and storage."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime


class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class IndicatorSnapshot:
    rsi_14: float = 50.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    ema_9: float = 0.0
    ema_21: float = 0.0
    ema_50: float = 0.0
    ema_50_prev: float = 0.0
    ema_50_slope: float = 0.0
    ema_200: float = 0.0
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_bandwidth: float = 0.0
    volume: float = 0.0
    volume_sma_20: float = 0.0
    volume_ratio: float = 1.0
    atr_14: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MarketSnapshot:
    ticker: str
    timestamp: str
    current_price: float
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    indicators: IndicatorSnapshot
    trend_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "current_price": round(self.current_price, 2),
            "open": round(self.open_price, 2),
            "high": round(self.high_price, 2),
            "low": round(self.low_price, 2),
            "close": round(self.close_price, 2),
            "volume": self.volume,
            "indicators": self.indicators.to_dict(),
            "trend_summary": self.trend_summary,
        }


@dataclass
class TradeDecision:
    ticker: str
    action: TradeAction
    confidence: float
    reasoning: str
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    quantity: float = 0.0
    rejection_reason: Optional[str] = None
    order_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "action": self.action.value if isinstance(self.action, TradeAction) else str(self.action),
            "confidence": round(float(self.confidence), 2),
            "reasoning": self.reasoning,
            "entry_price": round(float(self.entry_price), 2),
            "stop_loss": round(float(self.stop_loss), 2),
            "take_profit": round(float(self.take_profit), 2),
            "quantity": self.quantity,
            "rejection_reason": self.rejection_reason,
            "order_id": self.order_id,
        }


@dataclass
class TradeRecord:
    id: Optional[int] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ticker: str = ""
    action: str = "BUY"
    quantity: float = 0.0
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    stop_loss: float = 0.0
    take_profit: float = 0.0
    confidence: float = 0.0
    reasoning: str = ""
    indicators_json: str = "{}"
    market_conditions: str = ""
    status: str = TradeStatus.OPEN.value
    pnl_amount: Optional[float] = None
    pnl_percent: Optional[float] = None
    exit_timestamp: Optional[str] = None
    exit_reason: Optional[str] = None
    order_id: Optional[str] = None
    mode: str = "paper"
    alert_received_ts: Optional[str] = None
    fill_ts: Optional[str] = None
    latency_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Lesson:
    id: str
    timestamp: str
    text: str
    tags: List[str]
    category: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyStats:
    strategy_name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_pnl_percent: float = 0.0
    total_pnl_percent: float = 0.0
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())
