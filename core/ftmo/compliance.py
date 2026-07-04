"""FTMO Challenge Compliance Checker — exact rules from FTMO documentation."""
from __future__ import annotations

from core.config import config
from core.logger import get_logger

log = get_logger("ftmo.compliance")


class FTMOCompliance:
    """Checks if a strategy passes FTMO Challenge 1-Step rules.

    Rules (all must be satisfied concurrently):
    1. Profit Target: account balance > Initial Capital + 10% ($110,000)
    2. Max Daily Loss: equity cannot drop below (balance at 00:00 CET - 3% of Initial Capital)
       Recalculated daily at 00:00 CET
    3. Max Loss (trailing): equity cannot drop below (highest balance at 00:00 CET - 10% of Initial Capital)
       Limit can only increase, never decreases
    4. Best Day Rule: Best Day <= 50% of Positive Days' Profit
       (not a breach, but must keep trading until satisfied)
    """

    def __init__(self) -> None:
        ftmo = config.get("ftmo", default={})
        self.initial_capital = ftmo.get("account_size", 100000)
        self.profit_target_pct = 0.10  # 10% of initial capital
        self.max_daily_loss_pct = 0.03  # 3% of initial capital
        self.max_loss_pct = 0.10  # 10% of initial capital (trailing)
        self.best_day_rule_pct = 0.50  # 50%

        # Derived values
        self.profit_target = self.initial_capital * self.profit_target_pct  # $10,000
        self.max_daily_loss_amount = self.initial_capital * self.max_daily_loss_pct  # $3,000
        self.max_loss_amount = self.initial_capital * self.max_loss_pct  # $10,000
        self.balance_to_pass = self.initial_capital + self.profit_target  # $110,000

    def check(self, metrics: dict, equity_curve: list[float] = None,
              daily_bars: list[dict] = None) -> dict:
        """Check if strategy passes FTMO rules.

        Args:
            metrics: Backtest metrics (net_profit, max_drawdown, etc.)
            equity_curve: List of equity values over time
            daily_bars: List of {date, open_equity, close_equity, high_equity, low_equity}

        Returns:
            Compliance report with passed/violations/details/ftmo_score
        """
        result = {
            "passed": True,
            "violations": [],
            "warnings": [],
            "ftmo_score": 0.0,
            "details": {},
        }

        net_profit = metrics.get("net_profit", 0)
        final_balance = self.initial_capital + net_profit
        max_dd_abs = metrics.get("max_drawdown", 0)
        max_dd_pct = metrics.get("max_drawdown_pct", 0)

        # ── Rule 1: Profit Target ────────────────────────────────────────────
        # Balance must exceed Initial Capital + 10% = $110,000
        profit_target_met = final_balance >= self.balance_to_pass
        if not profit_target_met:
            result["violations"].append(
                f"Profit target not met: balance ${final_balance:,.0f} < ${self.balance_to_pass:,.0f} "
                f"(need ${self.balance_to_pass - final_balance:,.0f} more)")
            result["passed"] = False
        result["details"]["profit_target"] = {
            "initial_capital": self.initial_capital,
            "required_balance": self.balance_to_pass,
            "actual_balance": round(final_balance, 2),
            "net_profit": round(net_profit, 2),
            "passed": profit_target_met,
        }

        # ── Rule 2: Maximum Daily Loss ───────────────────────────────────────
        # Equity cannot drop below (balance at 00:00 CET - 3% of Initial Capital)
        # Recalculated daily at 00:00 CET
        if daily_bars and len(daily_bars) > 0:
            daily_loss_violated = False
            worst_daily_loss = 0.0
            day_balance = self.initial_capital  # Day 1 balance = Initial Capital

            for day in daily_bars:
                daily_limit = day_balance - self.max_daily_loss_amount
                low_equity = day.get("low_equity", day.get("close_equity", 0))

                if low_equity < daily_limit:
                    daily_loss_violated = True
                    actual_loss = day_balance - low_equity
                    worst_daily_loss = max(worst_daily_loss, actual_loss)

                # Recalculate for next day: balance at 00:00 CET = previous day's close
                day_balance = day.get("close_equity", day_balance)

            if daily_loss_violated:
                result["violations"].append(
                    f"Max daily loss breached: worst daily loss ${worst_daily_loss:,.0f} "
                    f"> ${self.max_daily_loss_amount:,.0f}")
                result["passed"] = False
            result["details"]["max_daily_loss"] = {
                "limit_amount": self.max_daily_loss_amount,
                "limit_pct": self.max_daily_loss_pct * 100,
                "worst_daily_loss": round(worst_daily_loss, 2),
                "passed": not daily_loss_violated,
            }
        else:
            # Estimate from overall drawdown
            est_daily_loss = max_dd_abs * 0.4
            result["details"]["max_daily_loss"] = {
                "limit_amount": self.max_daily_loss_amount,
                "limit_pct": self.max_daily_loss_pct * 100,
                "estimated_worst": round(est_daily_loss, 2),
                "passed": est_daily_loss <= self.max_daily_loss_amount,
            }

        # ── Rule 3: Maximum Loss (trailing) ──────────────────────────────────
        # Equity cannot drop below (highest balance at 00:00 CET - 10% of Initial Capital)
        # Limit can only increase, never decrease
        if daily_bars and len(daily_bars) > 0:
            max_loss_violated = False
            highest_balance = self.initial_capital
            worst_trailing_dd = 0.0

            for day in daily_bars:
                day_open = day.get("open_equity", 0)
                highest_balance = max(highest_balance, day_open)
                trailing_limit = highest_balance - self.max_loss_amount
                low_equity = day.get("low_equity", day.get("close_equity", 0))

                if low_equity < trailing_limit:
                    max_loss_violated = True
                    actual_dd = highest_balance - low_equity
                    worst_trailing_dd = max(worst_trailing_dd, actual_dd)

            if max_loss_violated:
                result["violations"].append(
                    f"Max trailing loss breached: worst DD ${worst_trailing_dd:,.0f} "
                    f"> ${self.max_loss_amount:,.0f}")
                result["passed"] = False
            result["details"]["max_loss"] = {
                "limit_amount": self.max_loss_amount,
                "limit_pct": self.max_loss_pct * 100,
                "highest_balance": round(highest_balance, 2),
                "worst_trailing_dd": round(worst_trailing_dd, 2),
                "passed": not max_loss_violated,
            }
        else:
            # Estimate from overall drawdown
            result["details"]["max_loss"] = {
                "limit_amount": self.max_loss_amount,
                "limit_pct": self.max_loss_pct * 100,
                "actual_dd": round(max_dd_abs, 2),
                "passed": max_dd_abs <= self.max_loss_amount,
            }
            if max_dd_abs > self.max_loss_amount:
                result["violations"].append(
                    f"Max loss exceeded: ${max_dd_abs:,.0f} > ${self.max_loss_amount:,.0f}")
                result["passed"] = False

        # ── Rule 4: Best Day Rule ────────────────────────────────────────────
        # Best Day <= 50% of Positive Days' Profit
        # Not a breach, but must keep trading until satisfied
        if daily_bars and len(daily_bars) > 0:
            positive_days_profit = 0.0
            best_day_profit = 0.0
            for day in daily_bars:
                day_pnl = day.get("close_equity", 0) - day.get("open_equity", 0)
                if day_pnl > 0:
                    positive_days_profit += day_pnl
                    best_day_profit = max(best_day_profit, day_pnl)

            if positive_days_profit > 0:
                best_day_ratio = best_day_profit / positive_days_profit
                best_day_ok = best_day_ratio <= self.best_day_rule_pct
                if not best_day_ok:
                    result["warnings"].append(
                        f"Best day rule not satisfied: {best_day_ratio:.1%} > {self.best_day_rule_pct:.0%} "
                        f"(Best Day=${best_day_profit:,.0f}, Positive Days=${positive_days_profit:,.0f})")
                result["details"]["best_day_rule"] = {
                    "max_pct": self.best_day_rule_pct * 100,
                    "best_day_profit": round(best_day_profit, 2),
                    "positive_days_profit": round(positive_days_profit, 2),
                    "best_day_ratio": round(best_day_ratio * 100, 1),
                    "passed": best_day_ok,
                }
            else:
                result["details"]["best_day_rule"] = {
                    "max_pct": self.best_day_rule_pct * 100,
                    "passed": True,
                    "note": "No positive days yet",
                }
        else:
            result["details"]["best_day_rule"] = {
                "max_pct": self.best_day_rule_pct * 100,
                "passed": True,
                "note": "No daily data available",
            }

        # ── Additional checks ────────────────────────────────────────────────
        total_trades = metrics.get("total_trades", 0)
        if total_trades < 15:
            result["warnings"].append(f"Low trade count: {total_trades}")

        win_rate = metrics.get("win_rate", 0)
        if win_rate > 80:
            result["warnings"].append(f"Win rate suspiciously high: {win_rate:.1f}%")

        pf = metrics.get("profit_factor", 0)
        if pf < 1.0:
            result["violations"].append(f"Profit factor below 1.0: {pf:.2f}")
            result["passed"] = False

        # ── Calculate FTMO Score (0-100) ─────────────────────────────────────
        result["ftmo_score"] = self._calc_ftmo_score(metrics, equity_curve, daily_bars)

        return result

    def _calc_ftmo_score(self, metrics: dict, equity_curve: list[float] = None,
                         daily_bars: list[dict] = None) -> float:
        """Calculate FTMO score (0-100) based on how well strategy meets rules."""
        score = 0.0
        net_profit = metrics.get("net_profit", 0)
        max_dd_pct = metrics.get("max_drawdown_pct", 0)
        pf = metrics.get("profit_factor", 0)
        win_rate = metrics.get("win_rate", 0)
        sharpe = metrics.get("sharpe_ratio", 0)

        # Profit score (0-30): how close to $10k target
        profit_ratio = net_profit / self.profit_target if self.profit_target > 0 else 0
        if profit_ratio >= 1.0:
            score += 30
        elif profit_ratio > 0:
            score += profit_ratio * 25

        # DD score (0-25): lower is better
        if max_dd_pct <= 3:
            score += 25
        elif max_dd_pct <= 5:
            score += 20
        elif max_dd_pct <= 8:
            score += 15
        elif max_dd_pct <= 10:
            score += 10
        elif max_dd_pct <= 15:
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

        # Win rate score (0-15): sweet spot 40-65%
        if 40 <= win_rate <= 65:
            score += 15
        elif 35 <= win_rate <= 75:
            score += 10
        elif win_rate > 75:
            score += 5

        # Sharpe score (0-10)
        if sharpe >= 2.0:
            score += 10
        elif sharpe >= 1.0:
            score += 7
        elif sharpe >= 0.5:
            score += 3

        return min(round(score, 1), 100.0)


ftmo_checker = FTMOCompliance()
