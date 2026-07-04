"""Test economic calendar integration."""
import sys, asyncio
sys.path.insert(0, '.')
from core.mt5.connector import mt5_connector
from core.ftmo.compliance import ftmo_checker
from core.calendar.economic_calendar import econ_calendar
from datetime import datetime

async def test():
    mt5_connector.connect()

    print("=== Calendar Events ===")
    events = econ_calendar.get_upcoming_events(days=60)
    for e in sorted(events, key=lambda x: x.get("datetime", "")):
        print(f"  {e['date']} {e.get('impact','').upper():8s} {e['name']}")

    print(f"\n=== No-Trade Windows ===")
    windows = econ_calendar.get_no_trade_windows("2026-07-01", "2026-08-01", "XAUUSD")
    for w in windows:
        print(f"  {w['event']}: {w['no_trade_start'][:16]} -> {w['no_trade_end'][:16]} ({w['before_min']}min before, {w['after_min']}min after)")

    print("\n=== XAUUSD Backtest with Calendar Filter ===")
    from core.pipeline.auto_loop import AutoOptimizationLoop
    loop = AutoOptimizationLoop()
    s = loop._generate_strategy("XAUUSD", "bullish")
    print(f"Strategy: {s.name}")

    windows = loop._get_2week_windows()[:2]
    for w in windows:
        result = await loop._run_backtest(s, w)
        if result and "metrics" in result:
            m = result["metrics"]
            print(f"  {w['start']}->{w['end']}: Sharpe={m.get('sharpe_ratio',0):.2f} "
                  f"DD={m.get('max_drawdown_pct',0):.1f}% "
                  f"Trades={m.get('total_trades',0)} "
                  f"FTMO={m.get('ftmo_score',0):.1f}")

asyncio.run(test())
