"""Optuna optimization of EA v4.5 parameters using full Strategy Tester."""
import sys, asyncio, json
sys.path.insert(0, '.')
from core.mt5.connector import mt5_connector
from core.backtest.engine import StrategyTester
from core.ftmo.compliance import ftmo_checker
from datetime import datetime, timedelta
from database.connection import get_connection

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("Optuna not installed. Run: pip install optuna")
    sys.exit(1)


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


def fetch_data():
    """Fetch M1 data for XAUUSD."""
    mt5_connector.connect()
    windows = get_2week_windows()[:8]
    data = {}
    for w in windows:
        rates = mt5_connector.get_rates_range("XAUUSD", "M1", w["start"], w["end"])
        if rates is not None and len(rates) > 500:
            data[f"{w['start']}_{w['end']}"] = rates
    return data


def objective(trial, data):
    """Optuna objective function."""
    params = {
        "initial_balance": 100000.0,
        "risk_per_trade_pct": trial.suggest_float("risk_per_trade_pct", 0.3, 2.0, step=0.1),
        "max_daily_loss_pct": 4.0,
        "max_total_loss_pct": 10.0,
        "target_ratio": trial.suggest_float("target_ratio", 1.5, 5.0, step=0.5),
        "trailing_atr_mult": trial.suggest_float("trailing_atr_mult", 0.5, 3.0, step=0.25),
        "partial_profit_pct": trial.suggest_float("partial_profit_pct", 0.3, 0.8, step=0.1),
        "sl_atr_multiplier": trial.suggest_float("sl_atr_multiplier", 0.5, 2.5, step=0.25),
        "ema_fast": trial.suggest_int("ema_fast", 5, 20),
        "ema_slow": trial.suggest_int("ema_slow", 20, 60),
        "regime_period": trial.suggest_int("regime_period", 10, 30),
        "min_efficiency": trial.suggest_float("min_efficiency", 0.03, 0.15, step=0.01),
        "min_volume_ratio": trial.suggest_int("min_volume_ratio", 5, 30),
        "max_spread_pips": trial.suggest_int("max_spread_pips", 15, 50),
        "max_trade_duration": trial.suggest_int("max_trade_duration", 30, 240, step=30),
        "spread_pips": 15,
        "slippage_pips": 2,
        "lot_size": 0.07,
    }

    total_sharpe = 0
    total_profit = 0
    total_trades = 0
    windows_tested = 0

    for key, rates in data.items():
        try:
            tester = StrategyTester(params)
            result = tester.run("XAUUSD", "M1", rates)
            if "error" in result or not result.get("trades"):
                continue

            m = result["metrics"]
            if m["total_trades"] < 10:
                continue

            # FTMO compliance
            compliance = ftmo_checker.check(m, m["equity_curve"])

            # Score: weighted combination
            score = 0
            score += min(m["sharpe_ratio"], 5) * 20  # Sharpe (capped at 5)
            score += min(m["profit_factor"], 3) * 15  # PF (capped at 3)
            score -= m["max_drawdown_pct"] * 3  # Penalize DD
            score += (1 if m["net_profit"] > 0 else -2) * 10  # Profit bonus
            score += compliance["ftmo_score"] * 0.3  # FTMO score

            total_sharpe += m["sharpe_ratio"]
            total_profit += m["net_profit"]
            total_trades += m["total_trades"]
            windows_tested += 1
        except Exception:
            continue

    if windows_tested == 0:
        return -1000

    avg_sharpe = total_sharpe / windows_tested
    avg_profit = total_profit / windows_tested

    # Final score
    final_score = avg_sharpe * 20 + avg_profit / 1000
    return final_score


def main():
    print("=" * 70)
    print("  Optuna Optimization — EA v4.5 Parameters")
    print("=" * 70)

    print("\nFetching M1 data from MT5...")
    data = fetch_data()
    print(f"Loaded {len(data)} windows of data")

    if not data:
        print("No data available!")
        return

    n_trials = 50
    print(f"\nRunning {n_trials} optimization trials...")
    print("-" * 70)

    study = optuna.create_study(direction="maximize", study_name="ea_v45_optimization")
    study.optimize(lambda trial: objective(trial, data), n_trials=n_trials, show_progress_bar=True)

    # Results
    best = study.best_trial
    print("\n" + "=" * 70)
    print("  OPTIMIZATION RESULTS")
    print("=" * 70)
    print(f"\nBest trial: #{best.number}")
    print(f"Best score: {best.value:.2f}")
    print(f"\nBest parameters:")
    for k, v in best.params.items():
        print(f"  {k}: {v}")

    # Run best params on all windows
    print("\n" + "=" * 70)
    print("  VALIDATION WITH BEST PARAMS")
    print("=" * 70)

    best_params = {
        "initial_balance": 100000.0,
        **best.params,
        "max_daily_loss_pct": 4.0,
        "max_total_loss_pct": 10.0,
        "spread_pips": 15,
        "slippage_pips": 2,
        "lot_size": 0.07,
    }

    for key, rates in data.items():
        try:
            tester = StrategyTester(best_params)
            result = tester.run("XAUUSD", "M1", rates)
            if "error" in result or not result.get("trades"):
                print(f"  {key}: No trades")
                continue

            m = result["metrics"]
            compliance = ftmo_checker.check(m, m["equity_curve"])
            print(f"  {key}: Trades={m['total_trades']} "
                  f"Win={m['win_rate']:.1f}% PF={m['profit_factor']:.2f} "
                  f"Sharpe={m['sharpe_ratio']:.2f} DD={m['max_drawdown_pct']:.1f}% "
                  f"Net=${m['net_profit']:,.0f} "
                  f"FTMO={'PASS' if compliance['passed'] else 'FAIL'} "
                  f"Score={compliance['ftmo_score']:.1f}")
        except Exception as e:
            print(f"  {key}: Error: {e}")

    # Save results
    try:
        asyncio.run(save_results(best_params, study))
    except Exception as e:
        print(f"\nDB save error: {e}")

    # Save params to file
    output = {
        "best_params": best_params,
        "best_score": best.value,
        "best_trial": best.number,
        "all_trials": len(study.trials),
    }
    with open("results/optimization_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to results/optimization_results.json")


async def save_results(params, study):
    conn = await get_connection()
    now = datetime.now().isoformat()

    # Save strategy
    await conn.execute(
        """INSERT OR REPLACE INTO strategies
           (id, name, version, parent_id, pattern, timeframe, symbol,
            params, code_path, created_at, generation, depth, fitness, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("alpha_v4.5_opt", "Quant_XAUUSD_Alpha_Ultimate_v4.5_Optimized", 5, "alpha_v4.5",
         "trend_following", "M1", "XAUUSD",
         json.dumps(params), "", now, 1, 0, study.best_value, 1))
    await conn.commit()
    print("Optimized strategy saved to database")


if __name__ == "__main__":
    main()
