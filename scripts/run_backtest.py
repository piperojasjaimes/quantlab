"""Run backtest with Quant_XAUUSD_Alpha_Ultimate v4.5 using full Strategy Tester."""
import sys, asyncio, json
sys.path.insert(0, '.')
from core.mt5.connector import mt5_connector
from core.backtest.engine import StrategyTester
from core.ftmo.compliance import ftmo_checker
from datetime import datetime, timedelta
from database.connection import get_connection

# Exact EA parameters
EA_PARAMS = {
    "initial_balance": 100000.0,
    "risk_per_trade_pct": 0.7,
    "max_daily_loss_pct": 4.0,
    "max_total_loss_pct": 10.0,
    "target_profit_pct": 10.0,
    "target_ratio": 3.0,
    "trailing_atr_mult": 1.5,
    "partial_profit_pct": 0.50,
    "sl_atr_multiplier": 1.2,
    "regime_period": 20,
    "min_efficiency": 0.08,
    "min_volume_ratio": 15,
    "max_spread_pips": 30,
    "consecutive_loss_limit": 3,
    "ema_fast": 12,
    "ema_slow": 26,
    "ema_period_h1": 50,
    "min_ma_alignment": 10,
    "m5_trend_bars": 5,
    "max_trade_duration": 120,
    "spread_pips": 15,
    "slippage_pips": 2,
    "lot_size": 0.07,
}


def get_2week_windows():
    windows = []
    end = datetime.now()
    start_limit = end - timedelta(days=365)
    while end > start_limit:
        win_start = end - timedelta(days=14)
        windows.append({
            "start": win_start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
        })
        end = win_start
    return windows


