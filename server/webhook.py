"""FastAPI Webhook Server for TradingView Alert Ingestion.

Receives alerts from TradingView or external webhooks, authenticates via secret,
validates payload structure, and delegates to the ExternalSignalValidator layer.
Emits periodic 5-minute background heartbeats and provides /api/health endpoint.
Guards against ngrok URL drift on startup.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from config import (
    logger,
    WEBHOOK_SECRET,
    WEBHOOK_PUBLIC_URL,
    TICKERS,
    EXECUTION_MODE,
)
from signals.external_validator import ExternalSignalValidator


app = FastAPI(
    title="Self-Improving Trading Agent - Webhook Receiver",
    description="Ingests external TradingView signals with strict authentication and risk validation",
    version="1.0.0",
)

validator = ExternalSignalValidator()

# Signal timing tracker for heartbeat
_last_signal_time: Optional[float] = None


def record_signal_received() -> None:
    """Updates the timestamp of the most recent incoming signal."""
    global _last_signal_time
    _last_signal_time = time.time()


def get_last_signal_age() -> str:
    """Returns the elapsed time since last signal, e.g. '42s' or 'never'."""
    if _last_signal_time is None:
        return "never"
    age_sec = int(time.time() - _last_signal_time)
    return f"{age_sec}s"


def get_heartbeat_data() -> Dict[str, Any]:
    """Compiles the 6 canonical heartbeat fields with full try/except crash safety."""
    try:
        from storage.database import TradeDatabase
        from broker.alpaca_client import is_us_market_open
        from config import PAPER_CAPITAL

        db = TradeDatabase()
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN' AND mode = 'paper'")
            open_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'CLOSED' AND mode = 'paper'")
            closed_count = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(pnl_amount) FROM trades WHERE status = 'CLOSED' AND mode = 'paper'")
            total_pnl = cursor.fetchone()[0] or 0.0

        capital = PAPER_CAPITAL + total_pnl
        try:
            is_open, _ = is_us_market_open()
            market_status = "OPEN" if is_open else "CLOSED"
        except Exception:
            market_status = "UNKNOWN"

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sig_age = get_last_signal_age()

        return {
            "ts": ts,
            "open": open_count,
            "closed": closed_count,
            "capital": round(capital, 2),
            "market": market_status,
            "last_signal_age": sig_age,
        }
    except Exception as e:
        logger.error(f"[HEARTBEAT] Error compiling heartbeat data: {e}", exc_info=True)
        from config import PAPER_CAPITAL
        return {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": 0,
            "closed": 0,
            "capital": PAPER_CAPITAL,
            "market": "UNKNOWN",
            "last_signal_age": "never",
        }


def format_heartbeat_log(data: Dict[str, Any]) -> str:
    """Formats canonical heartbeat log string exactly per specification."""
    return (
        f"[HEARTBEAT] ts={data['ts']} | "
        f"open={data['open']} | "
        f"closed={data['closed']} | "
        f"capital=${data['capital']:,.2f} | "
        f"market={data['market']} | "
        f"last_signal_age={data['last_signal_age']}"
    )


def check_ngrok_tunnel_guard() -> Dict[str, Any]:
    """Inspects running ngrok tunnel, detects URL drift, and runs end-to-end self-test."""
    import requests

    info = {
        "ngrok_running": False,
        "public_url": None,
        "configured_url": WEBHOOK_PUBLIC_URL,
        "url_drift": False,
        "health_status": None,
    }
    try:
        resp = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=1.0)
        if resp.status_code == 200:
            tunnels = resp.json().get("tunnels", [])
            if tunnels:
                info["ngrok_running"] = True
                https_tunnels = [t for t in tunnels if t.get("proto") == "https" or str(t.get("public_url", "")).startswith("https")]
                chosen = https_tunnels[0] if https_tunnels else tunnels[0]
                info["public_url"] = chosen.get("public_url")
    except Exception:
        pass

    if info["ngrok_running"] and info["public_url"]:
        pub_url = info["public_url"]
        logger.info(f"[NGROK] Current active ngrok public URL: {pub_url}")
        if WEBHOOK_PUBLIC_URL:
            pub_clean = pub_url.rstrip("/")
            conf_clean = WEBHOOK_PUBLIC_URL.rstrip("/")
            if pub_clean not in conf_clean and conf_clean not in pub_clean:
                info["url_drift"] = True
                logger.warning(
                    f"[WARN] WEBHOOK URL CHANGED — update TradingView alert "
                    f"(Current ngrok: {pub_url}, Configured in .env: {WEBHOOK_PUBLIC_URL})"
                )
            else:
                logger.info(f"[NGROK] Webhook public URL matches configured WEBHOOK_PUBLIC_URL: {WEBHOOK_PUBLIC_URL}")
        else:
            logger.warning(
                f"[WARN] WEBHOOK URL CHANGED — update TradingView alert "
                f"(Current ngrok: {pub_url}, WEBHOOK_PUBLIC_URL not configured in .env)"
            )

        # Self-test endpoint check: curl /health from public URL
        try:
            headers = {"ngrok-skip-browser-warning": "true"}
            test_resp = requests.get(f"{pub_url}/health", headers=headers, timeout=5.0)
            info["health_status"] = test_resp.status_code
            if test_resp.status_code == 200:
                logger.info(f"[INFO] Webhook tunnel self-test: {pub_url}/health returned 200 OK (tunnel alive end-to-end)")
            else:
                logger.warning(f"[WARN] Webhook tunnel self-test returned status {test_resp.status_code}")
        except Exception as exc:
            info["health_status"] = str(exc)
            logger.warning(f"[WARN] Webhook tunnel self-test failed to reach {pub_url}/health: {exc}")
    else:
        logger.warning("[WARN] ngrok is not running on http://127.0.0.1:4040. Public TradingView alerts cannot reach this local server until ngrok is started.")

    return info


async def _background_heartbeat_loop():
    """Background task logging heartbeats every 5 minutes (300s) without crashing."""
    await asyncio.sleep(5)  # initial pause to let startup logs complete
    while True:
        try:
            data = get_heartbeat_data()
            logger.info(format_heartbeat_log(data))
        except Exception as e:
            logger.error(f"[HEARTBEAT] Error in background heartbeat loop: {e}")
        await asyncio.sleep(300)


@app.on_event("startup")
async def on_startup():
    """Runs startup security and connectivity checks and launches background workers."""
    async def _run_guard_after_bind():
        await asyncio.sleep(1.0)
        try:
            await asyncio.to_thread(check_ngrok_tunnel_guard)
        except Exception as e:
            logger.warning(f"[STARTUP] ngrok check exception: {e}")

    asyncio.create_task(_run_guard_after_bind())
    asyncio.create_task(_background_heartbeat_loop())


class TradingViewSignal(BaseModel):
    ticker: str = Field(..., description="Ticker symbol (e.g. NVDA, AAPL, SPY)")
    action: str = Field(..., description="Action: buy, sell, close, or short")
    price: float = Field(..., description="Alert trigger price")
    secret: Optional[str] = Field(None, description="Optional webhook secret in body")
    timeframe: Optional[str] = Field("1D", description="Signal timeframe (e.g. 15m, 1h, 1D)")
    mode: Optional[str] = Field("paper", description="Execution mode: paper or test")
    # Test simulation hooks
    force_market_open: Optional[bool] = Field(None, description="Simulation override for market hours")
    mock_current_price: Optional[float] = Field(None, description="Simulation override for current price")
    mock_atr: Optional[float] = Field(None, description="Simulation override for current ATR")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Logs and handles 422 payload validation errors."""
    logger.warning(f"[WEBHOOK] Invalid payload: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "[WEBHOOK] Invalid payload", "errors": exc.errors()},
    )


