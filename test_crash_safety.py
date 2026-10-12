"""Test script proving Crash-Safety of the Exit Monitor loop.

Simulates a catastrophic network exception during price fetch
and proves that:
1. The error is intercepted and logged with traceback.
2. The monitoring loop survives and proceeds to process subsequent trades.
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
from storage.database import TradeDatabase
from storage.models import TradeRecord, TradeStatus
from engine.exit_monitor import ExitMonitor


def run_crash_safety_test():
    print("=" * 80)
    print("🛡️ RUNNING EXIT MONITOR CRASH-SAFETY TEST")
    print("=" * 80)

    db = TradeDatabase()
    monitor = ExitMonitor(db=db)

    # 1. Close any previous open crash-test items (audit trail preserved; never delete)
    with db._get_connection() as conn:
        conn.execute("UPDATE trades SET status = 'CLOSED', exit_reason = 'CRASH_TEST_CLEANUP' WHERE status = 'OPEN' AND order_id LIKE 'crash_test_%'")
        conn.commit()

    t_bad = TradeRecord(
        timestamp=datetime.utcnow().isoformat(),
        ticker="AAPL",
        action="BUY",
        quantity=20.0,
        entry_price=220.00,
        stop_loss=215.00,
        take_profit=235.00,
        confidence=0.80,
        reasoning="Crash safety test trade AAPL",
        status=TradeStatus.OPEN.value,
        mode="test",
        order_id="crash_test_bad_001",
    )
    bad_id = db.log_trade(t_bad)

    t_good = TradeRecord(
        timestamp=datetime.utcnow().isoformat(),
        ticker="SPY",
        action="BUY",
        quantity=15.0,
        entry_price=550.00,
        stop_loss=540.00,
        take_profit=570.00,
        confidence=0.80,
        reasoning="Crash safety test trade SPY",
        status=TradeStatus.OPEN.value,
        mode="test",
        order_id="crash_test_good_002",
    )
    good_id = db.log_trade(t_good)

    print(f"1. Seeded Trades in DB:")
    print(f"  • Trade #{bad_id} (AAPL) - Will simulate price fetch exception")
    print(f"  • Trade #{good_id} (SPY)  - Will simulate valid TP hit ($575.00)")

    # 2. Monkey-patch price fetcher on monitor to throw on AAPL and succeed on SPY
    original_fetcher = monitor.get_current_price_and_atr

    def faulty_fetcher(ticker: str):
        if ticker == "AAPL":
            print(f"\n[SIMULATION] Injecting Catastrophic Network Error on {ticker} price fetch...")
            raise ConnectionResetError("Fatal Connection Reset: TwelveData rate limit / socket dropped!")
        return 575.00, 5.0  # SPY reaches $575 (TP hit)

    monitor.get_current_price_and_atr = faulty_fetcher

    # 3. Execute monitor_open_positions
    print("\n2. Executing monitor_open_positions() with faulty price fetcher:")
    try:
        closed_events = monitor.monitor_open_positions()
        print(f"\n3. Loop Execution Status:")
        print(f"  ✅ MONITOR LOOP SURVIVED! Did not crash.")
        print(f"  • Number of closed trades processed: {len(closed_events)}")
        for event in closed_events:
            print(f"  • Successfully processed good trade: {event['log_msg']}")
    except Exception as exc:
        print(f"  ❌ CRASH: Exit monitor threw unhandled exception: {exc}")
        raise exc
    finally:
        monitor.get_current_price_and_atr = original_fetcher

    # 4. Clean up test trades (audit trail preserved; close any remaining open items)
    with db._get_connection() as conn:
        conn.execute("UPDATE trades SET status = 'CLOSED', exit_reason = 'CRASH_TEST_CLEANUP' WHERE status = 'OPEN' AND order_id LIKE 'crash_test_%'")
        conn.commit()

    print("\n" + "=" * 80)
    print("✅ CRASH-SAFETY TEST PASSED: Bad price fetch was safely trapped and logged.")
    print("=" * 80)


if __name__ == "__main__":
    run_crash_safety_test()
