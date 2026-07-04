"""Test one cycle of the auto-loop to verify DB persistence."""
import sys, asyncio
sys.path.insert(0, '.')
from core.pipeline.auto_loop import AutoOptimizationLoop
from database.connection import get_connection

async def test():
    loop = AutoOptimizationLoop()
    print("Running one cycle...")
    await loop._run_cycle()

    conn = await get_connection()
    for table in ['strategies', 'backtest_results', 'tasks', 'system_state']:
        cursor = await conn.execute(f'SELECT COUNT(*) as cnt FROM {table}')
        row = await cursor.fetchone()
        print(f'{table}: {row["cnt"]} rows')

    cursor = await conn.execute('SELECT key, value FROM system_state')
    rows = await cursor.fetchall()
    for r in rows:
        print(f'state: {r["key"]} = {r["value"][:200]}')

    cursor = await conn.execute('SELECT name, pattern, timeframe, fitness FROM strategies LIMIT 5')
    rows = await cursor.fetchall()
    print('\nSample strategies:')
    for r in rows:
        print(f'  {r["name"]} | {r["pattern"]} | {r["timeframe"]} | fitness={r["fitness"]}')

    cursor = await conn.execute('SELECT strategy_name, status, metrics FROM backtest_results LIMIT 5')
    rows = await cursor.fetchall()
    print('\nSample backtest results:')
    for r in rows:
        import json
        m = json.loads(r["metrics"]) if r["metrics"] else {}
        print(f'  {r["strategy_name"]} | {r["status"]} | Sharpe={m.get("sharpe_ratio","?")} PF={m.get("profit_factor","?")}')

asyncio.run(test())
