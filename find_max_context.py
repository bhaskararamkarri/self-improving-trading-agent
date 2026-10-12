exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

pos = 0
while True:
    pos = data.find(b'CLAUDE_CODE_MAX_CONTEXT_TOKENS', pos)
    if pos == -1:
        break
    snippet = data[pos - 100:pos + 300].decode('utf-8', errors='ignore')
    print(f"=== Match at {pos} ===")
    print(snippet)
    pos += 30
