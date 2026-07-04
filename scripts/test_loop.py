"""Test one cycle of the auto-loop."""
import sys, asyncio
sys.path.insert(0, '.')
from core.pipeline.auto_loop import AutoOptimizationLoop
from database.connection import get_connection

async def test():
    loop = AutoOptimizationLoop()
    print("Running one cycle (XAUUSD momentum, 2-week windows)...")
    await loop._run_cycle()
    print(f"\nStats: {loop._stats}")

    conn = await get_connection()
    for table in ['strategies', 'backtest_results', 'tasks', 'system_state']:
        cursor = await conn.execute(f'SELECT COUNT(*) as cnt FROM {table}')
        row = await cursor.fetchone()
        print(f'{table}: {row["cnt"]} rows')

    cursor = await conn.execute('SELECT key, value FROM system_state')
    rows = await cursor.fetchall()
    for r in rows:
        print(f'state: {r["key"]} = {r["value"][:300]}')

    cursor = await conn.execute('SELECT strategy_name, status, metrics FROM backtest_results ORDER BY created_at DESC LIMIT 5')
    rows = await cursor.fetchall()
    print('\nLatest backtests:')
    for r in rows:
        import json
        m = json.loads(r["metrics"]) if r["metrics"] else {}
        print(f'  {r["strategy_name"][:40]} | {r["status"]} | Sharpe={m.get("sharpe_ratio","?")} PF={m.get("profit_factor","?")} DD={m.get("max_drawdown_pct","?")} Trades={m.get("total_trades","?")}')

asyncio.run(test())