@app.get("/health")
def health_check():
    """Health check endpoint (backward compatible)."""
    return {
        "status": "healthy",
        "execution_mode": EXECUTION_MODE,
        "configured_tickers": TICKERS,
    }


@app.get("/api/health")
def api_health():
    """Periodic heartbeat health endpoint returning canonical JSON fields."""
    return get_heartbeat_data()


@app.post("/webhook/signal")
async def receive_tradingview_signal(request: Request, payload: TradingViewSignal):
    """
    Ingests TradingView alert webhook payload.
    
    Security:
    - Requires X-Webhook-Secret header (or matching payload secret) == config.WEBHOOK_SECRET
    - Returns 401 on mismatch and logs rejection
    
    Validation:
    - Verifies known ticker in config.TICKERS
    - Verifies action and positive price
    - Returns 422 on invalid payload
    """
    # 1. Capture Alert Arrival Timestamp for Latency Tracking
    t_recv = time.time()
    alert_received_ts = datetime.utcnow().isoformat()
    record_signal_received()
    logger.info(f"[WEBHOOK] Alert received at {alert_received_ts}: {payload.action.upper()} {payload.ticker.upper()} @ ${payload.price:.2f}")

    # 2. SECURITY: Authentication Header & Secret Check
    header_secret = request.headers.get("x-webhook-secret") or request.headers.get("X-Webhook-Secret")
    client_secret = header_secret or payload.secret

    if not client_secret or client_secret.strip() != WEBHOOK_SECRET.strip():
        logger.warning(f"[WEBHOOK] Rejected unauthorized attempt from {request.client.host if request.client else 'unknown'}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="[WEBHOOK] Rejected unauthorized attempt",
        )

    # 3. VALIDATION: Check known tickers & field rules
    ticker_clean = payload.ticker.upper().strip()
    configured_tickers = [t.upper().strip() for t in TICKERS]

    if ticker_clean not in configured_tickers:
        err_msg = f"[WEBHOOK] Invalid payload: Unknown ticker '{payload.ticker}'. Allowed: {configured_tickers}"
        logger.warning(err_msg)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_msg,
        )

    action_clean = payload.action.lower().strip()
    if action_clean not in ("buy", "sell", "close", "short"):
        err_msg = f"[WEBHOOK] Invalid payload: Unsupported action '{payload.action}'"
        logger.warning(err_msg)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_msg,
        )

    if payload.price <= 0:
        err_msg = f"[WEBHOOK] Invalid payload: Price must be > 0 (${payload.price})"
        logger.warning(err_msg)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_msg,
        )

    # 4. SIGNAL VALIDATION & EXECUTION LAYER
    result = validator.validate_and_process(
        ticker=ticker_clean,
        action=action_clean,
        webhook_price=payload.price,
        timeframe=payload.timeframe or "1D",
        force_market_open=payload.force_market_open,
        mock_current_price=payload.mock_current_price,
        mock_atr=payload.mock_atr,
        alert_received_ts=alert_received_ts,
        t_recv=t_recv,
        mode=payload.mode or "paper",
    )

    return {
        "status": result.get("status"),
        "step": result.get("step"),
        "decision": result,
    }
