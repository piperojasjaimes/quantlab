"""Backtest standalone bot — $500 account, no FTMO limits."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester
from core.backtest.data_cache import data_cache
from datetime import datetime, timedelta

# Standalone bot params — NO FTMO LIMITS
BOT_PARAMS = {
    "initial_balance": 500.0,
    "risk_per_trade_pct": 1.5,
    "max_daily_loss_pct": 999,    # NO LIMIT
    "max_total_loss_pct": 999,    # NO LIMIT
    "target_ratio": 4.0,          # R:R 1:4
    "trailing_atr_mult": 0.8,
    "partial_profit_pct": 0.6,
    "sl_atr_multiplier": 1.2,
    "ema_fast": 13,
    "ema_slow": 40,
    "ema_period_h1": 50,
    "regime_period": 20,
    "min_efficiency": 0.06,
    "min_volume_ratio": 10,
    "max_spread_pips": 40,
    "max_trade_duration": 180,
    "max_positions": 3,
    "max_daily_trades": 20,
    "consecutive_loss_limit": 5,
    "ticks_per_bar": 1,
    "spread_pips": 15,
    "commission_per_lot": 3.5,
    "swap_long": -2.5,
    "swap_short": -0.5,
    "lot_size": 0.01,
    "london_start": 3, "london_end": 12,
    "ny_start": 13, "ny_end": 21,
    "asia_start": 0, "asia_end": 3,
    "kill_switch_start": 22, "kill_switch_end": 1,
}


def simulate_compounding(balance, trades, equity_curve):
    """Simulate compounding effect on $500 account."""
    compound_thresholds = [500, 600, 700, 800, 1000, 1500, 2000, 3000, 5000, 10000]
    current_risk = 1.5
    results = []

    for trade in trades:
        balance += trade["profit"]
        equity_curve.append(balance)

        # Update risk based on balance
        for threshold in compound_thresholds:
            if balance >= threshold:
                current_risk = min(3.0, 1.5 + (threshold - 500) * 0.001)

        results.append({
            "balance": round(balance, 2),
            "risk_pct": round(current_risk, 2),
        })

    return results


def main():
    print("=" * 70)
    print("  Quant_XAUUSD_Alpha_StandAlone v1.0 — $500 Account")
    print("=" * 70)
    print(f"  Balance: ${BOT_PARAMS['initial_balance']:,.0f}")
    print(f"  Risk: {BOT_PARAMS['risk_per_trade_pct']}% (compounding)")
    print(f"  R:R: {BOT_PARAMS['target_ratio']}")
    print(f"  Max Positions: {BOT_PARAMS['max_positions']}")
    print(f"  Max Daily Trades: {BOT_PARAMS['max_daily_trades']}")
    print()

    # Test on full 2 years
    data = np.load("data/market/XAUUSD_M1.npz")["data"]
    print(f"Testing on {len(data):,} M1 bars (2 years)")
    print("-" * 70)

    start = time.time()
    tester = MT5StrategyTester(BOT_PARAMS)
    result = tester.run("XAUUSD", data)
    elapsed = time.time() - start

    m = result["metrics"]
    print(f"\n  Time: {elapsed:.1f}s")
    print(f"  Trades: {m['total_trades']}")
    print(f"  Win Rate: {m['win_rate']}%")
    print(f"  Profit Factor: {m['profit_factor']}")
    print(f"  Sharpe Ratio: {m['sharpe_ratio']}")
    print(f"  Sortino Ratio: {m['sortino_ratio']}")
    print(f"  Max Drawdown: ${m['max_drawdown']:,.0f} ({m['max_drawdown_pct']}%)")
    print(f"  Net Profit: ${m['net_profit']:,.0f}")
    print(f"  Final Balance: ${m['net_profit'] + 500:,.0f}")
    print(f"  Total Swaps: ${m['total_swaps']:,.0f}")
    print(f"  Total Commission: ${m['total_commission']:,.0f}")
    print(f"  Avg Trade: ${m['avg_trade']:,.0f}")
    print(f"  Avg Win: ${m['avg_win']:,.0f}")
    print(f"  Avg Loss: ${m['avg_loss']:,.0f}")
    print(f"  Recovery Factor: {m['recovery_factor']}")
    print(f"  Expectancy: ${m['expectancy']:,.0f}")

    # Compounding simulation
    if result["trades"]:
        print("\n  Compounding Effect:")
        balance = 500.0
        milestones = [500, 1000, 2000, 5000, 10000]
        for i, trade in enumerate(result["trades"]):
            balance += trade["profit"]
            if balance >= milestones[0] if milestones else False:
                print(f"    Trade #{i+1}: Balance ${balance:,.0f} ({milestones[0]})")
                milestones.pop(0)
                if not milestones:
                    break

    # Best trades
    if result["trades"]:
        sorted_trades = sorted(result["trades"], key=lambda x: x["profit"], reverse=True)
        print("\n  Top 5 Trades:")
        for t in sorted_trades[:5]:
            print(f"    {t['type']:4s} {t['open_time'][:16]} P/L ${t['profit']:>8,.0f} "
                  f"{t['pips']:>5.0f}p {t['exit_reason']}")

    # Monthly breakdown
    if result["trades"]:
        monthly = {}
        for t in result["trades"]:
            month = t["open_time"][:7]
            if month not in monthly:
                monthly[month] = {"trades": 0, "profit": 0, "wins": 0}
            monthly[month]["trades"] += 1
            monthly[month]["profit"] += t["profit"]
            if t["profit"] > 0:
                monthly[month]["wins"] += 1

        print("\n  Monthly Breakdown:")
        for month in sorted(monthly.keys()):
            d = monthly[month]
            wr = d["wins"] / max(d["trades"], 1) * 100
            print(f"    {month}: {d['trades']:>3d} trades | WR {wr:5.1f}% | P/L ${d['profit']:>8,.0f}")


if __name__ == "__main__":
    main()
