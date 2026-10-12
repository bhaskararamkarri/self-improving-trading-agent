import re
with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix the local_veto bug to expose is_soft_penalty
veto_target = """                        vetoed = False
                        from config import LESSON_MODE
                        is_soft = LESSON_MODE.lower() == "soft"
                        for l_dict in lessons:"""
veto_replace = """                        vetoed = False
                        is_soft_penalty = False
                        from config import LESSON_MODE
                        is_soft = LESSON_MODE.lower() == "soft"
                        for l_dict in lessons:"""
content = content.replace(veto_target, veto_replace)

veto2_target = """                            if local_veto:
                                if is_soft:
                                    # Don't veto, we will reduce qty
                                    pass
                                else:
                                    vetoed = True"""
veto2_replace = """                            if local_veto:
                                if is_soft:
                                    is_soft_penalty = True
                                else:
                                    vetoed = True"""
content = content.replace(veto2_target, veto2_replace)


qty_target = """                if entry_action:
                    portfolio_val = cash + sum(p["qty"] * current_price for p in positions.values())
                    max_alloc = portfolio_val * max_position_percent
                    qty = int(max_alloc / current_price) if current_price > 0 else 0
                    trade_cost = qty * current_price

                    if qty > 0 and trade_cost <= cash:
                        cash -= trade_cost
                        if entry_action == "BUY":
                            sl_price = round(current_price * 0.98, 2)
                            tp_price = round(current_price * 1.04, 2)
                        else:  # SHORT
                            sl_price = round(current_price * 1.02, 2)
                            tp_price = round(current_price * 0.96, 2)"""

qty_replace = """                if entry_action:
                    portfolio_val = cash + sum(p["qty"] * current_price for p in positions.values())
                    max_alloc = portfolio_val * max_position_percent
                    
                    from config import USE_ATR_STOPS, SL_ATR_MULT, TP_ATR_MULT, RISK_PER_TRADE
                    atr_14 = float(bar.get("ATR_14", max(0.01, current_price * 0.01)))
                    
                    if entry_action == "BUY":
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

                    if qty > 0 and trade_cost <= cash:
                        cash -= trade_cost"""
content = content.replace(qty_target, qty_replace)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated main.py backtest logic")
