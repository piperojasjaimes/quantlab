"""Test best config on full data."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester

data = np.load("data/market/XAUUSD_M1.npz")["data"]
print(f"Full data: {len(data):,} bars")

params = {
    "initial_balance": 500.0, "risk_per_trade_pct": 20,
    "max_daily_loss_pct": 999, "max_total_loss_pct": 999,
    "target_ratio": 2, "trailing_atr_mult": 0.3,
    "sl_atr_multiplier": 0.5, "ema_fast": 8, "ema_slow": 26,
    "regime_period": 20, "min_efficiency": 0.05, "min_volume_ratio": 5,
    "max_spread_pips": 50, "max_trade_duration": 240,
    "max_positions": 5, "max_daily_trades": 100,
    "consecutive_loss_limit": 10, "ticks_per_bar": 1,
    "spread_pips": 15, "commission_per_lot": 3.5,
    "swap_long": -2.5, "swap_short": -0.5, "lot_size": 0.01,
}

t0 = time.time()
tester = MT5StrategyTester(params)
r = tester.run("XAUUSD", data)
elapsed = time.time() - t0

m = r["metrics"]
final = m["net_profit"] + 500
ret = (final / 500 - 1) * 100

print(f"Time: {elapsed:.1f}s")
print(f"Final Balance: ${final:,.0f}")
print(f"Return: {ret:.0f}%")
print(f"Trades: {m['total_trades']}")
print(f"Win Rate: {m['win_rate']}%")
print(f"PF: {m['profit_factor']}")
print(f"Sharpe: {m['sharpe_ratio']}")
print(f"DD: {m['max_drawdown_pct']}%")
print(f"Commission: ${m['total_commission']:,.0f}")

if r["trades"]:
    sorted_t = sorted(r["trades"], key=lambda x: x["profit"], reverse=True)
    print("Top 5 trades:")
    for t in sorted_t[:5]:
        print(f"  {t['type']:4s} P/L ${t['profit']:>10,.0f} {t['pips']:>5.0f}p {t['exit_reason']}")
