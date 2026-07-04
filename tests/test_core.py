"""Core tests for QuantLab."""
from __future__ import annotations

import pytest
from core.models import Task, TaskType, TaskStatus, Strategy, StrategyParams, StrategyPattern, Timeframe, BacktestMetrics, BacktestResult
from core.config import Config


class TestModels:
    def test_task_creation(self):
        t = Task(type=TaskType.STRATEGY_GENERATE)
        assert t.status == TaskStatus.PENDING
        assert t.id != ""
        assert t.type == TaskType.STRATEGY_GENERATE

    def test_task_with_params(self):
        t = Task(type=TaskType.BACKTEST_RUN, params={"symbol": "EURUSD"})
        assert t.params["symbol"] == "EURUSD"

    def test_strategy_creation(self):
        s = Strategy(name="test_strategy", pattern=StrategyPattern.TREND_FOLLOWING, timeframe=Timeframe.M15)
        assert s.name == "test_strategy"
        assert s.version == 1
        assert s.params.stop_loss == 50

    def test_strategy_params(self):
        p = StrategyParams(ema_fast=8, ema_slow=21, rsi_period=14)
        assert p.ema_fast == 8
        assert p.ema_slow == 21

    def test_backtest_metrics(self):
        m = BacktestMetrics(total_trades=100, winning_trades=60, losing_trades=40, win_rate=60.0)
        assert m.total_trades == 100
        assert m.win_rate == 60.0

    def test_backtest_result(self):
        r = BacktestResult(strategy_id="test123", status="passed")
        assert r.strategy_id == "test123"
        assert r.status == "passed"

    def test_strategy_patterns(self):
        assert StrategyPattern.TREND_FOLLOWING.value == "trend_following"
        assert StrategyPattern.SMC_STRUCTURE.value == "smc_structure"

    def test_timeframes(self):
        assert Timeframe.M15.value == "M15"
        assert Timeframe.H4.value == "H4"


class TestConfig:
    def test_config_load(self):
        c = Config()
        c.raw = {"system": {"name": "test"}}
        assert c.get("system", "name") == "test"

    def test_config_default(self):
        c = Config()
        c.raw = {}
        assert c.get("system", "name", default="fallback") == "fallback"

    def test_config_nested(self):
        c = Config()
        c.raw = {"a": {"b": {"c": 42}}}
        assert c.get("a", "b", "c") == 42


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
