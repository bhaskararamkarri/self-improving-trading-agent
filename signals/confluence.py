import pandas as pd
from typing import Dict, Any, Tuple
import os

# Example logger state
example_count = 0

def calculate_confluence_score(bar: pd.Series, prev_bar: pd.Series) -> Tuple[int, int, Dict[str, bool], Dict[str, bool]]:
    global example_count
    current_price = float(bar['close'])
    current_open = float(bar['open'])
    is_green = current_price >= current_open
    is_red = current_price <= current_open
    
    # Safely extract variables
    ema21 = float(bar.get("EMA_21", current_price) or current_price)
    ema50 = float(bar.get("EMA_50", current_price) or current_price)
    ema200 = float(bar.get("EMA_200", current_price) or current_price)
    
    rsi = float(bar.get("RSI_14", 50.0) or 50.0)
    prev_rsi = float(prev_bar.get("RSI_14", 50.0) or 50.0)
    
    macd_hist = float(bar.get("MACD_HIST", 0.0) or 0.0)
    prev_macd_hist = float(prev_bar.get("MACD_HIST", 0.0) or 0.0)
    
    vol = float(bar.get("volume", 0.0) or 0.0)
    vol_sma = float(bar.get("VOLUME_SMA_20", 0.0) or 0.0)
    
    atr = float(bar.get("ATR_14", max(0.01, current_price * 0.01)) or max(0.01, current_price * 0.01))
    
    # === LONG CRITERIA ===
    l_c1 = (current_price > ema50) and (ema50 > ema200)
    l_c2 = (prev_rsi < 30.0) and (rsi >= 30.0)
    l_c3 = (prev_macd_hist < 0.0) and (macd_hist >= 0.0)
    dist_ema21 = abs(current_price - ema21)
    l_c4 = (dist_ema21 <= 1.5 * atr) and is_green
    l_c5 = vol > (1.5 * vol_sma) if vol_sma > 0 else False
    
    long_breakdown = {
        "Trend Align": l_c1,
        "RSI Cross < 30": l_c2,
        "MACD Cross": l_c3,
        "Pullback & Green": l_c4,
        "Volume > 1.5x": l_c5
    }
    long_score = sum(long_breakdown.values())
    
    # === SHORT CRITERIA ===
    s_c1 = (current_price < ema50) and (ema50 < ema200)
    s_c2 = (prev_rsi > 70.0) and (rsi <= 70.0)
    s_c3 = (prev_macd_hist > 0.0) and (macd_hist <= 0.0)
    s_c4 = (dist_ema21 <= 1.5 * atr) and is_red
    s_c5 = vol > (1.5 * vol_sma) if vol_sma > 0 else False
    
    short_breakdown = {
        "Trend Align": s_c1,
        "RSI Cross > 70": s_c2,
        "MACD Cross": s_c3,
        "Pullback & Red": s_c4,
        "Volume > 1.5x": s_c5
    }
    short_score = sum(short_breakdown.values())
    
    if (long_score >= 3 or short_score >= 3) and example_count < 3:
        with open("confluence_examples.txt", "a") as f:
            if long_score >= 3:
                f.write(f"LONG ENTRY - Score {long_score}/5\\n")
                f.write(f"Breakdown: {long_breakdown}\\n\\n")
            else:
                f.write(f"SHORT ENTRY - Score {short_score}/5\\n")
                f.write(f"Breakdown: {short_breakdown}\\n\\n")
        example_count += 1
    
    return long_score, short_score, long_breakdown, short_breakdown
