"""Check full project status."""
import sys, asyncio, json
sys.path.insert(0, '.')
from database.connection import get_connection

async def check():
    conn = await get_connection()
    for table in ['strategies', 'backtest_results', 'tasks', 'system_state']:
        cursor = await conn.execute(f'SELECT COUNT(*) as cnt FROM {table}')
        row = await cursor.fetchone()
        print(f"{table}: {row['cnt']} rows")

    cursor = await conn.execute('SELECT key, value FROM system_state')
    rows = await cursor.fetchall()
    for r in rows:
        print(f"state: {r['key']} = {r['value'][:500]}")

    cursor = await conn.execute('SELECT status, COUNT(*) as cnt FROM backtest_results GROUP BY status')
    rows = await cursor.fetchall()
    print("\nBacktest results by status:")
    for r in rows:
        print(f"  {r['status']}: {r['cnt']}")

    cursor = await conn.execute('SELECT symbol, COUNT(*) as cnt FROM strategies GROUP BY symbol')
    rows = await cursor.fetchall()
    print("\nStrategies by symbol:")
    for r in rows:
        print(f"  {r['symbol']}: {r['cnt']}")

asyncio.run(check())
