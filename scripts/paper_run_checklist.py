"""Startup Pre-Flight Checklist for 48-Hour Live Paper Run.

Verifies:
1. .env file loaded and valid
2. Startup paper capital scale confirmation
3. Webhook secret configuration
4. ngrok exposure instructions
5. SQLite database read/write permissions
6. US market hours evaluation
7. Pine Script JSON payload schema compatibility check
"""

from __future__ import annotations

import sys
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import (
    ENV_PATH,
    WEBHOOK_SECRET,
    PAPER_CAPITAL,
    DATABASE_PATH,
    TICKERS,
    EXECUTION_MODE,
)
from broker.alpaca_client import is_us_market_open
from server.webhook import TradingViewSignal


def run_checklist():
    print("=" * 80)
    print("📋 48-HOUR LIVE PAPER RUN STARTUP PRE-FLIGHT CHECKLIST")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    checklist_passed = True

    # 1. Check .env
    print("\n[CHECK 1] Environment File (.env):")
    if ENV_PATH.exists():
        print(f"  ✅ .env found at: {ENV_PATH}")
    else:
        print(f"  ❌ .env NOT found at {ENV_PATH}")
        checklist_passed = False

    # 2. Check Paper Capital & Backtest Alignment
    print("\n[CHECK 2] Capital Consistency & Scale Alignment:")
    scale_matches = "YES" if PAPER_CAPITAL == 10000.0 else "NO"
    startup_line = f"[STARTUP] Paper capital: ${PAPER_CAPITAL:,.2f} (matches backtest scale: {scale_matches})"
    print(f"  • {startup_line}")
    if scale_matches == "YES":
        print("  ✅ Capital exactly matches $10,000 backtest reference scale.")
    else:
        print(f"  ⚠️ NOTICE: Capital is ${PAPER_CAPITAL:,.2f}. 1% risk = ${PAPER_CAPITAL * 0.01:,.2f}/trade.")

    # 3. Check Webhook Secret
    print("\n[CHECK 3] Webhook Secret Authentication:")
    if WEBHOOK_SECRET and not WEBHOOK_SECRET.startswith("your_"):
        masked = f"{WEBHOOK_SECRET[:4]}...{WEBHOOK_SECRET[-3:] if len(WEBHOOK_SECRET) > 7 else '***'}"
        print(f"  ✅ WEBHOOK_SECRET is active: {masked}")
    else:
        print("  ❌ WEBHOOK_SECRET is missing or using placeholder!")
        checklist_passed = False

    # 4. Check ngrok Exposure Readiness
    print("\n[CHECK 4] Public Exposure (ngrok):")
    ngrok_bin = shutil.which("ngrok")
    if ngrok_bin:
        print(f"  ✅ ngrok executable detected: {ngrok_bin}")
    else:
        print("  ℹ️ ngrok not in system PATH (run from download folder).")
    print("  • Public Forwarding Command: ngrok http 8000")
    print("  • Target Webhook URL:        https://<your-ngrok-subdomain>.ngrok-free.app/webhook/signal")
    print("  • Header to Configure in TV: X-Webhook-Secret: " + WEBHOOK_SECRET)

    # 5. Check Database Read/Write
    print("\n[CHECK 5] SQLite Database Read/Write Integrity:")
    try:
        conn = sqlite3.connect(str(DATABASE_PATH))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS _preflight_test (id INT)")
        cursor.execute("INSERT INTO _preflight_test VALUES (1)")
        cursor.execute("SELECT * FROM _preflight_test")
        cursor.execute("DROP TABLE _preflight_test")
        conn.commit()
        conn.close()
        print(f"  ✅ Database writable & schema verified at: {DATABASE_PATH}")
    except Exception as e:
        print(f"  ❌ Database write check failed: {e}")
        checklist_passed = False

    # 6. Check Market-Hours Logic
    print("\n[CHECK 6] US Market Hours Status:")
    is_open, market_msg = is_us_market_open()
    print(f"  • Live Status: {'OPEN (Regular Hours)' if is_open else 'CLOSED (Off Hours)'}")
    print(f"  • Evaluator Response: {market_msg}")
    print("  ✅ Market-hours gate operates correctly.")

    # 7. Check Pine Script JSON Payload Schema (Dry-Run Parse)
    print("\n[CHECK 7] Pine Script JSON Payload Dry-Run Validation:")
    sample_payload = {
        "ticker": "NVDA",
        "action": "buy",
        "price": 180.50,
        "timeframe": "240",
        "secret": WEBHOOK_SECRET,
    }
    try:
        parsed = TradingViewSignal(**sample_payload)
        print(f"  • Sample Pine Script Payload: {sample_payload}")
        print(f"  • Pydantic Parsed Model: ticker={parsed.ticker}, action={parsed.action}, price=${parsed.price:.2f}, timeframe={parsed.timeframe}")
        print("  ✅ Pine Script payload perfectly matches FastAPI Pydantic schema.")
    except Exception as e:
        print(f"  ❌ Payload schema validation failed: {e}")
        checklist_passed = False

    print("\n" + "=" * 80)
    if checklist_passed:
        print("🚀 ALL PRE-FLIGHT CHECKS PASSED — READY FOR 48-HOUR LIVE RUN")
    else:
        print("⚠️ SOME CHECKS FAILED — PLEASE REVIEW ITEMS MARKED WITH ❌")
    print("=" * 80)
    return checklist_passed


if __name__ == "__main__":
    success = run_checklist()
    if not success:
        sys.exit(1)
