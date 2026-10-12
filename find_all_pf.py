exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

for term in [b'function pf(', b'function pf ', b'var pf=', b'let pf=', b'const pf=']:
    idx = 0
    while True:
        pos = data.find(term, idx)
        if pos == -1:
            break
        snippet = data[pos:pos + 300].decode('utf-8', errors='ignore')
        print(f"Match for {term} at {pos}: {snippet[:150]}")
        idx = pos + len(term)
