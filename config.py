"""Configuration module and secure credential validator for the Self-Improving AI Trading Agent."""

from __future__ import annotations

import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional
import pytz
from dotenv import load_dotenv

# --- Base Directory & .env Loading ---
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()


# --- Security Helper: Secret Masking ---
def mask_secret(val: Optional[str], prefix_len: int = 3, suffix_len: int = 4) -> str:
    """Masks secret values (e.g. 'sk-proj...1234') so they are never printed in logs or console."""
    if not val or not val.strip():
        return "[NOT SET]"
    val = val.strip()
    if val.startswith("your_") and val.endswith("_here"):
        return "[PLACEHOLDER - REQUIRES KEY]"
    if len(val) <= (prefix_len + suffix_len):
        return "****"
    return f"{val[:prefix_len]}...{val[-suffix_len:]}"


def validate_api_key(key_name: str, val: Optional[str], required: bool = False) -> bool:
    """Validates an environment key. Raises clear error if a strictly required key is missing."""
    is_missing = not val or not val.strip() or (val.strip().startswith("your_") and val.strip().endswith("_here"))
    if is_missing and required:
        raise ValueError(f"Missing API key: {key_name} — add it to .env file")
    return not is_missing


# --- LLM API Credentials (Cloud & Local) ---
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_CONFIGURED_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1")


def get_available_ollama_model() -> str:
    """Returns the configured model if available, or falls back to installed models."""
    import requests
    try:
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags"
        resp = requests.get(url, timeout=2)
        if resp.status_code == 200:
            models_data = resp.json().get("models", [])
            installed_names = [m.get("name", "") for m in models_data]
            for name in installed_names:
                if name == _CONFIGURED_MODEL or name.startswith(f"{_CONFIGURED_MODEL}:"):
                    return name
            for pref in ["llama3.1", "llama3.1:latest", "llama3.2:1b", "llama3.2:latest", "gemma4:latest"]:
                for name in installed_names:
                    if name == pref or name.startswith(f"{pref.split(':')[0]}:"):
                        return name
            if installed_names:
                return installed_names[0]
    except Exception:
        pass
    return _CONFIGURED_MODEL


OLLAMA_MODEL: str = get_available_ollama_model()

# --- Market Data & Webhook Credentials ---
ALPHA_VANTAGE_API_KEY: str = os.getenv("ALPHA_VANTAGE_API_KEY", "")
TWELVEDATA_API_KEY: str = os.getenv("TWELVEDATA_API_KEY", "")
TRADINGVIEW_WEBHOOK_SECRET: str = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "")
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", TRADINGVIEW_WEBHOOK_SECRET or "my_tradingview_secret_123")
WEBHOOK_PUBLIC_URL: str = os.getenv("WEBHOOK_PUBLIC_URL", "")

# --- Alpaca Paper Trading Credentials ---
ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
EXECUTION_MODE: str = os.getenv("EXECUTION_MODE", "paper").lower()  # "paper" or "live"
LIVE_TRADING: bool = (os.getenv("LIVE_TRADING", "false").lower() == "true") and (EXECUTION_MODE == "live")
DRY_RUN: bool = (os.getenv("DRY_RUN", "true").lower() == "true") or (EXECUTION_MODE == "paper")
ALLOW_EXTENDED_HOURS: bool = os.getenv("ALLOW_EXTENDED_HOURS", "false").lower() == "true"
MONITOR_INTERVAL: int = int(os.getenv("MONITOR_INTERVAL", "30"))

# --- Asset / Market Settings ---
DEFAULT_TICKERS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "SPY",
    "TSLA",
    "AMD",
]
raw_tickers = os.getenv("TRADING_TICKERS", "")
if raw_tickers.strip():
    TICKERS: List[str] = [t.strip().upper() for t in raw_tickers.split(",") if t.strip()]
else:
    TICKERS: List[str] = DEFAULT_TICKERS

# 6 fixed decision intervals per day (IST) & 1 reflection interval
TRADING_INTERVALS_IST: List[str] = [
    "09:30",
    "10:30",
    "11:30",
    "12:30",
    "13:30",
    "14:30",
]
REFLECTION_TIME_IST: str = "15:30"
TIMEZONE_STR: str = os.getenv("TIMEZONE", "Asia/Kolkata")
TIMEZONE = pytz.timezone(TIMEZONE_STR)

