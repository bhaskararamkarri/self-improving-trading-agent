import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

atr_target = """                    from config import USE_ATR_STOPS, SL_ATR_MULT, TP_ATR_MULT, RISK_PER_TRADE
                    atr_14 = float(bar.get("ATR_14", max(0.01, current_price * 0.01)))
                    
                    # Strict Risk Sizing & ATR Exit Tags"""

atr_replace = """                    from config import USE_ATR_STOPS, SL_ATR_MULT, TP_ATR_MULT, RISK_PER_TRADE
                    atr_val = bar.get("ATR_14", None)
                    import pandas as pd
                    if atr_val is None or pd.isna(atr_val):
                        atr_14 = max(0.01, current_price * 0.01)
                    else:
                        atr_14 = float(atr_val)
                    
                    # Strict Risk Sizing & ATR Exit Tags"""

content = content.replace(atr_target, atr_replace)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated atr NaN check in main.py")
