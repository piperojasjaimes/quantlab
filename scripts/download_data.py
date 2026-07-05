"""Download all available market data for the last 2 years."""
import sys
sys.path.insert(0, '.')
from core.backtest.data_cache import data_cache
from core.mt5.connector import mt5_connector

print("=" * 60)
print("  Downloading Market Data — Last 2 Years")
print("=" * 60)

# Correct symbol names for MT5
SYMBOL_MAP = {
    "XAUUSD": "XAUUSD",
    "USTEC": "USTEC",      # NASDAQ 100
    "US500": "US500",      # S&P 500
    "US30": "US30",        # Dow Jones
    "DE40": "DE40",        # DAX
}

timeframes = ["M1", "M5", "M15", "H1"]

print(f"\nSymbols: {', '.join(SYMBOL_MAP.keys())}")
print(f"Timeframes: {', '.join(timeframes)}")
print()

results = {}
for name, mt5_symbol in SYMBOL_MAP.items():
    results[name] = {}
    for tf in timeframes:
        try:
            data = data_cache.get_data(mt5_symbol, tf, "2024-07-04", "2026-07-04")
            if data is not None:
                results[name][tf] = len(data)
            else:
                results[name][tf] = 0
        except Exception as e:
            print(f"  Error {name} {tf}: {e}")
            results[name][tf] = 0

print("\n" + "=" * 60)
print("  DOWNLOAD RESULTS")
print("=" * 60)

for symbol, tfs in results.items():
    print(f"\n{symbol}:")
    for tf, bars in tfs.items():
        status = f"{bars:>10,} bars" if bars > 0 else "NOT AVAILABLE"
        print(f"  {tf}: {status}")

print("\n" + "=" * 60)
print("  CACHE INFO")
print("=" * 60)

info = data_cache.get_cache_info()
total_mb = 0
for name, details in info.items():
    print(f"  {name}: {details['bars']:>10,} bars | {details['start']} to {details['end']} | {details['size_mb']:.1f} MB")
    total_mb += details['size_mb']

print(f"\n  Total cached: {total_mb:.1f} MB")
