import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

trend_target = """                    if not vetoed:
                        in_macro_trend = (current_price >= ema21) and (current_price >= ema50 or ema50 >= ema200)
                        pullback_sweet_spot = (42.0 <= rsi <= 56.0)
                        reversal_confirmation = is_green and (current_price >= ema9) and (macd_hist >= 0.0)
                        resistance_clearance = current_price < bb_upper

                        if in_macro_trend and pullback_sweet_spot and reversal_confirmation and resistance_clearance:
                            entry_action = "BUY"

                if entry_action:
                    portfolio_val = cash + sum(p["qty"] * current_price for p in positions.values())"""

trend_replace = """                    if not vetoed:
                        in_macro_trend = (current_price >= ema21) and (current_price >= ema50 or ema50 >= ema200)
                        pullback_sweet_spot = (42.0 <= rsi <= 56.0)
                        reversal_confirmation = is_green and (current_price >= ema9) and (macd_hist >= 0.0)
                        resistance_clearance = current_price < bb_upper

                        if in_macro_trend and pullback_sweet_spot and reversal_confirmation and resistance_clearance:
                            entry_action = "BUY"

                # APPLY TREND FILTER
                from config import TREND_FILTER
                if entry_action and TREND_FILTER:
                    sma200 = float(bar.get("SMA_200", ema200))
                    if entry_action == "BUY" and current_price < sma200:
                        rejected[ticker] = {
                            "action": entry_action,
                            "entry_price": current_price,
                            "reasoning": f"[TREND] Filtered: long {ticker} vs SMA200 down",
                        }
                        entry_action = None
                    elif entry_action == "SHORT" and current_price > sma200:
                        rejected[ticker] = {
                            "action": entry_action,
                            "entry_price": current_price,
                            "reasoning": f"[TREND] Filtered: short {ticker} vs SMA200 up",
                        }
                        entry_action = None

                if entry_action:
                    portfolio_val = cash + sum(p["qty"] * current_price for p in positions.values())"""

content = content.replace(trend_target, trend_replace)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated main.py with trend filter")
