import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix initial capital
content = content.replace("initial_capital = 100000.0", "initial_capital = 10000.0")

# Fix DB logging hardcoded BUY and SL/TP
db_log_target = """        tr = TradeRecord(
            id=idx,
            timestamp=t.get("entry_date", t["exit_date"]),
            ticker=t["ticker"],
            action="BUY",
            quantity=t["qty"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            stop_loss=round(t["entry_price"] * 0.98, 2),
            take_profit=round(t["entry_price"] * 1.04, 2),
            confidence=0.70,
            reasoning=f"Backtest trade entry at ${t['entry_price']:.2f}, exit: {t['exit_reason']}",
            indicators_json=str(t.get("indicators_entry", {})),
            market_conditions=f"PnL: {t['pnl_pct']:+.2f}%",
            status="CLOSED",
            pnl_amount=t["pnl_amount"],
            pnl_percent=t["pnl_pct"],
            exit_timestamp=t["exit_date"],
            exit_reason=t["exit_reason"],
        )"""

db_log_replace = """        tr = TradeRecord(
            id=idx,
            timestamp=t.get("entry_date", t["exit_date"]),
            ticker=t["ticker"],
            action=t.get("action", "BUY"),
            quantity=t["qty"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            stop_loss=t.get("sl_price", round(t["entry_price"] * 0.98, 2)),
            take_profit=t.get("tp_price", round(t["entry_price"] * 1.04, 2)),
            confidence=0.70,
            reasoning=f"Backtest trade entry at ${t['entry_price']:.2f}, exit: {t['exit_reason']}",
            indicators_json=str(t.get("indicators_entry", {})),
            market_conditions=f"PnL: {t['pnl_pct']:+.2f}%",
            status="CLOSED",
            pnl_amount=t["pnl_amount"],
            pnl_percent=t["pnl_pct"],
            exit_timestamp=t["exit_date"],
            exit_reason=t.get("exit_reason_flag", t["exit_reason"]),
        )"""

content = content.replace(db_log_target, db_log_replace)

# Fix backtest sizing logic to strict formula and add sl_price, tp_price to positions dictionary
sizing_target = """                    if entry_action == "BUY":
                        if USE_ATR_STOPS and atr_14 > 0:
                            sl_dist = SL_ATR_MULT * atr_14
                            sl_price = round(current_price - sl_dist, 2)
                            tp_price = round(current_price + (TP_ATR_MULT * atr_14), 2)
                            if sl_dist > 0:
                                risk_cap = portfolio_val * RISK_PER_TRADE
                                qty = int(risk_cap / sl_dist)
                            else:
                                qty = int(max_alloc / current_price)
                        else:
                            qty = int(max_alloc / current_price)
                            sl_price = round(current_price * 0.98, 2)
                            tp_price = round(current_price * 1.04, 2)
                    else:  # SHORT
                        if USE_ATR_STOPS and atr_14 > 0:
                            sl_dist = SL_ATR_MULT * atr_14
                            sl_price = round(current_price + sl_dist, 2)
                            tp_price = round(current_price - (TP_ATR_MULT * atr_14), 2)
                            if sl_dist > 0:
                                risk_cap = portfolio_val * RISK_PER_TRADE
                                qty = int(risk_cap / sl_dist)
                            else:
                                qty = int(max_alloc / current_price)
                        else:
                            qty = int(max_alloc / current_price)
                            sl_price = round(current_price * 1.02, 2)
                            tp_price = round(current_price * 0.96, 2)
                            
                    if locals().get("is_soft_penalty", False):
                        qty = int(qty * 0.5)
                        
                    if (qty * current_price) > max_alloc:
                        qty = int(max_alloc / current_price)

                    trade_cost = qty * current_price

                    if qty > 0 and trade_cost <= cash:"""

