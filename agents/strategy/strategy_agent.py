"""Strategy Agent — generates new trading strategy definitions."""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from typing import Any

from agents.base_agent import BaseAgent
from core.models import (
    Strategy,
    StrategyParams,
    StrategyPattern,
    Task,
    Timeframe,
)
from core.config import config
from core.logger import get_logger

log = get_logger("agent.strategy")

INDICATORS = config.get("strategy_generation", "indicators", default=[
    "EMA", "SMA", "RSI", "MACD", "ADX", "ATR", "Bollinger", "VWAP",
    "Stochastic", "CCI",
])

TIMEFRAMES = [Timeframe(t) for t in config.get("strategy_generation", "timeframes", default=[
    "M5", "M15", "M30", "H1", "H4", "D1",
])]

PATTERNS = [StrategyPattern(p) for p in config.get("strategy_generation", "patterns", default=[
    "trend_following", "mean_reversion", "breakout", "scalping", "swing",
    "grid", "session_based", "killzone_trading", "smc_structure",
])]

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD"]


class StrategyAgent(BaseAgent):
    name = "strategy"

    async def execute(self, task: Task) -> dict:
        count = task.params.get("count", config.get("strategy_generation", "min_strategies_per_cycle", default=5))
        strategies = []
        for _ in range(count):
            s = self._generate_strategy()
            strategies.append(s.model_dump(mode="json"))
            log.info("Generated strategy: %s [%s/%s]", s.name, s.pattern.value, s.timeframe.value)
        return {"strategies": strategies, "count": len(strategies)}

    def _generate_strategy(self) -> Strategy:
        pattern = random.choice(PATTERNS)
        timeframe = random.choice(TIMEFRAMES)
        symbol = random.choice(SYMBOLS)
        gen = config.get("strategy_generation", "patterns", default=PATTERNS)
        params = self._randomize_params(pattern)
        name = f"{pattern.value}_{symbol}_{timeframe.value}_{uuid.uuid4().hex[:6]}"
        return Strategy(
            name=name,
            pattern=pattern,
            timeframe=timeframe,
            symbol=symbol,
            params=params,
        )

    def _randomize_params(self, pattern: StrategyPattern) -> StrategyParams:
        base = StrategyParams()
        base.ema_fast = random.randint(5, 30)
        base.ema_slow = random.randint(base.ema_fast + 5, 100)
        base.rsi_period = random.randint(7, 30)
        base.rsi_overbought = random.randint(65, 85)
        base.rsi_oversold = random.randint(15, 35)
        base.atr_period = random.randint(7, 25)
        base.atr_multiplier = round(random.uniform(0.8, 2.5), 1)
        base.trailing_stop = random.randint(10, 80)

        if pattern in (StrategyPattern.TREND_FOLLOWING, StrategyPattern.SWING):
            base.stop_loss = random.randint(30, 150)
            base.take_profit = random.randint(60, 400)
        elif pattern == StrategyPattern.SCALPING:
            base.stop_loss = random.randint(5, 30)
            base.take_profit = random.randint(10, 60)
        elif pattern == StrategyPattern.MEAN_REVERSION:
            base.stop_loss = random.randint(20, 80)
            base.take_profit = random.randint(30, 120)
        elif pattern == StrategyPattern.GRID:
            base.stop_loss = random.randint(50, 200)
            base.take_profit = random.randint(30, 100)
            base.max_positions = random.randint(3, 10)
        else:
            base.stop_loss = random.randint(20, 150)
            base.take_profit = random.randint(40, 300)

        base.lot_size = round(random.choice([0.01, 0.02, 0.05, 0.1, 0.2]), 2)
        base.session_start = random.randint(6, 10)
        base.session_end = random.randint(18, 23)
        base.adx_threshold = random.randint(20, 35)
        base.volume_filter = random.random() > 0.3

        return base
