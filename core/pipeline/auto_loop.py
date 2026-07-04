"""Auto-Optimization Loop — FTMO Challenge Focus, 5 symbols, 3 directions."""
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
from core.ftmo.compliance import ftmo_checker
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

SYMBOLS = config.get("symbols", default=["XAUUSD", "BTCUSD", "ETHUSD", "NAS100", "US500"])
DIRECTIONS = config.get("strategy_generation", "directions", default=["bullish", "bearish", "directional"])
ANALYSIS_TF = config.get("strategy_generation", "analysis_timeframes", default=["H1", "M15", "M5"])
EXEC_TF = config.get("strategy_generation", "execution_timeframe", default="M1")
WINDOW_DAYS = config.get("backtest", "window_days", default=14)
MAX_HISTORY = config.get("backtest", "max_history_days", default=365)
VALIDATION_WEEKS = config.get("backtest", "validation_weeks", default=4)
MIN_WEEKS_PASSED = config.get("validation", "min_weeks_passed", default=3)

PATTERNS = {
    "bullish": ["ema_bullish_cross", "rsi_oversold_bounce", "macd_bullish_cross",
                "break_of_structure_bull", "fair_value_gap_bull"],
    "bearish": ["ema_bearish_cross", "rsi_overbought_reject", "macd_bearish_cross",
                "break_of_structure_bear", "fair_value_gap_bear"],
    "directional": ["ema_crossover", "macd_crossover", "rsi_momentum",
                     "momentum_breakout", "multi_tf_momentum"],
}

# Point values per symbol
POINTS = {
    "XAUUSD": 0.01, "BTCUSD": 0.01, "ETHUSD": 0.01,
    "NAS100": 0.01, "US500": 0.01,
}


