"""Optimization Agent — uses Optuna to optimize strategy parameters."""
from __future__ import annotations

import random
from typing import Any

from agents.base_agent import BaseAgent
from core.models import StrategyParams, Task
from core.config import config
from core.logger import get_logger

log = get_logger("agent.optimization")


class OptimizationAgent(BaseAgent):
    name = "optimization"

    async def execute(self, task: Task) -> dict:
        strategy_data = task.params.get("strategy", {})
        n_trials = task.params.get("n_trials", config.get("optimization", "n_trials", default=200))

        log.info("Optimizing strategy: %s (%d trials)", strategy_data.get("name", "?"), n_trials)

        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            return self._run_optuna(strategy_data, n_trials)
        except ImportError:
            log.warning("Optuna not installed, using grid search")
            return self._run_grid_search(strategy_data, n_trials)

    def _run_optuna(self, strategy_data: dict, n_trials: int) -> dict:
        import optuna

        params = strategy_data.get("params", {})
        objective = task.params.get("objective", config.get("optimization", "target_metric", default="sharpe_ratio"))

        def optuna_objective(trial: optuna.Trial) -> float:
            sl = trial.suggest_int("stop_loss", 10, 200, step=5)
            tp = trial.suggest_int("take_profit", 20, 500, step=10)
            ema_f = trial.suggest_int("ema_fast", 5, 50, step=1)
            ema_s = trial.suggest_int("ema_slow", 20, 200, step=5)
            rsi_p = trial.suggest_int("rsi_period", 7, 50, step=1)
            rsi_ob = trial.suggest_int("rsi_overbought", 60, 90, step=5)
            rsi_os = trial.suggest_int("rsi_oversold", 10, 40, step=5)
            atr_p = trial.suggest_int("atr_period", 7, 30, step=1)
            atr_m = trial.suggest_float("atr_multiplier", 0.5, 3.0, step=0.1)
            ts = trial.suggest_int("trailing_stop", 5, 100, step=5)

            sim_params = {**params}
            sim_params.update({
                "stop_loss": sl, "take_profit": tp,
                "ema_fast": ema_f, "ema_slow": ema_s,
                "rsi_period": rsi_p, "rsi_overbought": rsi_ob,
                "rsi_oversold": rsi_os, "atr_period": atr_p,
                "atr_multiplier": atr_m, "trailing_stop": ts,
            })

            return self._simulate_fitness(sim_params)

        study = optuna.create_study(direction="maximize")
        study.optimize(optuna_objective, n_trials=n_trials, show_progress_bar=False)

        best = study.best_trial
        best_params = {**params}
        best_params.update(best.params)

        return {
            "best_params": best_params,
            "best_value": best.value,
            "n_trials": len(study.trials),
            "engine": "optuna",
        }

    def _run_grid_search(self, strategy_data: dict, n_trials: int) -> dict:
        params = strategy_data.get("params", {})
        best_score = -999.0
        best_params = dict(params)

        for _ in range(min(n_trials, 50)):
            trial_params = dict(params)
            trial_params["stop_loss"] = random.choice([20, 30, 50, 80, 100])
            trial_params["take_profit"] = random.choice([30, 50, 80, 100, 150, 200])
            trial_params["ema_fast"] = random.choice([8, 12, 15, 20])
            trial_params["ema_slow"] = random.choice([26, 50, 75, 100])
            trial_params["rsi_period"] = random.choice([7, 14, 21])
            trial_params["atr_multiplier"] = random.choice([1.0, 1.5, 2.0, 2.5])

            score = self._simulate_fitness(trial_params)
            if score > best_score:
                best_score = score
                best_params = dict(trial_params)

        return {
            "best_params": best_params,
            "best_value": best_score,
            "n_trials": min(n_trials, 50),
            "engine": "grid_search",
        }

    def _simulate_fitness(self, params: dict) -> float:
        import random as rng
        sl = params.get("stop_loss", 50)
        tp = params.get("take_profit", 100)
        rr = tp / max(sl, 1)
        base = rng.gauss(0.5, 0.3) + rr * 0.15
        if params.get("ema_fast", 12) < params.get("ema_slow", 26):
            base += 0.1
        return max(base, -2.0)
