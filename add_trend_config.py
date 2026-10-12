import re

with open("config.py", "r", encoding="utf-8") as f:
    content = f.read()

trend_params = """
# --- Trend Filter Parameters ---
TREND_FILTER: bool = os.getenv("TREND_FILTER", "true").lower() == "true"
TREND_SMA_PERIOD: int = int(os.getenv("TREND_SMA_PERIOD", "200"))
TREND_TF: str = os.getenv("TREND_TF", "1d")

# --- Storage Settings ---"""

content = content.replace("# --- Storage Settings ---", trend_params)

with open("config.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated config.py")
