import sys
import os
import time
import threading
import requests
import uvicorn
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from server.webhook import app
from config import WEBHOOK_SECRET, WEBHOOK_PUBLIC_URL

# Start uvicorn on port 8000 in daemon thread
config = uvicorn.Config(app=app, host="127.0.0.1", port=8000, log_level="warning")
server = uvicorn.Server(config)

server_thread = threading.Thread(target=server.run, daemon=True)
server_thread.start()

# Give server 2 seconds to start
time.sleep(2)

print("\n--- 1. Testing Local Server ---")
resp_local = requests.get("http://127.0.0.1:8000/health")
print("Local /health:", resp_local.status_code, resp_local.json())
assert resp_local.status_code == 200

resp_api = requests.get("http://127.0.0.1:8000/api/health")
print("Local /api/health:", resp_api.status_code, resp_api.json())
assert resp_api.status_code == 200
assert "ts" in resp_api.json()
assert "capital" in resp_api.json()

print("\n--- 2. Testing End-to-End via Public ngrok Tunnel ---")
public_domain = "https://pseudoviperously-quercetic-abe.ngrok-free.dev"

# Note: ngrok free tier displays an interstitial warning page unless ngrok-skip-browser-warning header is passed,
# but for programmatic/POST or with custom user-agent it passes directly.
headers = {
    "ngrok-skip-browser-warning": "true",
    "User-Agent": "TradingView-Webhook-Client/1.0",
}
resp_pub = requests.get(f"{public_domain}/health", headers=headers, timeout=10)
print(f"Public {public_domain}/health status:", resp_pub.status_code, resp_pub.json())
assert resp_pub.status_code == 200

resp_pub_api = requests.get(f"{public_domain}/api/health", headers=headers, timeout=10)
print(f"Public {public_domain}/api/health status:", resp_pub_api.status_code, resp_pub_api.json())
assert resp_pub_api.status_code == 200

print("\n--- 3. Testing Public Webhook Endpoint (Auth Verification) ---")
headers_webhook = {
    "Content-Type": "application/json",
    "X-Webhook-Secret": WEBHOOK_SECRET,
    "ngrok-skip-browser-warning": "true",
}
payload = {
    "ticker": "AAPL",
    "action": "buy",
    "price": 220.0,
    "timeframe": "1D",
    "mode": "test",
    "force_market_open": True,
}
resp_post = requests.post(f"{public_domain}/webhook/signal", json=payload, headers=headers_webhook, timeout=10)
print(f"Public {public_domain}/webhook/signal status:", resp_post.status_code, resp_post.json())
assert resp_post.status_code == 200
assert resp_post.json().get("status") in ["SUCCESS", "SIMULATED", "BLOCKED", "RISK_REJECTED", "rejected"]

print("\nALL END-TO-END VERIFICATIONS PASSED SUCCESSFULLY!")
server.should_exit = True
