"""External Signal Validator and Risk Sizing Layer.

Validates incoming webhook signals (TradingView alerts, external webhooks)
against market hours, price sanity, duplicate positions, and applies
strict risk management / ATR stop-loss calculations before paper or live execution.
"""

from __future__ import annotations

import math
import time
from typing import Dict, Any, Optional
from datetime import datetime

from config import (
    logger,
    RISK_PER_TRADE,
    SL_ATR_MULT,
    TP_ATR_MULT,
    USE_ATR_STOPS,
    POSITION_SIZING_MODE,
    INITIAL_PAPER_CASH,
    EXECUTION_MODE,
    LIVE_TRADING,
)
from broker.alpaca_client import is_us_market_open, AlpacaBrokerClient
from storage.database import TradeDatabase
from storage.models import TradeRecord, TradeStatus
from data.market_data import get_market_snapshot


class ExternalSignalValidator:
    """Validates external webhook signals and manages execution."""

    def __init__(self, db: Optional[TradeDatabase] = None, broker: Optional[AlpacaBrokerClient] = None):
        self.db = db or TradeDatabase()
        self.broker = broker or AlpacaBrokerClient()

    def get_current_market_metrics(self, ticker: str, fallback_price: float) -> tuple[float, float]:
        """Fetches current price and ATR(14) for the ticker, with safe fallbacks."""
        try:
            snapshot = get_market_snapshot(ticker)
            if snapshot and snapshot.current_price > 0:
                atr = float(snapshot.indicators.atr_14 or (snapshot.current_price * 0.02))
                return snapshot.current_price, atr
        except Exception as e:
            logger.warning(f"[SIGNAL] Could not fetch live snapshot for {ticker}: {e}. Using fallback.")

        # Fallback to webhook price and 2% ATR proxy
        return fallback_price, max(0.01, fallback_price * 0.02)

    def validate_and_process(
        self,
        ticker: str,
        action: str,
        webhook_price: float,
        timeframe: str = "1D",
        force_market_open: Optional[bool] = None,
        mock_current_price: Optional[float] = None,
        mock_atr: Optional[float] = None,
        alert_received_ts: Optional[str] = None,
        t_recv: Optional[float] = None,
        mode: str = "paper",
    ) -> Dict[str, Any]:
        """
        Processes an incoming webhook signal through validation and risk management.
        
        Decision Trail:
        [SIGNAL] Received → [VALIDATE] → [RISK] → [EXECUTE/SKIP]
        """
        ticker = ticker.upper().strip()
        action = action.upper().strip()

        logger.info(f"[SIGNAL] Received: {action} {ticker} @ ${webhook_price:.2f} (Timeframe: {timeframe})")

        # -------------------------------------------------------------
        # STEP 1: [VALIDATE] Market Hours
        # -------------------------------------------------------------
        if force_market_open is not None:
            market_open = force_market_open
            market_msg = "Market simulated open" if market_open else "Market simulated closed"
        else:
            market_open, market_msg = is_us_market_open()

        if not market_open:
            trail = f"[SIGNAL] Received {action} {ticker} @ ${webhook_price:.2f} → [VALIDATE] REJECT ({market_msg}) → [SKIP]"
            logger.warning(trail)
            return {
                "status": "rejected",
                "step": "VALIDATE",
                "reason": market_msg,
                "trail": trail,
            }

        # -------------------------------------------------------------
        # STEP 2: [VALIDATE] Price Sanity Check (|webhook - current| <= 2%)
        # -------------------------------------------------------------
        if mock_current_price is not None:
            current_price = mock_current_price
            atr_14 = mock_atr if mock_atr is not None else max(0.01, current_price * 0.02)
        else:
            current_price, atr_14 = self.get_current_market_metrics(ticker, webhook_price)

        if current_price > 0:
            deviation_pct = abs(webhook_price - current_price) / current_price
            if deviation_pct > 0.02:
                reason = f"[SIGNAL] Price deviation too large, possibly stale alert: Webhook ${webhook_price:.2f} vs Market ${current_price:.2f} ({deviation_pct*100:.1f}% > 2.0%)"
                trail = f"[SIGNAL] Received {action} {ticker} @ ${webhook_price:.2f} → [VALIDATE] REJECT ({reason}) → [SKIP]"
                logger.warning(trail)
                return {
                    "status": "rejected",
                    "step": "VALIDATE",
                    "reason": reason,
                    "trail": trail,
                }

        # -------------------------------------------------------------
        # STEP 3: Handle Position Closures (CLOSE or opposite action)
        # -------------------------------------------------------------
        open_trades = self.db.get_open_trades(ticker=ticker)
        if action == "CLOSE":
            if not open_trades:
                reason = f"No open position found to close for {ticker}"
                trail = f"[SIGNAL] Received CLOSE {ticker} @ ${webhook_price:.2f} → [VALIDATE] REJECT ({reason}) → [SKIP]"
                logger.warning(trail)
                return {
                    "status": "rejected",
                    "step": "VALIDATE",
                    "reason": reason,
                    "trail": trail,
                }
            # Close position in DB
            closed_results = []
            for ot in open_trades:
                closed = self.db.update_closed_trade(
                    trade_id=ot.id,
                    exit_price=webhook_price,
                    exit_reason="Webhook Signal CLOSE",
                )
                closed_results.append(closed)
            trail = f"[SIGNAL] Received CLOSE {ticker} @ ${webhook_price:.2f} → [VALIDATE] PASS → [RISK] N/A → [EXECUTE] Closed {len(closed_results)} trade(s)"
            logger.info(trail)
            return {
                "status": "executed",
                "action": "CLOSE",
                "ticker": ticker,
                "exit_price": webhook_price,
                "trades_closed": len(closed_results),
                "trail": trail,
            }

        # -------------------------------------------------------------
        # STEP 4: [VALIDATE] Duplicate Position Check
        # -------------------------------------------------------------
        if open_trades:
            reason = f"Duplicate position already open for {ticker} ({len(open_trades)} active)"
            trail = f"[SIGNAL] Received {action} {ticker} @ ${webhook_price:.2f} → [VALIDATE] REJECT ({reason}) → [SKIP]"
            logger.warning(trail)
            return {
                "status": "rejected",
                "step": "VALIDATE",
                "reason": reason,
                "trail": trail,
            }

        # -------------------------------------------------------------
        # STEP 5: [RISK] Risk Sizing & ATR Stops
        # -------------------------------------------------------------
        # Portfolio value determination
        try:
            account = self.broker.get_account()
            portfolio_val = float(account.get("portfolio_value", INITIAL_PAPER_CASH))
            if portfolio_val <= 0:
                portfolio_val = INITIAL_PAPER_CASH
        except Exception:
            portfolio_val = INITIAL_PAPER_CASH

        risk_dollars = portfolio_val * RISK_PER_TRADE  # e.g. 1% = $100

        # ATR distance
        if USE_ATR_STOPS and atr_14 > 0:
            sl_dist = SL_ATR_MULT * atr_14
            tp_dist = TP_ATR_MULT * atr_14
        else:
            sl_dist = webhook_price * 0.02
            tp_dist = webhook_price * 0.04

        if sl_dist <= 0:
            sl_dist = max(0.01, webhook_price * 0.02)

        # Risk-based sizing: qty = floor(risk_dollars / sl_dist)
        target_qty = math.floor(risk_dollars / sl_dist)

        # 25% max allocation safety cap
        max_alloc = portfolio_val * 0.25
        trade_cost = target_qty * webhook_price
        if trade_cost > max_alloc:
            trimmed_qty = math.floor(max_alloc / webhook_price)
            logger.info(f"[SIZE] Trimmed to capital cap: {trimmed_qty} (Cost: ${trimmed_qty * webhook_price:.2f})")
            qty = trimmed_qty
        else:
            qty = target_qty

        if qty <= 0:
            reason = f"Calculated quantity is 0 (Share price ${webhook_price:.2f} exceeds allocation)"
            trail = f"[SIGNAL] Received {action} {ticker} @ ${webhook_price:.2f} → [VALIDATE] PASS → [RISK] REJECT ({reason}) → [SKIP]"
            logger.warning(trail)
            return {
                "status": "rejected",
                "step": "RISK",
                "reason": reason,
                "trail": trail,
            }

        # Computed SL / TP levels
        if action in ("BUY", "LONG"):
            sl_price = round(webhook_price - sl_dist, 2)
            tp_price = round(webhook_price + tp_dist, 2)
            db_action = "BUY"
        else:  # SELL / SHORT
            sl_price = round(webhook_price + sl_dist, 2)
            tp_price = round(webhook_price - tp_dist, 2)
            db_action = "SELL"

        logger.info(
            f"[RISK] Approved sizing for {ticker}: {qty} shares @ ${webhook_price:.2f} | "
            f"SL: ${sl_price:.2f} ({SL_ATR_MULT}xATR) | TP: ${tp_price:.2f} ({TP_ATR_MULT}xATR) | "
            f"Risk Budget: ${risk_dollars:.2f}"
        )

        # -------------------------------------------------------------
        # STEP 6: [EXECUTE] Paper Execution & DB Journaling
        # -------------------------------------------------------------
        exec_mode = EXECUTION_MODE
        if exec_mode == "paper" or not LIVE_TRADING:
            now_dt = datetime.utcnow()
            fill_ts = now_dt.isoformat()
            alert_ts = alert_received_ts or fill_ts
            if t_recv is not None:
                latency_ms = round((time.time() - t_recv) * 1000.0, 2)
            else:
                latency_ms = 1.0

            # Paper/Test execution: simulated fill at webhook price
            effective_mode = mode.lower().strip() if mode else "paper"
            prefix = "test_ext" if effective_mode == "test" else "paper_ext"
            trade_record = TradeRecord(
                timestamp=fill_ts,
                ticker=ticker,
                action=db_action,
                quantity=float(qty),
                entry_price=float(webhook_price),
                stop_loss=float(sl_price),
                take_profit=float(tp_price),
                confidence=0.85,
                reasoning=f"External Webhook Alert [{timeframe}] filled at ${webhook_price:.2f}",
                status=TradeStatus.OPEN.value,
                mode=effective_mode,
                order_id=f"{prefix}_{int(now_dt.timestamp())}",
                alert_received_ts=alert_ts,
                fill_ts=fill_ts,
                latency_ms=latency_ms,
            )
            trade_id = self.db.log_trade(trade_record)
            trail = (
                f"[SIGNAL] Received {action} {ticker} @ ${webhook_price:.2f} → "
                f"[VALIDATE] PASS → [RISK] Qty {qty}, SL ${sl_price}, TP ${tp_price} → "
                f"[EXECUTE] Filled {db_action} {qty} shares in {effective_mode.upper()} mode (Trade #{trade_id}, Latency: {latency_ms:.1f}ms)"
            )
            logger.info(trail)
            return {
                "status": "executed",
                "trade_id": trade_id,
                "ticker": ticker,
                "action": db_action,
                "quantity": qty,
                "entry_price": webhook_price,
                "stop_loss": sl_price,
                "take_profit": tp_price,
                "mode": effective_mode,
                "alert_received_ts": alert_ts,
                "fill_ts": fill_ts,
                "latency_ms": latency_ms,
                "trail": trail,
            }
        else:
            # Live execution code path (strictly disabled in paper mode)
            trail = f"[SIGNAL] Received {action} {ticker} → [VALIDATE] PASS → [RISK] PASS → [EXECUTE] Live execution not allowed in safe configuration"
            logger.warning(trail)
            return {
                "status": "skipped",
                "step": "EXECUTE",
                "reason": "Live execution disabled",
                "trail": trail,
            }
