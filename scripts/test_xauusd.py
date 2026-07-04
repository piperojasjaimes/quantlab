"""Test XAUUSD momentum backtest with real data."""
import sys, asyncio
sys.path.insert(0, '.')
from core.pipeline.auto_loop import AutoOptimizationLoop
from core.mt5.connector import mt5_connector

async def test():
    mt5_connector.connect()
    loop = AutoOptimizationLoop()

    s = loop._generate_momentum_strategy()
    print(f"Strategy: {s.name}")
    print(f"Params: SL={s.params.stop_loss} TP={s.params.take_profit} EMA={s.params.ema_fast}/{s.params.ema_slow} ATR_M={s.params.atr_multiplier} TS={s.params.trailing_stop}")

    windows = loop._get_2week_windows()[:5]
    print(f"\nTesting across {len(windows)} windows:")
    for w in windows:
        print(f"  {w['start']} -> {w['end']}")
        result = await loop._run_backtest(s, w)
        if result and "metrics" in result:
            m = result["metrics"]
            print(f"    Sharpe={m.get('sharpe_ratio',0):.2f} PF={m.get('profit_factor',0):.2f} DD={m.get('max_drawdown_pct',0):.1f}% Trades={m.get('total_trades',0)} WinRate={m.get('win_rate',0):.1f}%")
        else:
            print(f"    No data")

asyncio.run(test())
