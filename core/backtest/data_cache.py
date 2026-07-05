"""Data Cache — downloads and stores all M1 data locally for fast backtesting."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

from core.config import config
from core.logger import get_logger

log = get_logger("backtest.cache")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "market"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["XAUUSD", "BTCUSD", "ETHUSD", "NAS100", "SP500"]
TIMEFRAMES = ["M1", "M5", "M15", "H1"]


class DataCache:
    """Manages local cache of market data from MT5."""

    def __init__(self):
        self._cache: dict[str, np.ndarray] = {}

    def get_data(self, symbol: str, timeframe: str, start_date: str, end_date: str) -> Optional[np.ndarray]:
        """Get data from cache or download from MT5.

        Args:
            symbol: e.g. "XAUUSD"
            timeframe: e.g. "M1"
            start_date: e.g. "2024-01-01"
            end_date: e.g. "2026-07-04"

        Returns:
            numpy array of (time, open, high, low, close, volume, spread, real_volume)
        """
        cache_key = f"{symbol}_{timeframe}"
        cache_file = DATA_DIR / f"{cache_key}.npz"

        # Try to load from cache
        if cache_file.exists():
            data = self._load_cache(cache_file, start_date, end_date)
            if data is not None and len(data) > 0:
                log.info("Loaded %d bars from cache: %s %s", len(data), symbol, timeframe)
                return data

        # Download from MT5
        log.info("Downloading %s %s from MT5 (%s to %s)...", symbol, timeframe, start_date, end_date)
        data = self._download_from_mt5(symbol, timeframe, start_date, end_date)

        if data is not None and len(data) > 0:
            self._save_cache(cache_file, data)
            log.info("Downloaded and cached %d bars: %s %s", len(data), symbol, timeframe)
            return data

        log.warning("No data available for %s %s", symbol, timeframe)
        return None

    def download_all(self, symbols: list[str] = None, timeframes: list[str] = None,
                     years: int = 2) -> dict:
        """Download all data for specified symbols and timeframes."""
        if symbols is None:
            symbols = SYMBOLS
        if timeframes is None:
            timeframes = TIMEFRAMES

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")

        results = {}
        for symbol in symbols:
            results[symbol] = {}
            for tf in timeframes:
                try:
                    data = self.get_data(symbol, tf, start_date, end_date)
                    if data is not None:
                        results[symbol][tf] = len(data)
                    else:
                        results[symbol][tf] = 0
                except Exception as e:
                    log.error("Failed to download %s %s: %s", symbol, tf, e)
                    results[symbol][tf] = 0

        # Save metadata
        meta = {
            "download_date": datetime.now().isoformat(),
            "start_date": start_date,
            "end_date": end_date,
            "bars": results,
        }
        meta_file = DATA_DIR / "metadata.json"
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return results

    def _download_from_mt5(self, symbol: str, timeframe: str, start_date: str, end_date: str) -> Optional[np.ndarray]:
        """Download data from MT5."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                log.error("MT5 not initialized")
                return None

            # Make sure symbol is visible
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                mt5.symbol_add(symbol)

            tf_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
            tf = tf_map.get(timeframe, 1)

            d_from = datetime.strptime(start_date, "%Y-%m-%d")
            d_to = datetime.strptime(end_date, "%Y-%m-%d")

            rates = mt5.copy_rates_range(symbol, tf, d_from, d_to)
            mt5.shutdown()

            if rates is not None and len(rates) > 0:
                # Convert structured array to plain float64 array
                result = np.column_stack([
                    rates["time"].astype(np.float64),
                    rates["open"].astype(np.float64),
                    rates["high"].astype(np.float64),
                    rates["low"].astype(np.float64),
                    rates["close"].astype(np.float64),
                    rates["tick_volume"].astype(np.float64),
                    rates["spread"].astype(np.float64),
                    rates["real_volume"].astype(np.float64),
                ])
                return result
            return None
        except Exception as e:
            log.error("MT5 download error: %s", e)
            return None

    def _save_cache(self, path: Path, data: np.ndarray) -> None:
        """Save data to compressed numpy file."""
        np.savez_compressed(str(path), data=data)

    def _load_cache(self, path: Path, start_date: str, end_date: str) -> Optional[np.ndarray]:
        """Load data from cache and filter by date range."""
        try:
            loaded = np.load(str(path))
            data = loaded["data"]

            if data is None or len(data) == 0:
                return None

            # Filter by date range (column 0 is timestamp)
            start_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
            end_ts = datetime.strptime(end_date, "%Y-%m-%d").timestamp()

            mask = (data[:, 0] >= start_ts) & (data[:, 0] <= end_ts)
            filtered = data[mask]

            if len(filtered) > 0:
                return filtered
            return data  # Return all data if filter removes everything
        except Exception as e:
            log.error("Cache load error: %s", e)
            return None

    def get_cache_info(self) -> dict:
        """Get info about cached data files."""
        info = {}
        for f in DATA_DIR.glob("*.npz"):
            try:
                loaded = np.load(str(f))
                data = loaded["data"]
                if data is not None and len(data) > 0:
                    start = datetime.fromtimestamp(data[0, 0]).strftime("%Y-%m-%d")
                    end = datetime.fromtimestamp(data[-1, 0]).strftime("%Y-%m-%d")
                    info[f.stem] = {
                        "bars": len(data),
                        "start": start,
                        "end": end,
                        "size_mb": round(os.path.getsize(f) / 1024 / 1024, 2),
                    }
            except Exception:
                pass
        return info


data_cache = DataCache()
