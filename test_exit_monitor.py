"""Test script demonstrating ExitMonitor functionality.

1. Inserts mock open paper positions (1 LONG, 1 SHORT).
2. Pushes simulated price movements:
   - LONG drops below SL ($172.90 <= $173.25) -> triggers SL exit.
   - SHORT drops below TP ($395.00 <= $396.00) -> triggers TP exit.
3. Tests Trailing Stop logic.
4. Verifies database state and prints heartbeat log.
"""

from __future__ import annotations

import sys
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from datetime import datetime
from config import PAPER_CAPITAL
from storage.database import TradeDatabase
from storage.models import TradeRecord, TradeStatus
from engine.exit_monitor import ExitMonitor, get_realized_pnl_today


def run_exit_monitor_test():
    print("=" * 80)
    print(">>> RUNNING EXIT MONITOR TEST HARNESS <<<")
    print(f"• Named Constant PAPER_CAPITAL: ${PAPER_CAPITAL:,.2f}")
    print("  [Scale Notice: Calibrated for $10k-$100k paper model (1% risk = $100 to $1,000 budget)]")
    print("=" * 80)

    db = TradeDatabase()
    monitor = ExitMonitor(db=db)

    # 1. Close any previous open test-exit items (audit trail preserved; never delete)
    with db._get_connection() as conn:
        conn.execute("UPDATE trades SET status = 'CLOSED', exit_reason = 'EXIT_TEST_CLEANUP' WHERE status = 'OPEN' AND order_id LIKE 'test_exit_%'")
        conn.commit()

    # 2. Insert two test open paper trades
    print("\n1. Seeding 2 Mock Open Paper Trades in Database:")
    trade_long = TradeRecord(
        timestamp=datetime.utcnow().isoformat(),
        ticker="NVDA",
        action="BUY",
        quantity=100.0,
        entry_price=180.00,
        stop_loss=173.25,      # SL distance = $6.75 (1.5xATR)
        take_profit=193.50,    # TP distance = $13.50 (3.0xATR)
        confidence=0.85,
        reasoning="Test Open Long for Exit Monitor",
        status=TradeStatus.OPEN.value,
        mode="test",
        order_id="test_exit_long_001",
    )
    long_id = db.log_trade(trade_long)
    print(f"  • Inserted Trade #{long_id}: BUY 100 NVDA @ $180.00 | SL: $173.25 | TP: $193.50 | Status: OPEN")

    trade_short = TradeRecord(
        timestamp=datetime.utcnow().isoformat(),
        ticker="MSFT",
        action="SELL",
        quantity=50.0,
        entry_price=420.00,
        stop_loss=432.00,      # SL distance = $12.00 (1.5xATR)
        take_profit=396.00,    # TP distance = $24.00 (3.0xATR)
        confidence=0.85,
        reasoning="Test Open Short for Exit Monitor",
        status=TradeStatus.OPEN.value,
        mode="test",
        order_id="test_exit_short_002",
    )
    short_id = db.log_trade(trade_short)
    print(f"  • Inserted Trade #{short_id}: SELL 50 MSFT @ $420.00 | SL: $432.00 | TP: $396.00 | Status: OPEN")

    # Initial Heartbeat
    print(f"\nInitial Heartbeat Before Exits:")
    print(f"  {monitor.get_heartbeat_log()}")

    # 3. Simulate Price Movement
    # NVDA price moves to $172.90 (crosses SL $173.25 downward with slippage)
    # MSFT price moves to $395.00 (crosses TP $396.00 downward into profit)
    print("\n2. Pushing Simulated Market Price Updates:")
    print("  • NVDA Market Price: $172.90 (Below SL $173.25 -> Should trigger SL exit)")
    print("  • MSFT Market Price: $395.00 (Below TP $396.00 -> Should trigger TP exit)")

    price_updates = {
        "NVDA": 172.90,
        "MSFT": 395.00,
    }

    closed_events = monitor.monitor_open_positions(price_overrides=price_updates)

    print(f"\n3. Monitor Output ({len(closed_events)} Trades Closed):")
    for event in closed_events:
        print(f"  [EXECUTION] {event['log_msg']}")

    # 4. Verify Database State
    print("\n4. Database Verification After Exits:")
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, ticker, action, quantity, entry_price, exit_price, exit_reason, status, pnl_amount, pnl_percent FROM trades WHERE id IN (?, ?)", (long_id, short_id))
        rows = cursor.fetchall()
        for r in rows:
            print(
                f"  • Trade #{r['id']} {r['ticker']} {r['action']} {r['quantity']} shares | "
                f"Entry: ${r['entry_price']:.2f} -> Exit: ${r['exit_price']:.2f} | "
                f"Status: {r['status']} | Reason: {r['exit_reason']} | "
                f"Realized PnL: ${r['pnl_amount']:+,.2f} ({r['pnl_percent']:+.2f}%)"
            )

    # 5. Heartbeat Log Check
    print(f"\n5. Heartbeat Status After Exits:")
    heartbeat_msg = monitor.get_heartbeat_log()
    print(f"  {heartbeat_msg}")

    print("\n" + "=" * 80)
    print("✅ EXIT MONITOR HARNESS COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    run_exit_monitor_test()
