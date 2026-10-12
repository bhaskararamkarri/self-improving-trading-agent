exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

pos = 211721416
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
# Find all definitions of pf in range [pos - 50000, pos]
idx = pos - 30000
while idx < pos:
    p = data.find(b'pf(', idx)
    if p != -1 and p < pos:
        # Check if it's declaration
        snippet = data[max(0, p - 60):min(len(data), p + 80)].decode('utf-8', errors='ignore')
        if 'function' in snippet or 'var pf' in snippet or 'let pf' in snippet or 'const pf' in snippet or 'pf=' in snippet:
            print(f"Declaration at {p}: {snippet}")
        idx = p + 3
    else:
        break
