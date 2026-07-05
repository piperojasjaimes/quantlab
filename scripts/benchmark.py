"""Benchmark MT5 engine speed."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester

data = np.load("data/market/XAUUSD_M1.npz")["data"]
print(f"Total M1 bars: {len(data)}")

for n in [50000, 100000, 200000]:
    subset = data[:n]
    params = {
        "initial_balance": 100000, "risk_per_trade_pct": 1.0,
        "max_daily_loss_pct": 4.0, "max_total_loss_pct": 10.0,
        "target_ratio": 5.0, "trailing_atr_mult": 0.5,
        "sl_atr_multiplier": 1.25, "ema_fast": 13, "ema_slow": 40,
        "regime_period": 23, "min_efficiency": 0.07, "min_volume_ratio": 25,
        "max_spread_pips": 25, "max_trade_duration": 30,
        "ticks_per_bar": 1, "spread_pips": 15, "commission_per_lot": 3.5,
        "swap_long": -2.5, "swap_short": -0.5,
    }
    start = time.time()
    tester = MT5StrategyTester(params)
    result = tester.run("XAUUSD", subset)
    elapsed = time.time() - start
    m = result["metrics"]
    print(f"{n:>10,} bars: {elapsed:.1f}s | Trades={m['total_trades']:>4d} "
          f"WR={m['win_rate']:5.1f}% PF={m['profit_factor']:5.2f} "
          f"Sharpe={m['sharpe_ratio']:6.2f} Net=${m['net_profit']:>9,.0f}")
