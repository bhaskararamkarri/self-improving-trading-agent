import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """          f_lessons = f_reflector._generate_heuristic_lessons(trades=f_records, stats=f_stats)"""

replace = """          import json
          if fold_id == 3:
              fold3_out = []
              for idx, t in enumerate(f_test_res["trades"], 1):
                  pnl = t["pnl_amount"]
                  risk = t.get("risk_dollars", 100.0)
                  fold3_out.append({"ticker": t["ticker"], "pnl": pnl, "r_multi": pnl / risk, "exit": t["exit_reason"]})
              with open("fold3_trades.json", "w") as jf:
                  json.dump(fold3_out, jf, indent=2)
          f_lessons = f_reflector._generate_heuristic_lessons(trades=f_records, stats=f_stats)"""

content = content.replace(target, replace)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Added Fold 3 logger")
