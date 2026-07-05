"""Aggressive optimization — find parameters that turn $500 into max returns."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
from core.backtest.mt5_engine import MT5StrategyTester
from core.backtest.data_cache import data_cache

# Aggressive parameter grid
AGGRESSIVE_GRID = {
    "risk_per_trade": [5, 8, 10, 12, 15, 20],
    "target_ratio": [2, 3, 4, 5, 6, 8],
    "sl_mult": [0.5, 0.8, 1.0, 1.2, 1.5],
    "trail_mult": [0.3, 0.5, 0.8, 1.0],
    "ema_fast": [8, 10, 13, 15],
    "ema_slow": [26, 34, 40, 50],
    "max_positions": [1, 2, 3, 5],
    "max_daily_trades": [10, 20, 50],
}


def run_backtest(data, params):
    tester = MT5StrategyTester(params)
    result = tester.run("XAUUSD", data)
    if "error" in result or not result.get("trades"):
        return None
    return result["metrics"]


def main():
    print("=" * 70)
    print("  AGGRESSIVE OPTIMIZATION — $500 to Maximize Returns")
    print("=" * 70)

    data = np.load("data/market/XAUUSD_M1.npz")["data"]
    print(f"Data: {len(data):,} M1 bars")

    best_return = 0
    best_params = None
    best_metrics = None
    tested = 0

    # Grid search with aggressive params
    for risk in AGGRESSIVE_GRID["risk_per_trade"]:
        for rr in AGGRESSIVE_GRID["target_ratio"]:
            for sl_m in AGGRESSIVE_GRID["sl_mult"]:
                for trail_m in AGGRESSIVE_GRID["trail_mult"]:
                    for ema_f in AGGRESSIVE_GRID["ema_fast"]:
                        for ema_s in AGGRESSIVE_GRID["ema_slow"]:
                            if ema_f >= ema_s:
                                continue
                            for max_pos in AGGRESSIVE_GRID["max_positions"]:
                                for max_daily in AGGRESSIVE_GRID["max_daily_trades"]:
                                    params = {
                                        "initial_balance": 500.0,
                                        "risk_per_trade_pct": risk,
                                        "max_daily_loss_pct": 999,
                                        "max_total_loss_pct": 999,
                                        "target_ratio": rr,
                                        "trailing_atr_mult": trail_m,
                                        "partial_profit_pct": 0.5,
                                        "sl_atr_multiplier": sl_m,
                                        "ema_fast": ema_f,
                                        "ema_slow": ema_s,
                                        "ema_period_h1": 50,
                                        "regime_period": 20,
                                        "min_efficiency": 0.05,
                                        "min_volume_ratio": 5,
                                        "max_spread_pips": 50,
                                        "max_trade_duration": 240,
                                        "max_positions": max_pos,
                                        "max_daily_trades": max_daily,
                                        "consecutive_loss_limit": 10,
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

                                    metrics = run_backtest(data, params)
                                    tested += 1

                                    if metrics and metrics["total_trades"] >= 20:
                                        final = metrics["net_profit"] + 500
                                        ret_pct = (final / 500 - 1) * 100

                                        if final > best_return:
                                            best_return = final
                                            best_params = params.copy()
                                            best_metrics = metrics.copy()
                                            print(f"  #{tested:>5d} Risk={risk}% RR={rr} SL={sl_m} "
                                                  f"Trail={trail_m} EMA={ema_f}/{ema_s} "
                                                  f"Pos={max_pos} Daily={max_daily} "
                                                  f"| Return=${final:,.0f} ({ret_pct:.0f}%) "
                                                  f"WR={metrics['win_rate']:.1f}% PF={metrics['profit_factor']:.2f} "
                                                  f"DD={metrics['max_drawdown_pct']:.1f}%")

                                    if tested % 500 == 0:
                                        print(f"  ... {tested} tested, best: ${best_return:,.0f}")

    # Results
    print("\n" + "=" * 70)
    print("  BEST PARAMETERS FOUND")
    print("=" * 70)
    if best_metrics:
        m = best_metrics
        print(f"  Return: ${best_return:,.0f} ({(best_return/500-1)*100:.0f}%)")
        print(f"  Trades: {m['total_trades']}")
        print(f"  Win Rate: {m['win_rate']}%")
        print(f"  Profit Factor: {m['profit_factor']}")
        print(f"  Sharpe: {m['sharpe_ratio']}")
        print(f"  Max DD: {m['max_drawdown_pct']}%")
        print(f"  Commissions: ${m['total_commission']:,.0f}")
        print(f"\n  Parameters:")
        for k, v in best_params.items():
            if k not in ["london_start", "london_end", "ny_start", "ny_end", "asia_start", "asia_end", "kill_switch_start", "kill_switch_end"]:
                print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
