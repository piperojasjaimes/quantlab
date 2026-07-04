"""Mutation Agent — evolves best strategies into new variants."""
from __future__ import annotations

import random
from typing import Any

from agents.base_agent import BaseAgent
from core.models import Strategy, StrategyParams, Task
from core.config import config
from core.logger import get_logger

log = get_logger("agent.mutation")


class MutationAgent(BaseAgent):
    name = "mutation"

    async def execute(self, task: Task) -> dict:
        strategy_data = task.params.get("strategy", {})
        mutation_type = task.params.get("mutation_type", "auto")
        n_variants = task.params.get("n_variants", 3)

        log.info("Mutating strategy: %s (%d variants)", strategy_data.get("name", "?"), n_variants)

        variants = []
        for i in range(n_variants):
            variant = self._mutate(strategy_data, mutation_type)
            variant["mutation_index"] = i + 1
            variants.append(variant)
            log.info("Generated variant: %s", variant.get("name", "?"))

        return {"variants": variants, "count": len(variants)}

    def _mutate(self, strategy_data: dict, mutation_type: str) -> dict:
        if mutation_type == "auto":
            mutation_type = random.choice(["param_tweak", "add_filter", "remove_filter", "timeframe_shift", "combine_indicators"])

        params = dict(strategy_data.get("params", {}))
        name_parts = [strategy_data.get("name", "strat")]

        if mutation_type == "param_tweak":
            params, name_parts = self._param_tweak(params, name_parts)
        elif mutation_type == "add_filter":
            params, name_parts = self._add_filter(params, name_parts)
        elif mutation_type == "remove_filter":
            params, name_parts = self._remove_filter(params, name_parts)
        elif mutation_type == "timeframe_shift":
            params, name_parts = self._timeframe_shift(params, name_parts, strategy_data)
        elif mutation_type == "combine_indicators":
            params, name_parts = self._combine_indicators(params, name_parts)

        new_name = "_".join(name_parts) + f"_m{random.randint(1000, 9999)}"
        return {
            "name": new_name,
            "pattern": strategy_data.get("pattern", "trend_following"),
            "timeframe": strategy_data.get("timeframe", "M15"),
            "symbol": strategy_data.get("symbol", "EURUSD"),
            "params": params,
            "parent_id": strategy_data.get("id", ""),
            "mutation_type": mutation_type,
        }

    def _param_tweak(self, params: dict, name_parts: list) -> tuple[dict, list]:
        key = random.choice(["ema_fast", "ema_slow", "rsi_period", "atr_period", "stop_loss", "take_profit", "atr_multiplier", "trailing_stop"])
        if key in params:
            val = params[key]
            if isinstance(val, float):
                params[key] = round(val * random.uniform(0.7, 1.3), 1)
            else:
                delta = max(1, int(abs(val) * 0.2))
                params[key] = val + random.randint(-delta, delta)
        name_parts.append(f"tweak{key}")
        return params, name_parts

    def _add_filter(self, params: dict, name_parts: list) -> tuple[dict, list]:
        filters = ["adx_threshold", "volume_filter", "session_start", "session_end"]
        chosen = random.choice(filters)
        if chosen == "adx_threshold":
            params["adx_threshold"] = random.randint(20, 35)
        elif chosen == "volume_filter":
            params["volume_filter"] = True
        elif chosen == "session_start":
            params["session_start"] = random.randint(6, 10)
        elif chosen == "session_end":
            params["session_end"] = random.randint(18, 23)
        name_parts.append(f"+{chosen}")
        return params, name_parts

    def _remove_filter(self, params: dict, name_parts: list) -> tuple[dict, list]:
        removable = ["adx_threshold", "volume_filter"]
        for key in removable:
            if key in params:
                del params[key]
                name_parts.append(f"-{key}")
                break
        return params, name_parts

    def _timeframe_shift(self, params: dict, name_parts: list, strategy_data: dict) -> tuple[dict, list]:
        tfs = ["M5", "M15", "M30", "H1", "H4"]
        current_tf = strategy_data.get("timeframe", "M15")
        idx = tfs.index(current_tf) if current_tf in tfs else 1
        new_idx = min(idx + random.choice([-1, 1]), len(tfs) - 1)
        new_tf = tfs[max(new_idx, 0)]
        name_parts.append(f"tf{new_tf}")
        return params, name_parts

    def _combine_indicators(self, params: dict, name_parts: list) -> tuple[dict, list]:
        params["ema_fast"] = random.randint(5, 25)
        params["ema_slow"] = random.randint(30, 100)
        params["rsi_period"] = random.randint(7, 25)
        params["atr_period"] = random.randint(7, 20)
        params["atr_multiplier"] = round(random.uniform(1.0, 2.5), 1)
        name_parts.append("combo")
        return params, name_parts
