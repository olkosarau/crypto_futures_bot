import httpx
import pandas as pd
from typing import List
from datetime import datetime

BINANCE_REST = 'https://fapi.binance.com'  # futures REST

async def fetch_klines(symbol: str, interval: str = '5m', limit: int = 500) -> pd.DataFrame:
    url = f"{BINANCE_REST}/fapi/v1/klines"
    params = {'symbol': symbol.upper(), 'interval': interval, 'limit': limit}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        raw = r.json()
    df = pd.DataFrame(raw, columns=["open_time","open","high","low","close","volume","close_time","q","n","taker_buy_base","taker_buy_quote","ignore"]) 
    df = df[['open_time','open','high','low','close','volume']]
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    for col in ['open','high','low','close','volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df
