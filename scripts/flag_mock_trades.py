"""Database Migration: Marks test harness trades (IDs 589-592) as mode='test'

This ensures that pre-run test artifacts are excluded from the live 48-hour paper statistics.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import DATABASE_PATH


def flag_mock_trades():
    conn = sqlite3.connect(str(DATABASE_PATH))
    cursor = conn.cursor()

    print("=" * 80)
    print(">>> FLAGGING MOCK TEST TRADES FOR CLEAN 48-HR BASELINE <<<")
    print("=" * 80)

    # Check trades before
    cursor.execute("SELECT id, ticker, action, mode, status FROM trades WHERE id IN (589, 590, 591, 592)")
    before_rows = cursor.fetchall()
    print("Trades Before Migration:")
    for r in before_rows:
        print(f"  • Trade #{r[0]}: {r[1]} {r[2]} | Mode: {r[3]} | Status: {r[4]}")

    # Apply migration
    cursor.execute("""
        UPDATE trades 
        SET mode = 'test', status = 'TEST' 
        WHERE id IN (589, 590, 591, 592) OR order_id LIKE 'test_%'
    """)
    updated_count = cursor.rowcount
    conn.commit()

    # Check trades after
    cursor.execute("SELECT id, ticker, action, mode, status FROM trades WHERE id IN (589, 590, 591, 592)")
    after_rows = cursor.fetchall()
    print(f"\nUpdated {updated_count} mock trades to mode='test', status='TEST':")
    for r in after_rows:
        print(f"  • Trade #{r[0]}: {r[1]} {r[2]} | Mode: {r[3]} | Status: {r[4]}")

    # Verify paper mode count
    cursor.execute("SELECT COUNT(*) FROM trades WHERE mode = 'paper'")
    paper_count = cursor.fetchone()[0]
    print(f"\nRemaining active live paper trades in DB: {paper_count} (Clean slate for 48-hr run)")
    print("=" * 80)
    conn.close()


if __name__ == "__main__":
    flag_mock_trades()
