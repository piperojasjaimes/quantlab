"""Run backtest with Quant_XAUUSD_Alpha_Ultimate v4.5 exact parameters."""
import sys, asyncio, json
sys.path.insert(0, '.')
from core.mt5.connector import mt5_connector
from core.ftmo.compliance import ftmo_checker
from datetime import datetime, timedelta
from database.connection import get_connection

# Exact parameters from the EA spec
EA_PARAMS = {
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
    "ema_period_h1": 50,
    "min_ma_alignment": 10,
    "m5_trend_bars": 5,
    "london_start": 3, "london_end": 12,
    "ny_start": 13, "ny_end": 21,
    "asia_start": 0, "asia_end": 3,
    "friday_close_hour": 21,
    "news_block_min": 1,
    "kill_switch_start": 22, "kill_switch_end": 1,
    "lot_size": 0.07,  # 0.7% risk on $100k with SL ~100 pips
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


def simulate_ea_backtest(closes, highs, lows, volumes, params):
    """Simulate the EA logic on historical data."""
    initial_balance = 100000.0
    balance = initial_balance
    equity_curve = [balance]
    trades = []
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    entry_time = 0
    daily_start = initial_balance
    consecutive_losses = 0
    max_daily_loss = initial_balance * params["max_daily_loss_pct"] / 100
    max_total_loss = initial_balance * params["max_total_loss_pct"] / 100

    # Calculate EMAs
    ema_fast = []
    ema_slow = []
    ema_h1 = []
    atr_values = []

    period = params["regime_period"]
    for i in range(len(closes)):
        if i < period:
            ema_fast.append(closes[i])
            ema_slow.append(closes[i])
            ema_h1.append(closes[i])
            atr_values.append(0)
            continue

        # EMA fast (M15 equivalent ~15 periods)
        alpha = 2.0 / 16
        ema_f = alpha * closes[i] + (1 - alpha) * ema_fast[-1]
        ema_fast.append(ema_f)

        # EMA slow (M15 equivalent ~50 periods)
        alpha_s = 2.0 / 51
        ema_s = alpha_s * closes[i] + (1 - alpha_s) * ema_slow[-1]
        ema_slow.append(ema_s)

        # EMA H1 (50 period equivalent)
        alpha_h = 2.0 / 51
        ema_h = alpha_h * closes[i] + (1 - alpha_h) * ema_h1[-1]
        ema_h1.append(ema_h)

        # ATR
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        alpha_a = 2.0 / (period + 1)
        atr = alpha_a * tr + (1 - alpha_a) * atr_values[-1] if atr_values[-1] > 0 else tr
        atr_values.append(atr)

    # Simulate
    for i in range(period + 50, len(closes)):
        price = closes[i]

        # Daily reset (assume 390 bars per day for M1)
        if i > 0 and i % 390 == 0:
            daily_start = balance

        # Drawdown checks
        daily_dd = daily_start - balance
        total_dd = initial_balance - balance
        if daily_dd >= max_daily_loss or total_dd >= max_total_loss:
            if position != 0:
                pnl = (price - entry_price) * position * params["lot_size"] * 100
                balance += pnl
                trades.append(pnl)
                position = 0
            equity_curve.append(balance)
            continue

        # Manage open position
        if position == 1:  # Long
            trailing_sl = price - atr_values[i] * params["trailing_atr_mult"]
            if trailing_sl > sl_price and trailing_sl > entry_price:
                sl_price = trailing_sl

            # Partial profit
            partial_price = entry_price + (tp_price - entry_price) * params["partial_profit_pct"]
            if price >= partial_price and sl_price < entry_price:
                sl_price = entry_price

            if price <= sl_price or price >= tp_price:
                pnl = (price - entry_price) * params["lot_size"] * 100
                balance += pnl
                trades.append(pnl)
                if pnl < 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                position = 0

        elif position == -1:  # Short
            trailing_sl = price + atr_values[i] * params["trailing_atr_mult"]
            if trailing_sl < sl_price and trailing_sl < entry_price:
                sl_price = trailing_sl

            partial_price = entry_price - abs(tp_price - entry_price) * params["partial_profit_pct"]
            if price <= partial_price and sl_price > entry_price:
                sl_price = entry_price

            if price >= sl_price or price <= tp_price:
                pnl = (entry_price - price) * params["lot_size"] * 100
                balance += pnl
                trades.append(pnl)
                if pnl < 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                position = 0

        equity_curve.append(balance)

        # Entry logic
        if position == 0:
            if consecutive_losses >= params["consecutive_loss_limit"]:
                continue

            # HTF bias (EMA H1)
            htf_bias = 0
            if price > ema_h1[i] + params["min_ma_alignment"] * 0.0001 * 10:
                htf_bias = 1
            elif price < ema_h1[i] - params["min_ma_alignment"] * 0.0001 * 10:
                htf_bias = -1

            if htf_bias == 0:
                continue

            # Efficiency
            net_change = abs(closes[i] - closes[i - period])
            sum_vol = sum(abs(closes[j] - closes[j+1]) for j in range(i - period, i))
            if sum_vol == 0:
                continue
            efficiency = net_change / sum_vol
            if efficiency < params["min_efficiency"]:
                continue

            # Volume check
            if volumes[i] < params["min_volume_ratio"]:
                continue

            # M5 confirmation
            bullish = sum(1 for j in range(params["m5_trend_bars"])
                         if closes[i-j] > closes[i-j-1])
            if htf_bias == 1 and bullish < params["m5_trend_bars"] // 2:
                continue
            if htf_bias == -1 and bullish >= params["m5_trend_bars"] // 2:
                continue

            # Entry
            sl_pips = max(20, min(atr_values[i] * params["sl_atr_multiplier"],
                                  min(atr_values[i] * 3, 60)))
            tp_pips = sl_pips * params["target_ratio"]

            if htf_bias == 1:
                position = 1
                entry_price = price
                sl_price = price - sl_pips * 0.01
                tp_price = price + tp_pips * 0.01
            else:
                position = -1
                entry_price = price
                sl_price = price + sl_pips * 0.01
                tp_price = price - tp_pips * 0.01

    # Close any remaining position
    if position != 0:
        pnl = (closes[-1] - entry_price) * position * params["lot_size"] * 100
        balance += pnl
        trades.append(pnl)

    # Calculate metrics
    if not trades:
        return None

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    total = len(trades)
    win_rate = len(wins) / total * 100
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_profit = gross_profit - gross_loss
    peak = max(equity_curve)
    trough = min(equity_curve)
    max_dd = peak - trough
    max_dd_pct = max_dd / max(peak, 1) * 100

    import numpy as np
    eq_arr = np.array(equity_curve)
    returns = np.diff(eq_arr) / np.maximum(eq_arr[:-1], 1)
    sharpe = float(np.mean(returns) / max(np.std(returns), 1e-8) * np.sqrt(252 * 390)) if len(returns) > 1 else 0
    neg_returns = returns[returns < 0]
    sortino = float(np.mean(returns) / max(np.std(neg_returns), 1e-8) * np.sqrt(252 * 390)) if len(neg_returns) > 0 else sharpe

    metrics = {
        "total_trades": total,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(gross_profit / max(gross_loss, 1), 2),
        "net_profit": round(net_profit, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "avg_trade": round(net_profit / total, 2),
        "avg_win": round(gross_profit / max(len(wins), 1), 2),
        "avg_loss": round(gross_loss / max(len(losses), 1), 2),
        "equity_curve": [round(e, 2) for e in equity_curve],
    }

    return {"metrics": metrics, "trades": trades, "equity_curve": equity_curve}


async def main():
    mt5_connector.connect()
    print("=== Quant_XAUUSD_Alpha_Ultimate v4.5 Backtest ===")
    print(f"Symbol: XAUUSD | Timeframe: M1 | Account: $100,000")
    print(f"Risk: {EA_PARAMS['risk_per_trade_pct']}% | R:R: {EA_PARAMS['target_ratio']}")
    print(f"Max Daily Loss: {EA_PARAMS['max_daily_loss_pct']}% | Max Total: {EA_PARAMS['max_total_loss_pct']}%")
    print()

    windows = get_2week_windows()[:13]  # Last ~6 months
    print(f"Testing {len(windows)} windows of 2 weeks each\n")

    all_results = []
    for w in windows:
        rates = mt5_connector.get_rates_range("XAUUSD", "M1", w["start"], w["end"])
        if rates is None or len(rates) < 500:
            print(f"  {w['start']}->{w['end']}: Insufficient data ({len(rates) if rates else 0} bars)")
            continue

        import numpy as np
        closes = np.array([r[4] for r in rates])
        highs = np.array([r[2] for r in rates])
        lows = np.array([r[3] for r in rates])
        volumes = np.array([r[5] for r in rates])

        result = simulate_ea_backtest(closes, highs, lows, volumes, EA_PARAMS)
        if result is None:
            print(f"  {w['start']}->{w['end']}: No trades")
            continue

        m = result["metrics"]
        compliance = ftmo_checker.check(m, m["equity_curve"])
        all_results.append((w, result, compliance))

        print(f"  {w['start']}->{w['end']}: "
              f"Trades={m['total_trades']} "
              f"WinRate={m['win_rate']:.1f}% "
              f"PF={m['profit_factor']:.2f} "
              f"Sharpe={m['sharpe_ratio']:.2f} "
              f"DD={m['max_drawdown_pct']:.1f}% "
              f"Net=${m['net_profit']:,.0f} "
              f"FTMO={'PASS' if compliance['passed'] else 'FAIL'} "
              f"Score={compliance['ftmo_score']:.1f}")

    # Summary
    if all_results:
        print(f"\n{'='*60}")
        print(f"SUMMARY ({len(all_results)} windows)")
        print(f"{'='*60}")

        avg_sharpe = sum(r[1]["metrics"]["sharpe_ratio"] for r in all_results) / len(all_results)
        avg_pf = sum(r[1]["metrics"]["profit_factor"] for r in all_results) / len(all_results)
        avg_dd = sum(r[1]["metrics"]["max_drawdown_pct"] for r in all_results) / len(all_results)
        avg_profit = sum(r[1]["metrics"]["net_profit"] for r in all_results) / len(all_results)
        avg_winrate = sum(r[1]["metrics"]["win_rate"] for r in all_results) / len(all_results)
        total_trades = sum(r[1]["metrics"]["total_trades"] for r in all_results)
        ftmo_passes = sum(1 for r in all_results if r[2]["passed"])

        print(f"  Avg Sharpe: {avg_sharpe:.2f}")
        print(f"  Avg PF: {avg_pf:.2f}")
        print(f"  Avg DD: {avg_dd:.1f}%")
        print(f"  Avg Win Rate: {avg_winrate:.1f}%")
        print(f"  Avg Net Profit: ${avg_profit:,.0f}")
        print(f"  Total Trades: {total_trades}")
        print(f"  FTMO Passed: {ftmo_passes}/{len(all_results)} windows")
        print(f"  Best FTMO Score: {max(r[2]['ftmo_score'] for r in all_results):.1f}")

        # Save to DB
        conn = await get_connection()
        from datetime import datetime as dt
        now = dt.now().isoformat()
        import uuid

        # First insert strategy
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
                 json.dumps({"ftmo_score": compliance["ftmo_score"]}),
                 json.dumps({}), json.dumps({}),
                 "", "", "", "",
                 "passed" if compliance["passed"] else "failed",
                 json.dumps(compliance.get("violations", [])),
                 now))
        await conn.commit()
        print(f"\nResults saved to database")


if __name__ == "__main__":
    asyncio.run(main())
