"""SQLite schema for QuantLab — migrate-ready to PostgreSQL."""
from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER DEFAULT 0,
    agent TEXT DEFAULT '',
    strategy_id TEXT DEFAULT '',
    params TEXT DEFAULT '{}',
    result TEXT DEFAULT '{}',
    logs TEXT DEFAULT '[]',
    retries INTEGER DEFAULT 0,
    error TEXT DEFAULT '',
    parent_task_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS strategies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    version INTEGER DEFAULT 1,
    parent_id TEXT DEFAULT '',
    pattern TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT 'EURUSD',
    params TEXT NOT NULL DEFAULT '{}',
    code_path TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    generation INTEGER DEFAULT 0,
    depth INTEGER DEFAULT 0,
    fitness REAL DEFAULT 0.0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT DEFAULT '',
    metrics TEXT NOT NULL DEFAULT '{}',
    optimization_params TEXT DEFAULT '{}',
    walk_forward_results TEXT DEFAULT '[]',
    monte_carlo_results TEXT DEFAULT '{}',
    stress_test_results TEXT DEFAULT '{}',
    html_report_path TEXT DEFAULT '',
    csv_path TEXT DEFAULT '',
    json_path TEXT DEFAULT '',
    png_path TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    rejection_reasons TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id)
);

CREATE TABLE IF NOT EXISTS rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    metrics TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (strategy_id) REFERENCES strategies(id)
);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent);
CREATE INDEX IF NOT EXISTS idx_strategies_pattern ON strategies(pattern);
CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_id);
CREATE INDEX IF NOT EXISTS idx_backtest_status ON backtest_results(status);
CREATE INDEX IF NOT EXISTS idx_rankings_score ON rankings(score DESC);
"""


async def initialize_database(conn) -> None:
    """Execute schema creation."""
    for statement in SCHEMA_SQL.split(";"):
        stmt = statement.strip()
        if stmt:
            await conn.execute(stmt)
    await conn.commit()
