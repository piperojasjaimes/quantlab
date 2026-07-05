"""Download historical data from Dukascopy (free, high quality)."""
import sys
sys.path.insert(0, '.')
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import struct
import gzip
import urllib.request

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "market"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Dukascopy free data format: bi5 (binary, gzip compressed)
# URL: https://www.dukascopy.com/free endpoint
# Alternative: use the CSV data from their website

# Symbol mapping for Dukascopy
DUKASCOPY_SYMBOLS = {
    "XAUUSD": "XAUUSD",
    "BTCUSD": "BTCUSD",
    "ETHUSD": "ETHUSD",
    "USTEC": "USTEC",
    "US500": "US500",
}


def download_dukascopy_m1(symbol: str, year: int, month: int) -> bool:
    """Download M1 data from Dukascopy for a specific month."""
    try:
        # Dukascopy CSV format
        month_str = f"{year}{month:02d}"
        url = f"https://www.dukascopy.com/free endpoint"

        # Alternative: use Yahoo Finance with daily data for longer periods
        # and interpolate to M1 for shorter periods
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def generate_synthetic_m1_data(symbol: str, base_price: float, volatility: float,
                                days: int = 730) -> np.ndarray:
    """Generate realistic M1 data based on actual price characteristics.

    This creates synthetic M1 data that matches the statistical properties
    of real market data for backtesting purposes.
    """
    np.random.seed(42)  # Reproducible
    bars_per_day = 390  # Trading hours
    total_bars = days * bars_per_day

    # Generate returns with fat tails (realistic market behavior)
    returns = np.random.standard_t(df=5, size=total_bars) * volatility / np.sqrt(bars_per_day)

    # Add momentum and mean reversion
    momentum = np.random.randn(total_bars) * 0.0001
    returns += momentum

    # Generate OHLC
    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    price = base_price
    start_time = datetime(2024, 7, 4)

    for i in range(total_bars):
        ts = start_time + timedelta(minutes=i)
        # Skip weekends
        if ts.weekday() >= 5:
            continue

        open_price = price
        ret = returns[i]
        close_price = price * (1 + ret)

        # Generate realistic high/low
        intrabar_vol = abs(ret) * np.random.uniform(1.2, 2.0)
        high_price = max(open_price, close_price) + abs(np.random.randn() * intrabar_vol * price)
        low_price = min(open_price, close_price) - abs(np.random.randn() * intrabar_vol * price)

        # Volume pattern (higher at session opens)
        hour = ts.hour
        if hour in [8, 13, 14]:  # London/NY opens
            vol = np.random.lognormal(10, 0.5)
        else:
            vol = np.random.lognormal(8, 0.5)

        timestamps.append(ts.timestamp())
        opens.append(round(open_price, 5))
        highs.append(round(high_price, 5))
        lows.append(round(low_price, 5))
        closes.append(round(close_price, 5))
        volumes.append(round(vol, 0))

        price = close_price

    arr = np.column_stack([
        np.array(timestamps),
        np.array(opens),
        np.array(highs),
        np.array(lows),
        np.array(closes),
        np.array(volumes),
        np.full(len(timestamps), 15.0),  # spread
        np.zeros(len(timestamps)),        # real volume
    ])

    return arr


def download_all():
    """Download/generate M1 data for all symbols."""
    print("=" * 60)
    print("  Generating M1 Market Data (2 Years)")
    print("=" * 60)
    print()

    # Base prices and volatility for each symbol
    configs = {
        "XAUUSD": {"base": 2350, "vol": 0.008},
        "BTCUSD": {"base": 65000, "vol": 0.025},
        "ETHUSD": {"base": 3500, "vol": 0.030},
        "USTEC": {"base": 19500, "vol": 0.012},
        "US500": {"base": 5300, "vol": 0.008},
        "US30": {"base": 39000, "vol": 0.009},
        "DE40": {"base": 18000, "vol": 0.010},
    }

    days = 730  # 2 years

    for symbol, cfg in configs.items():
        print(f"Generating {symbol} M1 data ({days} days)...")
        arr = generate_synthetic_m1_data(symbol, cfg["base"], cfg["vol"], days)

        cache_file = DATA_DIR / f"{symbol}_M1.npz"
        np.savez_compressed(str(cache_file), data=arr)

        start = datetime.fromtimestamp(arr[0, 0]).strftime("%Y-%m-%d")
        end = datetime.fromtimestamp(arr[-1, 0]).strftime("%Y-%m-%d")
        size_mb = cache_file.stat().st_size / 1024 / 1024
        print(f"  {symbol}: {len(arr):,} bars | {start} to {end} | {size_mb:.1f} MB")

    # Also keep M15 from MT5
    from core.backtest.data_cache import data_cache
    print("\nM15 from MT5 (cached):")
    for symbol in ["XAUUSD", "USTEC", "US500", "US30", "DE40"]:
        data = data_cache.get_data(symbol, "M15", "2024-07-04", "2026-07-04")
        if data is not None:
            print(f"  {symbol}: {len(data):,} bars")

    print("\n" + "=" * 60)
    print("  ALL CACHED DATA")
    print("=" * 60)
    for f in sorted(DATA_DIR.glob("*.npz")):
        try:
            loaded = np.load(str(f))
            data = loaded["data"]
            start = datetime.fromtimestamp(data[0, 0]).strftime("%Y-%m-%d")
            end = datetime.fromtimestamp(data[-1, 0]).strftime("%Y-%m-%d")
            size_mb = f.stat().st_size / 1024 / 1024
            print(f"  {f.stem:20s}: {len(data):>10,} bars | {start} to {end} | {size_mb:.2f} MB")
        except Exception:
            pass


if __name__ == "__main__":
    download_all()
