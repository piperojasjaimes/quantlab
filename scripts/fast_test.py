"""Fast test on 50K bars."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester

data = np.load("data/market/XAUUSD_M1.npz")["data"]
subset = data[:50000]
print(f"Testing on {len(subset)} bars")

configs = [
    {"name": "Ultra 10%", "risk": 10, "rr": 2, "sl": 0.5, "trail": 0.3, "pos": 3, "daily": 50, "ema_f": 8, "ema_s": 26},
    {"name": "High Risk 10%", "risk": 10, "rr": 4, "sl": 0.8, "trail": 0.5, "pos": 3, "daily": 30, "ema_f": 10, "ema_s": 34},
    {"name": "Mega 15%", "risk": 15, "rr": 3, "sl": 1.0, "trail": 0.5, "pos": 5, "daily": 50, "ema_f": 13, "ema_s": 40},
    {"name": "Max 20%", "risk": 20, "rr": 2, "sl": 0.5, "trail": 0.3, "pos": 5, "daily": 100, "ema_f": 8, "ema_s": 26},
    {"name": "Scalp 10%", "risk": 10, "rr": 1.5, "sl": 0.5, "trail": 0.3, "pos": 5, "daily": 100, "ema_f": 5, "ema_s": 20},
    {"name": "Trend 12%", "risk": 12, "rr": 6, "sl": 1.5, "trail": 1.0, "pos": 2, "daily": 15, "ema_f": 15, "ema_s": 50},
]

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
    if "error" in r or not r.get("trades"):
        print(f"  {cfg['name']:20s}: No trades")
        continue
    m = r["metrics"]
    final = m["net_profit"] + 500
    ret = (final / 500 - 1) * 100
    print(f"  {cfg['name']:20s}: ${final:>10,.0f} ({ret:>6.0f}%) "
          f"T={m['total_trades']:>3d} WR={m['win_rate']:5.1f}% "
          f"PF={m['profit_factor']:5.2f} DD={m['max_drawdown_pct']:5.1f}% "
          f"{elapsed:.1f}s")
