exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

pos = data.find(b'[1m]')
print("pos:", pos)
if pos != -1:
    snippet = data[pos - 500:pos + 1000].decode('utf-8', errors='ignore')
    print(snippet)
