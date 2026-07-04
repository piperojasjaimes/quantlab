"""Auto-Optimization Loop — the continuous research cycle."""
from __future__ import annotations

import asyncio
import json
import random
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import config
from core.logger import get_logger
from core.mt5.connector import mt5_connector
from core.models import (
    Strategy,
    StrategyParams,
    StrategyPattern,
    Task,
    TaskType,
    Timeframe,
    TaskStatus,
)
from database.connection import get_connection
from database.task_repository import save_task, update_task_status, add_task_log

log = get_logger("pipeline.loop")

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

        try:
            mt5_connector.connect()
        except Exception as e:
            log.warning("MT5 connect failed, using simulated: %s", e)

        await self._save_stats()

        while self._running:
            self._cycle += 1
            log.info("─── Cycle %d ───", self._cycle)
            try:
                await self._run_cycle()
                await self._save_stats()
                log.info("Cycle %d complete. Stats: %s", self._cycle, self._stats)
            except Exception as e:
                log.error("Cycle %d error: %s\n%s", self._cycle, e, traceback.format_exc())
            await asyncio.sleep(2)

    async def _run_cycle(self) -> None:
        batch_size = config.get("strategy_generation", "min_strategies_per_cycle", default=5)

        # ── 1. Generate Strategies ───────────────────────────────────────────
        await self._log_task("strategy", TaskType.STRATEGY_GENERATE, f"Generating {batch_size} strategies")

        strategies = []
        for _ in range(batch_size):
            try:
                s = self._generate_strategy()
                await self._save_strategy_to_db(s)
                strategies.append(s)
                self._stats["strategies_generated"] += 1
            except Exception as e:
                log.error("Strategy generation error: %s", e)

        log.info("Generated %d strategies, saved to DB", len(strategies))

        # ── 2. Run Backtests ─────────────────────────────────────────────────
        bt_results = []
        if strategies:
            await self._log_task("backtest", TaskType.BACKTEST_RUN, f"Running {len(strategies)} backtests")

            for s in strategies:
                try:
                    result = await self._run_backtest(s)
                    if result and "metrics" in result:
                        bt_results.append((s, result))
                        self._stats["backtests_run"] += 1
                        log.info("Backtest %s: Sharpe=%.2f PF=%.2f DD=%.1f%%",
                                 s.name[:30],
                                 result["metrics"].get("sharpe_ratio", 0),
                                 result["metrics"].get("profit_factor", 0),
                                 result["metrics"].get("max_drawdown_pct", 0))
                except Exception as e:
                    log.error("Backtest error for %s: %s", s.name, e)

        # ── 3. Optimize Best Strategies ──────────────────────────────────────
        optimized = []
        candidates = [(s, r) for s, r in bt_results if r.get("metrics", {}).get("sharpe_ratio", 0) > 0.3]
        if candidates:
            await self._log_task("optimization", TaskType.OPTIMIZE, f"Optimizing {len(candidates)} candidates")

            for s, bt in candidates[:3]:
                try:
                    opt = await self._optimize_strategy(s)
                    if opt:
                        optimized.append((s, opt))
                        self._stats["optimizations_run"] += 1
                        log.info("Optimized %s: Sharpe=%.2f",
                                 s.name[:30],
                                 opt.get("metrics", {}).get("sharpe_ratio", 0))
                except Exception as e:
                    log.error("Optimization error for %s: %s", s.name, e)

        # ── 4. Validate ──────────────────────────────────────────────────────
        validated = []
        if optimized:
            await self._log_task("validation", TaskType.VALIDATE, f"Validating {len(optimized)} optimized")

            for s, opt in optimized:
                try:
                    if self._validate(opt):
                        validated.append((s, opt))
                        self._stats["validations_passed"] += 1
                        await self._save_backtest_result(s, opt, "passed")
                        log.info("VALIDATED: %s", s.name[:30])
                    else:
                        await self._save_backtest_result(s, opt, "failed")
                        log.info("REJECTED: %s", s.name[:30])
                except Exception as e:
                    log.error("Validation error for %s: %s", s.name, e)

        # Also save non-optimized backtests that passed basic criteria
        for s, bt in bt_results:
            if bt.get("metrics", {}).get("sharpe_ratio", 0) > 0.5:
                already_saved = any(v[0].id == s.id for v in validated + optimized)
                if not already_saved:
                    try:
                        await self._save_backtest_result(s, bt, "passed")
                    except Exception:
                        pass

        # ── 5. Mutate Best ───────────────────────────────────────────────────
        if validated:
            best = max(validated, key=lambda x: x[1].get("metrics", {}).get("sharpe_ratio", 0))
            best_sharpe = best[1].get("metrics", {}).get("sharpe_ratio", 0)
            if best_sharpe > self._stats["best_sharpe"]:
                self._stats["best_sharpe"] = best_sharpe

            await self._log_task("mutation", TaskType.MUTATE, f"Mutating best: {best[0].name[:30]}")

            for _ in range(2):
                try:
                    mutation = await self._mutate_strategy(best[0])
                    if mutation:
                        self._stats["mutations_created"] += 1
                        log.info("Mutation improved: %s -> Sharpe=%.2f",
                                 mutation.name[:30], mutation.fitness)
                except Exception as e:
                    log.error("Mutation error: %s", e)

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
            log.error("Backtest failed: %s", e)
            return None

    async def _optimize_strategy(self, strategy: Strategy) -> dict | None:
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            return await self._grid_search(strategy)

        n_trials = config.get("optimization", "n_trials", default=50)

        def objective(trial):
            sl = trial.suggest_int("stop_loss", 10, 200, step=5)
            tp = trial.suggest_int("take_profit", 20, 500, step=10)
            ef = trial.suggest_int("ema_fast", 5, 50)
            es = trial.suggest_int("ema_slow", 20, 200)
            atr_m = trial.suggest_float("atr_multiplier", 0.5, 3.0)
            ts = trial.suggest_int("trailing_stop", 5, 100, step=5)
            params = strategy.params.model_dump()
            params.update({"stop_loss": sl, "take_profit": tp, "ema_fast": ef,
                           "ema_slow": es, "atr_multiplier": atr_m, "trailing_stop": ts})
            result = mt5_connector.run_backtest(
                strategy.name, strategy.symbol, strategy.timeframe.value,
                config.get("mt5", "start_date", default="2023-01-01"),
                config.get("mt5", "end_date", default="2025-12-31"),
                config.get("mt5", "initial_deposit", default=10000), params)
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
            config.get("mt5", "initial_deposit", default=10000), best_params)
        result["optimized_params"] = best_params
        return result

    async def _grid_search(self, strategy: Strategy) -> dict:
        best_score = -999.0
        best_params = strategy.params.model_dump()
        for _ in range(20):
            tp = dict(best_params)
            tp["stop_loss"] = random.choice([20, 30, 50, 80, 100])
            tp["take_profit"] = random.choice([30, 50, 80, 100, 150, 200])
            tp["ema_fast"] = random.choice([8, 12, 15, 20])
            tp["ema_slow"] = random.choice([26, 50, 75, 100])
            tp["atr_multiplier"] = random.choice([1.0, 1.5, 2.0, 2.5])
            result = mt5_connector.run_backtest(
                strategy.name, strategy.symbol, strategy.timeframe.value,
                config.get("mt5", "start_date", default="2023-01-01"),
                config.get("mt5", "end_date", default="2025-12-31"),
                config.get("mt5", "initial_deposit", default=10000), tp)
            score = result.get("metrics", {}).get("sharpe_ratio", 0)
            if score > best_score:
                best_score = score
                best_params = dict(tp)
        result = mt5_connector.run_backtest(
            strategy.name, strategy.symbol, strategy.timeframe.value,
            config.get("mt5", "start_date", default="2023-01-01"),
            config.get("mt5", "end_date", default="2025-12-31"),
            config.get("mt5", "initial_deposit", default=10000), best_params)
        result["optimized_params"] = best_params
        return result

    def _validate(self, bt_result: dict) -> bool:
        m = bt_result.get("metrics", {})
        if m.get("sharpe_ratio", 0) < 0.8:
            return False
        if m.get("max_drawdown_pct", 100) > 30:
            return False
        if m.get("profit_factor", 0) < 1.2:
            return False
        return True

    async def _mutate_strategy(self, strategy: Strategy) -> Strategy | None:
        params = strategy.params.model_dump()
        mutation_type = random.choice(["param_tweak", "combine"])
        if mutation_type == "param_tweak":
            key = random.choice(["ema_fast", "ema_slow", "rsi_period", "atr_multiplier", "stop_loss", "take_profit"])
            if key in params:
                val = params[key]
                if isinstance(val, float):
                    params[key] = round(val * random.uniform(0.7, 1.3), 1)
                else:
                    params[key] = val + random.randint(-3, 3)
        else:
            params["ema_fast"] = random.randint(5, 25)
            params["ema_slow"] = random.randint(30, 100)
            params["rsi_period"] = random.randint(7, 25)
            params["atr_multiplier"] = round(random.uniform(1.0, 2.5), 1)

        new_s = Strategy(
            name=f"{strategy.name}_m{uuid.uuid4().hex[:4]}",
            pattern=strategy.pattern, timeframe=strategy.timeframe,
            symbol=strategy.symbol, params=StrategyParams(**params),
            parent_id=strategy.id, generation=strategy.generation + 1,
            depth=strategy.depth + 1)
        await self._save_strategy_to_db(new_s)

        bt = await self._run_backtest(new_s)
        if bt and bt.get("metrics", {}).get("sharpe_ratio", 0) > strategy.fitness:
            new_s.fitness = bt["metrics"]["sharpe_ratio"]
            return new_s
        return None

    async def _save_strategy_to_db(self, strategy: Strategy) -> None:
        try:
            conn = await get_connection()
            now = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                """INSERT OR REPLACE INTO strategies
                   (id, name, version, parent_id, pattern, timeframe, symbol,
                    params, code_path, created_at, generation, depth, fitness, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (strategy.id, strategy.name, strategy.version, strategy.parent_id,
                 strategy.pattern.value, strategy.timeframe.value, strategy.symbol,
                 strategy.params.model_dump_json(), strategy.code_path, now,
                 strategy.generation, strategy.depth, strategy.fitness, 1))
            await conn.commit()
            log.debug("Saved strategy: %s", strategy.name)
        except Exception as e:
            log.error("Failed to save strategy %s: %s", strategy.name, e)

    async def _save_backtest_result(self, strategy: Strategy, bt_result: dict, status: str) -> None:
        try:
            conn = await get_connection()
            now = datetime.now(timezone.utc).isoformat()
            result_id = uuid.uuid4().hex[:12]
            metrics = bt_result.get("metrics", {})
            await conn.execute(
                """INSERT OR REPLACE INTO backtest_results
                   (id, strategy_id, strategy_name, metrics, optimization_params,
                    walk_forward_results, monte_carlo_results, stress_test_results,
                    html_report_path, csv_path, json_path, png_path, status,
                    rejection_reasons, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (result_id, strategy.id, strategy.name,
                 json.dumps(metrics, default=str),
                 json.dumps(bt_result.get("optimized_params", {})),
                 json.dumps(bt_result.get("walk_forward", {})),
                 json.dumps(bt_result.get("monte_carlo", {})),
                 json.dumps(bt_result.get("stress_test", {})),
                 "", "", "", "", status, "[]", now))
            await conn.commit()
            log.debug("Saved backtest result: %s [%s]", strategy.name, status)
        except Exception as e:
            log.error("Failed to save backtest result: %s", e)

    async def _save_stats(self) -> None:
        try:
            conn = await get_connection()
            now = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                """INSERT OR REPLACE INTO system_state (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                ("pipeline_stats", json.dumps(self._stats, default=str), now))
            await conn.commit()
        except Exception as e:
            log.error("Failed to save stats: %s", e)

    async def _log_task(self, agent: str, task_type: TaskType, message: str) -> None:
        try:
            task = Task(type=task_type, agent=agent)
            await save_task(task)
            await update_task_status(task.id, TaskStatus.RUNNING)
            await add_task_log(task.id, message)
            await update_task_status(task.id, TaskStatus.COMPLETED)
        except Exception as e:
            log.error("Task log error: %s", e)

    def stop(self) -> None:
        self._running = False
