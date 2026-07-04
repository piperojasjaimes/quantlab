"""Orchestrator — the brain that coordinates all agents."""
from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.models import (
    AgentState,
    SystemState,
    Task,
    TaskStatus,
    TaskType,
)
from core.config import config
from core.logger import get_logger, setup_logging
from database.connection import get_connection, close_connection
from database.task_repository import (
    save_task,
    get_pending_tasks,
    get_task,
    update_task_status,
    count_tasks_by_status,
)
from agents.strategy.strategy_agent import StrategyAgent
from agents.coding.coding_agent import CodingAgent
from agents.backtest.backtest_agent import BacktestAgent
from agents.optimization.optimization_agent import OptimizationAgent
from agents.validation.validation_agent import ValidationAgent
from agents.mutation.mutation_agent import MutationAgent
from agents.ranking.ranking_agent import RankingAgent
from agents.memory.memory_agent import MemoryAgent
from agents.report.report_agent import ReportAgent

log = get_logger("orchestrator")

_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "orchestrator_state.json"


class Orchestrator:
    def __init__(self) -> None:
        self.agents = {
            "strategy": StrategyAgent(),
            "coding": CodingAgent(),
            "backtest": BacktestAgent(),
            "optimization": OptimizationAgent(),
            "validation": ValidationAgent(),
            "mutation": MutationAgent(),
            "ranking": RankingAgent(),
            "memory": MemoryAgent(),
            "report": ReportAgent(),
        }
        self.state = SystemState()
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        setup_logging()
        log.info("=" * 60)
        log.info("QuantLab Orchestrator starting...")
        log.info("=" * 60)

        await get_connection()
        await self._load_state()

        for name, agent in self.agents.items():
            await agent.start()
            self.state.agents[name] = agent.get_state()

        self._running = True
        self.state.started_at = datetime.now(timezone.utc)
        log.info("All agents started. Entering main loop.")

        try:
            await self._main_loop()
        except asyncio.CancelledError:
            log.info("Main loop cancelled")
        finally:
            await self._shutdown()

    async def _main_loop(self) -> None:
        tick = 0
        while self._running and not self._shutdown_event.is_set():
            tick += 1
            try:
                self.state.last_heartbeat = datetime.now(timezone.utc)
                self.state.current_cycle = tick

                if tick % 10 == 0:
                    await self._check_agent_health()

                pending = await get_pending_tasks(limit=5)
                for task in pending:
                    await self._dispatch_task(task)

                if tick % 20 == 0:
                    await self._auto_generate_strategies()

                if tick % 50 == 0:
                    await self._save_state()

                await asyncio.sleep(config.get("system", "tick_interval_seconds", default=5))
            except Exception as e:
                log.error("Orchestrator tick %d error: %s", tick, e)
                await asyncio.sleep(10)

    async def _dispatch_task(self, task: Task) -> None:
        agent_name = self._select_agent(task.type)
        if not agent_name:
            log.warning("No agent for task type: %s", task.type)
            await update_task_status(task.id, TaskStatus.CANCELLED)
            return

        agent = self.agents.get(agent_name)
        if not agent or agent.state.status.value == "busy":
            return

        log.info("Dispatching task %s [%s] to agent %s", task.id, task.type.value, agent_name)
        task.agent = agent_name
        await save_task(task)

        result = await agent.run_task(task)

        if "error" in result and task.retries < config.get("system", "max_retries_per_task", default=3):
            task.retries += 1
            task.status = TaskStatus.RETRY
            await save_task(task)
            log.info("Task %s scheduled for retry (%d/%d)",
                     task.id, task.retries, config.get("system", "max_retries_per_task", default=3))
        elif "error" in result:
            log.error("Task %s permanently failed: %s", task.id, result["error"])

        if task.type == TaskType.STRATEGY_GENERATE and "strategies" in result:
            await self._handle_generated_strategies(result["strategies"])

    def _select_agent(self, task_type: TaskType) -> str:
        mapping = {
            TaskType.STRATEGY_GENERATE: "strategy",
            TaskType.STRATEGY_CODE: "coding",
            TaskType.BACKTEST_RUN: "backtest",
            TaskType.OPTIMIZE: "optimization",
            TaskType.VALIDATE: "validation",
            TaskType.MUTATE: "mutation",
            TaskType.RANK: "ranking",
            TaskType.REPORT: "report",
        }
        return mapping.get(task_type, "")

    async def _handle_generated_strategies(self, strategies: list[dict]) -> None:
        for s in strategies:
            await self._submit_task(TaskType.STRATEGY_CODE, {"strategy": s})
            await self._submit_task(TaskType.BACKTEST_RUN, {"strategy": s})
            await self._submit_task(TaskType.MEMORY, {
                "action": "save_strategy",
                "data": s,
            })

    async def _auto_generate_strategies(self) -> None:
        task_counts = await count_tasks_by_status()
        pending = task_counts.get("pending", 0)
        running = task_counts.get("running", 0)

        if pending + running < 10:
            count = config.get("strategy_generation", "min_strategies_per_cycle", default=5)
            await self._submit_task(TaskType.STRATEGY_GENERATE, {"count": count})

    async def _submit_task(self, task_type: TaskType, params: dict = None) -> Task:
        task = Task(type=task_type, params=params or {})
        await save_task(task)
        log.info("Task created: %s [%s]", task.id, task_type.value)
        return task

    async def _check_agent_health(self) -> None:
        for name, agent in self.agents.items():
            state = agent.get_state()
            self.state.agents[name] = state
            if state.status.value == "error":
                log.warning("Agent %s in error state: %s", name, state.error)
                await agent.start()

    async def _load_state(self) -> None:
        if _STATE_PATH.exists():
            try:
                import json
                data = json.loads(_STATE_PATH.read_text())
                self.state.total_strategies_generated = data.get("total_strategies_generated", 0)
                self.state.total_backtests_run = data.get("total_backtests_run", 0)
                self.state.current_cycle = data.get("current_cycle", 0)
                log.info("State loaded: cycle=%d", self.state.current_cycle)
            except Exception as e:
                log.warning("Failed to load state: %s", e)

    async def _save_state(self) -> None:
        try:
            import json
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "total_strategies_generated": self.state.total_strategies_generated,
                "total_backtests_run": self.state.total_backtests_run,
                "total_optimizations_run": self.state.total_optimizations_run,
                "total_validations_run": self.state.total_validations_run,
                "current_cycle": self.state.current_cycle,
                "started_at": self.state.started_at.isoformat(),
                "last_heartbeat": self.state.last_heartbeat.isoformat(),
            }
            _STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("Failed to save state: %s", e)

    async def _shutdown(self) -> None:
        log.info("Shutting down Orchestrator...")
        self._running = False
        for name, agent in self.agents.items():
            await agent.stop()
        await self._save_state()
        await close_connection()
        log.info("Orchestrator shut down cleanly.")

    def stop(self) -> None:
        self._running = False
        self._shutdown_event.set()


async def run_orchestrator() -> None:
    orch = Orchestrator()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, orch.stop)
        except NotImplementedError:
            pass
    await orch.start()