# --- Risk Management Parameters ---
MAX_POSITION_PERCENT: float = float(os.getenv("MAX_POSITION_PERCENT", "0.05"))
STOP_LOSS_PERCENT: float = float(os.getenv("STOP_LOSS_PERCENT", "0.02"))
TAKE_PROFIT_PERCENT: float = float(os.getenv("TAKE_PROFIT_PERCENT", "0.04"))
MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
MAX_DRAWDOWN_PERCENT: float = float(os.getenv("MAX_DRAWDOWN_PERCENT", "0.10"))
# --- Paper Trading Capital ---
# WARNING: Backtests were calibrated against $10,000 capital (1% risk = $100 budget).
# If PAPER_CAPITAL is set to $100,000, 1% risk = $1,000 budget per trade. Ensure scale alignment!
PAPER_CAPITAL: float = float(os.getenv("PAPER_CAPITAL", os.getenv("INITIAL_PAPER_CASH", "10000.0")))
INITIAL_PAPER_CASH: float = PAPER_CAPITAL
LESSON_MODE: str = os.getenv("LESSON_MODE", "soft")  # "soft" or "hard"

# --- ATR Risk Parameters ---
USE_ATR_STOPS: bool = True
SL_ATR_MULT: float = float(os.getenv("SL_ATR_MULT", "1.5"))
TP_ATR_MULT: float = float(os.getenv("TP_ATR_MULT", "3.0"))
RISK_PER_TRADE: float = float(os.getenv("RISK_PER_TRADE", "0.01"))  # 1% risk
TRAILING_STOP: bool = os.getenv("TRAILING_STOP", "false").lower() == "true"  # Default OFF


# --- Trend Filter Parameters ---
TREND_FILTER: bool = os.getenv("TREND_FILTER", "true").lower() == "true"
TREND_SMA_PERIOD: int = int(os.getenv("TREND_SMA_PERIOD", "200"))
TREND_TF: str = os.getenv("TREND_TF", "1d")


# --- Sizing Parameters ---
POSITION_SIZING_MODE: str = os.getenv("POSITION_SIZING_MODE", "risk") # "risk" or "alloc"

# --- Storage Settings ---
DATABASE_PATH: Path = BASE_DIR / os.getenv("DATABASE_PATH", "trading_agent.db")
CHROMA_PERSIST_DIR: Path = BASE_DIR / os.getenv("CHROMA_PERSIST_DIR", "chroma_db")
LOG_FILE_PATH: Path = BASE_DIR / os.getenv("LOG_FILE_PATH", "trading_agent.log")


# --- Startup Environment Validation ---
def validate_startup_config() -> dict[str, str]:
    """Inspects environment setup and returns a dictionary of masked credential statuses."""
    status_summary = {
        "OPENAI_API_KEY": mask_secret(OPENAI_API_KEY),
        "ANTHROPIC_API_KEY": mask_secret(ANTHROPIC_API_KEY),
        "ALPHA_VANTAGE_API_KEY": mask_secret(ALPHA_VANTAGE_API_KEY),
        "TWELVEDATA_API_KEY": mask_secret(TWELVEDATA_API_KEY),
        "TRADINGVIEW_WEBHOOK_SECRET": mask_secret(TRADINGVIEW_WEBHOOK_SECRET),
        "WEBHOOK_PUBLIC_URL": WEBHOOK_PUBLIC_URL or "Not configured",
        "ALPACA_API_KEY": mask_secret(ALPACA_API_KEY),
        "ALPACA_SECRET_KEY": mask_secret(ALPACA_SECRET_KEY),
        "OLLAMA_MODEL": OLLAMA_MODEL,
        "OLLAMA_BASE_URL": OLLAMA_BASE_URL,
    }
    return status_summary


# --- Logging Setup ---
def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configures console and rotating file logger."""
    logger = logging.getLogger("trading_agent")
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating File Handler (10MB per file, max 5 backups)
    file_handler = RotatingFileHandler(
        filename=str(LOG_FILE_PATH),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logging()

# --- Confluence Settings ---
CONFLUENCE_THRESHOLD: int = 4