sizing_replace = """                    # Strict Risk Sizing
                    risk_dollars = portfolio_val * RISK_PER_TRADE
                    
                    if entry_action == "BUY":
                        if USE_ATR_STOPS and atr_14 > 0:
                            sl_dist = SL_ATR_MULT * atr_14
                            sl_price = current_price - sl_dist
                            tp_price = current_price + (TP_ATR_MULT * atr_14)
                        else:
                            sl_dist = current_price * 0.02
                            sl_price = current_price - sl_dist
                            tp_price = current_price * 1.04
                    else:  # SHORT
                        if USE_ATR_STOPS and atr_14 > 0:
                            sl_dist = SL_ATR_MULT * atr_14
                            sl_price = current_price + sl_dist
                            tp_price = current_price - (TP_ATR_MULT * atr_14)
                        else:
                            sl_dist = current_price * 0.02
                            sl_price = current_price + sl_dist
                            tp_price = current_price * 0.96
                    
                    if sl_dist <= 0:
                        sl_dist = 0.01

                    # HARD RULE: sizing calculation
                    import math
                    qty = math.floor(risk_dollars / sl_dist)
                    
                    # ASSERT: qty * |entry - SL| <= risk_dollars
                    if qty * sl_dist > risk_dollars + 0.01:
                        # Log and skip
                        print(f"RISK VIOLATION SKIPPED: qty {qty} * sl_dist {sl_dist:.2f} > {risk_dollars}")
                        qty = 0

                    if locals().get("is_soft_penalty", False):
                        qty = math.floor(qty * 0.5)
                        
                    trade_cost = qty * current_price
                    # Still bound by max capital per trade (cash or margin limit)
                    if trade_cost > max_alloc or trade_cost > cash:
                        qty = math.floor(min(max_alloc, cash) / current_price)
                        trade_cost = qty * current_price

                    if qty > 0:"""

content = content.replace(sizing_target, sizing_replace)

# Save positions sl_price and tp_price
pos_target = """                        positions[ticker] = {
                            "ticker": ticker,
                            "action": entry_action,
                            "entry_date": current_date,
                            "entry_price": current_price,
                            "qty": qty,
                            "stop_loss": sl_price,
                            "take_profit": tp_price,"""

pos_replace = """                        positions[ticker] = {
                            "ticker": ticker,
                            "action": entry_action,
                            "entry_date": current_date,
                            "entry_price": current_price,
                            "qty": qty,
                            "stop_loss": sl_price,
                            "take_profit": tp_price,
                            "sl_price": sl_price,
                            "tp_price": tp_price,
                            "risk_dollars": risk_dollars,"""

content = content.replace(pos_target, pos_replace)

# Fix Close Logic for gaps / risk violations
close_target = """                    if pos_action == "BUY":
                        # Long Stop Loss (-2%)
                        if current_price <= sl:
                            pnl = (current_price - entry_price) * pos["qty"]
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                            cash += current_price * pos["qty"]
                            closed_trade = {
                                "ticker": ticker,
                                "action": "BUY",
                                "entry_date": pos["entry_date"],
                                "exit_date": current_date,
                                "entry_price": entry_price,
                                "pnl_amount": pnl,
                                "pnl_pct": pnl_pct,
                                "win": False,
                                "exit_reason": "Stop Loss (-2%)",
                                "indicators_entry": pos.get("indicators", {}),
                            }
                            del positions[ticker]

                        # Long Take Profit (+4%)
                        elif current_price >= tp:
                            pnl = (current_price - entry_price) * pos["qty"]
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                            cash += current_price * pos["qty"]
                            closed_trade = {
                                "ticker": ticker,
                                "action": "BUY",
                                "entry_date": pos["entry_date"],
                                "exit_date": current_date,
                                "entry_price": entry_price,
                                "pnl_amount": pnl,
                                "pnl_pct": pnl_pct,
                                "win": True,
                                "exit_reason": "Take Profit (+4%)",
                                "indicators_entry": pos.get("indicators", {}),
                            }
                            del positions[ticker]

                    elif pos_action == "SHORT":
                        # Short Stop Loss (Price rises 2% above entry)
                        if current_price >= sl:
                            pnl = (entry_price - current_price) * pos["qty"]
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100.0
                            cash += entry_price * pos["qty"] + pnl  # Refund initial capital + PnL
                            closed_trade = {
                                "ticker": ticker,
                                "action": "SHORT",
                                "entry_date": pos["entry_date"],
                                "exit_date": current_date,
                                "entry_price": entry_price,
                                "pnl_amount": pnl,
                                "pnl_pct": pnl_pct,
                                "win": False,
                                "exit_reason": "Short Stop Loss (-2%)",
                                "indicators_entry": pos.get("indicators", {}),
                            }
                            del positions[ticker]

                        # Short Take Profit (Price drops 4% below entry)
                        elif current_price <= tp:
                            pnl = (entry_price - current_price) * pos["qty"]
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100.0
                            cash += entry_price * pos["qty"] + pnl  # Refund initial capital + PnL
                            closed_trade = {
                                "ticker": ticker,
                                "action": "SHORT",
                                "entry_date": pos["entry_date"],
                                "exit_date": current_date,
                                "entry_price": entry_price,
                                "pnl_amount": pnl,
                                "pnl_pct": pnl_pct,
                                "win": True,
                                "exit_reason": "Short Take Profit (+4%)",
                                "indicators_entry": pos.get("indicators", {}),
                            }
                            del positions[ticker]"""

