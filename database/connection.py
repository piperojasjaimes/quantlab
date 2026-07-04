"""Async SQLite connection manager for QuantLab."""
from __future__ import annotations

import aiosqlite
from pathlib import Path

from database.schema import initialize_database
from core.logger import get_logger

log = get_logger("db.connection")

_DB_PATH: Path = Path(__file__).resolve().parent.parent / "data" / "quantlab.db"
_connection: aiosqlite.Connection | None = None


async def get_connection() -> aiosqlite.Connection:
    global _connection
    if _connection is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _connection = await aiosqlite.connect(str(_DB_PATH))
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA journal_mode=WAL")
        await _connection.execute("PRAGMA foreign_keys=ON")
        await initialize_database(_connection)
        log.info("Database connected: %s", _DB_PATH)
    return _connection


async def close_connection() -> None:
    global _connection
    if _connection:
        await _connection.close()
        _connection = None
        log.info("Database closed")
