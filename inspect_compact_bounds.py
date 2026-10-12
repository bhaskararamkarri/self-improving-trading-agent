exe_path = r'C:\Users\BHASKARARAM\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\node_modules\@anthropic-ai\claude-code-win32-x64\claude.exe'
with open(exe_path, 'rb') as f:
    data = f.read()

pos = 211727245
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
snippet = data[pos - 300:pos + 1500].decode('utf-8', errors='ignore')
print(snippet)