close_replace = """                    if pos_action == "BUY":
                        if current_price <= sl:
                            pnl = (current_price - entry_price) * pos["qty"]
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                            cash += current_price * pos["qty"]
                            exit_flag = "Stop Loss"
                            if pnl < -(pos.get("risk_dollars", 1000) * 1.5):
                                exit_flag = "[RISK VIOLATION] Gap SL Hit"
                            closed_trade = {
                                "ticker": ticker, "action": "BUY", "entry_date": pos["entry_date"], "exit_date": current_date,
                                "entry_price": entry_price, "pnl_amount": pnl, "pnl_pct": pnl_pct, "win": False,
                                "exit_reason": "Stop Loss", "exit_reason_flag": exit_flag, "indicators_entry": pos.get("indicators", {}),
                                "sl_price": sl, "tp_price": tp, "qty": pos["qty"],
                            }
                            del positions[ticker]
                        elif current_price >= tp:
                            pnl = (current_price - entry_price) * pos["qty"]
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                            cash += current_price * pos["qty"]
                            closed_trade = {
                                "ticker": ticker, "action": "BUY", "entry_date": pos["entry_date"], "exit_date": current_date,
                                "entry_price": entry_price, "pnl_amount": pnl, "pnl_pct": pnl_pct, "win": True,
                                "exit_reason": "Take Profit", "exit_reason_flag": "Take Profit", "indicators_entry": pos.get("indicators", {}),
                                "sl_price": sl, "tp_price": tp, "qty": pos["qty"],
                            }
                            del positions[ticker]
                    elif pos_action == "SHORT":
                        if current_price >= sl:
                            pnl = (entry_price - current_price) * pos["qty"]
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100.0
                            cash += entry_price * pos["qty"] + pnl
                            exit_flag = "Stop Loss"
                            if pnl < -(pos.get("risk_dollars", 1000) * 1.5):
                                exit_flag = "[RISK VIOLATION] Gap SL Hit"
                            closed_trade = {
                                "ticker": ticker, "action": "SHORT", "entry_date": pos["entry_date"], "exit_date": current_date,
                                "entry_price": entry_price, "pnl_amount": pnl, "pnl_pct": pnl_pct, "win": False,
                                "exit_reason": "Stop Loss", "exit_reason_flag": exit_flag, "indicators_entry": pos.get("indicators", {}),
                                "sl_price": sl, "tp_price": tp, "qty": pos["qty"],
                            }
                            del positions[ticker]
                        elif current_price <= tp:
                            pnl = (entry_price - current_price) * pos["qty"]
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100.0
                            cash += entry_price * pos["qty"] + pnl
                            closed_trade = {
                                "ticker": ticker, "action": "SHORT", "entry_date": pos["entry_date"], "exit_date": current_date,
                                "entry_price": entry_price, "pnl_amount": pnl, "pnl_pct": pnl_pct, "win": True,
                                "exit_reason": "Take Profit", "exit_reason_flag": "Take Profit", "indicators_entry": pos.get("indicators", {}),
                                "sl_price": sl, "tp_price": tp, "qty": pos["qty"],
                            }
                            del positions[ticker]"""

content = content.replace(close_target, close_replace)

# EOD exit mapping
eod_target = """                cash += current_price * pos["qty"] + pnl
                closed_trade = {
                    "ticker": ticker,
                    "action": pos_action,
                    "entry_date": pos["entry_date"],
                    "exit_date": current_date,
                    "entry_price": entry_price,
                    "pnl_amount": pnl,
                    "pnl_pct": pnl_pct,
                    "win": pnl > 0,
                    "exit_reason": "End of Backtest Segment",
                    "indicators_entry": pos.get("indicators", {}),
                }"""

eod_replace = """                cash += current_price * pos["qty"] + pnl
                closed_trade = {
                    "ticker": ticker,
                    "action": pos_action,
                    "entry_date": pos["entry_date"],
                    "exit_date": current_date,
                    "entry_price": entry_price,
                    "pnl_amount": pnl,
                    "pnl_pct": pnl_pct,
                    "win": pnl > 0,
                    "exit_reason": "EOD/Segment End",
                    "exit_reason_flag": "EOD/Segment End",
                    "indicators_entry": pos.get("indicators", {}),
                    "sl_price": pos["stop_loss"],
                    "tp_price": pos["take_profit"],
                    "qty": pos["qty"],
                }"""
content = content.replace(eod_target, eod_replace)

with open("main_fix.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Saved to main_fix.py")
