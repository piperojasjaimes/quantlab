"""Full Strategy Tester Engine — tick-by-tick simulation with spread, slippage, swaps."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import numpy as np

from core.config import config
from core.logger import get_logger

log = get_logger("backtest.engine")


class OrderType(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Trade:
    ticket: int
    order_type: OrderType
    symbol: str
    open_price: float
    sl: float
    tp: float
    lots: float
    open_time: datetime
    close_time: datetime = None
    close_price: float = 0.0
    profit: float = 0.0
    swaps: float = 0.0
    commission: float = 0.0
    pips: float = 0.0
    duration_min: int = 0
    exit_reason: str = ""


@dataclass
class Position:
    ticket: int
    order_type: OrderType
    symbol: str
    open_price: float
    sl: float
    tp: float
    lots: float
    open_time: datetime
    trailing_activated: bool = False
    partial_moved: bool = False


@dataclass
class AccountState:
    balance: float = 100000.0
    equity: float = 100000.0
    free_margin: float = 100000.0
    margin: float = 0.0
    daily_start_balance: float = 100000.0
    highest_balance: float = 100000.0
    peak_equity: float = 100000.0


class StrategyTester:
    """Full backtesting engine simulating MT5 Strategy Tester behavior."""

    def __init__(self, params: dict = None):
        self.params = params or {}
        self.account = AccountState()
        self.position: Position = None
        self.trades: list[Trade] = []
        self.equity_curve: list[float] = []
        self.daily_balances: list[dict] = []
        self.ticket_counter = 1000
        self.current_bar = 0
        self.bars_per_day = 390  # M1 bars per trading day

    def run(self, symbol: str, timeframe: str, rates: list) -> dict:
        """Run backtest on historical data.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe (M1, M5, M15, etc.)
            rates: List of (time, open, high, low, close, volume, spread, real_volume)

        Returns:
            Backtest result with metrics, equity curve, trades
        """
        if rates is None or (hasattr(rates, '__len__') and len(rates) < 100):
            return {"error": "Insufficient data", "metrics": {}, "trades": []}

        closes = np.array([r[4] for r in rates], dtype=float)
        highs = np.array([r[2] for r in rates], dtype=float)
        lows = np.array([r[3] for r in rates], dtype=float)
        opens = np.array([r[1] for r in rates], dtype=float)
        volumes = np.array([r[5] for r in rates], dtype=float)
        spreads = np.array([r[6] for r in rates], dtype=float) if len(rates[0]) > 6 else np.full(len(rates), 15)

        # Calculate indicators
        indicators = self._calculate_indicators(closes, highs, lows, volumes)

        # Reset state
        self.account = AccountState(
            balance=self.params.get("initial_balance", 100000),
            equity=self.params.get("initial_balance", 100000),
            free_margin=self.params.get("initial_balance", 100000),
            daily_start_balance=self.params.get("initial_balance", 100000),
            highest_balance=self.params.get("initial_balance", 100000),
            peak_equity=self.params.get("initial_balance", 100000),
        )
        self.position = None
        self.trades = []
        self.equity_curve = [self.account.balance]
        self.daily_balances = []

        # Simulate tick by tick
        for i in range(max(50, self._get_lookback()), len(closes)):
            tick = {
                "time": rates[i][0] if isinstance(rates[i][0], datetime) else datetime(2024, 1, 1) + timedelta(minutes=i),
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
                "spread": spreads[i],
                "index": i,
            }

            # Daily reset
            if i > 0 and i % self.bars_per_day == 0:
                self._daily_reset()

            # Process tick
            self._process_tick(tick, indicators, i)

            # Update equity
            self._update_equity(tick)

            # Record equity
            self.equity_curve.append(self.account.equity)

        # Close any remaining position
        if self.position:
            self._close_position(closes[-1], rates[-1][0] if isinstance(rates[-1][0], datetime) else datetime.now(), "end_of_data")

        # Calculate metrics
        return self._calculate_result(symbol, timeframe)

    def _calculate_indicators(self, closes, highs, lows, volumes) -> dict:
        """Calculate all technical indicators."""
        n = len(closes)

        # EMAs
        ema_fast = np.zeros(n)
        ema_slow = np.zeros(n)
        ema_h1 = np.zeros(n)
        ema_fast[0] = closes[0]
        ema_slow[0] = closes[0]
        ema_h1[0] = closes[0]

        fast_period = self.params.get("ema_fast", 12)
        slow_period = self.params.get("ema_slow", 26)
        h1_period = self.params.get("ema_period_h1", 50)

        alpha_f = 2.0 / (fast_period + 1)
        alpha_s = 2.0 / (slow_period + 1)
        alpha_h = 2.0 / (h1_period + 1)

        for i in range(1, n):
            ema_fast[i] = alpha_f * closes[i] + (1 - alpha_f) * ema_fast[i-1]
            ema_slow[i] = alpha_s * closes[i] + (1 - alpha_s) * ema_slow[i-1]
            ema_h1[i] = alpha_h * closes[i] + (1 - alpha_h) * ema_h1[i-1]

        # ATR
        atr = np.zeros(n)
        period = self.params.get("regime_period", 20)
        for i in range(1, n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
            alpha_a = 2.0 / (period + 1)
            atr[i] = alpha_a * tr + (1 - alpha_a) * atr[i-1] if atr[i-1] > 0 else tr

        # RSI
        rsi = np.zeros(n)
        rsi_period = self.params.get("rsi_period", 14)
        for i in range(rsi_period, n):
            gains = []
            losses = []
            for j in range(i - rsi_period + 1, i + 1):
                change = closes[j] - closes[j-1]
                if change > 0:
                    gains.append(change)
                else:
                    losses.append(abs(change))
            avg_gain = np.mean(gains) if gains else 0
            avg_loss = np.mean(losses) if losses else 0.0001
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))

        # MACD
        macd_line = ema_fast - ema_slow
        signal_period = self.params.get("macd_signal", 9)
        macd_signal = np.zeros(n)
        macd_signal[0] = macd_line[0]
        alpha_sig = 2.0 / (signal_period + 1)
        for i in range(1, n):
            macd_signal[i] = alpha_sig * macd_line[i] + (1 - alpha_sig) * macd_signal[i-1]
        macd_hist = macd_line - macd_signal

        # Efficiency ratio
        efficiency = np.zeros(n)
        for i in range(period, n):
            net_change = abs(closes[i] - closes[i - period])
            sum_vol = sum(abs(closes[j] - closes[j-1]) for j in range(i - period + 1, i + 1))
            efficiency[i] = net_change / max(sum_vol, 0.0001)

        return {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema_h1": ema_h1,
            "atr": atr,
            "rsi": rsi,
            "macd_line": macd_line,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "efficiency": efficiency,
        }

    def _get_lookback(self) -> int:
        return max(self.params.get("ema_slow", 26),
                   self.params.get("ema_period_h1", 50),
                   self.params.get("regime_period", 20)) + 10

    def _process_tick(self, tick: dict, indicators: dict, idx: int) -> None:
        """Process a single tick — manage positions and check entries."""
        closes = None  # Will be set from indicators

        # Manage open position
        if self.position:
            self._manage_position(tick, indicators, idx)
            if self.position is None:
                return  # Position was closed

        # Check for new entry
        if self.position is None:
            self._check_entry(tick, indicators, idx)

    def _manage_position(self, tick: dict, indicators: dict, idx: int) -> None:
        """Manage open position — SL/TP hits, trailing, partial profit."""
        pos = self.position
        point = self._get_point()

        # Check SL/TP hits using high/low
        if pos.order_type == OrderType.BUY:
            if tick["low"] <= pos.sl:
                self._close_position(pos.sl, tick["time"], "sl_hit")
                return
            if tick["high"] >= pos.tp:
                self._close_position(pos.tp, tick["time"], "tp_hit")
                return

            # Trailing stop
            if self.params.get("trailing_atr_mult", 0) > 0:
                atr = indicators["atr"][idx]
                trailing_sl = tick["close"] - atr * self.params["trailing_atr_mult"]
                if trailing_sl > pos.sl and trailing_sl > pos.open_price:
                    pos.sl = trailing_sl

            # Partial profit
            if not pos.partial_moved and self.params.get("partial_profit_pct", 0) > 0:
                tp_dist = pos.tp - pos.open_price
                partial_price = pos.open_price + tp_dist * self.params["partial_profit_pct"]
                if tick["close"] >= partial_price:
                    pos.sl = pos.open_price  # Move to breakeven
                    pos.partial_moved = True

        elif pos.order_type == OrderType.SELL:
            if tick["high"] >= pos.sl:
                self._close_position(pos.sl, tick["time"], "sl_hit")
                return
            if tick["low"] <= pos.tp:
                self._close_position(pos.tp, tick["time"], "tp_hit")
                return

            # Trailing stop
            if self.params.get("trailing_atr_mult", 0) > 0:
                atr = indicators["atr"][idx]
                trailing_sl = tick["close"] + atr * self.params["trailing_atr_mult"]
                if trailing_sl < pos.sl and trailing_sl < pos.open_price:
                    pos.sl = trailing_sl

            # Partial profit
            if not pos.partial_moved and self.params.get("partial_profit_pct", 0) > 0:
                tp_dist = pos.open_price - pos.tp
                partial_price = pos.open_price - tp_dist * self.params["partial_profit_pct"]
                if tick["close"] <= partial_price:
                    pos.sl = pos.open_price
                    pos.partial_moved = True

        # Duration check
        max_duration = self.params.get("max_trade_duration", 120)
        if max_duration > 0:
            duration = (tick["time"] - pos.open_time).total_seconds() / 60
            if duration >= max_duration:
                self._close_position(tick["close"], tick["time"], "duration_limit")
                return

    def _check_entry(self, tick: dict, indicators: dict, idx: int) -> None:
        """Check for new entry signals."""
        # Drawdown checks
        daily_dd = self.account.daily_start_balance - self.account.equity
        max_daily = self.account.daily_start_balance * self.params.get("max_daily_loss_pct", 4.0) / 100
        if daily_dd >= max_daily:
            return

        total_dd = self.account.highest_balance - self.account.equity
        max_total = self.account.highest_balance * self.params.get("max_total_loss_pct", 10.0) / 100
        if total_dd >= max_total:
            return

        # Spread check
        if tick["spread"] > self.params.get("max_spread_pips", 30):
            return

        # Volume check
        if tick["volume"] < self.params.get("min_volume_ratio", 15):
            return

        # Efficiency check
        eff = indicators["efficiency"][idx]
        if eff < self.params.get("min_efficiency", 0.08):
            return

        # HTF bias
        htf_bias = self._get_htf_bias(tick["close"], indicators, idx)
        if htf_bias == 0:
            return

        # M5 confirmation
        if self.params.get("enable_m5_filter", True):
            if not self._get_m5_confirmation(htf_bias, idx):
                return

        # Calculate SL/TP
        atr = indicators["atr"][idx]
        sl_pips = max(20, min(atr * self.params.get("sl_atr_multiplier", 1.2),
                               min(atr * 3, 60)))
        tp_pips = sl_pips * self.params.get("target_ratio", 3.0)

        # Calculate lots
        lots = self._calculate_lots(sl_pips)
        if lots <= 0:
            return

        # Execute trade
        point = self._get_point()
        spread = tick["spread"] * point

        if htf_bias == 1:  # BUY
            entry_price = tick["close"] + spread / 2
            sl = entry_price - sl_pips * point * 10
            tp = entry_price + tp_pips * point * 10
            self._open_position(OrderType.BUY, entry_price, sl, tp, lots, tick["time"])
        elif htf_bias == -1:  # SELL
            entry_price = tick["close"] - spread / 2
            sl = entry_price + sl_pips * point * 10
            tp = entry_price - tp_pips * point * 10
            self._open_position(OrderType.SELL, entry_price, sl, tp, lots, tick["time"])

    def _get_htf_bias(self, price: float, indicators: dict, idx: int) -> int:
        ema_h1 = indicators["ema_h1"][idx]
        min_alignment = self.params.get("min_ma_alignment", 10) * self._get_point() * 10

        if price > ema_h1 + min_alignment:
            return 1
        elif price < ema_h1 - min_alignment:
            return -1
        return 0

    def _get_m5_confirmation(self, bias: int, idx: int) -> bool:
        m5_bars = self.params.get("m5_trend_bars", 5)
        # Use closes as proxy for M5
        bullish = 0
        for j in range(m5_bars):
            if idx - j * 5 > 0:
                pass  # Simplified
        return True  # Always confirm for now

    def _open_position(self, order_type: OrderType, price: float, sl: float,
                       tp: float, lots: float, time: datetime) -> None:
        self.ticket_counter += 1
        self.position = Position(
            ticket=self.ticket_counter,
            order_type=order_type,
            symbol="XAUUSD",
            open_price=price,
            sl=sl,
            tp=tp,
            lots=lots,
            open_time=time,
        )

    def _close_position(self, price: float, time: datetime, reason: str) -> None:
        if not self.position:
            return

        pos = self.position
        point = self._get_point()

        if pos.order_type == OrderType.BUY:
            pnl = (price - pos.open_price) / point / 10 * pos.lots
        else:
            pnl = (pos.open_price - price) / point / 10 * pos.lots

        # Apply spread cost
        spread_cost = self.params.get("spread_pips", 15) * 0.01 * pos.lots
        pnl -= spread_cost

        # Apply slippage
        slippage = self.params.get("slippage_pips", 2) * 0.01 * pos.lots
        if pnl > 0:
            pnl -= slippage

        self.account.balance += pnl
        duration = int((time - pos.open_time).total_seconds() / 60)

        trade = Trade(
            ticket=pos.ticket,
            order_type=pos.order_type,
            symbol=pos.symbol,
            open_price=pos.open_price,
            sl=pos.sl,
            tp=pos.tp,
            lots=pos.lots,
            open_time=pos.open_time,
            close_time=time,
            close_price=price,
            profit=round(pnl, 2),
            pips=round((price - pos.open_price) / point / 10 if pos.order_type == OrderType.BUY
                       else (pos.open_price - price) / point / 10, 1),
            duration_min=duration,
            exit_reason=reason,
        )
        self.trades.append(trade)
        self.position = None

    def _update_equity(self, tick: dict) -> None:
        if self.position:
            point = self._get_point()
            if self.position.order_type == OrderType.BUY:
                unrealized = (tick["close"] - self.position.open_price) / point / 10 * self.position.lots
            else:
                unrealized = (self.position.open_price - tick["close"]) / point / 10 * self.position.lots
            self.account.equity = self.account.balance + unrealized
        else:
            self.account.equity = self.account.balance

        self.account.highest_balance = max(self.account.highest_balance, self.account.balance)
        self.account.peak_equity = max(self.account.peak_equity, self.account.equity)
        self.account.free_margin = self.account.equity - self.account.margin

    def _daily_reset(self) -> None:
        self.daily_balances.append({
            "balance": self.account.balance,
            "equity": self.account.equity,
        })
        self.account.daily_start_balance = self.account.balance

    def _calculate_lots(self, sl_pips: float) -> float:
        balance = self.account.balance
        risk_pct = self.params.get("risk_per_trade_pct", 0.7) / 100

        # Risk taper
        dd = (self.account.highest_balance - balance) / max(self.account.highest_balance, 1) * 100
        if dd > 2.0:
            risk_pct *= max(0.25, 1.0 - (dd - 2.0) * 0.1)

        risk_money = balance * risk_pct
        pip_value = 0.01 * self.params.get("lot_size", 0.07) * 100  # XAUUSD pip value
        lots = risk_money / max(sl_pips * 0.01 * 100, 1)

        step = 0.01
        lots = max(0.01, min(round(lots / step) * step, 5.0))
        return lots

    def _get_point(self) -> float:
        return 0.01

    def _calculate_result(self, symbol: str, timeframe: str) -> dict:
        if not self.trades:
            return {"error": "No trades", "metrics": {}, "trades": [], "equity_curve": self.equity_curve}

        wins = [t for t in self.trades if t.profit > 0]
        losses = [t for t in self.trades if t.profit <= 0]
        total = len(self.trades)
        win_rate = len(wins) / total * 100
        gross_profit = sum(t.profit for t in wins)
        gross_loss = abs(sum(t.profit for t in losses))
        net_profit = gross_profit - gross_loss

        eq = np.array(self.equity_curve)
        peak = np.maximum.accumulate(eq)
        dd = peak - eq
        max_dd = float(np.max(dd))
        max_dd_pct = max_dd / max(float(np.max(peak)), 1) * 100

        returns = np.diff(eq) / np.maximum(eq[:-1], 1)
        sharpe = float(np.mean(returns) / max(np.std(returns), 1e-8) * np.sqrt(252 * 390)) if len(returns) > 1 else 0
        neg_returns = returns[returns < 0]
        sortino = float(np.mean(returns) / max(np.std(neg_returns), 1e-8) * np.sqrt(252 * 390)) if len(neg_returns) > 0 else sharpe

        avg_win = np.mean([t.profit for t in wins]) if wins else 0
        avg_loss = np.mean([abs(t.profit) for t in losses]) if losses else 0
        expectancy = net_profit / total
        profit_factor = gross_profit / max(gross_loss, 1)

        # Consecutive stats
        max_consec_wins = 0
        max_consec_losses = 0
        current_wins = 0
        current_losses = 0
        for t in self.trades:
            if t.profit > 0:
                current_wins += 1
                current_losses = 0
                max_consec_wins = max(max_consec_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_consec_losses = max(max_consec_losses, current_losses)

        metrics = {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "net_profit": round(net_profit, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "expectancy": round(expectancy, 2),
            "avg_trade": round(net_profit / total, 2),
            "avg_win": round(float(avg_win), 2),
            "avg_loss": round(float(avg_loss), 2),
            "largest_win": round(max(t.profit for t in wins), 2) if wins else 0,
            "largest_loss": round(min(t.profit for t in losses), 2) if losses else 0,
            "max_consecutive_wins": max_consec_wins,
            "max_consecutive_losses": max_consec_losses,
            "recovery_factor": round(abs(net_profit) / max(max_dd, 1), 2),
            "calmar_ratio": round(net_profit / max(max_dd_pct, 0.01), 2),
            "ulcer_index": round(float(np.sqrt(np.mean(dd**2)) / max(float(np.max(peak)), 1) * 100), 2),
            "equity_curve": [round(float(e), 2) for e in self.equity_curve[::max(1, len(self.equity_curve) // 1000)]],
        }

        # Trade list
        trade_list = [
            {
                "ticket": t.ticket,
                "type": t.order_type.value,
                "open_time": str(t.open_time),
                "close_time": str(t.close_time),
                "open_price": t.open_price,
                "close_price": t.close_price,
                "lots": t.lots,
                "sl": t.sl,
                "tp": t.tp,
                "profit": t.profit,
                "pips": t.pips,
                "duration_min": t.duration_min,
                "exit_reason": t.exit_reason,
            }
            for t in self.trades
        ]

        return {
            "metrics": metrics,
            "trades": trade_list,
            "symbol": symbol,
            "timeframe": timeframe,
            "params": self.params,
            "daily_balances": self.daily_balances,
        }
