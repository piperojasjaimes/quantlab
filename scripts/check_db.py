"""Quick DB check script."""
import sys, asyncio
sys.path.insert(0, '.')
from database.connection import get_connection

async def check():
    conn = await get_connection()
    for table in ['strategies', 'backtest_results', 'tasks', 'rankings', 'system_state']:
        cursor = await conn.execute(f'SELECT COUNT(*) as cnt FROM {table}')
        row = await cursor.fetchone()
        print(f'{table}: {row["cnt"]} rows')

    cursor = await conn.execute('SELECT key, value FROM system_state')
    rows = await cursor.fetchall()
    for r in rows:
        print(f'state: {r["key"]} = {r["value"][:200]}')

    cursor = await conn.execute('SELECT status, agent, COUNT(*) as cnt FROM tasks GROUP BY status, agent')
    rows = await cursor.fetchall()
    print('\nTasks by status+agent:')
    for r in rows:
        print(f'  {r["status"]} / {r["agent"]}: {r["cnt"]}')

    cursor = await conn.execute('SELECT * FROM backtest_results LIMIT 3')
    rows = await cursor.fetchall()
    print(f'\nSample backtest_results: {len(rows)} rows')
    for r in rows:
        print(f'  id={r["id"]} strategy={r["strategy_name"]} status={r["status"]}')

asyncio.run(check())
