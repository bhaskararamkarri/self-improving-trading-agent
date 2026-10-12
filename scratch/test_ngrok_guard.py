import sys
import os
import requests
from pathlib import Path

# Ensure workspace root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import WEBHOOK_PUBLIC_URL
from server.webhook import check_ngrok_tunnel_guard

print(f"Configured WEBHOOK_PUBLIC_URL: {WEBHOOK_PUBLIC_URL}")
res = check_ngrok_tunnel_guard()
print("Guard result:", res)

# Verify ngrok is running and no drift
assert res["ngrok_running"] is True, "ngrok should be detected as running"
assert res["url_drift"] is False, f"Expected no URL drift, but got drift: {res}"
print("SUCCESS: ngrok tunnel guard verified without URL drift!")
