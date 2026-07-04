"""Report Agent — generates Markdown, HTML, CSV reports."""
from __future__ import annotations

import json
import csv
from datetime import datetime, timezone
from pathlib import Path

from agents.base_agent import BaseAgent
from core.models import Task
from core.logger import get_logger
from database.connection import get_connection

log = get_logger("agent.report")

_REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"
_REPORTS_DIR.mkdir(exist_ok=True)


class ReportAgent(BaseAgent):
    name = "report"

    async def execute(self, task: Task) -> dict:
        report_type = task.params.get("report_type", "daily")
        log.info("Generating %s report", report_type)

        if report_type == "daily":
            return await self._daily_report()
        elif report_type == "ranking":
            return await self._ranking_report()
        elif report_type == "strategy":
            return await self._strategy_report(task.params.get("strategy_id", ""))
        return {"error": f"Unknown report type: {report_type}"}

    async def _daily_report(self) -> dict:
        conn = await get_connection()
        now = datetime.now(timezone.utc)

        strategies_cursor = await conn.execute("SELECT COUNT(*) as cnt FROM strategies")
        strategies_count = (await strategies_cursor.fetchone())["cnt"]

        bt_cursor = await conn.execute("SELECT COUNT(*) as cnt FROM backtest_results")
        bt_count = (await bt_cursor.fetchone())["cnt"]

        passed_cursor = await conn.execute("SELECT COUNT(*) as cnt FROM backtest_results WHERE status = 'passed'")
        passed_count = (await passed_cursor.fetchone())["cnt"]

        ranking_cursor = await conn.execute("SELECT * FROM rankings ORDER BY score DESC LIMIT 10")
        top_rankings = [dict(r) for r in await ranking_cursor.fetchall()]

        tasks_cursor = await conn.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status")
        task_stats = {r["status"]: r["cnt"] for r in await tasks_cursor.fetchall()}

        md = f"""# QuantLab Daily Report — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Summary
| Metric | Value |
|--------|-------|
| Strategies Generated | {strategies_count} |
| Backtests Run | {bt_count} |
| Passed | {passed_count} |
| Pass Rate | {passed_count/max(bt_count,1)*100:.1f}% |

## Task Status
"""
        for status, count in task_stats.items():
            md += f"- **{status}**: {count}\n"

        md += "\n## Top 10 Rankings\n"
        md += "| Rank | Strategy | Score |\n|------|----------|-------|\n"
        for r in top_rankings:
            md += f"| {r['rank']} | {r.get('strategy_id', '?')} | {r.get('score', 0):.4f} |\n"

        report_path = _REPORTS_DIR / f"daily_{now.strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(md, encoding="utf-8")
        log.info("Daily report saved: %s", report_path)
        return {"path": str(report_path), "type": "daily"}

    async def _ranking_report(self) -> dict:
        conn = await get_connection()
        cursor = await conn.execute("SELECT * FROM rankings ORDER BY score DESC LIMIT 50")
        rankings = [dict(r) for r in await cursor.fetchall()]

        md = "# Strategy Rankings\n\n"
        md += "| Rank | Strategy | Score | Metrics |\n|------|----------|-------|----------|\n"
        for r in rankings:
            metrics = json.loads(r.get("metrics", "{}"))
            md += f"| {r['rank']} | {r.get('strategy_id', '?')} | {r.get('score', 0):.4f} | {json.dumps(metrics)[:80]}... |\n"

        now = datetime.now(timezone.utc)
        report_path = _REPORTS_DIR / f"ranking_{now.strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(md, encoding="utf-8")
        return {"path": str(report_path), "type": "ranking", "count": len(rankings)}

    async def _strategy_report(self, strategy_id: str) -> dict:
        conn = await get_connection()
        cursor = await conn.execute(
            "SELECT * FROM backtest_results WHERE strategy_id = ? ORDER BY created_at DESC",
            (strategy_id,),
        )
        results = [dict(r) for r in await cursor.fetchall()]
        if not results:
            return {"error": f"No results for strategy {strategy_id}"}

        latest = results[0]
        metrics = json.loads(latest.get("metrics", "{}"))

        md = f"# Strategy Report: {strategy_id}\n\n"
        md += f"**Created**: {latest.get('created_at', '?')}\n"
        md += f"**Status**: {latest.get('status', '?')}\n\n"
        md += "## Metrics\n\n"
        md += "| Metric | Value |\n|--------|-------|\n"
        for key, val in metrics.items():
            if key != "equity_curve":
                md += f"| {key} | {val} |\n"

        now = datetime.now(timezone.utc)
        report_path = _REPORTS_DIR / f"strategy_{strategy_id}_{now.strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(md, encoding="utf-8")
        return {"path": str(report_path), "type": "strategy"}
