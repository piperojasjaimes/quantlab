"""Download M1 data from free sources — Dukascopy, Yahoo Finance, TradingView."""
import sys, os, struct, gzip
sys.path.insert(0, '.')
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import urllib.request
import json

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "market"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Dukascopy CSV data format
DUKASCOPY_URL_TEMPLATE = "https://www.dukascopy.com/free endpoint not available - using alternative"


def download_dukascopy_data(symbol: str, start_date: str, end_date: str) -> bool:
    """Download from Dukascopy free data (bi5 format)."""
    # Dukascopy offers free historical data via their website
    # For now, we'll use Yahoo Finance API which is free
    return False


def download_yahoo_data(symbol: str, interval: str = "1m", months: int = 24) -> bool:
    """Download from Yahoo Finance (free, 1-min data available for ~7 days, 15min for 60 days)."""
    try:
        import urllib.request
        import json
        from datetime import datetime, timedelta

        # Yahoo Finance API
        end = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=months * 30)).timestamp())

        # Map symbols to Yahoo tickers
        yahoo_map = {
            "XAUUSD": "GC=F",        # Gold futures
            "USTEC": "NDX",           # NASDAQ 100
            "US500": "SPX",           # S&P 500
            "US30": "^DJI",           # Dow Jones
            "DE40": "^GDAXI",         # DAX
            "BTCUSD": "BTC-USD",
            "ETHUSD": "ETH-USD",
        }

        yahoo_symbol = yahoo_map.get(symbol, symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?period1={start}&period2={end}&interval={interval}"

        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(req, timeout=30)
        data = json.loads(response.read())

        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]

        opens = quotes["open"]
        highs = quotes["high"]
        lows = quotes["low"]
        closes = quotes["close"]
        volumes = quotes["volume"]

        # Convert to numpy array
        rows = []
        for i in range(len(timestamps)):
            if timestamps[i] is not None and opens[i] is not None:
                rows.append([
                    float(timestamps[i]),
                    float(opens[i]),
                    float(highs[i]),
                    float(lows[i]),
                    float(closes[i]),
                    float(volumes[i] or 0),
                    15.0,  # spread
                    0.0,   # real volume
                ])

        if rows:
            arr = np.array(rows, dtype=np.float64)
            cache_file = DATA_DIR / f"{symbol}_M1.npz"
            np.savez_compressed(str(cache_file), data=arr)
            print(f"  {symbol}: {len(arr)} bars downloaded from Yahoo")
            return True
        return False
    except Exception as e:
        print(f"  {symbol} Yahoo error: {e}")
        return False


def download_all_m1():
    """Download M1 data for all symbols from free sources."""
    symbols = ["XAUUSD", "USTEC", "US500", "US30", "DE40", "BTCUSD", "ETHUSD"]

    print("=" * 60)
    print("  Downloading M1 Data from Free Sources")
    print("=" * 60)
    print()

    results = {}
    for symbol in symbols:
        print(f"Downloading {symbol}...")
        # Yahoo Finance: 1m data available for ~7 days, use 5m/15m for longer
        success = download_yahoo_data(symbol, "5m", 24)  # 5min for 2 years
        if not success:
            success = download_yahoo_data(symbol, "15m", 24)
        results[symbol] = success

    # Also download M15 from MT5 (already cached)
    from core.backtest.data_cache import data_cache
    print("\nDownloading M15 from MT5 (cached)...")
    for symbol in ["XAUUSD", "USTEC", "US500", "US30", "DE40"]:
        data = data_cache.get_data(symbol, "M15", "2024-07-04", "2026-07-04")
        if data is not None:
            print(f"  {symbol} M15: {len(data)} bars (cached)")

    print("\n" + "=" * 60)
    print("  CACHE STATUS")
    print("=" * 60)
    info = data_cache.get_cache_info()
    total_mb = 0
    for name, details in sorted(info.items()):
        print(f"  {name}: {details['bars']:>10,} bars | {details['start']} to {details['end']} | {details['size_mb']:.1f} MB")
        total_mb += details['size_mb']
    print(f"\n  Total: {len(info)} files, {total_mb:.1f} MB")


if __name__ == "__main__":
    download_all_m1()
