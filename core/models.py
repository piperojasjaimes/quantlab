"""Data models for QuantLab."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    STRATEGY_GENERATE = "strategy_generate"
    STRATEGY_CODE = "strategy_code"
    BACKTEST_RUN = "backtest_run"
    OPTIMIZE = "optimize"
    VALIDATE = "validate"
    MUTATE = "mutate"
    RANK = "rank"
    REPORT = "report"


class AgentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    STOPPED = "stopped"


class StrategyPattern(str, Enum):
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    SCALPING = "scalping"
    SWING = "swing"
    GRID = "grid"
    MARTINGALE_ADAPTIVE = "martingale_adaptive"
    SESSION_BASED = "session_based"
    KILLZONE_TRADING = "killzone_trading"
    SMC_STRUCTURE = "smc_structure"


class Timeframe(str, Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"


# ── Task ─────────────────────────────────────────────────────────────────────

class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    agent: str = ""
    strategy_id: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    retries: int = 0
    error: str = ""
    parent_task_id: str = ""


# ── Strategy ─────────────────────────────────────────────────────────────────

class StrategyParams(BaseModel):
    stop_loss: int = 50
    take_profit: int = 100
    ema_fast: int = 12
    ema_slow: int = 26
    rsi_period: int = 14
    rsi_overbought: int = 70
    rsi_oversold: int = 30
    atr_period: int = 14
    atr_multiplier: float = 1.5
    trailing_stop: int = 30
    lot_size: float = 0.1
    max_positions: int = 1
    session_start: int = 8
    session_end: int = 20
    volume_filter: bool = True
    adx_threshold: int = 25


class Strategy(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    version: int = 1
    parent_id: str = ""
    pattern: StrategyPattern = StrategyPattern.TREND_FOLLOWING
    timeframe: Timeframe = Timeframe.M15
    symbol: str = "EURUSD"
    params: StrategyParams = Field(default_factory=StrategyParams)
    code_path: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    generation: int = 0
    depth: int = 0
    fitness: float = 0.0
    is_active: bool = True


# ── Backtest Result ──────────────────────────────────────────────────────────

class BacktestMetrics(BaseModel):
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    net_profit: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    recovery_factor: float = 0.0
    expectancy: float = 0.0
    ulcer_index: float = 0.0
    mar_ratio: float = 0.0
    avg_trade: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_duration: float = 0.0
    equity_curve: list[float] = Field(default_factory=list)
    monthly_returns: dict[str, float] = Field(default_factory=dict)


class BacktestResult(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    strategy_id: str
    strategy_name: str = ""
    metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    optimization_params: dict[str, Any] = Field(default_factory=dict)
    walk_forward_results: list[dict[str, Any]] = Field(default_factory=list)
    monte_carlo_results: dict[str, Any] = Field(default_factory=dict)
    stress_test_results: dict[str, Any] = Field(default_factory=dict)
    html_report_path: str = ""
    csv_path: str = ""
    json_path: str = ""
    png_path: str = ""
    status: str = "pending"  # pending | passed | failed
    rejection_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Agent State ──────────────────────────────────────────────────────────────

class AgentState(BaseModel):
    name: str
    status: AgentStatus = AgentStatus.IDLE
    current_task_id: str = ""
    tasks_completed: int = 0
    tasks_failed: int = 0
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str = ""


# ── System State ─────────────────────────────────────────────────────────────

class SystemState(BaseModel):
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_strategies_generated: int = 0
    total_backtests_run: int = 0
    total_optimizations_run: int = 0
    total_validations_run: int = 0
    strategies_in_ranking: int = 0
    is_paused: bool = False
    current_cycle: int = 0
    agents: dict[str, AgentState] = Field(default_factory=dict)
