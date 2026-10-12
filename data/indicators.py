"""Technical indicator calculation and market trend analysis using pandas-ta."""

from __future__ import annotations

import math
from typing import Any, Tuple

try:
    import pandas as pd  # type: ignore
    import numpy as np  # type: ignore
except (ImportError, Exception):
    from data.dataframe_compat import PandasShim as pd  # type: ignore
    np = None  # type: ignore

from storage.models import IndicatorSnapshot
from config import logger

# Try to import pandas_ta
try:
    import pandas_ta as ta  # type: ignore
    HAS_PANDAS_TA = True
except (ImportError, Exception):
    HAS_PANDAS_TA = False
    logger.warning("pandas-ta not installed. Falling back to internal indicator calculations.")


def compute_indicators(df: pd.DataFrame) -> Tuple[pd.DataFrame, IndicatorSnapshot, str]:
    """Calculates technical indicators on OHLCV dataframe.

    Returns:
        (augmented_df, latest_indicator_snapshot, trend_summary_text)
    """
    if df is None or len(df) < 20:
        logger.warning("DataFrame has fewer than 20 rows. Indicators may be inaccurate.")
        return df, IndicatorSnapshot(), "Insufficient data for full indicators."

    df = df.copy()

    # Ensure required column names are capitalized
    col_map = {c.lower(): c for c in df.columns}
    close_col = col_map.get("close", "Close")
    open_col = col_map.get("open", "Open")
    high_col = col_map.get("high", "High")
    low_col = col_map.get("low", "Low")
    volume_col = col_map.get("volume", "Volume")

    close = df[close_col].astype(float)
    high = df[high_col].astype(float)
    low = df[low_col].astype(float)
    vol = df[volume_col].astype(float)

    # 1. RSI (14)
    if HAS_PANDAS_TA:
        try:
            df["RSI_14"] = df.ta.rsi(close=close_col, length=14)
        except Exception:
            df["RSI_14"] = _calc_rsi(close, 14)
    else:
        df["RSI_14"] = _calc_rsi(close, 14)

    # 2. MACD (12, 26, 9)
    if HAS_PANDAS_TA:
        try:
            macd_df = df.ta.macd(close=close_col, fast=12, slow=26, signal=9)
            if macd_df is not None:
                df["MACD"] = macd_df.iloc[:, 0]
                df["MACD_HIST"] = macd_df.iloc[:, 1]
                df["MACD_SIGNAL"] = macd_df.iloc[:, 2]
            else:
                df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = _calc_macd(close, 12, 26, 9)
        except Exception:
            df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = _calc_macd(close, 12, 26, 9)
    else:
        df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = _calc_macd(close, 12, 26, 9)

    # 3. EMAs (9, 21, 50, 200)
    for length in [9, 21, 50, 200]:
        col_name = f"EMA_{length}"
        if HAS_PANDAS_TA and len(df) >= length:
            try:
                df[col_name] = df.ta.ema(close=close_col, length=length)
            except Exception:
                df[col_name] = close.ewm(span=length, adjust=False).mean()
        else:
            df[col_name] = close.ewm(span=length, adjust=False).mean()

    # EMA 50 Slope calculation
    df["EMA_50_PREV"] = df["EMA_50"].shift(1)
    df["EMA_50_SLOPE"] = df["EMA_50"] - df["EMA_50_PREV"]

    # 4. Bollinger Bands (20, 2 std)
    if HAS_PANDAS_TA and len(df) >= 20:
        try:
            bb_df = df.ta.bbands(close=close_col, length=20, std=2.0)
            if bb_df is not None:
                # pandas_ta bbands columns: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0, BBB_20_2.0, BBP_20_2.0
                df["BB_LOWER"] = bb_df.iloc[:, 0]
                df["BB_MIDDLE"] = bb_df.iloc[:, 1]
                df["BB_UPPER"] = bb_df.iloc[:, 2]
                df["BB_BANDWIDTH"] = bb_df.iloc[:, 3] if bb_df.shape[1] > 3 else (df["BB_UPPER"] - df["BB_LOWER"]) / df["BB_MIDDLE"]
            else:
                df["BB_LOWER"], df["BB_MIDDLE"], df["BB_UPPER"], df["BB_BANDWIDTH"] = _calc_bbands(close, 20, 2.0)
        except Exception:
            df["BB_LOWER"], df["BB_MIDDLE"], df["BB_UPPER"], df["BB_BANDWIDTH"] = _calc_bbands(close, 20, 2.0)
    else:
        df["BB_LOWER"], df["BB_MIDDLE"], df["BB_UPPER"], df["BB_BANDWIDTH"] = _calc_bbands(close, 20, 2.0)

    # 5. Volume Indicators
    vol_sma = vol.rolling(window=20, min_periods=1).mean()
    df["VOLUME_SMA_20"] = vol_sma
    vol_ratio = []
    for i in range(len(vol)):
        v = vol.iloc[i] if hasattr(vol, "iloc") else vol[i]
        sma_v = vol_sma.iloc[i] if hasattr(vol_sma, "iloc") else vol_sma[i]
        if v is not None and sma_v is not None and sma_v > 0:
            vol_ratio.append(v / sma_v)
        else:
            vol_ratio.append(1.0)
    df["VOLUME_RATIO"] = pd.Series(vol_ratio, index=df.index if hasattr(df, "index") else None)

    # 6. ATR (14)
    if HAS_PANDAS_TA and len(df) >= 14:
        try:
            df["ATR_14"] = df.ta.atr(high=high_col, low=low_col, close=close_col, length=14)
        except Exception:
            df["ATR_14"] = _calc_atr(high, low, close, 14)
    else:
        df["ATR_14"] = _calc_atr(high, low, close, 14)

    # Extract latest snapshot
    latest = df.iloc[-1]

    snapshot = IndicatorSnapshot(
        rsi_14=round(float(_safe_val(latest.get("RSI_14", 50.0), 50.0)), 2),
        macd=round(float(_safe_val(latest.get("MACD", 0.0), 0.0)), 3),
        macd_signal=round(float(_safe_val(latest.get("MACD_SIGNAL", 0.0), 0.0)), 3),
        macd_hist=round(float(_safe_val(latest.get("MACD_HIST", 0.0), 0.0)), 3),
        ema_9=round(float(_safe_val(latest.get("EMA_9", latest[close_col]), latest[close_col])), 2),
        ema_21=round(float(_safe_val(latest.get("EMA_21", latest[close_col]), latest[close_col])), 2),
        ema_50=round(float(_safe_val(latest.get("EMA_50", latest[close_col]), latest[close_col])), 2),
        ema_50_prev=round(float(_safe_val(latest.get("EMA_50_PREV", latest[close_col]), latest[close_col])), 2),
        ema_50_slope=round(float(_safe_val(latest.get("EMA_50_SLOPE", 0.0), 0.0)), 4),
        ema_200=round(float(_safe_val(latest.get("EMA_200", latest[close_col]), latest[close_col])), 2),
        bb_upper=round(float(_safe_val(latest.get("BB_UPPER", latest[close_col]), latest[close_col])), 2),
        bb_middle=round(float(_safe_val(latest.get("BB_MIDDLE", latest[close_col]), latest[close_col])), 2),
        bb_lower=round(float(_safe_val(latest.get("BB_LOWER", latest[close_col]), latest[close_col])), 2),
        bb_bandwidth=round(float(_safe_val(latest.get("BB_BANDWIDTH", 0.0), 0.0)), 4),
        volume=float(_safe_val(latest.get(volume_col, 0.0), 0.0)),
        volume_sma_20=float(_safe_val(latest.get("VOLUME_SMA_20", 0.0), 0.0)),
        volume_ratio=round(float(_safe_val(latest.get("VOLUME_RATIO", 1.0), 1.0)), 2),
        atr_14=round(float(_safe_val(latest.get("ATR_14", 0.0), 0.0)), 2),
    )

    trend_summary = generate_trend_summary(snapshot, float(latest[close_col]))
    return df, snapshot, trend_summary


