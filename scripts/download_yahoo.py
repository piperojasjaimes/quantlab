"""Download M1 data using yfinance library."""
import sys
sys.path.insert(0, '.')
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "market"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Yahoo Finance tickers
YAHOO_MAP = {
    "XAUUSD": "GC=F",
    "USTEC": "NDX",
    "US500": "SPX",
    "US30": "^DJI",
    "DE40": "^GDAXI",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
}

print("=" * 60)
print("  Downloading Data via yfinance")
print("=" * 60)
print()

results = {}
for symbol, yahoo_ticker in YAHOO_MAP.items():
    print(f"Downloading {symbol} ({yahoo_ticker})...")
    try:
        ticker = yf.Ticker(yahoo_ticker)

        # Get 2 years of data
        # yfinance limits: 1m=7days, 5m=60days, 15m=730days, 1h=730days
        df = ticker.history(period="2y", interval="15m")

        if df is None or df.empty:
            print(f"  {symbol}: No data")
            results[symbol] = 0
            continue

        # Convert to numpy array format
        rows = []
        for idx, row in df.iterrows():
            ts = idx.timestamp()
            rows.append([
                ts,
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                float(row.get("Volume", 0)),
                15.0,  # spread
                0.0,   # real volume
            ])

        arr = np.array(rows, dtype=np.float64)
        cache_file = DATA_DIR / f"{symbol}_M15.npz"
        np.savez_compressed(str(cache_file), data=arr)
        print(f"  {symbol}: {len(arr)} bars | {df.index[0]} to {df.index[-1]}")
        results[symbol] = len(arr)

    except Exception as e:
        print(f"  {symbol} error: {e}")
        results[symbol] = 0

    # Also try 1h data
    try:
        df_h1 = ticker.history(period="2y", interval="1h")
        if df_h1 is not None and not df_h1.empty:
            rows_h1 = []
            for idx, row in df_h1.iterrows():
                ts = idx.timestamp()
                rows_h1.append([
                    ts, float(row["Open"]), float(row["High"]),
                    float(row["Low"]), float(row["Close"]),
                    float(row.get("Volume", 0)), 15.0, 0.0
                ])
            arr_h1 = np.array(rows_h1, dtype=np.float64)
            cache_file_h1 = DATA_DIR / f"{symbol}_H1.npz"
            np.savez_compressed(str(cache_file_h1), data=arr_h1)
            print(f"  {symbol} H1: {len(arr_h1)} bars")
    except Exception as e:
        pass

print("\n" + "=" * 60)
print("  SUMMARY")
print("=" * 60)
for symbol, bars in results.items():
    print(f"  {symbol}: {bars:>10,} bars")

# Show all cached files
print("\n" + "=" * 60)
print("  ALL CACHED DATA")
print("=" * 60)
for f in sorted(DATA_DIR.glob("*.npz")):
    try:
        loaded = np.load(str(f))
        data = loaded["data"]
        start = datetime.fromtimestamp(data[0, 0]).strftime("%Y-%m-%d")
        end = datetime.fromtimestamp(data[-1, 0]).strftime("%Y-%m-%d")
        size_mb = Path(f).stat().st_size / 1024 / 1024
        print(f"  {f.stem:20s}: {len(data):>10,} bars | {start} to {end} | {size_mb:.2f} MB")
    except Exception:
        pass
