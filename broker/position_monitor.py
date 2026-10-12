"""Position Monitor: Background thread that continuously monitors open positions for SL/TP hits with gap protection."""

from __future__ import annotations

import threading
import time
from typing import Dict, Any, List, Optional, Callable

from config import (
    logger,
    DRY_RUN,
    LIVE_TRADING,
    MONITOR_INTERVAL,
)
from broker.alpaca_client import AlpacaBrokerClient
from storage.database import TradeDatabase
from storage.models import TradeRecord


class PositionMonitor:
    """Monitors active open positions every N seconds (default 30s) in a background thread.
    
    Features:
    - SL / TP immediate triggers
    - Gap protection: If price gaps past the SL (e.g., opens lower than SL for long),
      it exits at the realistic current price instead of assuming the ideal SL price.
    - Thread-based execution: Does not block the main scheduler or trading loop.
    - Respects DRY_RUN: When DRY_RUN=True, only simulated exits are executed.
    - Graceful shutdown: Reports open positions on stop or KeyboardInterrupt.
    """

    def __init__(
        self,
        broker: Optional[AlpacaBrokerClient] = None,
        db: Optional[TradeDatabase] = None,
        interval_sec: float = MONITOR_INTERVAL,
        dry_run: bool = DRY_RUN,
        price_fetcher: Optional[Callable[[str], Optional[float]]] = None,
    ):
        self.broker = broker or AlpacaBrokerClient()
        self.db = db or TradeDatabase()
        self.interval_sec = max(1.0, float(interval_sec))
        self.dry_run = dry_run
        self.price_fetcher = price_fetcher

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Starts the background position monitoring daemon thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("[MONITOR] Position monitor thread is already running.")
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="PositionMonitorThread",
                daemon=True,
            )
            self._thread.start()
            logger.info(f"[MONITOR] Started SL/TP position monitor thread (interval: {self.interval_sec}s, dry_run: {self.dry_run}).")

    def stop(self, timeout: float = 5.0) -> None:
        """Signals the monitor thread to stop and waits for completion."""
        with self._lock:
            if self._thread is None:
                return
            logger.info("[MONITOR] Stopping position monitor thread...")
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("[MONITOR] Position monitor thread stopped gracefully.")

    def is_running(self) -> bool:
        """Returns True if the background monitor thread is active."""
        return self._thread is not None and self._thread.is_alive()

    def _fetch_current_price(self, ticker: str) -> Optional[float]:
        """Fetches latest price using injected fetcher or market data."""
        if self.price_fetcher is not None:
            try:
                return self.price_fetcher(ticker)
            except Exception as e:
                logger.error(f"[MONITOR] Error in custom price fetcher for {ticker}: {e}")
                return None

        try:
            from data.market_data import fetch_historical_ohlcv
            df = fetch_historical_ohlcv(ticker=ticker, period="1d", interval="1min")
            if df is not None and not df.empty:
                return float(df["close"].iloc[-1])
        except Exception as e:
            logger.debug(f"[MONITOR] Failed to fetch 1min bar for {ticker}: {e}")

        # Fallback to daily bar
        try:
            from data.market_data import fetch_historical_ohlcv
            df = fetch_historical_ohlcv(ticker=ticker, period="5d", interval="1d")
            if df is not None and not df.empty:
                return float(df["close"].iloc[-1])
        except Exception as e:
            logger.error(f"[MONITOR] Failed to fetch current price for {ticker}: {e}")

        return None

    def check_positions(self) -> List[Dict[str, Any]]:
        """Evaluates all open positions against SL/TP with gap protection.
        
        Returns:
            List of executed exit action details.
        """
        exits: List[Dict[str, Any]] = []
        open_trades = self.db.get_open_trades()

        for trade in open_trades:
            ticker = trade.ticker
            action = trade.action.upper()
            entry_price = float(trade.entry_price)
            sl_price = float(trade.stop_loss)
            tp_price = float(trade.take_profit)
            qty = float(trade.quantity)

            current_price = self._fetch_current_price(ticker)
            if current_price is None or current_price <= 0:
                continue

            hit_exit = False
            exit_type = ""
            exit_reason = ""

            if action == "BUY":
                # Long Stop-Loss & Gap Protection
                if current_price <= sl_price:
                    hit_exit = True
                    exit_type = "SL"
                    if current_price < sl_price:
                        # Price gapped past SL
                        exit_reason = f"SL hit with gap past {sl_price:.2f} -> filled @ {current_price:.2f}"
                        logger.warning(
                            f"[MONITOR] SL hit on {ticker} @ {current_price:.2f} "
                            f"(GAP PROTECTION: Price gapped below SL ${sl_price:.2f} -> executing at current market ${current_price:.2f})"
                        )
                    else:
                        exit_reason = f"SL hit @ {current_price:.2f}"
                        logger.warning(f"[MONITOR] SL hit on {ticker} @ {current_price:.2f}")

                # Long Take-Profit
                elif current_price >= tp_price:
                    hit_exit = True
                    exit_type = "TP"
                    exit_reason = f"TP hit @ {current_price:.2f}"
                    logger.info(f"[MONITOR] TP hit on {ticker} @ {current_price:.2f}")

            elif action == "SHORT":
                # Short Stop-Loss & Gap Protection
                if current_price >= sl_price:
                    hit_exit = True
                    exit_type = "SL"
                    if current_price > sl_price:
                        exit_reason = f"Short SL hit with gap past {sl_price:.2f} -> filled @ {current_price:.2f}"
                        logger.warning(
                            f"[MONITOR] SL hit on {ticker} @ {current_price:.2f} "
                            f"(GAP PROTECTION: Price gapped above SL ${sl_price:.2f} -> executing at current market ${current_price:.2f})"
                        )
                    else:
                        exit_reason = f"Short SL hit @ {current_price:.2f}"
                        logger.warning(f"[MONITOR] SL hit on {ticker} @ {current_price:.2f}")

                # Short Take-Profit
                elif current_price <= tp_price:
                    hit_exit = True
                    exit_type = "TP"
                    exit_reason = f"Short TP hit @ {current_price:.2f}"
                    logger.info(f"[MONITOR] TP hit on {ticker} @ {current_price:.2f}")

            if hit_exit:
                # Execute realistic exit at current_price
                if self.dry_run:
                    logger.info(f"[MONITOR] [DRY_RUN] Simulated exit for {ticker} @ ${current_price:.2f} ({exit_reason})")
                    close_res = self.broker.close_position(ticker, current_price=current_price)
                else:
                    close_res = self.broker.close_position(ticker, current_price=current_price)

                closed_trade = self.db.update_closed_trade(
                    trade_id=trade.id,
                    exit_price=current_price,
                    exit_reason=exit_reason,
                )

                exits.append({
                    "ticker": ticker,
                    "trade_id": trade.id,
                    "exit_type": exit_type,
                    "entry_price": entry_price,
                    "exit_price": current_price,
                    "stop_loss": sl_price,
                    "take_profit": tp_price,
                    "pnl_percent": closed_trade.pnl_percent if closed_trade else 0.0,
                    "reason": exit_reason,
                    "broker_response": close_res,
                })

        # Also check local simulator positions if any exist outside DB
        for ticker, pos in list(self.broker.simulated_positions.items()):
            sl = float(pos.get("stop_loss", 0.0))
            tp = float(pos.get("take_profit", 0.0))
            if sl <= 0 and tp <= 0:
                continue

            current_price = self._fetch_current_price(ticker)
            if current_price is None or current_price <= 0:
                continue

            if sl > 0 and current_price <= sl:
                if current_price < sl:
                    logger.warning(
                        f"[MONITOR] SL hit on {ticker} @ {current_price:.2f} "
                        f"(GAP PROTECTION: Gapped below SL ${sl:.2f} -> filled @ {current_price:.2f})"
                    )
                else:
                    logger.warning(f"[MONITOR] SL hit on {ticker} @ {current_price:.2f}")
                self.broker.close_position(ticker, current_price=current_price)
            elif tp > 0 and current_price >= tp:
                logger.info(f"[MONITOR] TP hit on {ticker} @ {current_price:.2f}")
                self.broker.close_position(ticker, current_price=current_price)

        return exits

    def get_open_positions_summary(self) -> List[Dict[str, Any]]:
        """Returns structured data on all currently open positions."""
        summary: List[Dict[str, Any]] = []
        open_trades = self.db.get_open_trades()

        for t in open_trades:
            curr_p = self._fetch_current_price(t.ticker) or t.entry_price
            pnl_pct = ((curr_p - t.entry_price) / t.entry_price) * 100.0 if t.entry_price > 0 else 0.0
            summary.append({
                "ticker": t.ticker,
                "action": t.action,
                "qty": t.quantity,
                "entry_price": t.entry_price,
                "current_price": curr_p,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "unrealized_pnl_percent": pnl_pct,
            })
        return summary

    def report_open_positions(self) -> str:
        """Generates and logs an open positions report on shutdown."""
        summary = self.get_open_positions_summary()
        lines = [
            "=" * 50,
            "[MONITOR] Graceful Shutdown: Active Positions Report",
            "=" * 50,
        ]
        if not summary:
            lines.append("No active open positions remaining.")
        else:
            for p in summary:
                lines.append(
                    f"• {p['ticker']} ({p['action']}): {p['qty']} units @ ${p['entry_price']:.2f} "
                    f"| Current: ${p['current_price']:.2f} | Unr PnL: {p['unrealized_pnl_percent']:+.2f}% "
                    f"| SL: ${p['stop_loss']:.2f} | TP: ${p['take_profit']:.2f}"
                )
        lines.append("=" * 50)
        report_str = "\n".join(lines)
        logger.info(f"\n{report_str}")
        return report_str

    def _run_loop(self) -> None:
        """Background loop executing check_positions every interval_sec."""
        logger.debug("[MONITOR] Background thread loop started.")
        while not self._stop_event.is_set():
            try:
                self.check_positions()
            except Exception as e:
                logger.error(f"[MONITOR] Error during position check: {e}", exc_info=True)

            # Sleep in small increments for responsive stop_event handling
            elapsed = 0.0
            step = 0.5
            while elapsed < self.interval_sec and not self._stop_event.is_set():
                time.sleep(step)
                elapsed += step

        logger.debug("[MONITOR] Background thread loop exited.")