def generate_trend_summary(ind: IndicatorSnapshot, current_price: float) -> str:
    """Generates an intuitive textual summary of market conditions based on indicators."""
    signals = []

    # RSI condition
    if ind.rsi_14 >= 70:
        signals.append(f"RSI({ind.rsi_14}) Overbought (>70)")
    elif ind.rsi_14 <= 30:
        signals.append(f"RSI({ind.rsi_14}) Oversold (<30)")
    elif ind.rsi_14 > 50:
        signals.append(f"RSI({ind.rsi_14}) Bullish momentum (>50)")
    else:
        signals.append(f"RSI({ind.rsi_14}) Bearish momentum (<=50)")

    # MACD condition
    if ind.macd_hist > 0 and ind.macd > ind.macd_signal:
        signals.append(f"MACD Bullish crossover (Hist: {ind.macd_hist:+.2f})")
    elif ind.macd_hist < 0 and ind.macd < ind.macd_signal:
        signals.append(f"MACD Bearish crossover (Hist: {ind.macd_hist:+.2f})")
    else:
        signals.append(f"MACD Neutral (Hist: {ind.macd_hist:+.2f})")

    # EMA Alignment
    if current_price > ind.ema_9 > ind.ema_21:
        signals.append("Short-term EMA Bullish (Price > EMA9 > EMA21)")
    elif current_price < ind.ema_9 < ind.ema_21:
        signals.append("Short-term EMA Bearish (Price < EMA9 < EMA21)")

    if ind.ema_50 > 0 and ind.ema_200 > 0:
        if ind.ema_50 > ind.ema_200:
            signals.append("Long-term Bullish Trend (EMA50 > EMA200 Golden Cross zone)")
        else:
            signals.append("Long-term Bearish Trend (EMA50 < EMA200 Death Cross zone)")

    # Bollinger Bands
    if current_price >= ind.bb_upper:
        signals.append("Price testing Upper Bollinger Band (Resistance)")
    elif current_price <= ind.bb_lower:
        signals.append("Price testing Lower Bollinger Band (Support)")
    else:
        signals.append("Price inside Bollinger Bands")

    # Volume
    if ind.volume_ratio > 1.5:
        signals.append(f"High Volume Surge ({ind.volume_ratio:.1f}x 20-period avg)")
    elif ind.volume_ratio < 0.7:
        signals.append(f"Low Volume Activity ({ind.volume_ratio:.1f}x 20-period avg)")

    return " | ".join(signals)


