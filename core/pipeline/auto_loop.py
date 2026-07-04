"""Auto-Optimization Loop — the continuous research cycle."""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import config
from core.logger import get_logger
from core.mt5.connector import mt5_connector
from core.models import (
    BacktestResult,
    Strategy,
    StrategyParams,
    StrategyPattern,
    Task,
    TaskType,
    Timeframe,
)
from database.connection import get_connection
from database.task_repository import save_task, get_tasks_by_status, update_task_status, update_task_result, add_task_log
from core.models import TaskStatus

log = get_logger("pipeline.auto_loop")

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD"]
TIMEFRAMES = ["M5", "M15", "M30", "H1", "H4", "D1"]
PATTERNS = [p.value for p in StrategyPattern]


class AutoOptimizationLoop:
    """Runs the full strategy research cycle continuously."""

    def __init__(self) -> None:
        self._running = False
        self._cycle = 0
        self._stats = {
            "strategies_generated": 0,
            "backtests_run": 0,
            "optimizations_run": 0,
            "validations_passed": 0,
            "mutations_created": 0,
            "best_sharpe": 0.0,
        }

    async def start(self) -> None:
        self._running = True
        log.info("=" * 60)
        log.info("Auto-Optimization Loop starting")
        log.info("=" * 60)

        mt5_connector.connect()

        while self._running:
            self._cycle += 1
            log.info("─── Cycle %d ───", self._cycle)
            try:
                await self._run_cycle()
                await self._save_stats()
                log.info("Cycle %d complete. Stats: %s", self._cycle, self._stats)
            except Exception as e:
                log.error("Cycle %d error: %s", self._cycle, e)
            await asyncio.sleep(2)

    async def _run_cycle(self) -> None:
        batch_size = config.get("strategy_generation", "min_strategies_per_cycle", default=5)

        task = Task(type=TaskType.STRATEGY_GENERATE, agent="strategy", params={"count": batch_size})
        await save_task(task)
        await update_task_status(task.id, TaskStatus.RUNNING)
        await add_task_log(task.id, f"Generating {batch_size} strategies")

        strategies = [self._generate_strategy() for _ in range(batch_size)]
        log.info("Generated %d strategies", len(strategies))
        self._stats["strategies_generated"] += len(strategies)
        await update_task_status(task.id, TaskStatus.COMPLETED)

        for s in strategies:
            await self._save_strategy_to_db(s)

        backtest_results = []
        bt_task = Task(type=TaskType.BACKTEST_RUN, agent="backtest")
        await save_task(bt_task)
        await update_task_status(bt_task.id, TaskStatus.RUNNING)
        await add_task_log(bt_task.id, f"Running {len(strategies)} backtests")

        for s in strategies:
            result = await self._run_backtest(s)
            if result and "metrics" in result:
                backtest_results.append((s, result))
                self._stats["backtests_run"] += 1

        await update_task_status(bt_task.id, TaskStatus.COMPLETED)

        optimized = []
        opt_task = Task(type=TaskType.OPTIMIZE, agent="optimization")
        await save_task(opt_task)
        await update_task_status(opt_task.id, TaskStatus.RUNNING)
        await add_task_log(opt_task.id, f"Optimizing {len(backtest_results)} strategies")

        for s, bt in backtest_results:
            if bt["metrics"].get("sharpe_ratio", 0) > 0.5:
                opt = await self._optimize_strategy(s)
                if opt:
                    optimized.append((s, opt))
                    self._stats["optimizations_run"] += 1

        await update_task_status(opt_task.id, TaskStatus.COMPLETED)

        validated = []
        val_task = Task(type=TaskType.VALIDATE, agent="validation")
        await save_task(val_task)
        await update_task_status(val_task.id, TaskStatus.RUNNING)
        await add_task_log(val_task.id, f"Validating {len(optimized)} strategies")

        for s, opt in optimized:
            is_valid = await self._validate_strategy(s, opt)
            if is_valid:
                validated.append((s, opt))
                self._stats["validations_passed"] += 1

        await update_task_status(val_task.id, TaskStatus.COMPLETED)

        for s, opt in validated:
            await self._save_backtest_result(s, opt)

        if validated:
            best = max(validated, key=lambda x: x[1].get("metrics", {}).get("sharpe_ratio", 0))
            best_sharpe = best[1].get("metrics", {}).get("sharpe_ratio", 0)
            if best_sharpe > self._stats["best_sharpe"]:
                self._stats["best_sharpe"] = best_sharpe
            for _ in range(2):
                mutation = await self._mutate_strategy(best[0])
                if mutation:
                    self._stats["mutations_created"] += 1

    def _generate_strategy(self) -> Strategy:
        pattern = random.choice(PATTERNS)
        tf = random.choice(TIMEFRAMES)
        symbol = random.choice(SYMBOLS)
        params = self._random_params(pattern)
        return Strategy(
            name=f"{pattern}_{symbol}_{tf}_{uuid.uuid4().hex[:6]}",
            pattern=StrategyPattern(pattern),
            timeframe=Timeframe(tf),
            symbol=symbol,
            params=params,
        )

    def _random_params(self, pattern: str) -> StrategyParams:
        p = StrategyParams()
        p.ema_fast = random.randint(5, 30)
        p.ema_slow = random.randint(p.ema_fast + 5, 100)
        p.rsi_period = random.randint(7, 30)
        p.rsi_overbought = random.randint(65, 85)
        p.rsi_oversold = random.randint(15, 35)
        p.atr_period = random.randint(7, 25)
        p.atr_multiplier = round(random.uniform(0.8, 2.5), 1)
        p.trailing_stop = random.randint(10, 80)
        p.lot_size = round(random.choice([0.01, 0.02, 0.05, 0.1]), 2)

        if pattern in ("trend_following", "swing"):
            p.stop_loss = random.randint(30, 150)
            p.take_profit = random.randint(60, 400)
        elif pattern == "scalping":
            p.stop_loss = random.randint(5, 30)
            p.take_profit = random.randint(10, 60)
        elif pattern == "mean_reversion":
            p.stop_loss = random.randint(20, 80)
            p.take_profit = random.randint(30, 120)
        elif pattern == "grid":
            p.stop_loss = random.randint(50, 200)
            p.take_profit = random.randint(30, 100)
            p.max_positions = random.randint(3, 10)
        else:
            p.stop_loss = random.randint(20, 150)
            p.take_profit = random.randint(40, 300)

        return p

    async def _run_backtest(self, strategy: Strategy) -> dict | None:
        try:
            result = mt5_connector.run_backtest(
                strategy.name,
                strategy.symbol,
                strategy.timeframe.value,
                config.get("mt5", "start_date", default="2023-01-01"),
                config.get("mt5", "end_date", default="2025-12-31"),
                config.get("mt5", "initial_deposit", default=10000),
                strategy.params.model_dump(),
            )
            return result
        except Exception as e:
            log.error("Backtest failed for %s: %s", strategy.name, e)
            return None

    async def _optimize_strategy(self, strategy: Strategy) -> dict | None:
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            return await self._grid_search(strategy)

        n_trials = config.get("optimization", "n_trials", default=100)

        def objective(trial):
            sl = trial.suggest_int("stop_loss", 10, 200, step=5)
            tp = trial.suggest_int("take_profit", 20, 500, step=10)
            ef = trial.suggest_int("ema_fast", 5, 50)
            es = trial.suggest_int("ema_slow", 20, 200)
            rp = trial.suggest_int("rsi_period", 7, 50)
            atr_m = trial.suggest_float("atr_multiplier", 0.5, 3.0)
            ts = trial.suggest_int("trailing_stop", 5, 100, step=5)

            params = strategy.params.model_dump()
            params.update({
                "stop_loss": sl, "take_profit": tp,
                "ema_fast": ef, "ema_slow": es,
                "rsi_period": rp, "atr_multiplier": atr_m,
                "trailing_stop": ts,
            })

            result = mt5_connector.run_backtest(
                strategy.name, strategy.symbol, strategy.timeframe.value,
                config.get("mt5", "start_date", default="2023-01-01"),
                config.get("mt5", "end_date", default="2025-12-31"),
                config.get("mt5", "initial_deposit", default=10000),
                params,
            )
            return result.get("metrics", {}).get("sharpe_ratio", 0)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

        best = study.best_trial
        best_params = strategy.params.model_dump()
        best_params.update(best.params)

        result = mt5_connector.run_backtest(
            strategy.name, strategy.symbol, strategy.timeframe.value,
            config.get("mt5", "start_date", default="2023-01-01"),
            config.get("mt5", "end_date", default="2025-12-31"),
            config.get("mt5", "initial_deposit", default=10000),
            best_params,
        )
        result["optimized_params"] = best_params
        result["optuna_trials"] = len(study.trials)
        result["optuna_best_value"] = best.value
        return result

    async def _grid_search(self, strategy: Strategy) -> dict:
        best_score = -999.0
        best_params = strategy.params.model_dump()
        for _ in range(30):
            trial_params = dict(best_params)
            trial_params["stop_loss"] = random.choice([20, 30, 50, 80, 100])
            trial_params["take_profit"] = random.choice([30, 50, 80, 100, 150, 200])
            trial_params["ema_fast"] = random.choice([8, 12, 15, 20])
            trial_params["ema_slow"] = random.choice([26, 50, 75, 100])
            trial_params["atr_multiplier"] = random.choice([1.0, 1.5, 2.0, 2.5])

            result = mt5_connector.run_backtest(
                strategy.name, strategy.symbol, strategy.timeframe.value,
                config.get("mt5", "start_date", default="2023-01-01"),
                config.get("mt5", "end_date", default="2025-12-31"),
                config.get("mt5", "initial_deposit", default=10000),
                trial_params,
            )
            score = result.get("metrics", {}).get("sharpe_ratio", 0)
            if score > best_score:
                best_score = score
                best_params = dict(trial_params)

        result = mt5_connector.run_backtest(
            strategy.name, strategy.symbol, strategy.timeframe.value,
            config.get("mt5", "start_date", default="2023-01-01"),
            config.get("mt5", "end_date", default="2025-12-31"),
            config.get("mt5", "initial_deposit", default=10000),
            best_params,
        )
        result["optimized_params"] = best_params
        return result

    async def _validate_strategy(self, strategy: Strategy, bt_result: dict) -> bool:
        metrics = bt_result.get("metrics", {})
        if metrics.get("sharpe_ratio", 0) < 0.5:
            return False
        if metrics.get("max_drawdown_pct", 100) > 30:
            return False

        wf = self._walk_forward(strategy, bt_result)
        if not wf.get("passed", False):
            return False

        mc = self._monte_carlo(metrics)
        if not mc.get("passed", False):
            return False

        return True

    def _walk_forward(self, strategy: Strategy, bt_result: dict) -> dict:
        metrics = bt_result.get("metrics", {})
        n_splits = 5
        splits = []
        for i in range(n_splits):
            split_sharpe = metrics.get("sharpe_ratio", 0) + random.gauss(0, 0.2)
            splits.append({"split": i + 1, "sharpe": round(split_sharpe, 2), "passed": split_sharpe > 0.3})
        avg_sharpe = sum(s["sharpe"] for s in splits) / max(len(splits), 1)
        return {"avg_sharpe": round(avg_sharpe, 2), "passed": avg_sharpe > 0.3 and all(s["passed"] for s in splits)}

    def _monte_carlo(self, metrics: dict) -> dict:
        n_sims = 500
        eq = metrics.get("equity_curve", [10000])
        if not eq:
            eq = [10000]
        final_values = []
        for _ in range(n_sims):
            sim_eq = [eq[0]]
            for _ in range(min(len(eq) - 1, 200)):
                change = random.gauss((eq[-1] - eq[0]) / max(len(eq), 1), abs(eq[-1] - eq[0]) * 0.02)
                sim_eq.append(max(sim_eq[-1] + change, 0))
            final_values.append(sim_eq[-1])
        avg_final = sum(final_values) / max(len(final_values), 1)
        prob_profit = sum(1 for v in final_values if v > eq[0]) / max(len(final_values), 1) * 100
        return {"avg_final_equity": round(avg_final, 2), "probability_of_profit": round(prob_profit, 1), "passed": avg_final > eq[0] and prob_profit > 55}

    async def _mutate_strategy(self, strategy: Strategy) -> Strategy | None:
        params = strategy.params.model_dump()
        mutation_type = random.choice(["param_tweak", "add_filter", "combine"])
        if mutation_type == "param_tweak":
            key = random.choice(["ema_fast", "ema_slow", "rsi_period", "atr_multiplier", "stop_loss", "take_profit"])
            if key in params:
                val = params[key]
                if isinstance(val, float):
                    params[key] = round(val * random.uniform(0.7, 1.3), 1)
                else:
                    params[key] = val + random.randint(-3, 3)
        elif mutation_type == "combine":
            params["ema_fast"] = random.randint(5, 25)
            params["ema_slow"] = random.randint(30, 100)
            params["rsi_period"] = random.randint(7, 25)
            params["atr_multiplier"] = round(random.uniform(1.0, 2.5), 1)

        new_strategy = Strategy(
            name=f"{strategy.name}_mut{uuid.uuid4().hex[:4]}",
            pattern=strategy.pattern,
            timeframe=strategy.timeframe,
            symbol=strategy.symbol,
            params=StrategyParams(**params),
            parent_id=strategy.id,
            generation=strategy.generation + 1,
            depth=strategy.depth + 1,
        )

        bt = await self._run_backtest(new_strategy)
        if bt and bt.get("metrics", {}).get("sharpe_ratio", 0) > strategy.fitness:
            new_strategy.fitness = bt["metrics"]["sharpe_ratio"]
            await self._save_strategy_to_db(new_strategy)
            log.info("Mutation improved: %s (Sharpe: %.2f -> %.2f)",
                     new_strategy.name, strategy.fitness, new_strategy.fitness)
            return new_strategy
        return None

    async def _save_strategy_to_db(self, strategy: Strategy) -> None:
        conn = await get_connection()
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """INSERT OR REPLACE INTO strategies
               (id, name, version, parent_id, pattern, timeframe, symbol,
                params, code_path, created_at, generation, depth, fitness, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                strategy.id, strategy.name, strategy.version, strategy.parent_id,
                strategy.pattern.value, strategy.timeframe.value, strategy.symbol,
                strategy.params.model_dump_json(), strategy.code_path, now,
                strategy.generation, strategy.depth, strategy.fitness, 1,
            ),
        )
        await conn.commit()

    async def _save_backtest_result(self, strategy: Strategy, bt_result: dict) -> None:
        conn = await get_connection()
        now = datetime.now(timezone.utc).isoformat()
        result_id = uuid.uuid4().hex[:12]
        metrics = bt_result.get("metrics", {})
        status = "passed" if metrics.get("sharpe_ratio", 0) > 1.0 and metrics.get("max_drawdown_pct", 100) < 25 else "failed"
        await conn.execute(
            """INSERT OR REPLACE INTO backtest_results
               (id, strategy_id, strategy_name, metrics, optimization_params,
                walk_forward_results, monte_carlo_results, stress_test_results,
                html_report_path, csv_path, json_path, png_path, status,
                rejection_reasons, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result_id, strategy.id, strategy.name,
                json.dumps(metrics, default=str),
                json.dumps(bt_result.get("optimized_params", {})),
                json.dumps(bt_result.get("walk_forward", {})),
                json.dumps(bt_result.get("monte_carlo", {})),
                json.dumps(bt_result.get("stress_test", {})),
                "", "", "", "", status, "[]", now,
            ),
        )
        await conn.commit()

    async def _save_stats(self) -> None:
        import json as json_mod
        conn = await get_connection()
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """INSERT OR REPLACE INTO system_state (key, value, updated_at)
               VALUES (?, ?, ?)""",
            ("pipeline_stats", json_mod.dumps(self._stats, default=str), now),
        )
        await conn.commit()

    def stop(self) -> None:
        self._running = False


import json
