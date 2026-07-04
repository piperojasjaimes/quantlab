"""Agent tests for QuantLab."""
from __future__ import annotations

import pytest
import asyncio
from core.models import Task, TaskType
from agents.strategy.strategy_agent import StrategyAgent
from agents.coding.coding_agent import CodingAgent
from agents.mutation.mutation_agent import MutationAgent


class TestStrategyAgent:
    @pytest.mark.asyncio
    async def test_generate_strategies(self):
        agent = StrategyAgent()
        await agent.start()
        task = Task(type=TaskType.STRATEGY_GENERATE, params={"count": 3})
        result = await agent.run_task(task)
        assert "strategies" in result
        assert result["count"] == 3
        assert len(result["strategies"]) == 3

    @pytest.mark.asyncio
    async def test_strategy_has_required_fields(self):
        agent = StrategyAgent()
        await agent.start()
        task = Task(type=TaskType.STRATEGY_GENERATE, params={"count": 1})
        result = await agent.run_task(task)
        s = result["strategies"][0]
        assert "name" in s
        assert "pattern" in s
        assert "timeframe" in s
        assert "params" in s


class TestMutationAgent:
    @pytest.mark.asyncio
    async def test_mutate_strategy(self):
        agent = MutationAgent()
        await agent.start()
        strategy_data = {
            "id": "test123",
            "name": "trend_eurusd_m15",
            "pattern": "trend_following",
            "timeframe": "M15",
            "symbol": "EURUSD",
            "params": {"ema_fast": 12, "ema_slow": 26, "stop_loss": 50, "take_profit": 100},
        }
        task = Task(type=TaskType.MUTATE, params={"strategy": strategy_data, "n_variants": 2})
        result = await agent.run_task(task)
        assert "variants" in result
        assert result["count"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
