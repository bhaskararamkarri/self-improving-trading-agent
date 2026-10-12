import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('"exit_reason": "Stop Loss (-2%)",', '"exit_reason": pos.get("sl_label", "Stop Loss (-2%)"),')
content = content.replace('"exit_reason": "Take Profit (+4%)",', '"exit_reason": pos.get("tp_label", "Take Profit (+4%)"),')
content = content.replace('"exit_reason": "Short Stop Loss (-2%)",', '"exit_reason": pos.get("sl_label", "Short Stop Loss (-2%)"),')
content = content.replace('"exit_reason": "Short Take Profit (+4%)",', '"exit_reason": pos.get("tp_label", "Short Take Profit (+4%)"),')

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated exactly!")
