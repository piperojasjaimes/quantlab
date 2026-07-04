"""Auto-Optimization Loop — XAUUSD Momentum Focus, 2-week rolling windows."""
from __future__ import annotations

import asyncio
import json
import random
import traceback
import uuid
from datetime import datetime, timedelta, timezone
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

SYMBOL = "XAUUSD"
ANALYSIS_TF = ["H1", "M15", "M5"]
EXEC_TF = "M1"
WINDOW_DAYS = config.get("backtest", "window_days", default=14)
MAX_HISTORY = config.get("backtest", "max_history_days", default=365)

MOMENTUM_PATTERNS = [
    "macd_crossover", "macd_divergence", "rsi_momentum", "rsi_reversal",
    "ema_crossover", "ema_triple", "momentum_breakout",
    "macd_rsi_confluence", "ema_macd_combined", "multi_tf_momentum",
]


class AutoOptimizationLoop:
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
            "best_strategy": "",
            "windows_tested": 0,
        }

    async def start(self) -> None:
        self._running = True
        log.info("=" * 60)
        log.info("QuantLab v3 — XAUUSD Momentum Focus")
        log.info("2-week rolling windows, real MT5 data, M1 execution")
        log.info("=" * 60)

        try:
            mt5_connector.connect()
        except Exception as e:
            log.error("MT5 connection failed: %s", e)
            return

        await self._save_stats()

        while self._running:
            self._cycle += 1
            log.info("─── Cycle %d ───", self._cycle)
            try:
                await self._run_cycle()
                await self._save_stats()
                log.info("Cycle %d done. Best Sharpe: %.2f | Strategy: %s",
                         self._cycle, self._stats["best_sharpe"], self._stats["best_strategy"])
            except Exception as e:
                log.error("Cycle %d error: %s\n%s", self._cycle, e, traceback.format_exc())
            await asyncio.sleep(2)

    async def _run_cycle(self) -> None:
        # ── 1. Generate momentum strategies ──────────────────────────────────
        batch = config.get("strategy_generation", "min_strategies_per_cycle", default=8)
        strategies = []
        for _ in range(batch):
            s = self._generate_momentum_strategy()
            await self._save_strategy_to_db(s)
            strategies.append(s)
            self._stats["strategies_generated"] += 1
        log.info("Generated %d XAUUSD momentum strategies", len(strategies))

        # ── 2. Backtest each strategy across 2-week windows ──────────────────
        all_results = []
        windows = self._get_2week_windows()[:10]
        log.info("Testing %d strategies across %d windows", len(strategies), len(windows))

        for s in strategies:
            for window in windows:
                try:
                    result = await self._run_backtest(s, window)
                    if result and "metrics" in result:
                        m = result["metrics"]
                        all_results.append((s, result))
                        self._stats["backtests_run"] += 1
                        self._stats["windows_tested"] += 1
                        log.info("  %s | %s→%s | Sharpe=%.2f PF=%.2f DD=%.1f%% Trades=%d",
                                 s.name[:35],
                                 window["start"][:10], window["end"][:10],
                                 m.get("sharpe_ratio", 0),
                                 m.get("profit_factor", 0),
                                 m.get("max_drawdown_pct", 0),
                                 m.get("total_trades", 0))
                except Exception as e:
                    log.error("Backtest error %s: %s", s.name[:20], e)

        # ── 3. Optimize best strategies ──────────────────────────────────────
        best_candidates = self._aggregate_results(all_results)
        optimized = []
        for s, avg_metrics in best_candidates[:3]:
            try:
                opt = await self._optimize_strategy(s)
                if opt:
                    optimized.append((s, opt))
                    self._stats["optimizations_run"] += 1
                    log.info("Optimized %s: Sharpe=%.2f", s.name[:30],
                             opt.get("metrics", {}).get("sharpe_ratio", 0))
            except Exception as e:
                log.error("Optimization error: %s", e)

        # ── 4. Validate and save ─────────────────────────────────────────────
        validated = []
        for s, opt in optimized:
            if self._validate(opt):
                validated.append((s, opt))
                self._stats["validations_passed"] += 1
                await self._save_backtest_result(s, opt, "passed")
                log.info("VALIDATED: %s | Sharpe=%.2f", s.name[:30],
                         opt.get("metrics", {}).get("sharpe_ratio", 0))
            else:
                await self._save_backtest_result(s, opt, "failed")

        # ── 5. Mutate best ───────────────────────────────────────────────────
        if validated:
            best = max(validated, key=lambda x: x[1].get("metrics", {}).get("sharpe_ratio", 0))
            best_sharpe = best[1].get("metrics", {}).get("sharpe_ratio", 0)
            if best_sharpe > self._stats["best_sharpe"]:
                self._stats["best_sharpe"] = best_sharpe
                self._stats["best_strategy"] = best[0].name

            for _ in range(3):
                try:
                    m = await self._mutate_strategy(best[0])
                    if m:
                        self._stats["mutations_created"] += 1
                except Exception as e:
                    log.error("Mutation error: %s", e)

    def _generate_momentum_strategy(self) -> Strategy:
        pattern = random.choice(MOMENTUM_PATTERNS)
        params = self._random_momentum_params(pattern)
        name = f"{pattern}_{SYMBOL}_{EXEC_TF}_{uuid.uuid4().hex[:6]}"
        return Strategy(
            name=name,
            pattern=StrategyPattern.TREND_FOLLOWING,
            timeframe=Timeframe(EXEC_TF),
            symbol=SYMBOL,
            params=params,
        )

    def _random_momentum_params(self, pattern: str) -> StrategyParams:
        p = StrategyParams()
        if "macd" in pattern:
            p.ema_fast = random.choice([8, 10, 12])
            p.ema_slow = random.choice([21, 26, 30])
        elif "ema" in pattern:
            p.ema_fast = random.choice([5, 8, 10, 13])
            p.ema_slow = random.choice([21, 34, 50, 55])
        elif "rsi" in pattern:
            p.rsi_period = random.choice([7, 9, 14, 21])
            p.rsi_overbought = random.choice([70, 75, 80])
            p.rsi_oversold = random.choice([20, 25, 30])
        else:
            p.ema_fast = random.randint(5, 20)
            p.ema_slow = random.randint(20, 55)

        p.stop_loss = random.choice([15, 20, 30, 40, 50, 80, 100])
        p.take_profit = random.choice([30, 50, 80, 100, 150, 200, 300])
        p.atr_period = random.choice([10, 14, 20])
        p.atr_multiplier = round(random.uniform(1.0, 2.5), 1)
        p.trailing_stop = random.choice([15, 20, 30, 50, 80])
        p.lot_size = round(random.choice([0.01, 0.02, 0.05, 0.1]), 2)
        p.rsi_period = p.rsi_period if p.rsi_period > 0 else 14
        p.rsi_overbought = p.rsi_overbought if p.rsi_overbought > 0 else 70
        p.rsi_oversold = p.rsi_oversold if p.rsi_oversold > 0 else 30
        return p

    def _get_2week_windows(self) -> list[dict]:
        windows = []
        end = datetime.now()
        start_limit = end - timedelta(days=MAX_HISTORY)
        while end > start_limit:
            win_start = end - timedelta(days=WINDOW_DAYS)
            windows.append({
                "start": win_start.strftime("%Y-%m-%d"),
                "end": end.strftime("%Y-%m-%d"),
            })
            end = win_start
        return windows

    async def _run_backtest(self, strategy: Strategy, window: dict) -> dict | None:
        rates = mt5_connector.get_rates_range(
            SYMBOL, EXEC_TF, window["start"], window["end"])
        if rates is None or len(rates) < 100:
            return None
        import numpy as np
        closes = np.array([r[4] for r in rates])
        highs = np.array([r[2] for r in rates])
        lows = np.array([r[3] for r in rates])
        return mt5_connector._process_rates(closes, highs, lows, SYMBOL, EXEC_TF,
                                            strategy.params.model_dump())

    def _aggregate_results(self, all_results: list[tuple]) -> list[tuple]:
        from collections import defaultdict
        by_strategy = defaultdict(list)
        for s, r in all_results:
            by_strategy[s.id].append((s, r))
        ranked = []
        for sid, results in by_strategy.items():
            sharpes = [r.get("metrics", {}).get("sharpe_ratio", 0) for _, r in results]
            avg_sharpe = sum(sharpes) / max(len(sharpes), 1)
            avg_dd = sum(r.get("metrics", {}).get("max_drawdown_pct", 0) for _, r in results) / max(len(results), 1)
            avg_pf = sum(r.get("metrics", {}).get("profit_factor", 0) for _, r in results) / max(len(results), 1)
            best_result = max(results, key=lambda x: x[1].get("metrics", {}).get("sharpe_ratio", 0))
            avg_metrics = {
                "sharpe_ratio": round(avg_sharpe, 2),
                "max_drawdown_pct": round(avg_dd, 2),
                "profit_factor": round(avg_pf, 2),
                "windows_tested": len(results),
                **best_result[1].get("metrics", {}),
            }
            ranked.append((results[0][0], {"metrics": avg_metrics}))
        ranked.sort(key=lambda x: x[1].get("metrics", {}).get("sharpe_ratio", 0), reverse=True)
        return ranked

    def _validate(self, bt_result: dict) -> bool:
        m = bt_result.get("metrics", {})
        v = config.get("validation", default={})
        if m.get("sharpe_ratio", 0) < v.get("min_sharpe", 0.8):
            return False
        if m.get("max_drawdown_pct", 100) > v.get("max_drawdown_pct", 25):
            return False
        if m.get("profit_factor", 0) < v.get("min_profit_factor", 1.3):
            return False
        if m.get("total_trades", 0) < v.get("min_trades", 20):
            return False
        return True

    async def _optimize_strategy(self, strategy: Strategy) -> dict | None:
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            return await self._grid_search(strategy)

        n_trials = config.get("optimization", "n_trials", default=100)
        windows = self._get_2week_windows()[:5]

        def objective(trial):
            sl = trial.suggest_int("stop_loss", 10, 200, step=5)
            tp = trial.suggest_int("take_profit", 20, 500, step=10)
            ef = trial.suggest_int("ema_fast", 5, 50)
            es = trial.suggest_int("ema_slow", 20, 100)
            atr_m = trial.suggest_float("atr_multiplier", 0.5, 3.0)
            ts = trial.suggest_int("trailing_stop", 5, 100, step=5)
            params = strategy.params.model_dump()
            params.update({"stop_loss": sl, "take_profit": tp, "ema_fast": ef,
                           "ema_slow": es, "atr_multiplier": atr_m, "trailing_stop": ts})
            all_sharpes = []
            for w in windows:
                rates = mt5_connector.get_rates_range(SYMBOL, EXEC_TF, w["start"], w["end"])
                if rates is None or len(rates) < 100:
                    continue
                import numpy as np
                closes = np.array([r[4] for r in rates])
                highs = np.array([r[2] for r in rates])
                lows = np.array([r[3] for r in rates])
                result = mt5_connector._process_rates(closes, highs, lows, SYMBOL, EXEC_TF, params)
                if result and "metrics" in result:
                    all_sharpes.append(result["metrics"].get("sharpe_ratio", 0))
            return sum(all_sharpes) / max(len(all_sharpes), 1)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
        best = study.best_trial
        best_params = strategy.params.model_dump()
        best_params.update(best.params)
        result = mt5_connector.run_backtest(
            strategy.name, SYMBOL, EXEC_TF,
            windows[0]["start"], windows[0]["end"],
            config.get("mt5", "initial_deposit", default=10000), best_params)
        result["optimized_params"] = best_params
        return result

    async def _grid_search(self, strategy: Strategy) -> dict:
        best_score = -999.0
        best_params = strategy.params.model_dump()
        windows = self._get_2week_windows()[:3]
        for _ in range(30):
            tp = dict(best_params)
            tp["stop_loss"] = random.choice([15, 20, 30, 50, 80])
            tp["take_profit"] = random.choice([30, 50, 80, 120, 200])
            tp["ema_fast"] = random.choice([5, 8, 12, 15])
            tp["ema_slow"] = random.choice([21, 34, 50, 55])
            tp["atr_multiplier"] = random.choice([1.0, 1.5, 2.0])
            tp["trailing_stop"] = random.choice([15, 20, 30, 50])
            all_sharpes = []
            for w in windows:
                rates = mt5_connector.get_rates_range(SYMBOL, EXEC_TF, w["start"], w["end"])
                if rates is None or len(rates) < 100:
                    continue
                import numpy as np
                closes = np.array([r[4] for r in rates])
                highs = np.array([r[2] for r in rates])
                lows = np.array([r[3] for r in rates])
                result = mt5_connector._process_rates(closes, highs, lows, SYMBOL, EXEC_TF, tp)
                if result and "metrics" in result:
                    all_sharpes.append(result["metrics"].get("sharpe_ratio", 0))
            score = sum(all_sharpes) / max(len(all_sharpes), 1)
            if score > best_score:
                best_score = score
                best_params = dict(tp)
        result = mt5_connector.run_backtest(
            strategy.name, SYMBOL, EXEC_TF,
            windows[0]["start"], windows[0]["end"],
            config.get("mt5", "initial_deposit", default=10000), best_params)
        result["optimized_params"] = best_params
        return result

    async def _mutate_strategy(self, strategy: Strategy) -> Strategy | None:
        params = strategy.params.model_dump()
        mutation = random.choice(["param_tweak", "combine", "timeframe_shift"])
        if mutation == "param_tweak":
            key = random.choice(["ema_fast", "ema_slow", "stop_loss", "take_profit", "atr_multiplier", "trailing_stop"])
            if key in params:
                val = params[key]
                if isinstance(val, float):
                    params[key] = round(val * random.uniform(0.7, 1.3), 1)
                else:
                    params[key] = val + random.randint(-5, 5)
        elif mutation == "combine":
            params["ema_fast"] = random.choice([5, 8, 10, 13, 21])
            params["ema_slow"] = random.choice([34, 50, 55, 89])
            params["atr_multiplier"] = round(random.uniform(1.0, 2.5), 1)
            params["trailing_stop"] = random.choice([15, 20, 30, 50])
        else:
            params["ema_fast"] = random.randint(5, 20)
            params["ema_slow"] = random.randint(21, 55)

        new_s = Strategy(
            name=f"{strategy.name}_m{uuid.uuid4().hex[:4]}",
            pattern=strategy.pattern, timeframe=Timeframe(EXEC_TF),
            symbol=SYMBOL, params=StrategyParams(**params),
            parent_id=strategy.id, generation=strategy.generation + 1,
            depth=strategy.depth + 1)
        await self._save_strategy_to_db(new_s)

        windows = self._get_2week_windows()[:3]
        all_sharpes = []
        for w in windows:
            rates = mt5_connector.get_rates_range(SYMBOL, EXEC_TF, w["start"], w["end"])
            if rates is None or len(rates) < 100:
                continue
            import numpy as np
            closes = np.array([r[4] for r in rates])
            highs = np.array([r[2] for r in rates])
            lows = np.array([r[3] for r in rates])
            result = mt5_connector._process_rates(closes, highs, lows, SYMBOL, EXEC_TF, params)
            if result and "metrics" in result:
                all_sharpes.append(result["metrics"].get("sharpe_ratio", 0))
        avg_sharpe = sum(all_sharpes) / max(len(all_sharpes), 1)
        if avg_sharpe > strategy.fitness:
            new_s.fitness = avg_sharpe
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
        except Exception as e:
            log.error("Failed to save strategy: %s", e)

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
                 json.dumps({}), json.dumps({}), json.dumps({}),
                 "", "", "", "", status, "[]", now))
            await conn.commit()
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
