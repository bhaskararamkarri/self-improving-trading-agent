"""Market data fetcher using Twelve Data (Primary), yfinance (Secondary), and Yahoo Direct (Tertiary fallback)."""

from __future__ import annotations

import datetime
import time
from collections import deque
from typing import Dict, Optional, List, Tuple, Any
import requests

try:
    import pandas as pd  # type: ignore
    import yfinance as yf  # type: ignore
except (ImportError, Exception):
    from data.dataframe_compat import PandasShim as pd  # type: ignore
    yf = None  # type: ignore

from config import logger, TICKERS, TWELVEDATA_API_KEY
from storage.models import MarketSnapshot
from data.indicators import compute_indicators


class TwelveDataRateLimiter:
    """Sliding-window token-bucket rate limiter (max 7 calls per rolling 60 seconds)."""

    def __init__(self, max_calls: int = 7, period_sec: float = 60.0):
        self.max_calls = max_calls
        self.period_sec = period_sec
        self.call_timestamps: deque[float] = deque()

    def can_make_call(self) -> bool:
        now = time.time()
        while self.call_timestamps and (now - self.call_timestamps[0] > self.period_sec):
            self.call_timestamps.popleft()
        return len(self.call_timestamps) < self.max_calls

    def record_call(self) -> None:
        self.call_timestamps.append(time.time())


_rate_limiter = TwelveDataRateLimiter(max_calls=7, period_sec=60.0)
_market_data_cache: Dict[Tuple[str, str, str], Tuple[float, pd.DataFrame]] = {}
CACHE_TTL = 60.0  # 60s cache TTL


def is_market_open_day(date: Optional[datetime.date] = None) -> bool:
    """Checks if the given date is a weekday (Monday=0 to Friday=4)."""
    if date is None:
        date = datetime.date.today()
    return date.weekday() < 5


def _normalize_interval(interval: str) -> str:
    """Normalizes interval strings for Twelve Data."""
    i = interval.lower().strip()
    if i in ("1m", "1min"):
        return "1min"
    if i in ("5m", "5min"):
        return "5min"
    if i in ("15m", "15min"):
        return "15min"
    if i in ("30m", "30min"):
        return "30min"
    if i in ("1h", "60m", "60min"):
        return "1h"
    if i in ("1d", "1day", "d", "daily"):
        return "1day"
    if i in ("1wk", "1w", "week", "weekly"):
        return "1week"
    if i in ("1mo", "1month", "month", "monthly"):
        return "1month"
    return "1day"


