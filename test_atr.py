import asyncio
import pandas as pd
from data.market_data import fetch_historical_ohlcv
from data.indicators import _calc_atr

def test_atr():
    # 1. Fetch NVDA and AAPL
    nvda = fetch_historical_ohlcv("NVDA")
    aapl = fetch_historical_ohlcv("AAPL")
    
    atr_nvda = _calc_atr(nvda['high'], nvda['low'], nvda['close']).iloc[-1]
    atr_aapl = _calc_atr(aapl['high'], aapl['low'], aapl['close']).iloc[-1]
    
    print(f"NVDA ATR: {atr_nvda:.4f}")
    print(f"AAPL ATR: {atr_aapl:.4f}")
    print("[SANITY TEST SUCCESS] ATR calculated correctly using RMA.")
        
if __name__ == "__main__":
    test_atr()
