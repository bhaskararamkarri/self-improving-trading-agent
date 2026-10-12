"""Comprehensive Test Harness for Webhook Ingestion & Risk Validation.

Starts the FastAPI webhook server and runs 6 mock signals:
1. Valid buy -> should execute in paper mode
2. Valid sell/short -> should execute in paper mode
3. Wrong secret -> 401 Unauthorized
4. Stale price (10% off) -> rejected by price sanity check
5. Duplicate ticker -> rejected by duplicate position check
6. Market closed simulation -> rejected by market hours check

Also validates the risk sizing math against existing risk rules:
qty = floor(risk_dollars / |entry - SL|) with 25% capital safety cap.
"""

from __future__ import annotations

import sys
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
import math
import socket
import threading
import sqlite3
import requests
import uvicorn

from config import (
    WEBHOOK_SECRET,
    EXECUTION_MODE,
    INITIAL_PAPER_CASH,
    RISK_PER_TRADE,
    SL_ATR_MULT,
    TP_ATR_MULT,
    DATABASE_PATH,
)
from server.webhook import app
from storage.database import TradeDatabase
from signals.external_validator import ExternalSignalValidator


def find_free_port() -> int:
    """Finds an available TCP port for the local server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def reset_test_db():
    """Cleans up test trades in database for fresh test run without deleting rows.
    Preserves all records in SQLite audit trail by closing open trades instead of deleting."""
    conn = sqlite3.connect(str(DATABASE_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE trades 
        SET status = 'CLOSED', exit_reason = 'TEST_RESET_CLEANUP' 
        WHERE status = 'OPEN'
    """)
    conn.commit()
    conn.close()


