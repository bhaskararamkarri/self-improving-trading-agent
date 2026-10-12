import math

def simulate_sizing(capital, entry, sl):
    risk_dollars = capital * 0.01
    sl_dist = abs(entry - sl)
    
    # "risk" mode
    qty = math.floor(risk_dollars / sl_dist)
    cost = qty * entry
    max_alloc = capital * 0.25
    
    print(f"--- Sizing Test ---")
    print(f"Capital: ${capital}, Entry: ${entry}, SL: ${sl}, Risk: ${risk_dollars}")
    print(f"Initial calc -> Qty: {qty}, Cost: ${cost}")
    
    if cost > max_alloc:
        trimmed_qty = math.floor(max_alloc / entry)
        print(f"[SIZE] Trimmed to capital cap: {trimmed_qty} (Cost: ${trimmed_qty * entry})")
        qty = trimmed_qty
    else:
        print(f"Qty {qty} allowed. Cost: ${cost} <= ${max_alloc} cap")

if __name__ == "__main__":
    simulate_sizing(10000, 100, 98)
    simulate_sizing(10000, 500, 490)
