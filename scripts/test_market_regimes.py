"""Test 10% risk bot across different market regimes (bullish/bearish) from last year."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester
from datetime import datetime, timedelta

data = np.load("data/market/XAUUSD_M1.npz")["data"]
print(f"Total data: {len(data):,} bars")

# Define market regimes based on XAUUSD price action (2024-2025)
# We'll extract 2-week windows and classify them
def get_window(data, start_idx, days=14):
    bars_per_day = 390
    end_idx = min(start_idx + days * bars_per_day, len(data))
    return data[start_idx:end_idx]

def classify_regime(window_data):
    """Classify a window as bullish/bearish/neutral based on price action."""
    if len(window_data) < 100:
        return "unknown", 0
    closes = window_data[:, 4]
    start_price = closes[0]
    end_price = closes[-1]
    change_pct = (end_price - start_price) / start_price * 100

    if change_pct > 0.5:
        return "BULLISH", change_pct
    elif change_pct < -0.5:
        return "BEARISH", change_pct
    else:
        return "NEUTRAL", change_pct

# Test on different periods
print("\n" + "=" * 80)
print("  TESTING 10% RISK BOT ON DIFFERENT MARKET REGIMES")
print("=" * 80)

params = {
    "initial_balance": 1000.0, "risk_per_trade_pct": 10,
    "max_daily_loss_pct": 999, "max_total_loss_pct": 999,
    "target_ratio": 2, "trailing_atr_mult": 0.3,
    "sl_atr_multiplier": 0.5, "ema_fast": 8, "ema_slow": 26,
    "regime_period": 20, "min_efficiency": 0.05, "min_volume_ratio": 5,
    "max_spread_pips": 50, "max_trade_duration": 240,
    "max_positions": 3, "max_daily_trades": 50,
    "consecutive_loss_limit": 10, "ticks_per_bar": 1,
    "spread_pips": 15, "commission_per_lot": 3.5,
    "swap_long": -2.5, "swap_short": -0.5, "lot_size": 0.01,
}

# Test on rolling 2-week windows
windows = []
bars_per_day = 390
for start in range(0, len(data) - 14 * bars_per_day, 7 * bars_per_day):  # Every week
    end = min(start + 14 * bars_per_day, len(data))
    window_data = data[start:end]
    regime, change = classify_regime(window_data)
    windows.append((start, end, regime, change, window_data))

results_by_regime = {"BULLISH": [], "BEARISH": [], "NEUTRAL": []}

print(f"\nTesting {len(windows)} windows of 2 weeks each\n")

for i, (start, end, regime, change, window_data) in enumerate(windows):
    tester = MT5StrategyTester(params)
    result = tester.run("XAUUSD", window_data)

    if "error" in result or not result.get("trades"):
        continue

    m = result["metrics"]
    final = m["net_profit"] + 1000
    ret = (final / 1000 - 1) * 100
    results_by_regime[regime].append((final, ret, m))

    icon = "🟢" if regime == "BULLISH" else "🔴" if regime == "BEARISH" else "⚪"
    print(f"  {icon} Window {i+1:>2d} | {regime:8s} ({change:>+6.2f}%) | "
          f"${final:>8,.0f} ({ret:>+6.0f}%) | "
          f"T={m['total_trades']:>2d} WR={m['win_rate']:4.0f}% PF={m['profit_factor']:4.2f}")

# Summary by regime
print("\n" + "=" * 80)
print("  SUMMARY BY MARKET REGIME")
print("=" * 80)

for regime in ["BULLISH", "BEARISH", "NEUTRAL"]:
    if results_by_regime[regime]:
        avg_final = np.mean([r[0] for r in results_by_regime[regime]])
        avg_ret = np.mean([r[1] for r in results_by_regime[regime]])
        avg_wr = np.mean([r[2]["win_rate"] for r in results_by_regime[regime]])
        avg_pf = np.mean([r[2]["profit_factor"] for r in results_by_regime[regime]])
        avg_dd = np.mean([r[2]["max_drawdown_pct"] for r in results_by_regime[regime]])
        avg_sharpe = np.mean([r[2]["sharpe_ratio"] for r in results_by_regime[regime]])
        total_profit = sum(r[0] - 1000 for r in results_by_regime[regime])
        wins = sum(1 for r in results_by_regime[regime] if r[0] > 1000)

        icon = "🟢" if regime == "BULLISH" else "🔴" if regime == "BEARISH" else "⚪"
        print(f"\n  {icon} {regime} ({len(results_by_regime[regime])} windows)")
        print(f"     Avg Final: ${avg_final:,.0f} ({avg_ret:+.0f}%)")
        print(f"     Avg WinRate: {avg_wr:.1f}% | Avg PF: {avg_pf:.2f}")
        print(f"     Avg DD: {avg_dd:.1f}% | Avg Sharpe: {avg_sharpe:.2f}")
        print(f"     Total Profit: ${total_profit:,.0f} | Win Rate: {wins}/{len(results_by_regime[regime])}")
