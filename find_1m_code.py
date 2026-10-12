exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# Search for '[1m]' or '1m' in JS code
pos = data.find(b'append [1m]')
print("pos:", pos)
# search where that message is referenced:
snippet = data[pos - 100:pos + 1000].decode('utf-8', errors='ignore')
print(snippet)