def _fetch_twelve_data(
    ticker: str,
    period: str = "6mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetches OHLCV time series from Twelve Data REST API with rate-limiting and backoff retries."""
    if not TWELVEDATA_API_KEY or TWELVEDATA_API_KEY.startswith("your_"):
        return pd.DataFrame()

    if not _rate_limiter.can_make_call():
        logger.warning(f"Twelve Data rate limit throttle reached (7 calls/60s). Falling back for {ticker}.")
        return pd.DataFrame()

    norm_interval = _normalize_interval(interval)

    # Determine output size
    if period == "1d":
        outputsize = 78
    elif period == "5d":
        outputsize = 390
    elif period == "1mo":
        outputsize = 30 if norm_interval == "1day" else 500
    elif period == "3mo":
        outputsize = 70 if norm_interval == "1day" else 500
    elif period == "6mo":
        outputsize = 140 if norm_interval == "1day" else 500
    elif period == "1y":
        outputsize = 260 if norm_interval == "1day" else 500
    else:
        outputsize = 200

    clean_symbol = ticker
    exchange = None
    if ticker.upper().endswith(".NS"):
        clean_symbol = ticker[:-3]
        exchange = "NSE"
    elif ticker.upper().endswith(".BO"):
        clean_symbol = ticker[:-3]
        exchange = "BSE"

    url = "https://api.twelvedata.com/time_series"
    params: Dict[str, Any] = {
        "symbol": clean_symbol,
        "interval": norm_interval,
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY,
        "format": "JSON",
    }
    if exchange:
        params["exchange"] = exchange

    delays = [2, 4, 8]
    for attempt in range(len(delays) + 1):
        try:
            if not _rate_limiter.can_make_call():
                return pd.DataFrame()

            _rate_limiter.record_call()
            resp = requests.get(url, params=params, timeout=10)

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                return pd.DataFrame()

            if resp.status_code != 200:
                return pd.DataFrame()

            data = resp.json()
            if data.get("status") == "error" or "values" not in data or data.get("code") == 429:
                return pd.DataFrame()

            values = data["values"]
            if not values:
                return pd.DataFrame()

            # Values arrive newest-first -> reverse to oldest-first
            values = list(reversed(values))

            rows = []
            for v in values:
                dt_val = v.get("datetime", "")
                rows.append({
                    "Date": dt_val,
                    "Open": float(v.get("open", 0.0) or 0.0),
                    "High": float(v.get("high", 0.0) or 0.0),
                    "Low": float(v.get("low", 0.0) or 0.0),
                    "Close": float(v.get("close", 0.0) or 0.0),
                    "Volume": float(v.get("volume", 0.0) or 0.0),
                })

            df = pd.DataFrame(rows)
            return _normalize_df(df)
        except Exception as e:
            logger.debug(f"Twelve Data exception for {ticker}: {e}")
            if attempt < len(delays):
                time.sleep(delays[attempt])
            else:
                return _normalize_df(pd.DataFrame())

    return _normalize_df(pd.DataFrame())


def _fetch_yahoo_direct(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """Direct REST fetch from Yahoo Finance chart endpoint as lightweight robust fallback."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval={interval}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return _normalize_df(pd.DataFrame())

        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return _normalize_df(pd.DataFrame())

        chart_data = result[0]
        timestamps = chart_data.get("timestamp", [])
        quote = chart_data.get("indicators", {}).get("quote", [{}])[0]
        closes = quote.get("close", [])
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        volumes = quote.get("volume", [])

        rows = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            l = lows[i] if i < len(lows) else None
            v = volumes[i] if i < len(volumes) else None
            if c is not None and o is not None and h is not None and l is not None:
                dt_str = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")
                rows.append({
                    "Date": dt_str,
                    "Open": float(o),
                    "High": float(h),
                    "Low": float(l),
                    "Close": float(c),
                    "Volume": float(v or 0.0),
                })
        return _normalize_df(pd.DataFrame(rows))
    except Exception as e:
        logger.error(f"Error in direct Yahoo fetch for {ticker}: {e}")
        return _normalize_df(pd.DataFrame())


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizes any market data DataFrame to a consistent schema:
    - Index: tz-naive (UTC) DatetimeIndex, sorted ascending
    - Columns: strictly ['open', 'high', 'low', 'close', 'volume'] (lowercase, float)
    - Extra columns (e.g. 'Dividends', 'Stock Splits', 'Date', etc.) removed
    """
    required_cols = ["open", "high", "low", "close", "volume"]
    if df is None or df.empty:
        empty_df = pd.DataFrame(columns=required_cols)
        empty_df.index = pd.DatetimeIndex([], name="date")
        return empty_df

    df = df.copy()

    # Flatten MultiIndex columns if present (e.g. from yfinance history)
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    # 1. Standardize DatetimeIndex
    if "Date" in df.columns:
        df["datetime"] = pd.to_datetime(df["Date"], errors="coerce", utc=True)
        df.set_index("datetime", inplace=True)
        df.drop(columns=["Date"], inplace=True, errors="ignore")
    elif "Datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["Datetime"], errors="coerce", utc=True)
        df.set_index("datetime", inplace=True)
        df.drop(columns=["Datetime"], inplace=True, errors="ignore")
    elif "datetime" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
        df.set_index("datetime", inplace=True)
    elif not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, errors="coerce", utc=True)
        except Exception:
            pass

    # If index is a DatetimeIndex and tz-aware, convert to UTC and make tz-naive
    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        # Drop rows with NaT index
        df = df[~df.index.isna()]
        # Sort ascending in time
        df.sort_index(ascending=True, inplace=True)
        df.index.name = "date"

    # 2. Map and lower-case standard OHLCV columns
    col_map = {}
    for col in df.columns:
        c_lower = str(col).lower().strip()
        if c_lower in ("open", "high", "low", "close", "volume"):
            col_map[col] = c_lower

    df.rename(columns=col_map, inplace=True)

    for col in required_cols:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)

    # Keep ONLY the 5 required columns (strictly dropping Dividends, Stock Splits, Capital Gains, etc.)
    df = df[required_cols]

    # Remove any NaN/null close prices
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]

    return df


