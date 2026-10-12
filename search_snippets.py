import re

exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

# Search for occurrences of contextWindow in the binary
idx = 0
found = 0
while True:
    pos = data.find(b'contextWindow', idx)
    if pos == -1 or found > 10:
        break
    snippet = data[max(0, pos - 150):min(len(data), pos + 250)]
    try:
        decoded = snippet.decode('utf-8', errors='ignore')
        if any(w in decoded for w in ['model', '200', '1000', 'tokens', 'compact', 'behavesAs']):
            print(f"=== Match at {pos} ===")
            print(decoded)
            found += 1
    except:
        pass
    idx = pos + 13
