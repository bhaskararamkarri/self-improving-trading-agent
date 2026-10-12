import math

def simulate_trade(capital, risk_per_trade, entry_price, sl_price, exit_price):
    risk_dollars = capital * risk_per_trade
    sl_dist = abs(entry_price - sl_price)
    
    qty = math.floor(risk_dollars / sl_dist)
    expected_risk = qty * sl_dist
    
    print(f"--- MOCK SCENARIO ---")
    print(f"Capital: ${capital}, Risk/Trade: {risk_per_trade*100}%, Entry: ${entry_price}, SL: ${sl_price}")
    print(f"Target Risk: ${risk_dollars}")
    print(f"SL Distance: ${sl_dist:.2f}")
    
    if expected_risk > risk_dollars + 0.01:
        print(f"RISK VIOLATION: qty {qty} * sl_dist {sl_dist:.2f} = {expected_risk:.2f} > {risk_dollars}")
        return
        
    print(f"Sizing PASS: Qty = {qty}, Allocated Risk = ${expected_risk:.2f}")
    
    # Simulate exit
    pnl = (exit_price - entry_price) * qty if entry_price > sl_price else (entry_price - exit_price) * qty
    print(f"Actual Exit Price: ${exit_price}, Actual PnL: ${pnl:.2f}")
    
    if pnl < -(risk_dollars * 1.5):
        print(f"-> [RISK VIOLATION] Gap SL Hit! Loss ${pnl:.2f} exceeded 1.5x threshold (${risk_dollars * 1.5:.2f})")
    elif pnl < -risk_dollars:
        print(f"-> Normal SL Hit (Slight slippage/gap allowed). Loss ${pnl:.2f}")
    else:
        print(f"-> Trade closed cleanly. PnL ${pnl:.2f}")
    print()

if __name__ == "__main__":
    # Normal fill
    simulate_trade(10000, 0.01, 100.0, 95.0, 95.0)
    
    # 1.5x gap fill
    simulate_trade(10000, 0.01, 100.0, 95.0, 90.0)
    
    # Sizing edge case (Stock price high, SL distance small, qty floor kicks in)
    simulate_trade(10000, 0.01, 300.0, 298.0, 298.0)
    
    # Sizing edge case (SL distance huge, qty 0)
    simulate_trade(10000, 0.01, 100.0, 50.0, 50.0)
