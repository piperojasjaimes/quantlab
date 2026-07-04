"""Test FTMO compliance and XAUUSD backtest."""
import sys, asyncio
sys.path.insert(0, '.')
from core.mt5.connector import mt5_connector
from core.ftmo.compliance import ftmo_checker
from core.pipeline.auto_loop import AutoOptimizationLoop

async def test():
    mt5_connector.connect()
    loop = AutoOptimizationLoop()

    # Test 1: FTMO compliance checker
    print("=== FTMO Compliance Test ===")
    good_metrics = {
        "net_profit": 12000, "max_drawdown": 800, "max_drawdown_pct": 8.0,
        "profit_factor": 1.8, "win_rate": 55.0, "sharpe_ratio": 1.5,
        "total_trades": 50, "equity_curve": list(range(100000, 112000, 100)),
    }
    result = ftmo_checker.check(good_metrics, good_metrics["equity_curve"])
    print(f"Good strategy: passed={result['passed']} score={result['ftmo_score']:.1f}")
    for k, v in result["details"].items():
        print(f"  {k}: {v}")

    bad_metrics = {
        "net_profit": 5000, "max_drawdown": 15000, "max_drawdown_pct": 15.0,
        "profit_factor": 0.9, "win_rate": 35.0, "sharpe_ratio": 0.3,
        "total_trades": 10,
    }
    result2 = ftmo_checker.check(bad_metrics)
    print(f"\nBad strategy: passed={result2['passed']} score={result2['ftmo_score']:.1f}")

    # Test 2: XAUUSD backtest with FTMO check
    print("\n=== XAUUSD Backtest + FTMO ===")
    s = loop._generate_strategy("XAUUSD", "bullish")
    print(f"Strategy: {s.name}")

    windows = loop._get_2week_windows()[:3]
    for w in windows:
        result = await loop._run_backtest(s, w)
        if result and "metrics" in result:
            m = result["metrics"]
            eq = m.get("equity_curve", [])
            compliance = ftmo_checker.check(m, eq)
            print(f"  {w['start']}->{w['end']}: Sharpe={m.get('sharpe_ratio',0):.2f} "
                  f"DD={m.get('max_drawdown_pct',0):.1f}% "
                  f"FTMO={'PASS' if compliance['passed'] else 'FAIL'} "
                  f"Score={compliance['ftmo_score']:.1f}")

asyncio.run(test())