def run_webhook_tests():
    print("=" * 80)
    print(">>> STARTING WEBHOOK INGESTION & RISK TEST HARNESS <<<")
    print(f"• Execution Mode: {EXECUTION_MODE.upper()} (Default Paper Safety ON)")
    print(f"• Webhook Secret: {WEBHOOK_SECRET[:4]}...{WEBHOOK_SECRET[-3:] if len(WEBHOOK_SECRET) > 7 else '***'}")
    print(f"• Risk Budget: {RISK_PER_TRADE * 100:.1f}% (${INITIAL_PAPER_CASH * RISK_PER_TRADE:.2f} on ${INITIAL_PAPER_CASH:,.2f})")
    print("=" * 80)

    reset_test_db()
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    endpoint = f"{base_url}/webhook/signal"

    # Start FastAPI server in background thread
    server_config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(server_config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for server to be responsive
    for _ in range(50):
        try:
            resp = requests.get(f"{base_url}/health", timeout=0.5)
            if resp.status_code == 200:
                print(f"[OK] FastAPI Webhook Server listening on {base_url}")
                break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("FastAPI server failed to start in time.")

    print("\n" + "=" * 80)
    print("PART 2.1: RUNNING 6 MOCK WEBHOOK SIGNALS")
    print("=" * 80)

    test_cases = [
        {
            "name": "TEST 1: Valid Buy Signal",
            "url": endpoint,
            "headers": {"X-Webhook-Secret": WEBHOOK_SECRET},
            "payload": {
                "ticker": "NVDA",
                "action": "buy",
                "price": 180.0,
                "timeframe": "1D",
                "force_market_open": True,
                "mock_current_price": 180.0,
                "mock_atr": 4.50,
            },
            "expected_code": 200,
            "expected_status": "executed",
        },
        {
            "name": "TEST 2: Valid Sell/Short Signal",
            "url": endpoint,
            "headers": {"X-Webhook-Secret": WEBHOOK_SECRET},
            "payload": {
                "ticker": "MSFT",
                "action": "short",
                "price": 420.0,
                "timeframe": "1D",
                "force_market_open": True,
                "mock_current_price": 420.0,
                "mock_atr": 8.0,
            },
            "expected_code": 200,
            "expected_status": "executed",
        },
        {
            "name": "TEST 3: Unauthorized Request (Wrong Secret)",
            "url": endpoint,
            "headers": {"X-Webhook-Secret": "invalid_unauthorized_key_999"},
            "payload": {
                "ticker": "AAPL",
                "action": "buy",
                "price": 230.0,
                "timeframe": "1D",
            },
            "expected_code": 401,
            "expected_status": None,
        },
        {
            "name": "TEST 4: Stale Price Alert (10% Price Deviation)",
            "url": endpoint,
            "headers": {"X-Webhook-Secret": WEBHOOK_SECRET},
            "payload": {
                "ticker": "AAPL",
                "action": "buy",
                "price": 250.0,  # Alert says 250
                "timeframe": "1D",
                "force_market_open": True,
                "mock_current_price": 225.0,  # Live market is 225 (>11% deviation)
            },
            "expected_code": 200,
            "expected_status": "rejected",
        },
        {
            "name": "TEST 5: Duplicate Position Rejection",
            "url": endpoint,
            "headers": {"X-Webhook-Secret": WEBHOOK_SECRET},
            "payload": {
                "ticker": "NVDA",  # NVDA position already opened in Test 1
                "action": "buy",
                "price": 181.0,
                "timeframe": "1D",
                "force_market_open": True,
                "mock_current_price": 181.0,
            },
            "expected_code": 200,
            "expected_status": "rejected",
        },
        {
            "name": "TEST 6: Market Closed Simulation Rejection",
            "url": endpoint,
            "headers": {"X-Webhook-Secret": WEBHOOK_SECRET},
            "payload": {
                "ticker": "SPY",
                "action": "buy",
                "price": 550.0,
                "timeframe": "1D",
                "force_market_open": False,  # Explicitly simulated closed
            },
            "expected_code": 200,
            "expected_status": "rejected",
        },
    ]

    all_passed = True
    for i, tc in enumerate(test_cases, 1):
        print(f"\n[{tc['name']}]")
        print(f"  -> REQUEST: POST {tc['url']}")
        print(f"     Headers: {tc['headers']}")
        print(f"     Payload: {tc['payload']}")

        resp = requests.post(tc["url"], json=tc["payload"], headers=tc["headers"])
        resp_json = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text

        print(f"  <- RESPONSE (HTTP {resp.status_code}):")
        print(f"     {resp_json}")

        # Verification
        passed = (resp.status_code == tc["expected_code"])
        if tc["expected_status"]:
            actual_status = resp_json.get("status") if isinstance(resp_json, dict) else None
            passed = passed and (actual_status == tc["expected_status"])

        if passed:
            print(f"  [PASS] VERDICT: PASSED (Expected HTTP {tc['expected_code']}, Got {resp.status_code})")
        else:
            print(f"  [FAIL] VERDICT: FAILED (Expected HTTP {tc['expected_code']} & status={tc['expected_status']}, Got {resp.status_code})")
            all_passed = False

    # Check Database entries for executed paper trades
    print("\n" + "=" * 80)
    print("PART 2.2: DATABASE PAPER TRADES VERIFICATION")
    print("=" * 80)
    db = TradeDatabase()
    open_trades = db.get_open_trades()
    print(f"Active Open Trades in DB: {len(open_trades)}")
    for t in open_trades:
        print(
            f"  * Trade #{t.id} | {t.action} {t.quantity} {t.ticker} @ ${t.entry_price:.2f} | "
            f"SL: ${t.stop_loss:.2f} | TP: ${t.take_profit:.2f} | Status: {t.status} | Mode: {t.mode}"
        )
        assert t.mode == "paper", f"Expected mode 'paper', got '{t.mode}'"

    # Confirm Risk Sizing Math matches
    print("\n" + "=" * 80)
    print("PART 2.3: RISK SIZING MATH INTEGRITY CHECK")
    print("=" * 80)
    
    # Run existing mock test from test_sizing.py
    from test_sizing import simulate_sizing
    print("Executing existing test_sizing.py logic:")
    simulate_sizing(10000, 100, 98)
    simulate_sizing(10000, 500, 490)
    
    # Validate Test 1 NVDA sizing from webhook execution
    nvda_trade = next((t for t in open_trades if t.ticker == "NVDA"), None)
    if nvda_trade:
        from broker.alpaca_client import AlpacaBrokerClient
        acc = AlpacaBrokerClient().get_account()
        actual_capital = float(acc.get("portfolio_value", INITIAL_PAPER_CASH))
        risk_budget = actual_capital * RISK_PER_TRADE
        expected_sl_dist = 1.5 * 4.50  # 6.75
        expected_raw_qty = math.floor(risk_budget / expected_sl_dist)
        max_alloc = actual_capital * 0.25
        if (expected_raw_qty * 180.0) > max_alloc:
            expected_final_qty = math.floor(max_alloc / 180.0)
        else:
            expected_final_qty = expected_raw_qty

        print(f"\nWebhook NVDA Execution Sizing Verification:")
        print(f"  * Portfolio Capital: ${actual_capital:,.2f} | Risk Budget (1%): ${risk_budget:,.2f}")
        print(f"  * Raw Risk Qty: floor(${risk_budget:.2f} / ${expected_sl_dist:.2f}) = {expected_raw_qty} shares (Cost: ${expected_raw_qty * 180:.2f})")
        print(f"  * 25% Safety Cap: floor(${max_alloc:,.2f} / $180.00) = {expected_final_qty} shares (Cost: ${expected_final_qty * 180:.2f})")
        print(f"  * Actual DB Logged Qty: {nvda_trade.quantity} shares")
        assert nvda_trade.quantity == expected_final_qty, f"Expected {expected_final_qty}, got {nvda_trade.quantity}"
        print(f"  [PASS] Webhook Path Matches Exact Risk Sizing & Safety Trim Math!")

    # Cleanly close opened test trades without deleting
    with db._get_connection() as conn:
        conn.execute("UPDATE trades SET status = 'CLOSED', exit_reason = 'TEST_HARNESS_COMPLETED' WHERE status = 'OPEN'")
        conn.commit()

    print("\n" + "=" * 80)
    print(f"SUMMARY: ALL 6 TEST CASES PASSED = {all_passed}")
    print("=" * 80)
    return all_passed


if __name__ == "__main__":
    success = run_webhook_tests()
    if not success:
        sys.exit(1)
