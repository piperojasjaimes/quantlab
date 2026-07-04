"""Persistent task queue using SQLite."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.connection import get_connection
from core.models import Task, TaskStatus, TaskType
from core.logger import get_logger

log = get_logger("db.tasks")


async def save_task(task: Task) -> None:
    conn = await get_connection()
    await conn.execute(
        """INSERT OR REPLACE INTO tasks
           (id, created_at, updated_at, type, status, priority, agent,
            strategy_id, params, result, logs, retries, error, parent_task_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task.id,
            task.created_at.isoformat(),
            task.updated_at.isoformat(),
            task.type.value,
            task.status.value,
            task.priority,
            task.agent,
            task.strategy_id,
            json.dumps(task.params),
            json.dumps(task.result),
            json.dumps(task.logs),
            task.retries,
            task.error,
            task.parent_task_id,
        ),
    )
    await conn.commit()


async def get_task(task_id: str) -> Task | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_task(row)


async def get_pending_tasks(limit: int = 10) -> list[Task]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, created_at ASC LIMIT ?",
        (TaskStatus.PENDING.value, limit),
    )
    rows = await cursor.fetchall()
    return [_row_to_task(r) for r in rows]


async def get_tasks_by_status(status: TaskStatus, limit: int = 50) -> list[Task]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
        (status.value, limit),
    )
    rows = await cursor.fetchall()
    return [_row_to_task(r) for r in rows]


async def get_tasks_by_agent(agent: str, limit: int = 50) -> list[Task]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM tasks WHERE agent = ? ORDER BY created_at DESC LIMIT ?",
        (agent, limit),
    )
    rows = await cursor.fetchall()
    return [_row_to_task(r) for r in rows]


async def update_task_status(task_id: str, status: TaskStatus, error: str = "") -> None:
    conn = await get_connection()
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        "UPDATE tasks SET status = ?, updated_at = ?, error = ? WHERE id = ?",
        (status.value, now, error, task_id),
    )
    await conn.commit()


async def update_task_result(task_id: str, result: dict[str, Any]) -> None:
    conn = await get_connection()
    now = datetime.now(timezone.utc).isoformat()

    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    await conn.execute(
        "UPDATE tasks SET result = ?, updated_at = ?, status = ? WHERE id = ?",
        (json.dumps(result, default=_default), now, TaskStatus.COMPLETED.value, task_id),
    )
    await conn.commit()


async def add_task_log(task_id: str, message: str) -> None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT logs FROM tasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    if row:
        logs = json.loads(row["logs"])
        logs.append(f"[{datetime.now(timezone.utc).isoformat()}] {message}")
        await conn.execute(
            "UPDATE tasks SET logs = ? WHERE id = ?",
            (json.dumps(logs), task_id),
        )
        await conn.commit()


async def count_tasks_by_status() -> dict[str, int]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
    )
    rows = await cursor.fetchall()
    return {row["status"]: row["cnt"] for row in rows}


def _row_to_task(row) -> Task:
    return Task(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        type=TaskType(row["type"]),
        status=TaskStatus(row["status"]),
        priority=row["priority"],
        agent=row["agent"],
        strategy_id=row["strategy_id"],
        params=json.loads(row["params"]),
        result=json.loads(row["result"]),
        logs=json.loads(row["logs"]),
        retries=row["retries"],
        error=row["error"],
        parent_task_id=row["parent_task_id"],
    )