def _safe_val(val: Any, default: float = 0.0) -> float:
    if val is None or pd.isna(val):
        return default
    try:
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return default
        return fval
    except (ValueError, TypeError):
        return default


def _calc_rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Computes standard Relative Strength Index (RSI) using Wilder's Smoothed Moving Average (RMA)."""
    if len(series) == 0:
        return pd.Series(dtype=float, index=series.index)
    if len(series) <= length:
        return pd.Series(50.0, index=series.index)

    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    rsi_values = [50.0] * len(series)

    # Calculate initial seed average (simple mean of first `length` changes)
    seed_gain = gain.iloc[1 : length + 1].mean()
    seed_loss = loss.iloc[1 : length + 1].mean()

    avg_gain = seed_gain
    avg_loss = seed_loss

    if avg_loss == 0:
        rsi_values[length] = 100.0 if avg_gain > 0 else 50.0
    else:
        rs = avg_gain / avg_loss
        rsi_values[length] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(length + 1, len(series)):
        current_gain = gain.iloc[i]
        current_loss = loss.iloc[i]

        avg_gain = (avg_gain * (length - 1) + current_gain) / length
        avg_loss = (avg_loss * (length - 1) + current_loss) / length

        if avg_loss == 0:
            rsi_values[i] = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i] = 100.0 - (100.0 / (1.0 + rs))

    rsi_series = pd.Series(rsi_values, index=series.index, dtype=float)
    return rsi_series.clip(lower=0.0, upper=100.0)


def _calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist


def _calc_bbands(series: pd.Series, length: int = 20, std: float = 2.0):
    middle = series.rolling(window=length, min_periods=1).mean()
    rolling_std = series.rolling(window=length, min_periods=1).std().fillna(0)
    upper = middle + (rolling_std * std)
    lower = middle - (rolling_std * std)
    bandwidth = []
    for i in range(len(series)):
        m = middle.iloc[i] if hasattr(middle, "iloc") else middle[i]
        u = upper.iloc[i] if hasattr(upper, "iloc") else upper[i]
        l = lower.iloc[i] if hasattr(lower, "iloc") else lower[i]
        if m is not None and u is not None and l is not None and m > 0:
            bandwidth.append((u - l) / m)
        else:
            bandwidth.append(0.0)
    return lower, middle, upper, pd.Series(bandwidth, index=series.index)


def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr_list = []
    for i in range(len(close)):
        h = high.iloc[i] if hasattr(high, "iloc") else high[i]
        l = low.iloc[i] if hasattr(low, "iloc") else low[i]
        pc = prev_close.iloc[i] if hasattr(prev_close, "iloc") else prev_close[i]
        if h is not None and l is not None and not pd.isna(h) and not pd.isna(l):
            if pc is not None and not pd.isna(pc):
                tr = max(h - l, abs(h - pc), abs(l - pc))
            else:
                tr = h - l
            tr_list.append(tr)
        else:
            tr_list.append(0.0)
    tr_series = pd.Series(tr_list, index=close.index)
    
    # Wilder's RMA smoothing
    atr = np.zeros(len(tr_series))
    atr[0] = tr_series.iloc[0]
    for i in range(1, len(tr_series)):
        atr[i] = (atr[i-1] * (length - 1) + tr_series.iloc[i]) / length
        
    # Standard Wilder's first value is often SMA of first `length` periods, 
    # but recursive EMA format works universally too. Let's strictly do:
    # First `length` values as SMA, then RMA
    if len(tr_series) >= length:
        atr[length-1] = tr_series.iloc[:length].mean()
        for i in range(length, len(tr_series)):
            atr[i] = (atr[i-1] * (length - 1) + tr_series.iloc[i]) / length
            
    # Pad early values with NaN or just leave as is (we leave as is, same as previous logic)
    return pd.Series(atr, index=close.index)
