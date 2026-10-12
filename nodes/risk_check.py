"""RISK_CHECK Node: Strict rule-based risk management (Position sizing, Stop-loss, Max positions)."""

from __future__ import annotations

from typing import Dict, Any, List
from config import (
    MAX_POSITION_PERCENT,
    STOP_LOSS_PERCENT,
    TAKE_PROFIT_PERCENT,
    MAX_OPEN_POSITIONS,
    MAX_DRAWDOWN_PERCENT,
    USE_ATR_STOPS,
    SL_ATR_MULT,
    TP_ATR_MULT,
    RISK_PER_TRADE,
    logger,
)
from graph.state import AgentState
from broker.alpaca_client import AlpacaBrokerClient
from storage.database import TradeDatabase


def risk_check_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node enforcing rule-based risk filters before order execution."""
    raw_decisions = state.get("raw_decisions", [])
    logger.info(f"--- [NODE: RISK_CHECK] Evaluating {len(raw_decisions)} decisions ---")

    broker = AlpacaBrokerClient()
    db = TradeDatabase()

    account_info = broker.get_account()
    open_positions = broker.get_positions()
    open_tickers = {p["ticker"]: p for p in open_positions}

    portfolio_val = account_info.get("portfolio_value", 100000.0)
    cash_val = account_info.get("cash", 100000.0)
    peak_val = account_info.get("peak_equity", account_info.get("last_equity", portfolio_val))
    if peak_val <= 0:
        peak_val = portfolio_val

    drawdown_from_peak = (peak_val - portfolio_val) / peak_val if peak_val > 0 else 0.0
    circuit_breaker_triggered = drawdown_from_peak >= MAX_DRAWDOWN_PERCENT

    current_open_count = len(open_positions)
    max_trade_capital = portfolio_val * MAX_POSITION_PERCENT

    logger.info(
        f"Portfolio Value: ${portfolio_val:,.2f} (Peak: ${peak_val:,.2f}, DD: {drawdown_from_peak*100:.1f}%) | "
        f"Available Cash: ${cash_val:,.2f} | Open Positions: {current_open_count}/{MAX_OPEN_POSITIONS} | "
        f"Max Per Trade: ${max_trade_capital:,.2f}"
    )

    if circuit_breaker_triggered:
        logger.warning(
            f"🚨 CIRCUIT BREAKER ACTIVE: Portfolio drawdown is {drawdown_from_peak*100:.1f}% from peak "
            f"(${peak_val:,.2f} -> ${portfolio_val:,.2f}), exceeding {MAX_DRAWDOWN_PERCENT*100:.0f}% threshold. Halting trading for the day."
        )

    approved_decisions: List[Dict[str, Any]] = []
    rejected_decisions: List[Dict[str, Any]] = []

    snapshots = state.get("market_snapshots", {})

    for decision in raw_decisions:
        ticker = decision["ticker"]
        action = decision["action"].upper()
        price = float(decision.get("entry_price", 0.0))
        conf = float(decision.get("confidence", 0.0))

        # 1. HOLD Actions pass through without execution
        if action == "HOLD":
            approved_decisions.append(decision)
            continue

        # 2. BUY Action Risk Checks
        if action == "BUY":
            # Rule 0: Max drawdown circuit breaker (if portfolio drops 10% from peak, stop trading for the day)
            if circuit_breaker_triggered:
                reason = f"Max drawdown circuit breaker active ({drawdown_from_peak*100:.1f}% drop from peak >= {MAX_DRAWDOWN_PERCENT*100:.0f}%). Trading halted for the day."
                _reject(decision, reason, rejected_decisions)
                continue

            # Rule A: Minimum confidence threshold (e.g. 0.60)
            if conf < 0.60:
                reason = f"Confidence ({conf:.2f}) below minimum 0.60 threshold."
                _reject(decision, reason, rejected_decisions)
                continue

            # Rule B: Ticker already held
            if ticker in open_tickers:
                reason = f"Position for {ticker} is already open ({open_tickers[ticker]['qty']} shares)."
                _reject(decision, reason, rejected_decisions)
                continue

            # Rule C: Maximum concurrent open positions (Max 2)
            if current_open_count >= MAX_OPEN_POSITIONS:
                reason = f"Max open positions reached ({current_open_count}/{MAX_OPEN_POSITIONS})."
                _reject(decision, reason, rejected_decisions)
                continue

            # Rule D: Position Sizing (Max 5% of portfolio)
            if price <= 0:
                reason = f"Invalid asset price (${price})."
                _reject(decision, reason, rejected_decisions)
                continue

            snapshot = snapshots.get(ticker, {})
            ind = snapshot.get("indicators", {})
            atr_14 = float(ind.get("atr_14", max(0.01, price * 0.01)))
            
            if USE_ATR_STOPS and atr_14 > 0:
                sl_dist = SL_ATR_MULT * atr_14
                sl_price = price - sl_dist
                tp_price = price + (TP_ATR_MULT * atr_14)
                if sl_dist > 0:
                    risk_cap = portfolio_val * RISK_PER_TRADE
                    target_qty = risk_cap / sl_dist
                else:
                    target_qty = max_trade_capital / price
                if (target_qty * price) > max_trade_capital:
                    target_qty = max_trade_capital / price
            else:
                target_qty = max_trade_capital / price
                sl_price = price * (1.0 - STOP_LOSS_PERCENT)
                tp_price = price * (1.0 + TAKE_PROFIT_PERCENT)

            # Round quantity (whole shares if price > $10, otherwise 4 decimals)
            qty = round(target_qty, 4) if price < 10.0 else int(target_qty)

            if decision.get("soft_penalty"):
                qty = qty * 0.5
                qty = round(qty, 4) if price < 10.0 else int(qty)
                # Keep the reasoning log
                decision["reasoning"] = f"[LESSON Applied: {decision.get('lesson_id', 'unknown')} -> size 50% (soft)] " + decision.get("reasoning", "")
                logger.info(f"  [LESSON] Applied: {decision.get('lesson_id', 'unknown')} -> size 50% (soft) for {ticker}")

            if qty <= 0:
                reason = f"Calculated quantity is 0 (Share price ${price:.2f} > max allocation ${max_trade_capital:.2f})."
                _reject(decision, reason, rejected_decisions)
                continue

            total_cost = qty * price
            if total_cost > cash_val:
                reason = f"Insufficient cash (${cash_val:,.2f}) for trade cost (${total_cost:,.2f})."
                _reject(decision, reason, rejected_decisions)
                continue

            decision["quantity"] = qty
            decision["stop_loss"] = round(sl_price, 2)
            decision["take_profit"] = round(tp_price, 2)

            logger.info(f"  ✓ APPROVED BUY {ticker}: {qty} shares @ ${price:.2f} (Cost: ${total_cost:,.2f}) | SL: ${decision['stop_loss']} | TP: ${decision['take_profit']}")
            approved_decisions.append(decision)
            current_open_count += 1
            cash_val -= total_cost

        # 3. SHORT Action Risk Checks (Downtrend alternative)
        elif action == "SHORT":
            if circuit_breaker_triggered:
                reason = f"Max drawdown circuit breaker active ({drawdown_from_peak*100:.1f}% drop from peak >= {MAX_DRAWDOWN_PERCENT*100:.0f}%)."
                _reject(decision, reason, rejected_decisions)
                continue

            if conf < 0.70:
                reason = f"Downtrend SHORT confidence ({conf:.2f}) below required 0.70 threshold."
                _reject(decision, reason, rejected_decisions)
                continue

            if ticker in open_tickers:
                reason = f"Position for {ticker} is already open ({open_tickers[ticker]['qty']} shares)."
                _reject(decision, reason, rejected_decisions)
                continue

            if current_open_count >= MAX_OPEN_POSITIONS:
                reason = f"Max open positions reached ({current_open_count}/{MAX_OPEN_POSITIONS})."
                _reject(decision, reason, rejected_decisions)
                continue

            if price <= 0:
                reason = f"Invalid asset price (${price})."
                _reject(decision, reason, rejected_decisions)
                continue

            snapshot = snapshots.get(ticker, {})
            ind = snapshot.get("indicators", {})
            atr_14 = float(ind.get("atr_14", max(0.01, price * 0.01)))
            
            if USE_ATR_STOPS and atr_14 > 0:
                sl_dist = SL_ATR_MULT * atr_14
                sl_price = price + sl_dist
                tp_price = price - (TP_ATR_MULT * atr_14)
                if sl_dist > 0:
                    risk_cap = portfolio_val * RISK_PER_TRADE
                    target_qty = risk_cap / sl_dist
                else:
                    target_qty = max_trade_capital / price
                if (target_qty * price) > max_trade_capital:
                    target_qty = max_trade_capital / price
            else:
                target_qty = max_trade_capital / price
                sl_price = price * (1.0 + STOP_LOSS_PERCENT)
                tp_price = price * (1.0 - TAKE_PROFIT_PERCENT)

            qty = round(target_qty, 4) if price < 10.0 else int(target_qty)

            if decision.get("soft_penalty"):
                qty = qty * 0.5
                qty = round(qty, 4) if price < 10.0 else int(qty)
                decision["reasoning"] = f"[LESSON Applied: {decision.get('lesson_id', 'unknown')} -> size 50% (soft)] " + decision.get("reasoning", "")
                logger.info(f"  [LESSON] Applied: {decision.get('lesson_id', 'unknown')} -> size 50% (soft) for {ticker} SHORT")

            if qty <= 0:
                reason = f"Calculated short quantity is 0."
                _reject(decision, reason, rejected_decisions)
                continue

            margin_required = qty * price
            if margin_required > cash_val:
                reason = f"Insufficient margin/cash (${cash_val:,.2f}) for short position (${margin_required:,.2f})."
                _reject(decision, reason, rejected_decisions)
                continue

            decision["quantity"] = qty
            decision["stop_loss"] = round(sl_price, 2)
            decision["take_profit"] = round(tp_price, 2)

            logger.info(f"  ✓ APPROVED SHORT {ticker}: {qty} shares @ ${price:.2f} (Margin: ${margin_required:,.2f}) | SL: ${decision['stop_loss']} | TP: ${decision['take_profit']}")
            approved_decisions.append(decision)
            current_open_count += 1
            cash_val -= margin_required

        # 4. SELL Action Risk Checks
        elif action == "SELL":
            if ticker not in open_tickers:
                reason = f"Cannot SELL {ticker} - no open position currently held."
                _reject(decision, reason, rejected_decisions)
                continue

            held_qty = open_tickers[ticker]["qty"]
            decision["quantity"] = held_qty
            logger.info(f"  ✓ APPROVED SELL {ticker}: Closing all {held_qty} shares @ ${price:.2f}")
            approved_decisions.append(decision)
            current_open_count -= 1

    return {
        "approved_decisions": approved_decisions,
        "rejected_decisions": rejected_decisions,
        "account_info": account_info,
        "open_positions": open_positions,
    }


def _reject(decision: Dict[str, Any], reason: str, rejected_list: List[Dict[str, Any]]) -> None:
    """Helper to reject a decision and override action to HOLD."""
    logger.warning(f"  ✗ REJECTED {decision['action']} {decision['ticker']}: {reason} -> Overridden to HOLD")
    rejected_copy = dict(decision)
    rejected_copy["rejection_reason"] = reason
    rejected_copy["action"] = "HOLD"
    rejected_list.append(rejected_copy)
