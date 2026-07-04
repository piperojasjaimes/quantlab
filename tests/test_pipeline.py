"""Pipeline and MT5 connector tests for QuantLab Phase 2."""
from __future__ import annotations

import pytest
import asyncio
from core.mt5.connector import MT5Connector
from core.pipeline.auto_loop import AutoOptimizationLoop
from core.models import Strategy, StrategyParams, StrategyPattern, Timeframe


class TestMT5Connector:
    def test_connector_init(self):
        c = MT5Connector()
        assert c._connected is False
        assert c._mt5 is None

    def test_simulate_backtest(self):
        c = MT5Connector()
        result = c._simulate_backtest("EURUSD", "M15", {"ema_fast": 12, "ema_slow": 26, "stop_loss": 50, "take_profit": 100})
        assert "metrics" in result
        m = result["metrics"]
        assert m["total_trades"] > 0
        assert m["win_rate"] > 0
        assert m["profit_factor"] > 0
        assert len(m["equity_curve"]) > 0

    def test_ema_calculation(self):
        import numpy as np
        c = MT5Connector()
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        ema = c._ema(data, 3)
        assert len(ema) == len(data)
        assert ema[0] == 1.0
        assert ema[-1] > ema[0]

    def test_compute_metrics(self):
        import numpy as np
        c = MT5Connector()
        trades = [100, -50, 200, -30, 150, -80, 120]
        equity = [10000]
        for t in trades:
            equity.append(equity[-1] + t)
        result = c._compute_metrics(trades, equity, "EURUSD", "M15", {})
        m = result["metrics"]
        assert m["total_trades"] == 7
        assert m["winning_trades"] == 4
        assert m["losing_trades"] == 3
        assert m["net_profit"] == 410
        assert m["sharpe_ratio"] != 0

    def test_tf_mapping(self):
        c = MT5Connector()
        assert c._tf_to_mt5("M1") == 1
        assert c._tf_to_mt5("M15") == 15
        assert c._tf_to_mt5("H1") == 60
        assert c._tf_to_mt5("D1") == 1440


class TestAutoLoop:
    def test_generate_strategy(self):
        loop = AutoOptimizationLoop()
        s = loop._generate_strategy()
        assert isinstance(s, Strategy)
        assert s.name != ""
        assert s.pattern in StrategyPattern
        assert s.timeframe in Timeframe

    def test_random_params(self):
        loop = AutoOptimizationLoop()
        for pattern in ["trend_following", "scalping", "mean_reversion", "grid", "breakout"]:
            p = loop._random_params(pattern)
            assert p.ema_fast < p.ema_slow
            assert p.stop_loss > 0
            assert p.take_profit > 0

    def test_monte_carlo(self):
        loop = AutoOptimizationLoop()
        metrics = {"sharpe_ratio": 1.5, "equity_curve": [10000, 10500, 11000, 10800, 11200]}
        result = loop._monte_carlo(metrics)
        assert "probability_of_profit" in result
        assert "avg_final_equity" in result
        assert result["probability_of_profit"] > 0

    def test_walk_forward(self):
        loop = AutoOptimizationLoop()
        s = Strategy(name="test", pattern=StrategyPattern.TREND_FOLLOWING, timeframe=Timeframe.M15)
        bt = {"metrics": {"sharpe_ratio": 1.5, "max_drawdown_pct": 10}}
        result = loop._walk_forward(s, bt)
        assert "avg_sharpe" in result
        assert "passed" in result

    def test_stop(self):
        loop = AutoOptimizationLoop()
        loop._running = True
        loop.stop()
        assert loop._running is False


class TestStrategyEvolution:
    def test_strategy_with_depth(self):
        s = Strategy(
            name="test_gen1",
            pattern=StrategyPattern.TREND_FOLLOWING,
            timeframe=Timeframe.M15,
            parent_id="parent123",
            generation=1,
            depth=1,
        )
        assert s.generation == 1
        assert s.depth == 1
        assert s.parent_id == "parent123"

    def test_params_validation(self):
        p = StrategyParams(ema_fast=8, ema_slow=21, stop_loss=30, take_profit=90)
        assert p.ema_fast < p.ema_slow
        assert p.stop_loss < p.take_profit

    def test_strategy_serialization(self):
        s = Strategy(name="test_serial", pattern=StrategyPattern.BREAKOUT, timeframe=Timeframe.H1)
        d = s.model_dump(mode="json")
        assert isinstance(d, dict)
        assert d["name"] == "test_serial"
        assert d["pattern"] == "breakout"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
