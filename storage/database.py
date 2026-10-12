"""SQLite database operations for Trade Journal and Strategy Statistics."""

from __future__ import annotations

import json
import sqlite3
import traceback
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from config import DATABASE_PATH, logger
from storage.models import TradeRecord, TradeStatus, StrategyStats


class TradeDatabase:
    """Manages SQLite persistent storage for trades and performance metrics."""

    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = Path(db_path)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Creates tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT,
                    indicators_json TEXT,
                    market_conditions TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    pnl_amount REAL,
                    pnl_percent REAL,
                    exit_timestamp TEXT,
                    exit_reason TEXT,
                    order_id TEXT,
                    mode TEXT DEFAULT 'paper',
                    alert_received_ts TEXT,
                    fill_ts TEXT,
                    latency_ms REAL
                );
            """)

            # Ensure columns exist if table was already created
            cursor.execute("PRAGMA table_info(trades)")
            columns = [c[1] for c in cursor.fetchall()]
            if "mode" not in columns:
                cursor.execute("ALTER TABLE trades ADD COLUMN mode TEXT DEFAULT 'paper'")
            if "alert_received_ts" not in columns:
                cursor.execute("ALTER TABLE trades ADD COLUMN alert_received_ts TEXT")
            if "fill_ts" not in columns:
                cursor.execute("ALTER TABLE trades ADD COLUMN fill_ts TEXT")
            if "latency_ms" not in columns:
                cursor.execute("ALTER TABLE trades ADD COLUMN latency_ms REAL")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_stats (
                    strategy_name TEXT PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0.0,
                    avg_pnl_percent REAL DEFAULT 0.0,
                    total_pnl_percent REAL DEFAULT 0.0,
                    last_updated TEXT NOT NULL
                );
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
            """)
            conn.commit()

    def log_trade(self, trade: TradeRecord) -> int:
        """Inserts a new trade record with explicit transaction safety and returns its database ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            mode_val = getattr(trade, "mode", "paper") or "paper"
            alert_ts = getattr(trade, "alert_received_ts", None)
            fill_ts = getattr(trade, "fill_ts", None)
            lat_ms = getattr(trade, "latency_ms", None)

            cursor.execute("""
                INSERT INTO trades (
                    timestamp, ticker, action, quantity, entry_price, exit_price,
                    stop_loss, take_profit, confidence, reasoning, indicators_json,
                    market_conditions, status, pnl_amount, pnl_percent, exit_timestamp,
                    exit_reason, order_id, mode, alert_received_ts, fill_ts, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.timestamp,
                trade.ticker,
                trade.action,
                trade.quantity,
                trade.entry_price,
                trade.exit_price,
                trade.stop_loss,
                trade.take_profit,
                trade.confidence,
                trade.reasoning,
                trade.indicators_json,
                trade.market_conditions,
                trade.status,
                trade.pnl_amount,
                trade.pnl_percent,
                trade.exit_timestamp,
                trade.exit_reason,
                trade.order_id,
                mode_val,
                alert_ts,
                fill_ts,
                lat_ms,
            ))
            conn.commit()
            trade_id = cursor.lastrowid
            lat_str = f", Latency: {lat_ms:.1f}ms" if lat_ms is not None else ""
            logger.info(f"Logged trade #{trade_id}: {trade.action} {trade.quantity} {trade.ticker} @ ${trade.entry_price:.2f} (Status: {trade.status}, Mode: {mode_val}{lat_str})")
            return trade_id
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(
                f"[ERROR] DB COMMIT FAILED for trade: {trade.action} {trade.quantity} {trade.ticker} @ ${trade.entry_price:.2f} (order_id={getattr(trade, 'order_id', None)}): {e}\n"
                f"{traceback.format_exc()}"
            )
            raise
        finally:
            conn.close()

    def get_open_trades(self, ticker: Optional[str] = None, mode: Optional[str] = None) -> List[TradeRecord]:
        """Retrieves all active open trades, optionally filtered by ticker and/or mode."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM trades WHERE status = 'OPEN'"
            params = []
            if ticker:
                query += " AND ticker = ?"
                params.append(ticker)
            if mode:
                query += " AND mode = ?"
                params.append(mode)
            query += " ORDER BY id ASC"
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_trade_record(row) for row in rows]

    def get_recent_trades(self, limit: int = 30) -> List[TradeRecord]:
        """Fetches the last N trades for reflection analysis."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [self._row_to_trade_record(row) for row in rows]

    def get_closed_trades(self, limit: int = 50) -> List[TradeRecord]:
        """Fetches the last N closed trades."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [self._row_to_trade_record(row) for row in rows]

    def update_closed_trade(
        self,
        trade_id: int,
        exit_price: float,
        exit_reason: str,
        exit_timestamp: Optional[str] = None,
    ) -> Optional[TradeRecord]:
        """Updates an open trade when closed with PnL and exit details."""
        if exit_timestamp is None:
            exit_timestamp = datetime.utcnow().isoformat()

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"Trade #{trade_id} not found to close.")
                return None

            trade = self._row_to_trade_record(row)
            entry_price = trade.entry_price
            qty = trade.quantity

            # Calculate PnL
            if trade.action == "BUY":
                pnl_amount = (exit_price - entry_price) * qty
                pnl_percent = ((exit_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
            else:  # Short / SELL
                pnl_amount = (entry_price - exit_price) * qty
                pnl_percent = ((entry_price - exit_price) / entry_price) * 100.0 if entry_price > 0 else 0.0

            cursor.execute("""
                UPDATE trades
                SET exit_price = ?,
                    exit_timestamp = ?,
                    exit_reason = ?,
                    status = 'CLOSED',
                    pnl_amount = ?,
                    pnl_percent = ?
                WHERE id = ?
            """, (exit_price, exit_timestamp, exit_reason, pnl_amount, pnl_percent, trade_id))
            conn.commit()

            trade.exit_price = exit_price
            trade.exit_timestamp = exit_timestamp
            trade.exit_reason = exit_reason
            trade.status = TradeStatus.CLOSED.value
            trade.pnl_amount = pnl_amount
            trade.pnl_percent = pnl_percent

            logger.info(f"Closed trade #{trade_id} ({trade.ticker}): Exit ${exit_price:.2f}, PnL: {pnl_percent:+.2f}% (${pnl_amount:+.2f}), Reason: {exit_reason}")
            self.recalculate_strategy_stats()
            return trade
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"[ERROR] DB COMMIT FAILED for trade close #{trade_id}: {e}\n{traceback.format_exc()}")
            raise
        finally:
            conn.close()

    def update_trade_stop_loss(self, trade_id: int, new_sl: float) -> bool:
        """Updates the stop-loss level for an active trade (used for trailing stops)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE trades SET stop_loss = ? WHERE id = ? AND status = 'OPEN'", (new_sl, trade_id))
            conn.commit()
            return cursor.rowcount > 0

    def recalculate_strategy_stats(self, strategy_name: str = "SelfImprovingAgent") -> StrategyStats:
        """Calculates win rate and average PnL across all closed trades."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pnl_percent FROM trades WHERE status = 'CLOSED'")
            rows = cursor.fetchall()

            total_trades = len(rows)
            if total_trades == 0:
                stats = StrategyStats(strategy_name=strategy_name)
            else:
                pnls = [row["pnl_percent"] for row in rows if row["pnl_percent"] is not None]
                wins = sum(1 for p in pnls if p > 0)
                losses = sum(1 for p in pnls if p <= 0)
                win_rate = (wins / total_trades) * 100.0 if total_trades > 0 else 0.0
                avg_pnl = sum(pnls) / total_trades if total_trades > 0 else 0.0
                total_pnl = sum(pnls)

                stats = StrategyStats(
                    strategy_name=strategy_name,
                    total_trades=total_trades,
                    wins=wins,
                    losses=losses,
                    win_rate=round(win_rate, 2),
                    avg_pnl_percent=round(avg_pnl, 2),
                    total_pnl_percent=round(total_pnl, 2),
                    last_updated=datetime.utcnow().isoformat(),
                )

            cursor.execute("""
                INSERT INTO strategy_stats (
                    strategy_name, total_trades, wins, losses, win_rate, avg_pnl_percent, total_pnl_percent, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_name) DO UPDATE SET
                    total_trades=excluded.total_trades,
                    wins=excluded.wins,
                    losses=excluded.losses,
                    win_rate=excluded.win_rate,
                    avg_pnl_percent=excluded.avg_pnl_percent,
                    total_pnl_percent=excluded.total_pnl_percent,
                    last_updated=excluded.last_updated
            """, (
                stats.strategy_name,
                stats.total_trades,
                stats.wins,
                stats.losses,
                stats.win_rate,
                stats.avg_pnl_percent,
                stats.total_pnl_percent,
                stats.last_updated,
            ))
            conn.commit()
            return stats

    def get_strategy_stats(self, strategy_name: str = "SelfImprovingAgent") -> Optional[StrategyStats]:
        """Retrieves stored strategy performance stats."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM strategy_stats WHERE strategy_name = ?", (strategy_name,))
            row = cursor.fetchone()
            if not row:
                return self.recalculate_strategy_stats(strategy_name)
            return StrategyStats(
                strategy_name=row["strategy_name"],
                total_trades=row["total_trades"],
                wins=row["wins"],
                losses=row["losses"],
                win_rate=row["win_rate"],
                avg_pnl_percent=row["avg_pnl_percent"],
                total_pnl_percent=row["total_pnl_percent"],
                last_updated=row["last_updated"],
            )

    @staticmethod
    def _row_to_trade_record(row: sqlite3.Row) -> TradeRecord:
        return TradeRecord(
            id=row["id"],
            timestamp=row["timestamp"],
            ticker=row["ticker"],
            action=row["action"],
            quantity=row["quantity"],
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            confidence=row["confidence"],
            reasoning=row["reasoning"],
            indicators_json=row["indicators_json"],
            market_conditions=row["market_conditions"],
            status=row["status"],
            pnl_amount=row["pnl_amount"],
            pnl_percent=row["pnl_percent"],
            exit_timestamp=row["exit_timestamp"],
            exit_reason=row["exit_reason"],
            order_id=row["order_id"],
            mode=row["mode"] if "mode" in row.keys() else "paper",
            alert_received_ts=row["alert_received_ts"] if "alert_received_ts" in row.keys() else None,
            fill_ts=row["fill_ts"] if "fill_ts" in row.keys() else None,
            latency_ms=row["latency_ms"] if "latency_ms" in row.keys() else None,
        )
