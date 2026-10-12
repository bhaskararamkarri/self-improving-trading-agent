import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """                    atr_val = bar.get("ATR_14", None)
                    import pandas as pd
                    if atr_val is None or pd.isna(atr_val):"""

replace = """                    atr_val = bar.get("ATR_14", None)
                    if atr_val is None or pd.isna(atr_val):"""

content = content.replace(target, replace)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Removed local pd import")
