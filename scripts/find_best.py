"""Find best aggressive config on 50K bars."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester

data = np.load("data/market/XAUUSD_M1.npz")["data"]
subset = data[:50000]

configs = [
    {"name": "Risk8 RR5", "risk": 8, "rr": 5, "sl": 1.0, "trail": 0.8, "pos": 3, "daily": 20, "ema_f": 13, "ema_s": 40},
    {"name": "Risk10 RR4", "risk": 10, "rr": 4, "sl": 0.8, "trail": 0.5, "pos": 3, "daily": 30, "ema_f": 10, "ema_s": 34},
    {"name": "Risk10 RR3", "risk": 10, "rr": 3, "sl": 0.8, "trail": 0.5, "pos": 3, "daily": 30, "ema_f": 10, "ema_s": 34},
    {"name": "Risk12 RR3", "risk": 12, "rr": 3, "sl": 0.8, "trail": 0.5, "pos": 3, "daily": 25, "ema_f": 10, "ema_s": 34},
    {"name": "Risk15 RR2", "risk": 15, "rr": 2, "sl": 0.5, "trail": 0.3, "pos": 3, "daily": 40, "ema_f": 8, "ema_s": 26},
    {"name": "Risk10 RR6", "risk": 10, "rr": 6, "sl": 1.2, "trail": 0.8, "pos": 2, "daily": 15, "ema_f": 13, "ema_s": 40},
]

best_profit = 0
best_cfg = None

for cfg in configs:
    t0 = time.time()
    params = {
        "initial_balance": 500.0, "risk_per_trade_pct": cfg["risk"],
        "max_daily_loss_pct": 999, "max_total_loss_pct": 999,
        "target_ratio": cfg["rr"], "trailing_atr_mult": cfg["trail"],
        "sl_atr_multiplier": cfg["sl"], "ema_fast": cfg["ema_f"], "ema_slow": cfg["ema_s"],
        "regime_period": 20, "min_efficiency": 0.05, "min_volume_ratio": 5,
        "max_spread_pips": 50, "max_trade_duration": 240,
        "max_positions": cfg["pos"], "max_daily_trades": cfg["daily"],
        "consecutive_loss_limit": 10, "ticks_per_bar": 1,
        "spread_pips": 15, "commission_per_lot": 3.5,
        "swap_long": -2.5, "swap_short": -0.5, "lot_size": 0.01,
    }
    tester = MT5StrategyTester(params)
    r = tester.run("XAUUSD", subset)
    elapsed = time.time() - t0

    m = r["metrics"]
    final = m["net_profit"] + 500
    if final > best_profit:
        best_profit = final
        best_cfg = cfg
    print(f"  {cfg['name']:14s}: ${final:>10,.0f} T={m['total_trades']:>3d} WR={m['win_rate']:5.1f}% PF={m['profit_factor']:5.2f} DD={m['max_drawdown_pct']:5.1f}% {elapsed:.1f}s")

print(f"\nBest: {best_cfg['name']} — ${best_profit:,.0f}")
