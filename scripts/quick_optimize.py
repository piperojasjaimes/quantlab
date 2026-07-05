"""Quick Optuna optimization — 30 trials."""
import sys
sys.path.insert(0, '.')
import optuna
from core.mt5.connector import mt5_connector
from core.backtest.engine import StrategyTester
from core.ftmo.compliance import ftmo_checker
from datetime import datetime, timedelta

optuna.logging.set_verbosity(optuna.logging.WARNING)
mt5_connector.connect()

# Fetch data
windows = []
end = datetime.now()
for _ in range(6):
    win_start = end - timedelta(days=14)
    windows.append({"start": win_start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")})
    end = win_start

data = {}
for w in windows:
    rates = mt5_connector.get_rates_range("XAUUSD", "M1", w["start"], w["end"])
    if rates is not None and len(rates) > 500:
        data[f"{w['start']}_{w['end']}"] = rates

print(f"Data: {len(data)} windows")


def objective(trial):
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
    total_score = 0
    cnt = 0
    for key, rates in data.items():
        try:
            tester = StrategyTester(params)
            result = tester.run("XAUUSD", "M1", rates)
            if "error" in result or not result.get("trades"):
                continue
            m = result["metrics"]
            if m["total_trades"] < 10:
                continue
            compliance = ftmo_checker.check(m, m["equity_curve"])
            score = min(m["sharpe_ratio"], 5) * 20 + min(m["profit_factor"], 3) * 15
            score -= m["max_drawdown_pct"] * 3
            score += (1 if m["net_profit"] > 0 else -2) * 10
            score += compliance["ftmo_score"] * 0.3
            total_score += score
            cnt += 1
        except Exception:
            continue
    return total_score / max(cnt, 1)


study = optuna.create_study(direction="maximize", study_name="ea_v45_quick")
study.optimize(objective, n_trials=30, show_progress_bar=False)

best = study.best_trial
print(f"\nBest score: {best.value:.2f}")
print(f"Best params:")
for k, v in best.params.items():
    print(f"  {k}: {v}")

# Validate
best_params = {
    "initial_balance": 100000.0,
    **best.params,
    "max_daily_loss_pct": 4.0,
    "max_total_loss_pct": 10.0,
    "spread_pips": 15,
    "slippage_pips": 2,
    "lot_size": 0.07,
}
print("\nValidation:")
for key, rates in data.items():
    tester = StrategyTester(best_params)
    result = tester.run("XAUUSD", "M1", rates)
    if "error" in result or not result.get("trades"):
        print(f"  {key}: No trades")
        continue
    m = result["metrics"]
    c = ftmo_checker.check(m, m["equity_curve"])
    print(f"  {key}: T={m['total_trades']} WR={m['win_rate']:.1f}% "
          f"PF={m['profit_factor']:.2f} Sharpe={m['sharpe_ratio']:.2f} "
          f"DD={m['max_drawdown_pct']:.1f}% Net=${m['net_profit']:,.0f} "
          f"FTMO={'PASS' if c['passed'] else 'FAIL'} Score={c['ftmo_score']:.1f}")
