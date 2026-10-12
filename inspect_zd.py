exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

for term in [b'function zd(', b'var uB=', b'let uB=', b'const uB=', b'function tv(']:
    pos = data.find(term)
    if pos != -1:
        snippet = data[pos - 50:pos + 500].decode('utf-8', errors='ignore')
        print(f"=== {term} at {pos} ===")
        print(snippet[:300])
