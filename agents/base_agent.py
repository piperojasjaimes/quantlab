"""Base agent class — all agents inherit from this."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from core.models import AgentState, AgentStatus, Task, TaskStatus
from core.logger import get_logger
from database.task_repository import (
    update_task_status,
    update_task_result,
    add_task_log,
)


class BaseAgent(ABC):
    """Abstract base for all QuantLab agents."""

    name: str = "base"

    def __init__(self) -> None:
        self.log = get_logger(f"agent.{self.name}")
        self.state = AgentState(name=self.name)
        self._running = False
        self._task: Task | None = None

    async def start(self) -> None:
        self.state.status = AgentStatus.IDLE
        self._running = True
        self.log.info("Agent %s started", self.name)

    async def stop(self) -> None:
        self._running = False
        self.state.status = AgentStatus.STOPPED
        self.log.info("Agent %s stopped", self.name)

    async def run_task(self, task: Task) -> dict:
        """Execute a task, update status, return result."""
        self._task = task
        self.state.status = AgentStatus.BUSY
        self.state.current_task_id = task.id
        self.state.last_activity = datetime.now(timezone.utc)

        await update_task_status(task.id, TaskStatus.RUNNING)
        await add_task_log(task.id, f"[{self.name}] Starting task")

        try:
            result = await self.execute(task)
            await update_task_result(task.id, result)
            await add_task_log(task.id, f"[{self.name}] Task completed")
            self.state.tasks_completed += 1
            self.state.status = AgentStatus.IDLE
            self.state.current_task_id = ""
            self.log.info("Task %s completed by %s", task.id, self.name)
            return result
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            await update_task_status(task.id, TaskStatus.FAILED, error_msg)
            await add_task_log(task.id, f"[{self.name}] FAILED: {error_msg}")
            self.state.tasks_failed += 1
            self.state.status = AgentStatus.ERROR
            self.state.error = error_msg
            self.state.current_task_id = ""
            self.log.error("Task %s failed in %s: %s", task.id, self.name, error_msg)
            return {"error": error_msg}
        finally:
            self._task = None

    @abstractmethod
    async def execute(self, task: Task) -> dict:
        """Override in subclass. Must return a dict result."""
        ...

    def get_state(self) -> AgentState:
        self.state.last_activity = datetime.now(timezone.utc)
        return self.state
