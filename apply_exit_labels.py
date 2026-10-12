import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace hardcoded exit reasons with pos.get("sl_label", "Stop Loss")
content = content.replace('"exit_reason": "Stop Loss", "exit_reason_flag": exit_flag', '"exit_reason": pos.get("sl_label", "Stop Loss"), "exit_reason_flag": exit_flag')
content = content.replace('"exit_reason": "Take Profit", "exit_reason_flag": "Take Profit"', '"exit_reason": pos.get("tp_label", "Take Profit"), "exit_reason_flag": pos.get("tp_label", "Take Profit")')
content = content.replace('exit_flag = "Stop Loss"', 'exit_flag = pos.get("sl_label", "Stop Loss")')

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated exit logic string replacements")
