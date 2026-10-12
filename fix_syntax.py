import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('# print(f"--- Confluence Trigger [{ticker}] BUY --- Score: {l_score}\n{l_brk}")', '# print("buy")')
content = content.replace('# print(f"--- Confluence Trigger [{ticker}] SHORT --- Score: {s_score}\n{s_brk}")', '# print("short")')

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed syntax error")
