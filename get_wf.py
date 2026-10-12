import subprocess
import re
result = subprocess.run(["python", "main.py", "--backtest"], capture_output=True, text=True, encoding='utf-8')
wf_match = re.search(r'(b\)\s*Walk-Forward Validation: Fold 1/2/3 Out-of-Sample Win Rates.*?)(?=\(c\)\s*Overall)', result.stdout, re.DOTALL)
if wf_match:
    with open("wf_output.txt", "w", encoding="utf-8") as f:
        f.write(wf_match.group(1))
