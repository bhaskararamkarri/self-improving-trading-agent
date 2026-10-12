import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """                    if entry_action == "BUY":
                        if USE_ATR_STOPS and atr_14 > 0:"""

replace = """                    if entry_action == "BUY":
                        logger.info(f"DEBUG: entry_action=BUY, USE_ATR_STOPS={USE_ATR_STOPS}, atr_14={atr_14}, sl_atr_mult={SL_ATR_MULT}")
                        if USE_ATR_STOPS and atr_14 > 0:"""

content = content.replace(target, replace)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Added debug prints")