class AutoOptimizationLoop:
    def __init__(self) -> None:
        self._running = False
        self._cycle = 0
        self._stats = {
            "strategies_generated": 0,
            "backtests_run": 0,
            "optimizations_run": 0,
            "ftmo_passed": 0,
            "mutations_created": 0,
            "best_ftmo_score": 0.0,
            "best_strategy": "",
            "windows_tested": 0,
            "symbols_tested": {},
        }

    async def start(self) -> None:
        self._running = True
        log.info("=" * 60)
        log.info("QuantLab v4 — FTMO Challenge Focus")
        log.info("Symbols: %s", ", ".join(SYMBOLS))
        log.info("Directions: %s", ", ".join(DIRECTIONS))
        log.info("2-week windows, real MT5 data, FTMO rules")
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
                log.info("Cycle %d done. Best FTMO: %.1f | %s",
                         self._cycle, self._stats["best_ftmo_score"],
                         self._stats["best_strategy"])
            except Exception as e:
                log.error("Cycle %d error: %s\n%s", self._cycle, e, traceback.format_exc())
            await asyncio.sleep(2)

    async def _run_cycle(self) -> None:
        # ── 1. Generate strategies for each symbol × direction ───────────────
        strategies = []
        for symbol in SYMBOLS:
            for direction in DIRECTIONS:
                batch = config.get("strategy_generation", "min_strategies_per_cycle", default=10) // (len(SYMBOLS) * len(DIRECTIONS))
                for _ in range(max(batch, 2)):
                    s = self._generate_strategy(symbol, direction)
                    await self._save_strategy_to_db(s)
                    strategies.append(s)
                    self._stats["strategies_generated"] += 1
        log.info("Generated %d strategies across %d symbols × %d directions",
                 len(strategies), len(SYMBOLS), len(DIRECTIONS))

        # ── 2. Backtest each strategy ────────────────────────────────────────
        all_results = []
        windows = self._get_2week_windows()[:10]

        for s in strategies:
            symbol = s.symbol
            window_results = []
            for w in windows:
                try:
                    result = await self._run_backtest(s, w)
                    if result and "metrics" in result:
                        window_results.append((w, result))
                        self._stats["backtests_run"] += 1
                        self._stats["windows_tested"] += 1
                except Exception as e:
                    log.error("Backtest error %s %s: %s", symbol, s.name[:20], e)

            if window_results:
                # FTMO check on each window
                ftmo_pass_count = 0
                for w, r in window_results:
                    eq = r.get("metrics", {}).get("equity_curve", [])
                    compliance = ftmo_checker.check(r["metrics"], eq)
                    if compliance["passed"]:
                        ftmo_pass_count += 1

                all_results.append((s, window_results, ftmo_pass_count))
                if symbol not in self._stats["symbols_tested"]:
                    self._stats["symbols_tested"][symbol] = 0
                self._stats["symbols_tested"][symbol] += 1

        # ── 3. Rank by FTMO compliance across windows ────────────────────────
        ranked = self._rank_by_ftmo(all_results)
        log.info("Ranked %d strategies. Top FTMO scores:", len(ranked))
        for s, score, details in ranked[:5]:
            log.info("  %s | Score=%.1f | Weeks passed: %d/%d | %s",
                     s.name[:40], score, details.get("weeks_passed", 0),
                     details.get("weeks_total", 0), s.symbol)

        # ── 4. Optimize and validate best strategies ─────────────────────────
        for s, score, details in ranked[:5]:
            if score < 50:
                continue
            try:
                opt = await self._optimize_strategy(s)
                if opt:
                    opt_compliance = ftmo_checker.check(
                        opt.get("metrics", {}),
                        opt.get("metrics", {}).get("equity_curve", []))
                    if opt_compliance["passed"]:
                        self._stats["ftmo_passed"] += 1
                        await self._save_backtest_result(s, opt, "passed",
                                                         opt_compliance["ftmo_score"])
                        log.info("FTMO PASSED: %s | Score=%.1f | Profit=$%.0f",
                                 s.name[:30], opt_compliance["ftmo_score"],
                                 opt["metrics"].get("net_profit", 0))
                    else:
                        await self._save_backtest_result(s, opt, "failed")
                    self._stats["optimizations_run"] += 1
            except Exception as e:
                log.error("Optimization error: %s", e)

        # ── 5. Mutate best ───────────────────────────────────────────────────
        if ranked and ranked[0][1] > 50:
            best = ranked[0][0]
            for _ in range(3):
                try:
                    m = await self._mutate_strategy(best)
                    if m:
                        self._stats["mutations_created"] += 1
                except Exception as e:
                    log.error("Mutation error: %s", e)

    def _generate_strategy(self, symbol: str, direction: str) -> Strategy:
        pattern = random.choice(PATTERNS[direction])
        params = self._random_params(pattern, direction, symbol)
        name = f"{pattern}_{symbol}_{EXEC_TF}_{uuid.uuid4().hex[:6]}"
        return Strategy(
            name=name,
            pattern=StrategyPattern.TREND_FOLLOWING,
            timeframe=Timeframe(EXEC_TF),
            symbol=symbol,
            params=params,
        )

    def _random_params(self, pattern: str, direction: str, symbol: str) -> StrategyParams:
        p = StrategyParams()
        # EMA settings
        if "ema" in pattern:
            p.ema_fast = random.choice([5, 8, 10, 13, 21])
            p.ema_slow = random.choice([21, 34, 50, 55, 89])
        elif "macd" in pattern:
            p.ema_fast = random.choice([8, 10, 12])
            p.ema_slow = random.choice([21, 26, 30])
        else:
            p.ema_fast = random.randint(5, 20)
            p.ema_slow = random.randint(20, 55)

        # RSI settings
        p.rsi_period = random.choice([7, 9, 14, 21])
        p.rsi_overbought = random.choice([70, 75, 80])
        p.rsi_oversold = random.choice([20, 25, 30])

        # SL/TP — risk 1% per trade ($1000 on $100k account)
        p.atr_period = random.choice([10, 14, 20])
        p.atr_multiplier = round(random.uniform(1.0, 2.5), 1)

        if direction == "bullish":
            p.stop_loss = random.choice([20, 30, 50, 80])
            p.take_profit = random.choice([40, 60, 100, 150, 200])
        elif direction == "bearish":
            p.stop_loss = random.choice([20, 30, 50, 80])
            p.take_profit = random.choice([40, 60, 100, 150, 200])
        else:
            p.stop_loss = random.choice([15, 20, 30, 50])
            p.take_profit = random.choice([30, 50, 80, 120, 200])

        p.trailing_stop = random.choice([10, 15, 20, 30, 50])
        # Lot size: risk $1000 per trade with SL
        p.lot_size = round(random.choice([0.01, 0.02, 0.05, 0.1]), 2)
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
            strategy.symbol, EXEC_TF, window["start"], window["end"])
        if rates is None or len(rates) < 100:
            return None
        import numpy as np
        closes = np.array([r[4] for r in rates])
        highs = np.array([r[2] for r in rates])
        lows = np.array([r[3] for r in rates])
        return mt5_connector._process_rates(closes, highs, lows,
                                            strategy.symbol, EXEC_TF,
                                            strategy.params.model_dump())

    def _rank_by_ftmo(self, all_results: list) -> list:
        ranked = []
        for s, window_results, ftmo_pass_count in all_results:
            if not window_results:
                continue
            # Average metrics across windows
            all_sharpes = [r.get("metrics", {}).get("sharpe_ratio", 0) for _, r in window_results]
            all_pf = [r.get("metrics", {}).get("profit_factor", 0) for _, r in window_results]
            all_dd = [r.get("metrics", {}).get("max_drawdown_pct", 0) for _, r in window_results]
            all_profit = [r.get("metrics", {}).get("net_profit", 0) for _, r in window_results]

            avg_sharpe = sum(all_sharpes) / max(len(all_sharpes), 1)
            avg_pf = sum(all_pf) / max(len(all_pf), 1)
            avg_dd = sum(all_dd) / max(len(all_dd), 1)
            avg_profit = sum(all_profit) / max(len(all_profit), 1)

            # FTMO score: weighted by weeks passed
            weeks_passed_ratio = ftmo_pass_count / max(len(window_results), 1)
            ftmo_score = weeks_passed_ratio * 60 + min(avg_sharpe * 10, 20) + min(avg_pf * 5, 20)

            details = {
                "weeks_passed": ftmo_pass_count,
                "weeks_total": len(window_results),
                "avg_sharpe": round(avg_sharpe, 2),
                "avg_pf": round(avg_pf, 2),
                "avg_dd": round(avg_dd, 2),
                "avg_profit": round(avg_profit, 2),
            }
            ranked.append((s, ftmo_score, details))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    async def _optimize_strategy(self, strategy: Strategy) -> dict | None:
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            return None

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
            ftmo_scores = []
            for w in windows:
                rates = mt5_connector.get_rates_range(strategy.symbol, EXEC_TF, w["start"], w["end"])
                if rates is None or len(rates) < 100:
                    continue
                import numpy as np
                closes = np.array([r[4] for r in rates])
                highs = np.array([r[2] for r in rates])
                lows = np.array([r[3] for r in rates])
                result = mt5_connector._process_rates(closes, highs, lows,
                                                      strategy.symbol, EXEC_TF, params)
                if result and "metrics" in result:
                    eq = result["metrics"].get("equity_curve", [])
                    compliance = ftmo_checker.check(result["metrics"], eq)
                    ftmo_scores.append(compliance["ftmo_score"])
            return sum(ftmo_scores) / max(len(ftmo_scores), 1)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
        best = study.best_trial
        best_params = strategy.params.model_dump()
        best_params.update(best.params)
        result = mt5_connector.run_backtest(
            strategy.name, strategy.symbol, EXEC_TF,
            windows[0]["start"], windows[0]["end"],
            config.get("mt5", "initial_deposit", default=100000), best_params)
        result["optimized_params"] = best_params
        return result

    async def _mutate_strategy(self, strategy: Strategy) -> Strategy | None:
        params = strategy.params.model_dump()
        mutation = random.choice(["param_tweak", "combine"])
        if mutation == "param_tweak":
            key = random.choice(["ema_fast", "ema_slow", "stop_loss", "take_profit", "atr_multiplier", "trailing_stop"])
            if key in params:
                val = params[key]
                if isinstance(val, float):
                    params[key] = round(val * random.uniform(0.7, 1.3), 1)
                else:
                    params[key] = val + random.randint(-5, 5)
        else:
            params["ema_fast"] = random.choice([5, 8, 10, 13, 21])
            params["ema_slow"] = random.choice([34, 50, 55, 89])
            params["atr_multiplier"] = round(random.uniform(1.0, 2.5), 1)

        new_s = Strategy(
            name=f"{strategy.name}_m{uuid.uuid4().hex[:4]}",
            pattern=strategy.pattern, timeframe=Timeframe(EXEC_TF),
            symbol=strategy.symbol, params=StrategyParams(**params),
            parent_id=strategy.id, generation=strategy.generation + 1,
            depth=strategy.depth + 1)
        await self._save_strategy_to_db(new_s)
        return new_s

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

    async def _save_backtest_result(self, strategy: Strategy, bt_result: dict,
                                     status: str, ftmo_score: float = 0.0) -> None:
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
                 json.dumps({"ftmo_score": ftmo_score}),
                 json.dumps({}), json.dumps({}),
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
