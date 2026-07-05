"""Fast aggressive test — specific high-risk configurations."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester

data = np.load("data/market/XAUUSD_M1.npz")["data"]
print(f"Data: {len(data):,} bars")

# Aggressive configurations to test
CONFIGS = [
    {"name": "Ultra Aggressive", "risk": 10, "rr": 2, "sl": 0.5, "trail": 0.3, "pos": 3, "daily": 50, "ema_f": 8, "ema_s": 26},
    {"name": "High Risk R:R4", "risk": 10, "rr": 4, "sl": 0.8, "trail": 0.5, "pos": 3, "daily": 30, "ema_f": 10, "ema_s": 34},
    {"name": "Mega Compounding", "risk": 15, "rr": 3, "sl": 1.0, "trail": 0.5, "pos": 5, "daily": 50, "ema_f": 13, "ema_s": 40},
    {"name": "Max Profit", "risk": 20, "rr": 2, "sl": 0.5, "trail": 0.3, "pos": 5, "daily": 100, "ema_f": 8, "ema_s": 26},
    {"name": "Balanced Aggressive", "risk": 8, "rr": 5, "sl": 1.2, "trail": 0.8, "pos": 3, "daily": 20, "ema_f": 13, "ema_s": 40},
    {"name": "Scalping King", "risk": 10, "rr": 1.5, "sl": 0.5, "trail": 0.3, "pos": 5, "daily": 100, "ema_f": 5, "ema_s": 20},
    {"name": "Trend Rider", "risk": 12, "rr": 6, "sl": 1.5, "trail": 1.0, "pos": 2, "daily": 15, "ema_f": 15, "ema_s": 50},
    {"name": "Compound Machine", "risk": 10, "rr": 3, "sl": 0.8, "trail": 0.5, "pos": 4, "daily": 40, "ema_f": 10, "ema_s": 34},
]

results = []
for cfg in CONFIGS:
    start = time.time()
    params = {
        "initial_balance": 500.0,
        "risk_per_trade_pct": cfg["risk"],
        "max_daily_loss_pct": 999,
        "max_total_loss_pct": 999,
        "target_ratio": cfg["rr"],
        "trailing_atr_mult": cfg["trail"],
        "partial_profit_pct": 0.5,
        "sl_atr_multiplier": cfg["sl"],
        "ema_fast": cfg["ema_f"],
        "ema_slow": cfg["ema_s"],
        "ema_period_h1": 50,
        "regime_period": 20,
        "min_efficiency": 0.05,
        "min_volume_ratio": 5,
        "max_spread_pips": 50,
        "max_trade_duration": 240,
        "max_positions": cfg["pos"],
        "max_daily_trades": cfg["daily"],
        "consecutive_loss_limit": 10,
        "ticks_per_bar": 1,
        "spread_pips": 15,
        "commission_per_lot": 3.5,
        "swap_long": -2.5,
        "swap_short": -0.5,
        "lot_size": 0.01,
    }

    tester = MT5StrategyTester(params)
    result = tester.run("XAUUSD", data)
    elapsed = time.time() - start

    if "error" in result or not result.get("trades"):
        print(f"  {cfg['name']:25s}: No trades")
        continue

    m = result["metrics"]
    final = m["net_profit"] + 500
    ret = (final / 500 - 1) * 100
    results.append((cfg["name"], final, ret, m, elapsed))

    print(f"  {cfg['name']:25s}: ${final:>10,.0f} ({ret:>6.0f}%) | "
          f"Trades={m['total_trades']:>3d} WR={m['win_rate']:5.1f}% "
          f"PF={m['profit_factor']:5.2f} DD={m['max_drawdown_pct']:5.1f}% "
          f"Sharpe={m['sharpe_ratio']:6.2f} | {elapsed:.1f}s")

# Best result
if results:
    results.sort(key=lambda x: x[1], reverse=True)
    best = results[0]
    print(f"\n{'='*70}")
    print(f"  BEST: {best[0]} — ${best[1]:,.0f} ({best[2]:.0f}% return)")
    print(f"  Trades: {best[3]['total_trades']} | WR: {best[3]['win_rate']}%")
    print(f"  PF: {best[3]['profit_factor']} | DD: {best[3]['max_drawdown_pct']}%")
