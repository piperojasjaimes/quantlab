"""Test FTMO compliance with exact rules."""
import sys, random
sys.path.insert(0, '.')
from core.ftmo.compliance import ftmo_checker

print("=== FTMO Challenge 1-Step Rules ===")
print(f"Account Size: ${ftmo_checker.initial_capital:,.0f}")
print(f"Profit Target: {ftmo_checker.profit_target_pct:.0%} = ${ftmo_checker.profit_target:,.0f}")
print(f"Balance to Pass: ${ftmo_checker.balance_to_pass:,.0f}")
print(f"Max Daily Loss: {ftmo_checker.max_daily_loss_pct:.0%} = ${ftmo_checker.max_daily_loss_amount:,.0f}")
print(f"Max Loss (trailing): {ftmo_checker.max_loss_pct:.0%} = ${ftmo_checker.max_loss_amount:,.0f}")
print(f"Best Day Rule: {ftmo_checker.best_day_rule_pct:.0%}")
print()

# Simulate 14 days
daily_bars = []
balance = 100000.0
for i in range(14):
    open_eq = balance
    daily_pnl = random.gauss(800, 1500)
    close_eq = balance + daily_pnl
    low_eq = min(open_eq, close_eq) - abs(random.gauss(0, 500))
    daily_bars.append({
        "date": f"2026-06-{i+1:02d}",
        "open_equity": open_eq,
        "close_equity": close_eq,
        "low_equity": low_eq,
    })
    balance = close_eq

final_profit = balance - 100000
metrics = {
    "net_profit": final_profit,
    "max_drawdown": abs(min(d["low_equity"] for d in daily_bars) - 100000),
    "max_drawdown_pct": abs(min(d["low_equity"] for d in daily_bars) - 100000) / 100000 * 100,
    "profit_factor": 1.5,
    "win_rate": 55,
    "sharpe_ratio": 1.2,
    "total_trades": 50,
}

result = ftmo_checker.check(metrics, daily_bars=daily_bars)
print(f"Passed: {result['passed']}")
print(f"FTMO Score: {result['ftmo_score']}")
for v in result["violations"]:
    print(f"  VIOLATION: {v}")
for w in result["warnings"]:
    print(f"  WARNING: {w}")
print()
for k, v in result["details"].items():
    print(f"{k}: {v}")
