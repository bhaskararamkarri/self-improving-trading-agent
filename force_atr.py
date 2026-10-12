import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("if USE_ATR_STOPS and atr_14 > 0:", "if True:")

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Forced ATR STOPS to True")
