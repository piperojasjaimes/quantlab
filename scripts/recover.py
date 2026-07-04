"""Recovery script — resume QuantLab from last saved state."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logger import setup_logging, get_logger
from database.connection import get_connection, close_connection
from database.task_repository import count_tasks_by_status

log = get_logger("recover")

_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "orchestrator_state.json"


async def recover() -> None:
    setup_logging()
    log.info("Recovering QuantLab state...")

    conn = await get_connection()
    stats = await count_tasks_by_status()
    log.info("Task stats: %s", stats)

    if _STATE_PATH.exists():
        data = json.loads(_STATE_PATH.read_text())
        log.info("Last state: cycle=%d, strategies=%d, backtests=%d",
                 data.get("current_cycle", 0),
                 data.get("total_strategies_generated", 0),
                 data.get("total_backtests_run", 0))
    else:
        log.info("No previous state found — starting fresh")

    await close_connection()
    log.info("State recovered. Starting orchestrator...")

    from agents.orchestrator.orchestrator import run_orchestrator
    await run_orchestrator()


if __name__ == "__main__":
    asyncio.run(recover())
