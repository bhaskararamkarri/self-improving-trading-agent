import re

# UPDATE CONFIG.PY
with open("config.py", "r", encoding="utf-8") as f:
    config_content = f.read()

if "POSITION_SIZING_MODE" not in config_content:
    sizing_params = """
# --- Sizing Parameters ---
POSITION_SIZING_MODE: str = os.getenv("POSITION_SIZING_MODE", "risk") # "risk" or "alloc"

# --- Storage Settings ---"""
    config_content = config_content.replace("# --- Storage Settings ---", sizing_params)
    with open("config.py", "w", encoding="utf-8") as f:
        f.write(config_content)
