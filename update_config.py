import os

with open("config.py", "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    if '"SPY",' in line:
        new_lines.append('    "TSLA",\n')
        new_lines.append('    "AMD",\n')

text = "".join(new_lines)
if "CONFLUENCE_THRESHOLD" not in text:
    text += '\n# --- Confluence Settings ---\nCONFLUENCE_THRESHOLD: int = int(os.getenv("CONFLUENCE_THRESHOLD", "3"))\n'

with open("config.py", "w") as f:
    f.write(text)
