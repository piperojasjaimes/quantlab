"""Run backtest with MT5-equivalent Strategy Tester engine."""
import sys, asyncio, json
sys.path.insert(0, '.')
from core.backtest.mt5_engine import MT5StrategyTester
from core.backtest.data_cache import data_cache
from core.ftmo.compliance import ftmo_checker
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

# EA v4.5 optimized parameters
EA_PARAMS = {
    "initial_balance": 100000.0,
    "risk_per_trade_pct": 1.0,
    "max_daily_loss_pct": 4.0,
    "max_total_loss_pct": 10.0,
    "target_ratio": 5.0,
    "trailing_atr_mult": 0.5,
    "partial_profit_pct": 0.8,
    "sl_atr_multiplier": 1.25,
    "ema_fast": 13,
    "ema_slow": 40,
    "ema_period_h1": 50,
    "regime_period": 23,
    "min_efficiency": 0.07,
    "min_volume_ratio": 25,
    "max_spread_pips": 25,
    "max_trade_duration": 30,
    "consecutive_loss_limit": 3,
    "min_ma_alignment": 10,
    "enable_m5_filter": True,
    "m5_trend_bars": 5,
    # MT5 simulation params
    "ticks_per_bar": 1,
    "spread_pips": 15,
    "slippage_pips": 2,
    "commission_per_lot": 3.5,
    "swap_long": -2.5,
    "swap_short": -0.5,
    "lot_size": 0.07,
    # Sessions
    "london_start": 3, "london_end": 12,
    "ny_start": 13, "ny_end": 21,
    "asia_start": 0, "asia_end": 3,
    "kill_switch_start": 22, "kill_switch_end": 1,
}


def get_2week_windows():
    windows = []
    end = datetime.now()
    start_limit = end - timedelta(days=365)
    while end > start_limit:
        win_start = end - timedelta(days=14)
        windows.append({"start": win_start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")})
        end = win_start
    return windows


def load_data(symbol, start_date, end_date):
    """Load data from cache for all timeframes."""
    m1 = data_cache.get_data(symbol, "M1", start_date, end_date)
    m5 = data_cache.get_data(symbol, "M5", start_date, end_date)
    m15 = data_cache.get_data(symbol, "M15", start_date, end_date)
    h1 = data_cache.get_data(symbol, "H1", start_date, end_date)
    return m1, m5, m15, h1


async def main():
    print("=" * 70)
    print("  MT5-Equivalent Strategy Tester — XAUUSD Alpha v4.5")
    print("=" * 70)
    print(f"  Ticks/bar: {EA_PARAMS['ticks_per_bar']} | Spread: {EA_PARAMS['spread_pips']}p")
    print(f"  Commission: ${EA_PARAMS['commission_per_lot']}/lot | Swaps: L={EA_PARAMS['swap_long']} S={EA_PARAMS['swap_short']}")
    print(f"  Sessions: London {EA_PARAMS['london_start']}-{EA_PARAMS['london_end']}, NY {EA_PARAMS['ny_start']}-{EA_PARAMS['ny_end']}")
    print()

    windows = get_2week_windows()[:4]  # Reduced for speed
    print(f"Testing {len(windows)} windows with M1+M5+M15+H1 data")
    print("-" * 70)

    all_results = []
    for w in windows:
        m1, m5, m15, h1 = load_data("XAUUSD", w["start"], w["end"])
        if m1 is None or len(m1) < 500:
            print(f"  {w['start']}->{w['end']}: Insufficient M1 data")
            continue

        tester = MT5StrategyTester(EA_PARAMS)
        result = tester.run("XAUUSD", m1, m5, m15, h1)

        if "error" in result:
            print(f"  {w['start']}->{w['end']}: {result['error']}")
            continue

        m = result["metrics"]
        compliance = ftmo_checker.check(m, m["equity_curve"])
        all_results.append((w, result, compliance))

        print(f"  {w['start']}->{w['end']}: "
              f"Trades={m['total_trades']:4d} "
              f"Win={m['win_rate']:5.1f}% "
              f"PF={m['profit_factor']:5.2f} "
              f"Sharpe={m['sharpe_ratio']:6.2f} "
              f"DD={m['max_drawdown_pct']:5.1f}% "
              f"Net=${m['net_profit']:>9,.0f} "
              f"Swaps=${m['total_swaps']:>7,.0f} "
              f"Comm=${m['total_commission']:>6,.0f} "
              f"FTMO={'PASS' if compliance['passed'] else 'FAIL'} "
              f"Score={compliance['ftmo_score']:5.1f}")

    # Summary
    if all_results:
        print("-" * 70)
        print("SUMMARY")
        print("-" * 70)
        avg = lambda key: sum(r[1]["metrics"][key] for r in all_results) / len(all_results)
        total_trades = sum(r[1]["metrics"]["total_trades"] for r in all_results)
        ftmo_passes = sum(1 for r in all_results if r[2]["passed"])

        print(f"  Avg Sharpe: {avg('sharpe_ratio'):.2f} | Avg PF: {avg('profit_factor'):.2f}")
        print(f"  Avg DD: {avg('max_drawdown_pct'):.1f}% | Avg WinRate: {avg('win_rate'):.1f}%")
        print(f"  Avg Net: ${avg('net_profit'):,.0f} | Total Swaps: ${sum(r[1]['metrics']['total_swaps'] for r in all_results):,.0f}")
        print(f"  Total Trades: {total_trades} | FTMO Passed: {ftmo_passes}/{len(all_results)}")
        print(f"  Best Score: {max(r[2]['ftmo_score'] for r in all_results):.1f}")

        # Save to DB
        from database.connection import get_connection
        conn = await get_connection()
        now = datetime.now().isoformat()
        import uuid
        for w, result, compliance in all_results:
            rid = uuid.uuid4().hex[:12]
            await conn.execute(
                """INSERT OR REPLACE INTO backtest_results
                   (id, strategy_id, strategy_name, metrics, optimization_params,
                    walk_forward_results, monte_carlo_results, stress_test_results,
                    html_report_path, csv_path, json_path, png_path, status,
                    rejection_reasons, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (rid, "alpha_v4.5_mt5", "Quant_XAUUSD_Alpha_Ultimate_v4.5_MT5",
                 json.dumps(result["metrics"], default=str), json.dumps(EA_PARAMS),
                 json.dumps({"ftmo_score": compliance["ftmo_score"], "window": w}),
                 json.dumps({}), json.dumps({}), "", "", "", "",
                 "passed" if compliance["passed"] else "failed",
                 json.dumps(compliance.get("violations", [])), now))
        await conn.commit()
        print("  Results saved to database")


if __name__ == "__main__":
    asyncio.run(main())
