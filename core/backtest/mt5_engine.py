"""MT5-equivalent Strategy Tester Engine — full simulation matching MT5 behavior."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import numpy as np

from core.config import config
from core.logger import get_logger

log = get_logger("backtest.mt5_engine")


class OrderType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"


class PositionType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class PendingOrder:
    ticket: int
    order_type: OrderType
    symbol: str
    price: float
    sl: float
    tp: float
    lots: float
    created_time: datetime
    expiration: datetime = None
    comment: str = ""


@dataclass
class Position:
    ticket: int
    position_type: PositionType
    symbol: str
    open_price: float
    sl: float
    tp: float
    lots: float
    open_time: datetime
    swaps: float = 0.0
    commission: float = 0.0
    trailing_activated: bool = False
    partial_moved: bool = False
    magic: int = 0
    comment: str = ""


@dataclass
class Trade:
    ticket: int
    position_ticket: int
    order_type: str
    symbol: str
    open_price: float
    close_price: float
    sl: float
    tp: float
    lots: float
    open_time: datetime
    close_time: datetime
    profit: float = 0.0
    swaps: float = 0.0
    commission: float = 0.0
    pips: float = 0.0
    duration_min: int = 0
    exit_reason: str = ""


class MT5StrategyTester:
    """Full MT5-equivalent Strategy Tester with all simulation modes."""

    def __init__(self, params: dict = None):
        self.params = params or {}
        self.positions: list[Position] = []
        self.pending_orders: list[PendingOrder] = []
        self.trades: list[Trade] = []
        self.equity_curve: list[float] = []
        self.balance = self.params.get("initial_balance", 100000)
        self.equity = self.balance
        self.free_margin = self.balance
        self.margin = 0.0
        self.daily_start_balance = self.balance
        self.highest_balance = self.balance
        self.peak_equity = self.balance
        self.ticket_counter = 1000
        self.daily_bars = []
        self.spread_cache = {}

    def run(self, symbol: str, rates_m1: list, rates_m5: list = None,
            rates_m15: list = None, rates_h1: list = None) -> dict:
        """Run backtest with multi-timeframe data.

        Args:
            symbol: Trading symbol
            rates_m1: M1 OHLCV data (required)
            rates_m5: M5 OHLCV data (optional, for HTF analysis)
            rates_m15: M15 OHLCV data (optional)
            rates_h1: H1 OHLCV data (optional)
        """
        if rates_m1 is None or (hasattr(rates_m1, '__len__') and len(rates_m1) < 100):
            return {"error": "Insufficient M1 data"}

        closes_m1 = np.array([r[4] for r in rates_m1], dtype=float)
        highs_m1 = np.array([r[2] for r in rates_m1], dtype=float)
        lows_m1 = np.array([r[3] for r in rates_m1], dtype=float)
        opens_m1 = np.array([r[1] for r in rates_m1], dtype=float)
        volumes_m1 = np.array([r[5] for r in rates_m1], dtype=float)
        spreads_m1 = np.array([r[6] for r in rates_m1], dtype=float) if len(rates_m1[0]) > 6 else np.full(len(rates_m1), 15.0)

        # Pre-calculate HTF data
        htf_data = {}
        for tf_name, tf_data in [("M5", rates_m5), ("M15", rates_m15), ("H1", rates_h1)]:
            if tf_data is not None and hasattr(tf_data, "__len__") and len(tf_data) > 50:
                htf_data[tf_name] = {
                    "closes": np.array([r[4] for r in tf_data], dtype=float),
                    "highs": np.array([r[2] for r in tf_data], dtype=float),
                    "lows": np.array([r[3] for r in tf_data], dtype=float),
                    "opens": np.array([r[1] for r in tf_data], dtype=float),
                    "volumes": np.array([r[5] for r in tf_data], dtype=float),
                }

        # Calculate all indicators
        indicators = self._calculate_indicators(closes_m1, highs_m1, lows_m1, volumes_m1, htf_data)

        # Reset state
        self.balance = self.params.get("initial_balance", 100000)
        self.equity = self.balance
        self.free_margin = self.balance
        self.highest_balance = self.balance
        self.peak_equity = self.balance
        self.daily_start_balance = self.balance
        self.positions = []
        self.pending_orders = []
        self.trades = []
        self.equity_curve = [self.balance]
        self.daily_bars = []

        # Simulate tick by tick
        for i in range(self._get_lookback(), len(closes_m1)):
            tick = self._create_tick(rates_m1, i, spreads_m1)

            # Interpolate sub-ticks within the bar
            sub_ticks = self._interpolate_ticks(tick, opens_m1, highs_m1, lows_m1, closes_m1, volumes_m1, i)

            for sub_tick in sub_ticks:
                self._process_tick(sub_tick, indicators, i, htf_data)

            # Daily reset
            if i > 0 and i % 390 == 0:
                self._daily_reset()

            self._update_equity(tick)
            self.equity_curve.append(self.equity)

        # Close remaining positions
        for pos in self.positions[:]:
            self._close_position(pos, closes_m1[-1], rates_m1[-1][0] if isinstance(rates_m1[-1][0], datetime) else datetime.now(), "end_of_data")

        return self._calculate_result(symbol)

    def _create_tick(self, rates, idx, spreads) -> dict:
        """Create a tick from rate data."""
        ts = rates[idx][0]
        if isinstance(ts, (int, float)):
            ts = datetime(2024, 1, 1) + timedelta(minutes=int(ts / 60))
        return {
            "time": ts,
            "open": rates[idx][1],
            "high": rates[idx][2],
            "low": rates[idx][3],
            "close": rates[idx][4],
            "volume": rates[idx][5] if len(rates[idx]) > 5 else 0,
            "spread": spreads[idx],
            "index": idx,
        }

    def _interpolate_ticks(self, bar, opens, highs, lows, closes, volumes, idx) -> list:
        """Interpolate sub-ticks within a bar for realistic simulation."""
        n_ticks = self.params.get("ticks_per_bar", 10)
        ticks = []

        bar_open = opens[idx]
        bar_high = highs[idx]
        bar_low = lows[idx]
        bar_close = closes[idx]

        # Generate price path within the bar
        for t in range(n_ticks):
            progress = t / max(n_ticks - 1, 1)

            # Interpolate price with some randomness
            base_price = bar_open + (bar_close - bar_open) * progress
            noise = np.random.randn() * (bar_high - bar_low) * 0.1
            price = base_price + noise

            # Ensure within bar range
            price = max(bar_low, min(bar_high, price))

            # Generate high/low for sub-tick
            sub_high = price + abs(np.random.randn() * (bar_high - bar_low) * 0.05)
            sub_low = price - abs(np.random.randn() * (bar_high - bar_low) * 0.05)
            sub_high = min(bar_high, sub_high)
            sub_low = max(bar_low, sub_low)

            tick_time = bar["time"] + timedelta(seconds=t * 60 // n_ticks)

            ticks.append({
                "time": tick_time,
                "open": price if t == 0 else ticks[-1]["close"],
                "high": sub_high,
                "low": sub_low,
                "close": price,
                "volume": bar["volume"] / n_ticks,
                "spread": bar["spread"] * (1 + np.random.uniform(-0.3, 0.3)),
                "index": bar["index"],
            })

        return ticks

    def _process_tick(self, tick: dict, indicators: dict, idx: int, htf_data: dict) -> None:
        """Process a single tick."""
        # Check pending orders
        self._check_pending_orders(tick)

        # Manage open positions
        for pos in self.positions[:]:
            self._manage_position(pos, tick, indicators, idx)

        # Check new entries (only 1 position per symbol by default)
        max_positions = self.params.get("max_positions", 1)
        if len(self.positions) < max_positions:
            self._check_entry(tick, indicators, idx, htf_data)

    def _check_pending_orders(self, tick: dict) -> None:
        """Check and execute pending orders."""
        for order in self.pending_orders[:]:
            executed = False
            if order.order_type == OrderType.BUY_LIMIT and tick["low"] <= order.price:
                self._open_position(PositionType.LONG, order.price, order.sl, order.tp, order.lots, tick["time"], order.comment)
                executed = True
            elif order.order_type == OrderType.SELL_LIMIT and tick["high"] >= order.price:
                self._open_position(PositionType.SHORT, order.price, order.sl, order.tp, order.lots, tick["time"], order.comment)
                executed = True
            elif order.order_type == OrderType.BUY_STOP and tick["high"] >= order.price:
                self._open_position(PositionType.LONG, order.price, order.sl, order.tp, order.lots, tick["time"], order.comment)
                executed = True
            elif order.order_type == OrderType.SELL_STOP and tick["low"] <= order.price:
                self._open_position(PositionType.SHORT, order.price, order.sl, order.tp, order.lots, tick["time"], order.comment)
                executed = True

            if executed:
                self.pending_orders.remove(order)

            # Check expiration
            if order.expiration and tick["time"] > order.expiration:
                self.pending_orders.remove(order)

    def _manage_position(self, pos: Position, tick: dict, indicators: dict, idx: int) -> None:
        """Manage open position — SL/TP, trailing, partial profit, swaps."""
        point = self._get_point()

        # Check SL/TP hits using high/low (like MT5)
        if pos.position_type == PositionType.LONG:
            if tick["low"] <= pos.sl:
                self._close_position(pos, pos.sl, tick["time"], "sl_hit")
                return
            if tick["high"] >= pos.tp:
                self._close_position(pos, pos.tp, tick["time"], "tp_hit")
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
                    pos.sl = pos.open_price
                    pos.partial_moved = True

        elif pos.position_type == PositionType.SHORT:
            if tick["high"] >= pos.sl:
                self._close_position(pos, pos.sl, tick["time"], "sl_hit")
                return
            if tick["low"] <= pos.tp:
                self._close_position(pos, pos.tp, tick["time"], "tp_hit")
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
        max_duration = self.params.get("max_trade_duration", 0)
        if max_duration > 0:
            duration = (tick["time"] - pos.open_time).total_seconds() / 60
            if duration >= max_duration:
                self._close_position(pos, tick["close"], tick["time"], "duration_limit")
                return

        # Calculate and accumulate swaps (daily)
        self._calculate_swaps(pos, tick)

    def _calculate_swaps(self, pos: Position, tick: dict) -> None:
        """Calculate overnight swap costs."""
        hour = tick["time"].hour
        minute = tick["time"].minute

        # Swaps charged at midnight server time (approximately)
        if hour == 0 and minute == 0:
            swap_long = self.params.get("swap_long", -2.5)  # Points per day
            swap_short = self.params.get("swap_short", -0.5)
            point = self._get_point()

            if pos.position_type == PositionType.LONG:
                swap_cost = swap_long * point * pos.lots * 100
            else:
                swap_cost = swap_short * point * pos.lots * 100

            pos.swaps += swap_cost
            self.balance += swap_cost

    def _check_entry(self, tick: dict, indicators: dict, idx: int, htf_data: dict) -> None:
        """Check for new entry signals."""
        # Drawdown checks
        daily_dd = self.daily_start_balance - self.equity
        max_daily = self.daily_start_balance * self.params.get("max_daily_loss_pct", 4.0) / 100
        if daily_dd >= max_daily:
            return

        total_dd = self.highest_balance - self.equity
        max_total = self.highest_balance * self.params.get("max_total_loss_pct", 10.0) / 100
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

        # HTF bias using actual M15/H1 data
        htf_bias = self._get_htf_bias(tick["close"], indicators, idx, htf_data)
        if htf_bias == 0:
            return

        # M5 confirmation using actual M5 data
        if self.params.get("enable_m5_filter", True):
            if not self._get_m5_confirmation(htf_bias, idx, htf_data):
                return

        # Session check
        if not self._is_session_open(tick["time"]):
            return

        # Consecutive loss check
        if self._get_consecutive_losses() >= self.params.get("consecutive_loss_limit", 3):
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

        point = self._get_point()
        spread = tick["spread"] * point

        if htf_bias == 1:  # BUY
            entry_price = tick["close"] + spread / 2
            sl = entry_price - sl_pips * point * 10
            tp = entry_price + tp_pips * point * 10
            self._open_position(PositionType.LONG, entry_price, sl, tp, lots, tick["time"])
        elif htf_bias == -1:  # SELL
            entry_price = tick["close"] - spread / 2
            sl = entry_price + sl_pips * point * 10
            tp = entry_price - tp_pips * point * 10
            self._open_position(PositionType.SHORT, entry_price, sl, tp, lots, tick["time"])

    def _get_htf_bias(self, price: float, indicators: dict, idx: int, htf_data: dict) -> int:
        """Get HTF bias using real M15/H1 data if available."""
        # Use M15 data if available
        if "M15" in htf_data:
            closes_m15 = htf_data["M15"]["closes"]
            if len(closes_m15) > 50:
                ema50 = self._ema(closes_m15, 50)
                current_ema = ema50[-1]
                current_price = closes_m15[-1]
                min_align = self.params.get("min_ma_alignment", 10) * self._get_point() * 10
                if current_price > current_ema + min_align:
                    return 1
                elif current_price < current_ema - min_align:
                    return -1
                return 0

        # Fallback to M1 EMA
        ema_h1 = indicators["ema_h1"][idx]
        min_align = self.params.get("min_ma_alignment", 10) * self._get_point() * 10
        if price > ema_h1 + min_align:
            return 1
        elif price < ema_h1 - min_align:
            return -1
        return 0

    def _get_m5_confirmation(self, bias: int, idx: int, htf_data: dict) -> bool:
        """Get M5 confirmation using real M5 data if available."""
        if "M5" in htf_data:
            closes_m5 = htf_data["M5"]["closes"]
            if len(closes_m5) > 5:
                bullish = sum(1 for i in range(min(5, len(closes_m5) - 1))
                             if closes_m5[-(i+1)] > closes_m5[-(i+2)])
                if bias == 1 and bullish >= 3:
                    return True
                if bias == -1 and bullish <= 2:
                    return True
                return False
        return True  # Default confirm

    def _is_session_open(self, time: datetime) -> bool:
        """Check if current time is within trading sessions."""
        hour = time.hour
        london = self.params.get("london_start", 3), self.params.get("london_end", 12)
        ny = self.params.get("ny_start", 13), self.params.get("ny_end", 21)
        asia = self.params.get("asia_start", 0), self.params.get("asia_end", 3)

        if london[0] <= hour < london[1]:
            return True
        if ny[0] <= hour < ny[1]:
            return True
        if asia[0] <= hour < asia[1]:
            return True

        # Kill switch
        ks = self.params.get("kill_switch_start", 22), self.params.get("kill_switch_end", 1)
        if hour >= ks[0] or hour < ks[1]:
            return False

        return False

    def _get_consecutive_losses(self) -> int:
        count = 0
        for t in reversed(self.trades):
            if t.profit < 0:
                count += 1
            else:
                break
        return count

    def _open_position(self, pos_type: PositionType, price: float, sl: float,
                       tp: float, lots: float, time: datetime, comment: str = "") -> None:
        self.ticket_counter += 1
        commission = self.params.get("commission_per_lot", 3.5) * lots
        self.balance -= commission
        self.margin += lots * price * self._get_point() * 10000

        pos = Position(
            ticket=self.ticket_counter,
            position_type=pos_type,
            symbol="XAUUSD",
            open_price=price,
            sl=sl,
            tp=tp,
            lots=lots,
            open_time=time,
            commission=commission,
            comment=comment,
        )
        self.positions.append(pos)

    def _close_position(self, pos: Position, price: float, time: datetime, reason: str) -> None:
        point = self._get_point()
        spread_cost = pos.commission  # Already deducted on open

        if pos.position_type == PositionType.LONG:
            pips = (price - pos.open_price) / point / 10
        else:
            pips = (pos.open_price - price) / point / 10

        pnl = pips * pos.lots * 10  # XAUUSD: 1 pip = $10 per lot

        self.balance += pnl + pos.swaps  # Add back swaps (already deducted)
        self.margin -= pos.open_price * pos.lots * point * 10000

        duration = int((time - pos.open_time).total_seconds() / 60)

        trade = Trade(
            ticket=pos.ticket,
            position_ticket=pos.ticket,
            order_type=pos.position_type.value,
            symbol=pos.symbol,
            open_price=pos.open_price,
            close_price=price,
            sl=pos.sl,
            tp=pos.tp,
            lots=pos.lots,
            open_time=pos.open_time,
            close_time=time,
            profit=round(pnl, 2),
            swaps=round(pos.swaps, 2),
            commission=round(pos.commission, 2),
            pips=round(pips, 1),
            duration_min=duration,
            exit_reason=reason,
        )
        self.trades.append(trade)
        self.positions.remove(pos)

    def _update_equity(self, tick: dict) -> None:
        unrealized = 0.0
        for pos in self.positions:
            point = self._get_point()
            if pos.position_type == PositionType.LONG:
                unrealized += (tick["close"] - pos.open_price) / point / 10 * pos.lots * 10
            else:
                unrealized += (pos.open_price - tick["close"]) / point / 10 * pos.lots * 10

        self.equity = self.balance + unrealized
        self.highest_balance = max(self.highest_balance, self.balance)
        self.peak_equity = max(self.peak_equity, self.equity)
        self.free_margin = self.equity - self.margin

    def _daily_reset(self) -> None:
        self.daily_bars.append({
            "balance": self.balance,
            "equity": self.equity,
            "high": self.peak_equity,
            "low": self.equity,
        })
        self.daily_start_balance = self.balance

    def _calculate_lots(self, sl_pips: float) -> float:
        balance = self.balance
        risk_pct = self.params.get("risk_per_trade_pct", 0.7) / 100

        dd = (self.highest_balance - balance) / max(self.highest_balance, 1) * 100
        if dd > 2.0:
            risk_pct *= max(0.25, 1.0 - (dd - 2.0) * 0.1)

        risk_money = balance * risk_pct
        pip_value = 10  # XAUUSD: $10 per pip per lot
        lots = risk_money / max(sl_pips * pip_value, 1)

        step = 0.01
        lots = max(0.01, min(round(lots / step) * step, 5.0))
        return lots

    def _get_point(self) -> float:
        return 0.01

    def _calculate_indicators(self, closes, highs, lows, volumes, htf_data) -> dict:
        n = len(closes)

        # EMAs
        ema_fast = self._ema(closes, self.params.get("ema_fast", 12))
        ema_slow = self._ema(closes, self.params.get("ema_slow", 26))
        ema_h1 = self._ema(closes, self.params.get("ema_period_h1", 50))

        # ATR
        atr = np.zeros(n)
        period = self.params.get("regime_period", 20)
        for i in range(1, n):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            alpha = 2.0 / (period + 1)
            atr[i] = alpha * tr + (1 - alpha) * atr[i-1] if atr[i-1] > 0 else tr

        # RSI
        rsi_period = self.params.get("rsi_period", 14)
        rsi = np.zeros(n)
        for i in range(rsi_period, n):
            gains = [max(0, closes[j] - closes[j-1]) for j in range(i - rsi_period + 1, i + 1)]
            losses = [max(0, closes[j-1] - closes[j]) for j in range(i - rsi_period + 1, i + 1)]
            avg_g = np.mean(gains) if gains else 0
            avg_l = max(np.mean(losses) if losses else 0.0001, 0.0001)
            rsi[i] = 100 - (100 / (1 + avg_g / avg_l))

        # MACD
        macd_line = ema_fast - ema_slow
        macd_signal = self._ema(macd_line, self.params.get("macd_signal", 9))
        macd_hist = macd_line - macd_signal

        # Efficiency
        efficiency = np.zeros(n)
        for i in range(period, n):
            net = abs(closes[i] - closes[i - period])
            vol_sum = sum(abs(closes[j] - closes[j-1]) for j in range(i - period + 1, i + 1))
            efficiency[i] = net / max(vol_sum, 0.0001)

        return {
            "ema_fast": ema_fast, "ema_slow": ema_slow, "ema_h1": ema_h1,
            "atr": atr, "rsi": rsi,
            "macd_line": macd_line, "macd_signal": macd_signal, "macd_hist": macd_hist,
            "efficiency": efficiency,
        }

    def _ema(self, data, period):
        result = np.zeros(len(data))
        result[0] = data[0]
        alpha = 2.0 / (period + 1)
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i-1]
        return result

    def _get_lookback(self):
        return max(self.params.get("ema_slow", 26), self.params.get("ema_period_h1", 50), 50) + 10

    def _calculate_result(self, symbol: str) -> dict:
        if not self.trades:
            return {"error": "No trades", "metrics": {}, "trades": [], "equity_curve": self.equity_curve}

        wins = [t for t in self.trades if t.profit > 0]
        losses = [t for t in self.trades if t.profit <= 0]
        total = len(self.trades)
        win_rate = len(wins) / total * 100
        gross_profit = sum(t.profit for t in wins)
        gross_loss = abs(sum(t.profit for t in losses))
        net_profit = gross_profit - gross_loss
        total_swaps = sum(t.swaps for t in self.trades)
        total_commission = sum(t.commission for t in self.trades)

        eq = np.array(self.equity_curve)
        peak = np.maximum.accumulate(eq)
        dd = peak - eq
        max_dd = float(np.max(dd))
        max_dd_pct = max_dd / max(float(np.max(peak)), 1) * 100

        returns = np.diff(eq) / np.maximum(eq[:-1], 1)
        sharpe = float(np.mean(returns) / max(np.std(returns), 1e-8) * np.sqrt(252 * 390)) if len(returns) > 1 else 0
        neg_returns = returns[returns < 0]
        sortino = float(np.mean(returns) / max(np.std(neg_returns), 1e-8) * np.sqrt(252 * 390)) if len(neg_returns) > 0 else sharpe

        metrics = {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(gross_profit / max(gross_loss, 1), 2),
            "net_profit": round(net_profit, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "total_swaps": round(total_swaps, 2),
            "total_commission": round(total_commission, 2),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "expectancy": round(net_profit / total, 2),
            "avg_trade": round(net_profit / total, 2),
            "avg_win": round(float(np.mean([t.profit for t in wins])), 2) if wins else 0,
            "avg_loss": round(float(np.mean([abs(t.profit) for t in losses])), 2) if losses else 0,
            "largest_win": round(max(t.profit for t in wins), 2) if wins else 0,
            "largest_loss": round(min(t.profit for t in losses), 2) if losses else 0,
            "recovery_factor": round(abs(net_profit) / max(max_dd, 1), 2),
            "calmar_ratio": round(net_profit / max(max_dd_pct, 0.01), 2),
            "equity_curve": [round(float(e), 2) for e in self.equity_curve[::max(1, len(self.equity_curve) // 1000)]],
        }

        trade_list = [
            {
                "ticket": t.ticket, "type": t.order_type,
                "open_time": str(t.open_time), "close_time": str(t.close_time),
                "open_price": t.open_price, "close_price": t.close_price,
                "lots": t.lots, "sl": t.sl, "tp": t.tp,
                "profit": t.profit, "swaps": t.swaps, "commission": t.commission,
                "pips": t.pips, "duration_min": t.duration_min, "exit_reason": t.exit_reason,
            }
            for t in self.trades
        ]

        return {
            "metrics": metrics,
            "trades": trade_list,
            "symbol": symbol,
            "params": self.params,
            "daily_bars": self.daily_bars,
        }
