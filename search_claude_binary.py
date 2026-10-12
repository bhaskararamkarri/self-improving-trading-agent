import re

exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

print("File size:", len(data))

# Search for context window definitions
for pattern in [rb'contextWindow', rb'autoCompactWindow', rb'behavesAs', rb'CLAUDE_CODE_', rb'autoCompact']:
    matches = set(re.findall(pattern + rb'[a-zA-Z0-9_\-:]*', data))
    print(f"Pattern {pattern}:", [m.decode('ascii', errors='ignore') for m in list(matches)[:15]])
