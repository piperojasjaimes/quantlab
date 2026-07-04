"""Economic Calendar — ForexFactory integration, FTMO no-trade zones."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.config import config
from core.logger import get_logger

log = get_logger("calendar.economic")

# FTMO restricted events — cannot trade X minutes before/after
# Based on ForexFactory impact levels and FTMO rules
FTMO_RESTRICTED_EVENTS = {
    # Red (High Impact) — No trading 30 min before and after
    "Non-Farm Employment Change": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Non-Farm Payrolls": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "NFP": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "FOMC Statement": {"impact": "red", "no_trade_before_min": 60, "no_trade_after_min": 60},
    "Federal Funds Rate": {"impact": "red", "no_trade_before_min": 60, "no_trade_after_min": 60},
    "FOMC Press Conference": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "CPI m/m": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "CPI y/y": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Core CPI m/m": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Core CPI y/y": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "ECB Press Conference": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "ECB Rate Decision": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "BoE Rate Decision": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "BoJ Policy Rate": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "RBA Rate Statement": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "SNB Monetary Policy Assessment": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "BOC Rate Statement": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Interest Rate Decision": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "GDP m/m": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "GDP q/q": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Unemployment Rate": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Claimant Count Change": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Average Hourly Earnings m/m": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Retail Sales m/m": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Core Retail Sales m/m": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Trade Balance": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Consumer Price Index m/m": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Producer Price Index m/m": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "ISM Manufacturing PMI": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "ISM Services PMI": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "ADP Non-Farm Employment Change": {"impact": "red", "no_trade_before_min": 30, "no_trade_after_min": 30},
    "Prelim UoM Consumer Sentiment": {"impact": "red", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "CB Consumer Confidence": {"impact": "red", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "JOLTS Job Openings": {"impact": "red", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Economic Optimism": {"impact": "red", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Durable Goods Orders m/m": {"impact": "red", "no_trade_before_min": 15, "no_trade_after_min": 15},

    # Orange (Medium Impact) — No trading 15 min before
    "CPI m/m": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Core CPI m/m": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Unemployment Claims": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Initial Jobless Claims": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Manufacturing PMI": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Services PMI": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Building Permits": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Housing Starts": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Existing Home Sales": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "New Home Sales": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Industrial Production m/m": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Capacity Utilization Rate": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Crude Oil Inventories": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Natural Gas Storage": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Federal Budget Balance": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Import Price Index m/m": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
    "Export Price Index m/m": {"impact": "orange", "no_trade_before_min": 15, "no_trade_after_min": 15},
}

# Events that affect specific symbols
SYMBOL_EVENTS = {
    "XAUUSD": ["Non-Farm Employment Change", "Non-Farm Payrolls", "NFP", "CPI m/m", "Core CPI m/m",
               "FOMC Statement", "Federal Funds Rate", "Unemployment Rate", "GDP m/m",
               "ISM Manufacturing PMI", "ISM Services PMI", "ECB Press Conference",
               "ECB Rate Decision", "Retail Sales m/m"],
    "BTCUSD": ["FOMC Statement", "Federal Funds Rate", "CPI m/m", "Core CPI m/m",
               "GDP m/m", "ISM Manufacturing PMI", "ISM Services PMI", "Interest Rate Decision"],
    "ETHUSD": ["FOMC Statement", "Federal Funds Rate", "CPI m/m", "Core CPI m/m",
               "GDP m/m", "ISM Manufacturing PMI", "ISM Services PMI", "Interest Rate Decision"],
    "NAS100": ["FOMC Statement", "Federal Funds Rate", "CPI m/m", "Core CPI m/m",
               "GDP m/m", "ISM Manufacturing PMI", "ISM Services PMI",
               "ADP Non-Farm Employment Change", "Non-Farm Payrolls", "NFP",
               "Retail Sales m/m", "Durable Goods Orders m/m", "JOLTS Job Openings"],
    "SP500": ["FOMC Statement", "Federal Funds Rate", "CPI m/m", "Core CPI m/m",
              "GDP m/m", "ISM Manufacturing PMI", "ISM Services PMI",
              "Non-Farm Payrolls", "NFP", "Unemployment Rate",
              "Retail Sales m/m", "CB Consumer Confidence", "Prelim UoM Consumer Sentiment"],
}


class EconomicCalendar:
    """Manages economic calendar events and FTMO no-trade zones."""

    def __init__(self) -> None:
        self._events_cache: list[dict] = []
        self._cache_path = Path(__file__).resolve().parent.parent.parent / "data" / "economic_calendar.json"
        self._load_cache()

    def _load_cache(self) -> None:
        if self._cache_path.exists():
            try:
                self._events_cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
                log.info("Loaded %d calendar events from cache", len(self._events_cache))
            except Exception as e:
                log.warning("Failed to load calendar cache: %s", e)

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(self._events_cache, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save calendar cache: %s", e)

    def get_events(self, start_date: str, end_date: str, symbol: str = None) -> list[dict]:
        """Get calendar events for a date range, optionally filtered by symbol."""
        events = []
        for event in self._events_cache:
            event_date = event.get("date", "")
            if start_date <= event_date <= end_date:
                if symbol is None or self._event_affects_symbol(event, symbol):
                    events.append(event)
        return events

    def is_no_trade_zone(self, timestamp: datetime, symbol: str = None) -> tuple[bool, str]:
        """Check if a timestamp falls within a no-trade zone.

        Returns:
            (is_blocked, reason) — reason describes which event caused the block
        """
        for event in self._events_cache:
            if not self._event_affects_symbol(event, symbol):
                continue

            event_name = event.get("name", "")
            event_dt_str = event.get("datetime", "")
            if not event_dt_str:
                continue

            try:
                event_dt = datetime.fromisoformat(event_dt_str.replace("Z", "+00:00"))
            except Exception:
                continue

            # Get no-trade window
            restriction = FTMO_RESTRICTED_EVENTS.get(event_name, {})
            if not restriction:
                # Check partial matches
                for key, val in FTMO_RESTRICTED_EVENTS.items():
                    if key.lower() in event_name.lower() or event_name.lower() in key.lower():
                        restriction = val
                        break

            if not restriction:
                continue

            before_min = restriction.get("no_trade_before_min", 0)
            after_min = restriction.get("no_trade_after_min", 0)

            no_trade_start = event_dt - timedelta(minutes=before_min)
            no_trade_end = event_dt + timedelta(minutes=after_min)

            if no_trade_start <= timestamp <= no_trade_end:
                return True, f"{event_name} ({event.get('impact', 'red')} impact) — no trade {before_min}min before to {after_min}min after"

        return False, ""

    def is_no_trade_zone_for_backtest(self, timestamp: datetime, symbol: str = None) -> bool:
        """Simplified check for backtesting — returns True if in no-trade zone."""
        blocked, _ = self.is_no_trade_zone(timestamp, symbol)
        return blocked

    def get_no_trade_windows(self, start_date: str, end_date: str, symbol: str = None) -> list[dict]:
        """Get all no-trade windows for a date range."""
        windows = []
        for event in self._events_cache:
            if not self._event_affects_symbol(event, symbol):
                continue

            event_name = event.get("name", "")
            event_dt_str = event.get("datetime", "")
            if not event_dt_str:
                continue

            try:
                event_dt = datetime.fromisoformat(event_dt_str.replace("Z", "+00:00"))
            except Exception:
                continue

            restriction = FTMO_RESTRICTED_EVENTS.get(event_name, {})
            if not restriction:
                for key, val in FTMO_RESTRICTED_EVENTS.items():
                    if key.lower() in event_name.lower() or event_name.lower() in key.lower():
                        restriction = val
                        break

            if not restriction:
                continue

            before_min = restriction.get("no_trade_before_min", 0)
            after_min = restriction.get("no_trade_after_min", 0)

            windows.append({
                "event": event_name,
                "impact": event.get("impact", "red"),
                "datetime": event_dt_str,
                "no_trade_start": (event_dt - timedelta(minutes=before_min)).isoformat(),
                "no_trade_end": (event_dt + timedelta(minutes=after_min)).isoformat(),
                "before_min": before_min,
                "after_min": after_min,
            })

        return windows

    def _event_affects_symbol(self, event: dict, symbol: str) -> bool:
        if symbol is None:
            return True
        event_name = event.get("name", "")
        relevant_events = SYMBOL_EVENTS.get(symbol, [])
        for re_name in relevant_events:
            if re_name.lower() in event_name.lower() or event_name.lower() in re_name.lower():
                return True
        return False

    def add_event(self, name: str, datetime_str: str, impact: str = "red",
                  currency: str = "USD", forecast: str = "", previous: str = "") -> None:
        """Add an event to the calendar."""
        event = {
            "name": name,
            "datetime": datetime_str,
            "date": datetime_str[:10],
            "impact": impact,
            "currency": currency,
            "forecast": forecast,
            "previous": previous,
        }
        self._events_cache.append(event)
        self._save_cache()

    def add_events_batch(self, events: list[dict]) -> None:
        """Add multiple events."""
        for e in events:
            self._events_cache.append(e)
        self._save_cache()

    def clear_cache(self) -> None:
        self._events_cache = []
        self._save_cache()

    def get_upcoming_events(self, days: int = 7, symbol: str = None) -> list[dict]:
        """Get upcoming events for the next N days."""
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        return self.get_events(
            now.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            symbol
        )


econ_calendar = EconomicCalendar()