async def main():
    mt5_connector.connect()
    print("=" * 70)
    print("  Quant_XAUUSD_Alpha_Ultimate v4.5 — Full Strategy Tester")
    print("=" * 70)
    print(f"  Symbol: XAUUSD | TF: M1 | Account: ${EA_PARAMS['initial_balance']:,.0f}")
    print(f"  Risk: {EA_PARAMS['risk_per_trade_pct']}% | R:R: {EA_PARAMS['target_ratio']}")
    print(f"  SL: ATR x{EA_PARAMS['sl_atr_multiplier']} | Trail: ATR x{EA_PARAMS['trailing_atr_mult']}")
    print(f"  Spread: {EA_PARAMS['spread_pips']}p | Slippage: {EA_PARAMS['slippage_pips']}p")
    print(f"  Max Daily Loss: {EA_PARAMS['max_daily_loss_pct']}% | Max Total: {EA_PARAMS['max_total_loss_pct']}%")
    print(f"  Max Duration: {EA_PARAMS['max_trade_duration']}min")
    print()

    windows = get_2week_windows()[:15]
    print(f"Testing {len(windows)} windows of 2 weeks each")
    print("-" * 70)

    all_results = []
    for w in windows:
        rates = mt5_connector.get_rates_range("XAUUSD", "M1", w["start"], w["end"])
        if rates is None or len(rates) < 500:
            print(f"  {w['start']}->{w['end']}: Insufficient data ({len(rates) if rates else 0} bars)")
            continue

        tester = StrategyTester(EA_PARAMS)
        result = tester.run("XAUUSD", "M1", rates)

        if "error" in result:
            print(f"  {w['start']}->{w['end']}: {result['error']}")
            continue

        m = result["metrics"]
        compliance = ftmo_checker.check(m, m["equity_curve"])
        all_results.append((w, result, compliance))

        print(f"  {w['start']}->{w['end']}: "
              f"Trades={m['total_trades']:3d} "
              f"Win={m['win_rate']:5.1f}% "
              f"PF={m['profit_factor']:5.2f} "
              f"Sharpe={m['sharpe_ratio']:6.2f} "
              f"DD={m['max_drawdown_pct']:5.1f}% "
              f"Net=${m['net_profit']:>8,.0f} "
              f"FTMO={'PASS' if compliance['passed'] else 'FAIL'} "
              f"Score={compliance['ftmo_score']:5.1f}")

    # Summary
    if all_results:
        print("-" * 70)
        print(f"SUMMARY ({len(all_results)} windows)")
        print("-" * 70)

        avg_sharpe = sum(r[1]["metrics"]["sharpe_ratio"] for r in all_results) / len(all_results)
        avg_pf = sum(r[1]["metrics"]["profit_factor"] for r in all_results) / len(all_results)
        avg_dd = sum(r[1]["metrics"]["max_drawdown_pct"] for r in all_results) / len(all_results)
        avg_profit = sum(r[1]["metrics"]["net_profit"] for r in all_results) / len(all_results)
        avg_winrate = sum(r[1]["metrics"]["win_rate"] for r in all_results) / len(all_results)
        total_trades = sum(r[1]["metrics"]["total_trades"] for r in all_results)
        ftmo_passes = sum(1 for r in all_results if r[2]["passed"])
        best_score = max(r[2]["ftmo_score"] for r in all_results)
        best_window = max(all_results, key=lambda x: x[2]["ftmo_score"])

        print(f"  Avg Sharpe:    {avg_sharpe:.2f}")
        print(f"  Avg PF:        {avg_pf:.2f}")
        print(f"  Avg DD:        {avg_dd:.1f}%")
        print(f"  Avg Win Rate:  {avg_winrate:.1f}%")
        print(f"  Avg Net:       ${avg_profit:,.0f}")
        print(f"  Total Trades:  {total_trades}")
        print(f"  FTMO Passed:   {ftmo_passes}/{len(all_results)}")
        print(f"  Best Score:    {best_score:.1f}")
        print(f"  Best Window:   {best_window[0]['start']}->{best_window[0]['end']}")

        # Show best window trade details
        best_result = best_window[1]
        if best_result["trades"]:
            print(f"\n  Best Window Trades:")
            for t in best_result["trades"][:10]:
                print(f"    #{t['ticket']} {t['type']:4s} {t['open_time'][:16]} "
                      f"SL={t['sl']:.2f} TP={t['tp']:.2f} "
                      f"Exit={t['close_price']:.2f} ${t['profit']:>7.0f} "
                      f"{t['pips']:>5.0f}p {t['exit_reason']}")

        # Save to DB
        try:
            conn = await get_connection()
            now = datetime.now().isoformat()
            import uuid

            await conn.execute(
                """INSERT OR REPLACE INTO strategies
                   (id, name, version, parent_id, pattern, timeframe, symbol,
                    params, code_path, created_at, generation, depth, fitness, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("alpha_v4.5", "Quant_XAUUSD_Alpha_Ultimate_v4.5", 4, "",
                 "trend_following", "M1", "XAUUSD",
                 json.dumps(EA_PARAMS), "", now, 0, 0, 0, 1))
            await conn.commit()

            for w, result, compliance in all_results:
                result_id = uuid.uuid4().hex[:12]
                await conn.execute(
                    """INSERT OR REPLACE INTO backtest_results
                       (id, strategy_id, strategy_name, metrics, optimization_params,
                        walk_forward_results, monte_carlo_results, stress_test_results,
                        html_report_path, csv_path, json_path, png_path, status,
                        rejection_reasons, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (result_id, "alpha_v4.5", "Quant_XAUUSD_Alpha_Ultimate_v4.5",
                     json.dumps(result["metrics"], default=str),
                     json.dumps(EA_PARAMS),
                     json.dumps({"ftmo_score": compliance["ftmo_score"], "window": w}),
                     json.dumps({}), json.dumps({}),
                     "", "", "", "",
                     "passed" if compliance["passed"] else "failed",
                     json.dumps(compliance.get("violations", [])),
                     now))
            await conn.commit()
            print(f"\n  Results saved to database")
        except Exception as e:
            print(f"\n  DB save error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
