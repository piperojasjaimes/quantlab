"""Ranking Agent — ranks strategies by composite score."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agents.base_agent import BaseAgent
from core.models import Task
from core.config import config
from core.logger import get_logger
from database.connection import get_connection

log = get_logger("agent.ranking")


class RankingAgent(BaseAgent):
    name = "ranking"

    async def execute(self, task: Task) -> dict:
        log.info("Running ranking analysis")
        results = await self._load_all_results()
        if not results:
            return {"rankings": [], "count": 0}

        weights = config.get("ranking", "weights", default={
            "sharpe_ratio": 0.25, "sortino_ratio": 0.15, "calmar_ratio": 0.10,
            "profit_factor": 0.15, "max_drawdown": 0.10, "win_rate": 0.10,
            "recovery_factor": 0.05, "expectancy": 0.05, "ulcer_index": 0.03,
            "mar_ratio": 0.02,
        })

        ranked = []
        for r in results:
            m = r.get("metrics", {})
            score = 0.0
            for metric, weight in weights.items():
                val = m.get(metric, 0)
                if metric == "max_drawdown":
                    val = max(0, 100 - val)
                    score += val / 100 * weight
                elif metric == "ulcer_index":
                    val = max(0, 50 - val)
                    score += val / 50 * weight
                else:
                    score += min(max(val, -5), 5) / 5 * weight
            ranked.append({**r, "composite_score": round(score, 4)})

        ranked.sort(key=lambda x: x["composite_score"], reverse=True)
        for i, r in enumerate(ranked):
            r["rank"] = i + 1

        await self._save_rankings(ranked)
        log.info("Ranked %d strategies. Top: %s (score: %.4f)",
                 len(ranked), ranked[0].get("strategy_name", "?"), ranked[0].get("composite_score", 0))
        return {"rankings": ranked[:50], "count": len(ranked)}

    async def _load_all_results(self) -> list[dict]:
        conn = await get_connection()
        cursor = await conn.execute(
            """SELECT br.*, s.name as strategy_name, s.pattern, s.timeframe, s.symbol
               FROM backtest_results br
               JOIN strategies s ON br.strategy_id = s.id
               WHERE br.status = 'passed'
               ORDER BY br.created_at DESC
               LIMIT 500"""
        )
        rows = await cursor.fetchall()
        import json
        return [dict({
            "id": r["id"],
            "strategy_id": r["strategy_id"],
            "strategy_name": r["strategy_name"],
            "metrics": json.loads(r["metrics"]) if r["metrics"] else {},
            "status": r["status"],
        }) for r in rows]

    async def _save_rankings(self, ranked: list[dict]) -> None:
        conn = await get_connection()
        now = datetime.now(timezone.utc).isoformat()
        import json
        for r in ranked:
            await conn.execute(
                """INSERT INTO rankings (created_at, strategy_id, rank, score, metrics)
                   VALUES (?, ?, ?, ?, ?)""",
                (now, r.get("strategy_id", ""), r.get("rank", 0),
                 r.get("composite_score", 0), json.dumps(r.get("metrics", {}))),
            )
        await conn.commit()
