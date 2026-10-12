import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace the entire sizing and position logging block
sizing_block_target = """                    # Strict Risk Sizing
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

                    if qty > 0:
                        cash -= trade_cost

                        positions[ticker] = {
                            "ticker": ticker,
                            "action": entry_action,
                            "entry_date": current_date,
                            "entry_price": current_price,
                            "qty": qty,
                            "stop_loss": sl_price,
                            "take_profit": tp_price,
                            "sl_price": sl_price,
                            "tp_price": tp_price,
                            "risk_dollars": risk_dollars,
                            "indicators": {
                                "rsi_14": rsi,
                                "ema_9": ema9,
                                "ema_21": ema21,
                                "ema_50": ema50,
                                "ema_200": ema200,
                                "macd_hist": macd_hist,
                            }
                        }"""

sizing_block_replace = """                    # Strict Risk Sizing & ATR Exit Tags
                    from config import POSITION_SIZING_MODE
                    risk_dollars = portfolio_val * RISK_PER_TRADE
                    
                    sl_label = ""
                    tp_label = ""
                    
                    if entry_action == "BUY":
                        if USE_ATR_STOPS and atr_14 > 0:
                            sl_dist = SL_ATR_MULT * atr_14
                            sl_price = current_price - sl_dist
                            tp_price = current_price + (TP_ATR_MULT * atr_14)
                            sl_label = f"SL ({SL_ATR_MULT}xATR)"
                            tp_label = f"TP ({TP_ATR_MULT}xATR)"
                        else:
                            sl_dist = current_price * 0.02
                            sl_price = current_price - sl_dist
                            tp_price = current_price * 1.04
                            sl_label = "Stop Loss (-2%)"
                            tp_label = "Take Profit (+4%)"
                    else:  # SHORT
                        if USE_ATR_STOPS and atr_14 > 0:
                            sl_dist = SL_ATR_MULT * atr_14
                            sl_price = current_price + sl_dist
                            tp_price = current_price - (TP_ATR_MULT * atr_14)
                            sl_label = f"Short SL ({SL_ATR_MULT}xATR)"
                            tp_label = f"Short TP ({TP_ATR_MULT}xATR)"
                        else:
                            sl_dist = current_price * 0.02
                            sl_price = current_price + sl_dist
                            tp_price = current_price * 0.96
                            sl_label = "Short Stop Loss (-2%)"
                            tp_label = "Short Take Profit (+4%)"
                    
                    if sl_dist <= 0:
                        sl_dist = 0.01

                    import math
                    
                    if POSITION_SIZING_MODE == "risk":
                        # Risk mode: qty based on risk bucket, capped at 25% portfolio safety limit
                        qty = math.floor(risk_dollars / sl_dist)
                        max_safety_alloc = portfolio_val * 0.25
                        if qty * current_price > max_safety_alloc:
                            # Trim to capital cap
                            qty = math.floor(max_safety_alloc / current_price)
                            # print(f"[SIZE] Trimmed to capital cap: {qty} (Cost: ${qty*current_price})")
                    else:
                        # Alloc mode: old 20% cap
                        max_alloc = portfolio_val * 0.20
                        qty = math.floor(max_alloc / current_price)
                        
                    # ASSERT: qty * |entry - SL| <= risk_dollars (unless trimmed by capital)
                    if qty * sl_dist > risk_dollars + 0.01:
                        qty = 0

                    if locals().get("is_soft_penalty", False):
                        qty = math.floor(qty * 0.5)
                        
                    trade_cost = qty * current_price
                    # Still bound by available cash
                    if trade_cost > cash:
                        qty = math.floor(cash / current_price)
                        trade_cost = qty * current_price

                    if qty > 0:
                        cash -= trade_cost

                        positions[ticker] = {
                            "ticker": ticker,
                            "action": entry_action,
                            "entry_date": current_date,
                            "entry_price": current_price,
                            "qty": qty,
                            "stop_loss": sl_price,
                            "take_profit": tp_price,
                            "sl_price": sl_price,
                            "tp_price": tp_price,
                            "sl_label": sl_label,
                            "tp_label": tp_label,
                            "risk_dollars": risk_dollars,
                            "indicators": {
                                "rsi_14": rsi,
                                "ema_9": ema9,
                                "ema_21": ema21,
                                "ema_50": ema50,
                                "ema_200": ema200,
                                "macd_hist": macd_hist,
                            }
                        }"""

content = content.replace(sizing_block_target, sizing_block_replace)

# Fix exit labels usage
exit_block_target = """                                "win": False,
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

exit_block_replace = """                                "win": False,
                                "exit_reason": pos.get("sl_label", "Stop Loss"), "exit_reason_flag": exit_flag, "indicators_entry": pos.get("indicators", {}),
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
                                "exit_reason": pos.get("tp_label", "Take Profit"), "exit_reason_flag": pos.get("tp_label", "Take Profit"), "indicators_entry": pos.get("indicators", {}),
                                "sl_price": sl, "tp_price": tp, "qty": pos["qty"],
                            }
                            del positions[ticker]
                    elif pos_action == "SHORT":
                        if current_price >= sl:
                            pnl = (entry_price - current_price) * pos["qty"]
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100.0
                            cash += entry_price * pos["qty"] + pnl
                            exit_flag = pos.get("sl_label", "Short Stop Loss")
                            if pnl < -(pos.get("risk_dollars", 1000) * 1.5):
                                exit_flag = "[RISK VIOLATION] Gap SL Hit"
                            closed_trade = {
                                "ticker": ticker, "action": "SHORT", "entry_date": pos["entry_date"], "exit_date": current_date,
                                "entry_price": entry_price, "pnl_amount": pnl, "pnl_pct": pnl_pct, "win": False,
                                "exit_reason": pos.get("sl_label", "Short Stop Loss"), "exit_reason_flag": exit_flag, "indicators_entry": pos.get("indicators", {}),
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
                                "exit_reason": pos.get("tp_label", "Short Take Profit"), "exit_reason_flag": pos.get("tp_label", "Short Take Profit"), "indicators_entry": pos.get("indicators", {}),
                                "sl_price": sl, "tp_price": tp, "qty": pos["qty"],
                            }
                            del positions[ticker]"""

content = content.replace(exit_block_target, exit_block_replace)

# Also fix the EOD exit reason flag to avoid overriding actual reason logic in DB
eod_target = """                    "exit_reason": "EOD/Segment End",
                    "exit_reason_flag": "EOD/Segment End","""
eod_replace = """                    "exit_reason": "EOD/Segment End",
                    "exit_reason_flag": "EOD/Segment End","""
# Nothing to change here, looks fine.

with open("main_fix_sizing.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Saved to main_fix_sizing.py")
