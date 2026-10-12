import re
import sys

with open("nodes/risk_check.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add snapshots extraction
content = content.replace('for decision in raw_decisions:', 'snapshots = state.get("market_snapshots", {})\n\n    for decision in raw_decisions:')

# Replace target_qty and SL/TP for BUY
buy_target = """            target_qty = max_trade_capital / price
            # Round quantity (whole shares if price > $10, otherwise 4 decimals)"""

buy_replace = """            snapshot = snapshots.get(ticker, {})
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

            # Round quantity (whole shares if price > $10, otherwise 4 decimals)"""
content = content.replace(buy_target, buy_replace)

buy_sl_target = """            # Set exact 2% Stop Loss and 4% Take Profit
            decision["quantity"] = qty
            decision["stop_loss"] = round(price * (1.0 - STOP_LOSS_PERCENT), 2)
            decision["take_profit"] = round(price * (1.0 + TAKE_PROFIT_PERCENT), 2)"""

buy_sl_replace = """            decision["quantity"] = qty
            decision["stop_loss"] = round(sl_price, 2)
            decision["take_profit"] = round(tp_price, 2)"""
content = content.replace(buy_sl_target, buy_sl_replace)


# Replace target_qty and SL/TP for SHORT
short_target = """            target_qty = max_trade_capital / price
            qty = round(target_qty, 4) if price < 10.0 else int(target_qty)"""

short_replace = """            snapshot = snapshots.get(ticker, {})
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

            qty = round(target_qty, 4) if price < 10.0 else int(target_qty)"""
content = content.replace(short_target, short_replace)

short_sl_target = """            decision["quantity"] = qty
            decision["stop_loss"] = round(price * (1.0 + STOP_LOSS_PERCENT), 2)  # 2% stop above
            decision["take_profit"] = round(price * (1.0 - TAKE_PROFIT_PERCENT), 2)  # 4% take profit below"""

short_sl_replace = """            decision["quantity"] = qty
            decision["stop_loss"] = round(sl_price, 2)
            decision["take_profit"] = round(tp_price, 2)"""
content = content.replace(short_sl_target, short_sl_replace)

with open("nodes/risk_check.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated risk_check.py")
