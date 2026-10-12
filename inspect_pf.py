exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

# Search for "function pf(" or "function pf "
pos = data.find(b'function pf(')
if pos == -1:
    pos = data.find(b'pf=')
print("Position:", pos)
if pos != -1:
    snippet = data[pos - 100:pos + 1500].decode('utf-8', errors='ignore')
    print(snippet)
