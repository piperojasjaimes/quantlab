"""Test MT5 engine with smaller dataset."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester

data = np.load("data/market/XAUUSD_M1.npz")["data"]
subset = data[:10000]
print(f"Testing with {len(subset)} bars")

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
print(f"Time: {elapsed:.1f}s")
print(f"Trades: {m['total_trades']}")
print(f"WinRate: {m['win_rate']}%")
print(f"PF: {m['profit_factor']}")
print(f"Sharpe: {m['sharpe_ratio']}")
print(f"DD: {m['max_drawdown_pct']}%")
print(f"Net: ${m['net_profit']:,.0f}")
print(f"Swaps: ${m['total_swaps']:,.0f}")
print(f"Commission: ${m['total_commission']:,.0f}")
