"""Exit Monitor Engine for Paper Trading.

Monitors active open paper positions every 60s during market hours:
- Evaluates real current prices against Stop-Loss (1.5xATR) and Take-Profit (3.0xATR).
- Simulates realistic fill execution at real market exit prices.
- Computes realized PnL and exact R-multiples signed by direction.
- Supports optional ATR trailing stops (default OFF).
- Emits formatted [EXIT] logs and periodic [HEARTBEAT] statuses.
"""

from __future__ import annotations

import time
import threading
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime, date

from config import (
    logger,
    SL_ATR_MULT,
    TP_ATR_MULT,
    TRAILING_STOP,
    PAPER_CAPITAL,
    EXECUTION_MODE,
)
from storage.database import TradeDatabase
from storage.models import TradeRecord, TradeStatus
from broker.alpaca_client import is_us_market_open
from data.market_data import get_market_snapshot


def get_realized_pnl_today(db: Optional[TradeDatabase] = None) -> float:
    """Calculates cumulative realized PnL in dollars for all trades closed today."""
    db = db or TradeDatabase()
    today_str = date.today().isoformat()
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pnl_amount FROM trades WHERE status = 'CLOSED' AND exit_timestamp LIKE ?",
            (f"{today_str}%",),
        )
        rows = cursor.fetchall()
        return sum(row["pnl_amount"] for row in rows if row["pnl_amount"] is not None)


