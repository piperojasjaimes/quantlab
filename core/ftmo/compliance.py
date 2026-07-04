"""FTMO Challenge Compliance Checker."""
from __future__ import annotations

from typing import Any

from core.config import config
from core.logger import get_logger

log = get_logger("ftmo.compliance")


class FTMOCompliance:
    """Checks if a strategy passes FTMO Challenge rules."""

    def __init__(self) -> None:
        ftmo = config.get("ftmo", default={})
        self.account_size = ftmo.get("account_size", 100000)
        self.profit_target = ftmo.get("profit_target", 10000)
        self.max_daily_loss = ftmo.get("max_daily_loss", 3000)
        self.max_loss = ftmo.get("max_loss", 10000)
        self.best_day_rule_pct = ftmo.get("best_day_rule_pct", 50)
        self.risk_per_trade_pct = ftmo.get("risk_per_trade_pct", 1.0)
        self.max_risk_per_trade = ftmo.get("max_risk_per_trade", 1000)

    def check(self, metrics: dict, equity_curve: list[float] = None) -> dict:
        """Check if strategy passes FTMO rules. Returns compliance report."""
        result = {
            "passed": True,
            "violations": [],
            "warnings": [],
            "ftmo_score": 0.0,
            "details": {},
        }

        net_profit = metrics.get("net_profit", 0)
        max_dd = metrics.get("max_drawdown_pct", 0)
        max_dd_abs = metrics.get("max_drawdown", 0)

        # 1. Profit Target
        if net_profit < self.profit_target:
            result["violations"].append(
                f"Profit target not met: ${net_profit:.0f} < ${self.profit_target}")
            result["passed"] = False
        result["details"]["profit_target"] = {
            "required": self.profit_target,
            "achieved": net_profit,
            "passed": net_profit >= self.profit_target,
        }

        # 2. Max Daily Loss
        if equity_curve and len(equity_curve) > 1:
            daily_dd = self._calc_max_daily_drawdown(equity_curve)
            if daily_dd > self.max_daily_loss:
                result["violations"].append(
                    f"Max daily loss exceeded: ${daily_dd:.0f} > ${self.max_daily_loss}")
                result["passed"] = False
            result["details"]["max_daily_loss"] = {
                "required": self.max_daily_loss,
                "actual": round(daily_dd, 2),
                "passed": daily_dd <= self.max_daily_loss,
            }
        else:
            # Estimate from overall DD
            est_daily_dd = max_dd_abs * 0.5
            if est_daily_dd > self.max_daily_loss:
                result["warnings"].append(
                    f"Estimated daily DD may exceed limit: ~${est_daily_dd:.0f}")

        # 3. Max Loss (total drawdown)
        if max_dd_abs > self.max_loss:
            result["violations"].append(
                f"Max loss exceeded: ${max_dd_abs:.0f} > ${self.max_loss}")
            result["passed"] = False
        result["details"]["max_loss"] = {
            "required": self.max_loss,
            "actual": round(max_dd_abs, 2),
            "passed": max_dd_abs <= self.max_loss,
        }

        # 4. Max DD percentage (should be < 10% for FTMO)
        if max_dd > 10:
            result["violations"].append(
                f"Drawdown too high: {max_dd:.1f}% > 10%")
            result["passed"] = False
        result["details"]["max_dd_pct"] = {
            "required": 10.0,
            "actual": max_dd,
            "passed": max_dd <= 10,
        }

        # 5. Best Day Rule: no single day > 50% of total profit
        if equity_curve and len(equity_curve) > 1:
            best_day = self._calc_best_day_profit(equity_curve)
            if net_profit > 0 and best_day > net_profit * (self.best_day_rule_pct / 100):
                result["violations"].append(
                    f"Best day rule violated: ${best_day:.0f} > {self.best_day_rule_pct}% of ${net_profit:.0f}")
                result["passed"] = False
            result["details"]["best_day_rule"] = {
                "max_pct": self.best_day_rule_pct,
                "best_day_profit": round(best_day, 2),
                "passed": best_day <= net_profit * (self.best_day_rule_pct / 100) if net_profit > 0 else True,
            }

        # 6. Minimum trades
        total_trades = metrics.get("total_trades", 0)
        if total_trades < 15:
            result["warnings"].append(f"Low trade count: {total_trades} < 15")
        result["details"]["min_trades"] = {
            "required": 15,
            "actual": total_trades,
            "passed": total_trades >= 15,
        }

        # 7. Win rate sanity
        win_rate = metrics.get("win_rate", 0)
        if win_rate > 80:
            result["warnings"].append(f"Win rate suspiciously high: {win_rate:.1f}%")
        if win_rate < 30:
            result["warnings"].append(f"Win rate too low: {win_rate:.1f}%")

        # 8. Profit factor
        pf = metrics.get("profit_factor", 0)
        if pf < 1.0:
            result["violations"].append(f"Profit factor below 1.0: {pf:.2f}")
            result["passed"] = False

        # Calculate FTMO score (0-100)
        result["ftmo_score"] = self._calc_ftmo_score(metrics, equity_curve)

        return result

    def _calc_max_daily_drawdown(self, equity_curve: list[float]) -> float:
        if len(equity_curve) < 2:
            return 0.0
        # Assume ~390 M1 bars per trading day for forex
        # For crypto: ~1440 bars per day
        bars_per_day = 390
        max_dd = 0.0
        peak = equity_curve[0]
        day_start = equity_curve[0]
        for i, val in enumerate(equity_curve):
            if i > 0 and i % bars_per_day == 0:
                day_start = val
            peak = max(peak, val)
            dd = peak - val
            max_dd = max(max_dd, dd)
        return max_dd

    def _calc_best_day_profit(self, equity_curve: list[float]) -> float:
        if len(equity_curve) < 2:
            return 0.0
        bars_per_day = 390
        best_day = 0.0
        day_start = equity_curve[0]
        for i, val in enumerate(equity_curve):
            if i > 0 and i % bars_per_day == 0:
                day_profit = val - day_start
                best_day = max(best_day, day_profit)
                day_start = val
        return best_day

    def _calc_ftmo_score(self, metrics: dict, equity_curve: list[float] = None) -> float:
        score = 0.0
        net_profit = metrics.get("net_profit", 0)
        max_dd = metrics.get("max_drawdown_pct", 0)
        pf = metrics.get("profit_factor", 0)
        win_rate = metrics.get("win_rate", 0)
        sharpe = metrics.get("sharpe_ratio", 0)

        # Profit score (0-30)
        if net_profit >= self.profit_target:
            score += 30
        elif net_profit > 0:
            score += (net_profit / self.profit_target) * 20

        # DD score (0-25)
        if max_dd <= 5:
            score += 25
        elif max_dd <= 10:
            score += 15
        elif max_dd <= 15:
            score += 5

        # PF score (0-20)
        if pf >= 2.0:
            score += 20
        elif pf >= 1.5:
            score += 15
        elif pf >= 1.2:
            score += 10
        elif pf >= 1.0:
            score += 5

        # Win rate score (0-15)
        if 40 <= win_rate <= 70:
            score += 15
        elif 30 <= win_rate <= 80:
            score += 10
        elif win_rate > 80:
            score += 5  # Suspicious

        # Sharpe score (0-10)
        if sharpe >= 2.0:
            score += 10
        elif sharpe >= 1.0:
            score += 7
        elif sharpe >= 0.5:
            score += 3

        return min(score, 100.0)


ftmo_checker = FTMOCompliance()
