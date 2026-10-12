exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

pos = 211721416
snippet = data[pos - 500:pos + 3000].decode('utf-8', errors='ignore')
print(snippet)
