"""Daily Paper Trading Review & Performance Audit Script.

Supports standard summary or detailed --full audit:
- Core metrics: Trades count, Win Rate, Avg R, Expectancy, Profit Factor
- Latency metrics: Avg, Max, and P95 latency (ms)
- Reject breakdown: Rejection counts filtered for live alerts
- Per-ticker performance breakdown
- Graduation Verdict Check vs quantitative gate criteria
"""

from __future__ import annotations

import sys
import argparse
import sqlite3
import re
from pathlib import Path
from datetime import datetime, date

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import DATABASE_PATH, LOG_FILE_PATH, PAPER_CAPITAL, MAX_POSITION_PERCENT


def run_daily_review(full_mode: bool = False):
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("=" * 80)
    print("📊 48-HOUR DAILY PAPER TRADING AUDIT & REVIEW" + (" [--full mode]" if full_mode else ""))
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Database: {DATABASE_PATH}")
    print(f"Paper Capital Benchmark: ${PAPER_CAPITAL:,.2f}")
    print("=" * 80)

    # 1. Summary Metrics for Active Live Paper Trades (mode='paper', excluding mode='test')
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open_count,
            SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) as closed_count,
            SUM(CASE WHEN status = 'CLOSED' AND pnl_amount > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN status = 'CLOSED' AND pnl_amount <= 0 THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN status = 'CLOSED' THEN pnl_amount ELSE 0 END) as total_pnl,
            SUM(CASE WHEN status = 'CLOSED' AND pnl_amount > 0 THEN pnl_amount ELSE 0 END) as gross_wins,
            SUM(CASE WHEN status = 'CLOSED' AND pnl_amount < 0 THEN ABS(pnl_amount) ELSE 0 END) as gross_losses
        FROM trades 
        WHERE mode = 'paper' AND status != 'TEST'
    """)
    summary = cursor.fetchone()
    total_trades = summary["total"] or 0
    open_count = summary["open_count"] or 0
    closed_count = summary["closed_count"] or 0
    wins = summary["wins"] or 0
    losses = summary["losses"] or 0
    total_pnl = summary["total_pnl"] or 0.0
    gross_wins = summary["gross_wins"] or 0.0
    gross_losses = summary["gross_losses"] or 0.0
    win_rate = (wins / closed_count * 100.0) if closed_count > 0 else 0.0
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

    # 2. Detailed Closed Trades List & R-Multiples
    cursor.execute("""
        SELECT id, timestamp, ticker, action, quantity, entry_price, exit_price, stop_loss, exit_reason, pnl_amount, pnl_percent, latency_ms
        FROM trades
        WHERE mode = 'paper' AND status = 'CLOSED'
        ORDER BY id DESC
    """)
    closed_rows = cursor.fetchall()

    r_multiples: list[float] = []
    win_r_list: list[float] = []
    loss_r_list: list[float] = []
    sizing_violations = 0

    for r in closed_rows:
        entry = float(r["entry_price"])
        exit_p = float(r["exit_price"]) if r["exit_price"] else entry
        sl = float(r["stop_loss"])
        sl_dist = abs(entry - sl) if sl else (entry * 0.02)
        if sl_dist <= 0:
            sl_dist = entry * 0.02

        if r["action"].upper() in ("BUY", "LONG"):
            r_val = (exit_p - entry) / sl_dist
        else:
            r_val = (entry - exit_p) / sl_dist

        r_multiples.append(r_val)
        if r_val > 0:
            win_r_list.append(r_val)
        else:
            loss_r_list.append(abs(r_val))

        # Sizing violation check: cost should not exceed 25% + small margin
        pos_cost = r["quantity"] * entry
        if pos_cost > (PAPER_CAPITAL * 0.25 * 1.05):
            sizing_violations += 1

    avg_r = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0
    avg_win_r = (sum(win_r_list) / len(win_r_list)) if win_r_list else 0.0
    avg_loss_r = (sum(loss_r_list) / len(loss_r_list)) if loss_r_list else 0.0
    wr_decimal = win_rate / 100.0
    expectancy_r = (wr_decimal * avg_win_r) - ((1.0 - wr_decimal) * avg_loss_r)

    print(f"\n[1] CORE PERFORMANCE METRICS:")
    print(f"  • Total Live Paper Trades Logged : {total_trades}")
    print(f"  • Currently Open Positions       : {open_count}")
    print(f"  • Closed Trades Evaluated        : {closed_count} (Wins: {wins}, Losses: {losses})")
    print(f"  • Win Rate (WR)                  : {win_rate:.1f}%")
    print(f"  • Average R-Multiple (Avg R)     : {avg_r:+.2f}R")
    print(f"  • Expectancy (per trade)         : {expectancy_r:+.2f}R (Avg Win: +{avg_win_r:.2f}R | Avg Loss: -{avg_loss_r:.2f}R)")
    print(f"  • Profit Factor (PF)             : {profit_factor:.2f}")
    print(f"  • Net Realized PnL               : ${total_pnl:+,.2f}")
    print(f"  • Current Estimated Capital      : ${PAPER_CAPITAL + total_pnl:,.2f}")

    # 3. Latency Statistics
    cursor.execute("""
        SELECT latency_ms FROM trades 
        WHERE mode = 'paper' AND latency_ms IS NOT NULL AND status != 'TEST'
        ORDER BY latency_ms ASC
    """)
    latency_rows = [float(row[0]) for row in cursor.fetchall()]
    print(f"\n[2] SIGNAL LATENCY AUDIT (Alert Reception → Fill Execution):")
    if latency_rows:
        avg_lat = sum(latency_rows) / len(latency_rows)
        max_lat = max(latency_rows)
        p95_idx = int(0.95 * len(latency_rows))
        p95_lat = latency_rows[min(p95_idx, len(latency_rows) - 1)]
        print(f"  • Sampled Fills : {len(latency_rows)}")
        print(f"  • Average Latency : {avg_lat:.1f} ms")
        print(f"  • Max Latency     : {max_lat:.1f} ms")
        print(f"  • 95th Percentile : {p95_lat:.1f} ms")
    else:
        print("  • No live trade latency entries recorded yet (mock test trades excluded).")

    # 4. Per-Ticker Breakdown
    if full_mode or closed_rows:
        cursor.execute("""
            SELECT 
                ticker,
                COUNT(*) as count,
                SUM(CASE WHEN pnl_amount > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl_amount) as sum_pnl
            FROM trades
            WHERE mode = 'paper' AND status = 'CLOSED'
            GROUP BY ticker
        """)
        ticker_stats = cursor.fetchall()
        print(f"\n[3] PER-TICKER BREAKDOWN:")
        if ticker_stats:
            print(f"  {'Ticker':<8} {'Closed Trades':<14} {'Wins':<8} {'Win Rate':<10} {'Net PnL ($)'}")
            print("  " + "-" * 55)
            for ts in ticker_stats:
                t_wr = (ts["wins"] / ts["count"] * 100.0) if ts["count"] > 0 else 0.0
                sum_pnl_val = ts["sum_pnl"] or 0.0
                print(f"  {ts['ticker']:<8} {ts['count']:<14} {ts['wins']:<8} {t_wr:<9.1f}% ${sum_pnl_val:+,.2f}")
        else:
            print("  (No closed trades to aggregate)")

    # 5. Rejected Signals Audit (Filtering for Genuine Live Signals)
    print(f"\n[4] REJECTED SIGNALS BREAKDOWN (Audit from {LOG_FILE_PATH.name}):")
    reject_counts = {
        "Unauthorized / Secret Mismatch": 0,
        "Market Closed Gate": 0,
        "Stale / Deviated Price (>2%)": 0,
        "Duplicate Position Gate": 0,
        "Zero Allocation / Sizing Cap": 0,
    }
    if Path(LOG_FILE_PATH).exists():
        with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="ignore") as lf:
            for line in lf:
                # Filter out intentional test harness noise
                if "invalid_unauthorized_key_999" in line:
                    continue
                if "Rejected unauthorized attempt" in line:
                    reject_counts["Unauthorized / Secret Mismatch"] += 1
                elif "Market closed" in line or "Market simulated closed" in line:
                    if "Market simulated closed" not in line:  # real market closed
                        reject_counts["Market Closed Gate"] += 1
                elif "Price deviation too large" in line:
                    if "250.00 vs Market $225.00" not in line:  # real stale alert
                        reject_counts["Stale / Deviated Price (>2%)"] += 1
                elif "Duplicate position already open" in line:
                    reject_counts["Duplicate Position Gate"] += 1
                elif "Calculated quantity is 0" in line:
                    reject_counts["Zero Allocation / Sizing Cap"] += 1

        for reason, count in reject_counts.items():
            print(f"  • {reason:<32}: {count} live rejected alert(s)")
    else:
        print("  (Log file not found)")

    # 6. Orphaned Positions Audit
    cursor.execute("""
        SELECT COUNT(*) FROM trades 
        WHERE mode = 'paper' AND status = 'OPEN' AND (stop_loss <= 0 OR take_profit <= 0)
    """)
    orphaned_count = cursor.fetchone()[0]

    # 7. Graduation Criteria Verdict Line
    print(f"\n[5] 48-72HR GRADUATION CRITERIA VERDICT:")
    c1 = closed_count >= 15
    c2 = avg_r >= 0.20
    c3 = sizing_violations == 0
    c4 = orphaned_count == 0

    print(f"  1. Minimum 15 Closed Trades    : {'[PASS]' if c1 else '[PENDING]'} ({closed_count}/15 trades completed)")
    print(f"  2. Positive Expectancy Avg R   : {'[PASS]' if c2 else '[FAIL]'} (Target >= +0.20R, Current: {avg_r:+.2f}R)")
    print(f"  3. Zero Sizing Cap Violations  : {'[PASS]' if c3 else '[FAIL]'} ({sizing_violations} violations)")
    print(f"  4. Zero Orphaned Positions     : {'[PASS]' if c4 else '[FAIL]'} ({orphaned_count} orphaned)")

    if c1 and c2 and c3 and c4:
        print("\n  >>> VERDICT: GRADUATE: YES <<< (Ready for micro-live broker execution)")
    else:
        pending_reasons = []
        if not c1: pending_reasons.append("insufficient sample size (<15)")
        if not c2: pending_reasons.append("avg R < +0.20R")
        if not c3: pending_reasons.append("sizing cap violation detected")
        if not c4: pending_reasons.append("orphaned position found")
        print(f"\n  >>> VERDICT: GRADUATE: NO ({', '.join(pending_reasons)}) <<<")

    print("=" * 80)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily Paper Trading Review")
    parser.add_argument("--full", action="store_true", help="Display full audit including per-ticker details")
    args = parser.parse_args()
    run_daily_review(full_mode=args.full)
