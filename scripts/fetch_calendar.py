"""Fetch economic calendar events from ForexFactory."""
import sys
sys.path.insert(0, '.')
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from core.calendar.economic_calendar import econ_calendar
from core.logger import get_logger, setup_logging

log = get_logger("fetch_calendar")

# Pre-defined high-impact events for the next 3 months
# These are recurring events that FTMO restricts
RECURRING_EVENTS = [
    # US Events (USD)
    {"name": "Non-Farm Payrolls", "day": "first_friday", "time": "12:30", "currency": "USD", "impact": "red"},
    {"name": "Unemployment Rate", "day": "first_friday", "time": "12:30", "currency": "USD", "impact": "red"},
    {"name": "Average Hourly Earnings m/m", "day": "first_friday", "time": "12:30", "currency": "USD", "impact": "red"},
    {"name": "CPI m/m", "day": "10-15", "time": "12:30", "currency": "USD", "impact": "red"},
    {"name": "Core CPI m/m", "day": "10-15", "time": "12:30", "currency": "USD", "impact": "red"},
    {"name": "FOMC Statement", "day": "fomc", "time": "18:00", "currency": "USD", "impact": "red"},
    {"name": "Federal Funds Rate", "day": "fomc", "time": "18:00", "currency": "USD", "impact": "red"},
    {"name": "FOMC Press Conference", "day": "fomc", "time": "18:30", "currency": "USD", "impact": "red"},
    {"name": "GDP m/m", "day": "last_week", "time": "12:30", "currency": "USD", "impact": "red"},
    {"name": "ISM Manufacturing PMI", "day": "first_business", "time": "14:00", "currency": "USD", "impact": "red"},
    {"name": "ISM Services PMI", "day": "third_business", "time": "14:00", "currency": "USD", "impact": "red"},
    {"name": "Retail Sales m/m", "day": "15-17", "time": "12:30", "currency": "USD", "impact": "red"},
    {"name": "ADP Non-Farm Employment Change", "day": "two_days_before_nfp", "time": "12:15", "currency": "USD", "impact": "orange"},
    {"name": "JOLTS Job Openings", "day": "first_tuesday", "time": "14:00", "currency": "USD", "impact": "red"},
    {"name": "CB Consumer Confidence", "day": "last_tuesday", "time": "14:00", "currency": "USD", "impact": "red"},
    {"name": "Unemployment Claims", "day": "thursday", "time": "12:30", "currency": "USD", "impact": "orange"},

    # GBP Events
    {"name": "BoE Rate Decision", "day": "boe_first_thursday", "time": "12:00", "currency": "GBP", "impact": "red"},

    # EUR Events
    {"name": "ECB Press Conference", "day": "ecb_first_thursday", "time": "12:45", "currency": "EUR", "impact": "red"},

    # JPY Events
    {"name": "BoJ Policy Rate", "day": "boj_last_friday", "time": "23:00", "currency": "JPY", "impact": "red"},

    # AUD Events
    {"name": "RBA Rate Statement", "day": "rba_first_tuesday", "time": "00:30", "currency": "AUD", "impact": "red"},
]


def get_first_friday(year: int, month: int) -> datetime:
    d = datetime(year, month, 1)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


def get_fomc_dates(year: int) -> list[datetime]:
    # FOMC typically meets 8 times a year
    months = [1, 3, 5, 6, 8, 9, 11, 12]
    dates = []
    for m in months:
        d = datetime(year, m, 1)
        while d.weekday() != 2:  # Wednesday
            d += timedelta(days=1)
        dates.append(d)
    return dates


def generate_events_for_month(year: int, month: int) -> list[dict]:
    events = []
    days_in_month = 30 if month in [4, 6, 9, 11] else 31 if month != 2 else 28

    # FOMC dates
    fomc_dates = get_fomc_dates(year)

    for event_def in RECURRING_EVENTS:
        try:
            if event_def["day"] == "first_friday":
                d = get_first_friday(year, month)
                events.append({
                    "name": event_def["name"],
                    "datetime": f"{d.strftime('%Y-%m-%d')}T{event_def['time']}:00",
                    "date": d.strftime("%Y-%m-%d"),
                    "impact": event_def["impact"],
                    "currency": event_def["currency"],
                })
            elif event_def["day"] == "fomc":
                for fd in fomc_dates:
                    if fd.month == month:
                        events.append({
                            "name": event_def["name"],
                            "datetime": f"{fd.strftime('%Y-%m-%d')}T{event_def['time']}:00",
                            "date": fd.strftime("%Y-%m-%d"),
                            "impact": event_def["impact"],
                            "currency": event_def["currency"],
                        })
            elif event_def["day"].startswith("10-15"):
                d = datetime(year, month, 12)
                events.append({
                    "name": event_def["name"],
                    "datetime": f"{d.strftime('%Y-%m-%d')}T{event_def['time']}:00",
                    "date": d.strftime("%Y-%m-%d"),
                    "impact": event_def["impact"],
                    "currency": event_def["currency"],
                })
            elif event_def["day"] == "first_business":
                d = datetime(year, month, 1)
                while d.weekday() >= 5:
                    d += timedelta(days=1)
                events.append({
                    "name": event_def["name"],
                    "datetime": f"{d.strftime('%Y-%m-%d')}T{event_def['time']}:00",
                    "date": d.strftime("%Y-%m-%d"),
                    "impact": event_def["impact"],
                    "currency": event_def["currency"],
                })
            elif event_def["day"] == "third_business":
                d = datetime(year, month, 1)
                biz_count = 0
                while biz_count < 3:
                    if d.weekday() < 5:
                        biz_count += 1
                    if biz_count < 3:
                        d += timedelta(days=1)
                events.append({
                    "name": event_def["name"],
                    "datetime": f"{d.strftime('%Y-%m-%d')}T{event_def['time']}:00",
                    "date": d.strftime("%Y-%m-%d"),
                    "impact": event_def["impact"],
                    "currency": event_def["currency"],
                })
        except Exception as e:
            log.warning("Failed to generate event %s for %d-%02d: %s", event_def["name"], year, month, e)

    return events


def main():
    setup_logging()
    log.info("Generating economic calendar events...")

    now = datetime.now()
    events = []

    # Generate for current month and next 3 months
    for offset in range(4):
        m = now.month + offset
        y = now.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        month_events = generate_events_for_month(y, m)
        events.extend(month_events)
        log.info("Generated %d events for %d-%02d", len(month_events), y, m)

    # Clear and reload
    econ_calendar.clear_cache()
    econ_calendar.add_events_batch(events)

    log.info("Total events: %d", len(events))

    # Show upcoming events
    upcoming = econ_calendar.get_upcoming_events(days=30)
    log.info("Upcoming events (next 30 days):")
    for e in sorted(upcoming, key=lambda x: x.get("datetime", "")):
        log.info("  %s | %s | %s", e["date"], e["impact"].upper(), e["name"])


if __name__ == "__main__":
    main()