def fetch_historical_ohlcv(
    ticker: str,
    period: str = "6mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """Downloads historical OHLCV data using Twelve Data as PRIMARY, yfinance as secondary, and Yahoo Direct as tertiary fallback.

    All return DataFrames are guaranteed normalized (lowercase ['open', 'high', 'low', 'close', 'volume'], tz-naive UTC DatetimeIndex).
    """
    cache_key = (ticker, period, interval)
    now = time.time()
    if cache_key in _market_data_cache:
        cached_time, cached_df = _market_data_cache[cache_key]
        if now - cached_time < CACHE_TTL and not cached_df.empty:
            logger.info(f"[CACHE] {ticker} {interval} retrieved from cache (TTL 60s)")
            return cached_df.copy()

    # 1. Primary Source: Twelve Data
    if TWELVEDATA_API_KEY and not TWELVEDATA_API_KEY.startswith("your_"):
        df_td = _fetch_twelve_data(ticker, period=period, interval=interval)
        if df_td is not None and not df_td.empty and len(df_td) >= 1:
            norm_df = _normalize_df(df_td)
            if not norm_df.empty:
                logger.info(f"[DATA] {ticker} {interval} → twelve_data")
                _market_data_cache[cache_key] = (now, norm_df.copy())
                return norm_df

    # 2. Secondary Fallback: yfinance
    if yf is not None:
        try:
            yf_ticker = yf.Ticker(ticker)
            yf_interval = interval
            if interval == "1day":
                yf_interval = "1d"
            elif interval == "5min":
                yf_interval = "5m"
            elif interval == "1min":
                yf_interval = "1m"
            elif interval == "15min":
                yf_interval = "15m"
            elif interval == "1h":
                yf_interval = "1h"

            df = yf_ticker.history(period=period, interval=yf_interval, auto_adjust=True)

            if (df is None or df.empty or len(df) < 5) and yf_interval not in ("1d", "1day"):
                df = yf_ticker.history(period=period, interval="1d", auto_adjust=True)

            if df is not None and not df.empty:
                norm_df = _normalize_df(df)
                if not norm_df.empty:
                    logger.info(f"[DATA] {ticker} {interval} → yfinance")
                    _market_data_cache[cache_key] = (now, norm_df.copy())
                    return norm_df
        except Exception as e:
            logger.error(f"yfinance error for {ticker}: {e}")

    # 3. Tertiary Fallback: Direct Yahoo REST
    df_direct = _fetch_yahoo_direct(ticker, period=period, interval="1d" if interval in ("1h", "1day") else interval)
    if not df_direct.empty:
        norm_df = _normalize_df(df_direct)
        if not norm_df.empty:
            logger.info(f"[DATA] {ticker} {interval} → yahoo_direct")
            _market_data_cache[cache_key] = (now, norm_df.copy())
            return norm_df

    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def get_market_snapshot(ticker: str, df: Optional[pd.DataFrame] = None) -> Optional[MarketSnapshot]:
    """Computes technical indicators and builds a MarketSnapshot for a given ticker."""
    if df is None or df.empty:
        df = fetch_historical_ohlcv(ticker=ticker, period="6mo", interval="1h")

    if df.empty or len(df) < 5:
        logger.warning(f"Insufficient OHLCV data to create snapshot for {ticker}")
        return None

    augmented_df, snapshot_indicators, trend_summary = compute_indicators(df)
    latest = augmented_df.iloc[-1]

    # Parse date / timestamp
    date_val = latest.get("Date")
    if hasattr(date_val, "isoformat"):
        ts_str = date_val.isoformat()
    else:
        ts_str = str(date_val or datetime.datetime.utcnow().isoformat())

    col_map = {c.lower(): c for c in df.columns}
    close_val = float(latest[col_map.get("close", "Close")])
    open_val = float(latest[col_map.get("open", "Open")])
    high_val = float(latest[col_map.get("high", "High")])
    low_val = float(latest[col_map.get("low", "Low")])
    vol_val = float(latest[col_map.get("volume", "Volume")])

    return MarketSnapshot(
        ticker=ticker,
        timestamp=ts_str,
        current_price=close_val,
        open_price=open_val,
        high_price=high_val,
        low_price=low_val,
        close_price=close_val,
        volume=vol_val,
        indicators=snapshot_indicators,
        trend_summary=trend_summary,
    )


def fetch_all_market_snapshots(tickers: Optional[List[str]] = None) -> Dict[str, MarketSnapshot]:
    """Fetches market snapshots for all configured tickers."""
    target_tickers = tickers or TICKERS
    snapshots: Dict[str, MarketSnapshot] = {}

    for ticker in target_tickers:
        snap = get_market_snapshot(ticker)
        if snap is not None:
            snapshots[ticker] = snap

    logger.info(f"Generated snapshots for {len(snapshots)}/{len(target_tickers)} tickers.")
    return snapshots
