"""Memory Agent — persists all knowledge to SQLite."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from agents.base_agent import BaseAgent
from core.models import Strategy, Task
from core.logger import get_logger
from database.connection import get_connection

log = get_logger("agent.memory")


class MemoryAgent(BaseAgent):
    name = "memory"

    async def execute(self, task: Task) -> dict:
        action = task.params.get("action", "save_strategy")
        data = task.params.get("data", {})

        if action == "save_strategy":
            return await self._save_strategy(data)
        elif action == "save_backtest":
            return await self._save_backtest(data)
        elif action == "save_error":
            return await self._save_error(data)
        elif action == "get_best":
            return await self._get_best_strategies(data)
        elif action == "get_stats":
            return await self._get_stats()
        return {"error": f"Unknown action: {action}"}

    async def _save_strategy(self, data: dict) -> dict:
        conn = await get_connection()
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """INSERT OR REPLACE INTO strategies
               (id, name, version, parent_id, pattern, timeframe, symbol,
                params, code_path, created_at, generation, depth, fitness, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("id", ""),
                data.get("name", ""),
                data.get("version", 1),
                data.get("parent_id", ""),
                data.get("pattern", ""),
                data.get("timeframe", ""),
                data.get("symbol", "EURUSD"),
                json.dumps(data.get("params", {})),
                data.get("code_path", ""),
                now,
                data.get("generation", 0),
                data.get("depth", 0),
                data.get("fitness", 0),
                1,
            ),
        )
        await conn.commit()
        log.info("Saved strategy: %s", data.get("name", "?"))
        return {"saved": True, "id": data.get("id", "")}

    async def _save_backtest(self, data: dict) -> dict:
        conn = await get_connection()
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """INSERT OR REPLACE INTO backtest_results
               (id, strategy_id, strategy_name, metrics, optimization_params,
                walk_forward_results, monte_carlo_results, stress_test_results,
                html_report_path, csv_path, json_path, png_path, status,
                rejection_reasons, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("id", ""),
                data.get("strategy_id", ""),
                data.get("strategy_name", ""),
                json.dumps(data.get("metrics", {})),
                json.dumps(data.get("optimization_params", {})),
                json.dumps(data.get("walk_forward_results", [])),
                json.dumps(data.get("monte_carlo_results", {})),
                json.dumps(data.get("stress_test_results", {})),
                data.get("html_report_path", ""),
                data.get("csv_path", ""),
                data.get("json_path", ""),
                data.get("png_path", ""),
                data.get("status", "pending"),
                json.dumps(data.get("rejection_reasons", [])),
                now,
            ),
        )
        await conn.commit()
        log.info("Saved backtest: %s", data.get("id", "?"))
        return {"saved": True}

    async def _save_error(self, data: dict) -> dict:
        conn = await get_connection()
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """INSERT INTO system_state (key, value, updated_at)
               VALUES (?, ?, ?)""",
            (f"error_{now}", json.dumps(data), now),
        )
        await conn.commit()
        return {"saved": True}

    async def _get_best_strategies(self, data: dict) -> dict:
        limit = data.get("limit", 10)
        conn = await get_connection()
        cursor = await conn.execute(
            """SELECT s.*, br.metrics
               FROM strategies s
               LEFT JOIN backtest_results br ON s.id = br.strategy_id
               WHERE s.is_active = 1 AND br.status = 'passed'
               ORDER BY br.created_at DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return {"strategies": [dict(r) for r in rows]}

    async def _get_stats(self) -> dict:
        conn = await get_connection()
        stats = {}
        for table in ["strategies", "backtest_results", "rankings"]:
            cursor = await conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
            row = await cursor.fetchone()
            stats[f"total_{table}"] = row["cnt"] if row else 0
        return stats