class ExitMonitor:
    """Monitors open paper trades for SL/TP hits and manages exits."""

    def __init__(self, db: Optional[TradeDatabase] = None):
        self.db = db or TradeDatabase()

    def get_current_price_and_atr(self, ticker: str) -> tuple[Optional[float], Optional[float]]:
        """Fetches current price and ATR(14) for a ticker."""
        try:
            snapshot = get_market_snapshot(ticker)
            if snapshot and snapshot.current_price > 0:
                atr = float(snapshot.indicators.atr_14 or (snapshot.current_price * 0.02))
                return snapshot.current_price, atr
        except Exception as e:
            logger.debug(f"[EXIT_MONITOR] Snapshot fetch failed for {ticker}: {e}")
        return None, None

    def monitor_open_positions(
        self, price_overrides: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Scans all active OPEN paper trades and executes SL/TP exits.
        
        Args:
            price_overrides: Optional dict mapping ticker -> price for test simulation.
        
        Returns:
            List of closed trade execution dicts.
        """
        open_trades = [t for t in self.db.get_open_trades() if getattr(t, "mode", "paper") in ("paper", "test")]
        if not open_trades:
            return []

        closed_trades: List[Dict[str, Any]] = []

        for trade in open_trades:
            try:
                ticker = trade.ticker
                action = trade.action.upper()
                entry_price = float(trade.entry_price)
                sl_price = float(trade.stop_loss)
                tp_price = float(trade.take_profit)

                # Determine real current price & ATR
                if price_overrides and ticker in price_overrides:
                    current_price = float(price_overrides[ticker])
                    atr_14 = max(0.01, current_price * 0.02)
                else:
                    current_price, atr_14 = self.get_current_price_and_atr(ticker)

                if current_price is None or current_price <= 0:
                    continue

                # ---------------------------------------------------------
                # 1. OPTIONAL TRAILING STOP (Default OFF via config)
                # ---------------------------------------------------------
                if TRAILING_STOP and atr_14 and atr_14 > 0:
                    if action == "BUY":
                        # After price moves +1xATR in favor, trail SL to entry + 0.5xATR
                        if current_price >= entry_price + (1.0 * atr_14):
                            new_sl = round(entry_price + (0.5 * atr_14), 2)
                            if new_sl > sl_price:
                                self.db.update_trade_stop_loss(trade.id, new_sl)
                                logger.info(f"[TRAILING] Trade #{trade.id} {ticker} LONG SL trailed from ${sl_price:.2f} to ${new_sl:.2f}")
                                sl_price = new_sl
                                trade.stop_loss = new_sl
                    elif action == "SELL":  # SHORT
                        # After price moves -1xATR in favor, trail SL to entry - 0.5xATR
                        if current_price <= entry_price - (1.0 * atr_14):
                            new_sl = round(entry_price - (0.5 * atr_14), 2)
                            if new_sl < sl_price:
                                self.db.update_trade_stop_loss(trade.id, new_sl)
                                logger.info(f"[TRAILING] Trade #{trade.id} {ticker} SHORT SL trailed from ${sl_price:.2f} to ${new_sl:.2f}")
                                sl_price = new_sl
                                trade.stop_loss = new_sl

                # ---------------------------------------------------------
                # 2. EVALUATE SL / TP TRIGGERS
                # ---------------------------------------------------------
                sl_dist = abs(entry_price - sl_price)
                if sl_dist <= 0:
                    sl_dist = max(0.01, entry_price * 0.02)

                is_exit = False
                exit_reason = ""
                hit_type = ""

                if action == "BUY":
                    if current_price <= sl_price:
                        is_exit = True
                        hit_type = "SL hit"
                        exit_reason = f"SL ({SL_ATR_MULT}xATR)"
                    elif current_price >= tp_price:
                        is_exit = True
                        hit_type = "TP hit"
                        exit_reason = f"TP ({TP_ATR_MULT}xATR)"
                elif action == "SELL":  # SHORT
                    if current_price >= sl_price:
                        is_exit = True
                        hit_type = "SL hit"
                        exit_reason = f"SL ({SL_ATR_MULT}xATR)"
                    elif current_price <= tp_price:
                        is_exit = True
                        hit_type = "TP hit"
                        exit_reason = f"TP ({TP_ATR_MULT}xATR)"

                if not is_exit:
                    continue

                # Calculate realized PnL and signed R-Multiple
                if action == "BUY":
                    pnl_amount = (current_price - entry_price) * trade.quantity
                    r_multiple = (current_price - entry_price) / sl_dist
                    dir_label = "LONG"
                else:
                    pnl_amount = (entry_price - current_price) * trade.quantity
                    r_multiple = (trade.entry_price - current_price) / sl_dist
                    dir_label = "SHORT"

                # Update DB with real fill price and exit details
                closed_record = self.db.update_closed_trade(
                    trade_id=trade.id,
                    exit_price=current_price,
                    exit_reason=exit_reason,
                )

                # Log exact requested format:
                # "[EXIT] Trade #589 NVDA LONG closed @ $172.90 | SL hit | PnL: -$991.20 | -1.02R"
                log_msg = (
                    f"[EXIT] Trade #{trade.id} {ticker} {dir_label} closed @ ${current_price:.2f} | "
                    f"{hit_type} | PnL: ${pnl_amount:+,.2f} | {r_multiple:+.2f}R"
                )
                logger.info(log_msg)

                closed_trades.append({
                    "trade_id": trade.id,
                    "ticker": ticker,
                    "direction": dir_label,
                    "entry_price": entry_price,
                    "exit_price": current_price,
                    "quantity": trade.quantity,
                    "hit_type": hit_type,
                    "exit_reason": exit_reason,
                    "pnl_amount": pnl_amount,
                    "r_multiple": r_multiple,
                    "log_msg": log_msg,
                })

            except Exception as e:
                logger.error(
                    f"[EXIT_MONITOR] Crash prevented: Error monitoring trade #{trade.id} ({trade.ticker}): {e}\n"
                    f"{traceback.format_exc()}"
                )
                continue

        return closed_trades

    def get_heartbeat_log(self) -> str:
        """Constructs the 5-minute heartbeat status string per canonical specification."""
        try:
            from server.webhook import get_heartbeat_data, format_heartbeat_log
            return format_heartbeat_log(get_heartbeat_data())
        except Exception as e:
            logger.error(f"[HEARTBEAT] Error generating exit monitor heartbeat: {e}", exc_info=True)
            return f"[HEARTBEAT] ts={datetime.utcnow().isoformat()}Z | open=0 | closed=0 | capital=${PAPER_CAPITAL:,.2f} | market=UNKNOWN | last_signal_age=never"

    def run_loop(
        self,
        interval_sec: int = 60,
        heartbeat_interval_sec: int = 300,
        stop_event: Optional[threading.Event] = None,
        force_market_open: bool = False,
    ):
        """Runs the continuous monitoring loop."""
        logger.info(f"[EXIT_MONITOR] Starting exit monitor loop (Check interval: {interval_sec}s, Heartbeat: {heartbeat_interval_sec}s)...")
        last_heartbeat = 0.0

        while stop_event is None or not stop_event.is_set():
            now = time.time()

            # Heartbeat check
            if now - last_heartbeat >= heartbeat_interval_sec:
                logger.info(self.get_heartbeat_log())
                last_heartbeat = now

            # Market hours check
            if not force_market_open:
                is_open, _ = is_us_market_open()
                if not is_open:
                    time.sleep(min(30, interval_sec))
                    continue

            # Run open position monitoring with loop-level safety
            try:
                self.monitor_open_positions()
            except Exception as e:
                logger.error(f"[EXIT_MONITOR] Unexpected crash-level error in monitor loop: {e}\n{traceback.format_exc()}")

            time.sleep(interval_sec)
