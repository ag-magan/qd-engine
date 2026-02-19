import logging
from collections import defaultdict
from datetime import datetime, timezone

from src.shared.database import Database
from src.account2_daytrader.config import (
    ACCOUNT_ID,
    MAX_CONSECUTIVE_LOSSES_BEFORE_COOLDOWN,
)

logger = logging.getLogger(__name__)


class AdaptiveEngine:
    """EOD learning, stop calibration, and behavioral detection."""

    def __init__(self):
        self.db = Database()

    def eod_review(self) -> dict:
        """End-of-day review: analyze today's trades and update learnings."""
        todays_trades = self.db.get_todays_trades(ACCOUNT_ID)
        outcomes = self.db.get_trade_outcomes(ACCOUNT_ID, limit=100)

        review = {
            "trades_today": len(todays_trades),
            "adjustments": [],
            "behavioral_flags": [],
        }

        # Analyze by strategy
        strategy_stats = self._analyze_strategy_performance(outcomes)
        review["strategy_stats"] = strategy_stats

        # Check for behavioral patterns
        behavioral = self._detect_behavioral_issues(todays_trades, outcomes)
        review["behavioral_flags"] = behavioral

        # Calibrate stops
        stop_adjustments = self._calibrate_stops(outcomes)
        review["stop_adjustments"] = stop_adjustments

        # Apply adaptive config updates
        for adj in stop_adjustments:
            self.db.upsert_adaptive_config({
                "account_id": ACCOUNT_ID,
                "parameter": f"stop_pct",
                "strategy": adj["strategy"],
                "value": adj["new_stop"],
                "previous_value": adj["old_stop"],
                "reason": adj["reason"],
            })

        return review

    def _analyze_strategy_performance(self, outcomes: list) -> dict:
        """Break down performance by strategy, time of day, day of week."""
        by_strategy = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})
        by_hour = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})
        by_weekday = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})

        for o in outcomes:
            strategy = o.get("strategy", "unknown")
            pnl = float(o.get("realized_pnl", 0) or 0)
            is_win = pnl > 0

            by_strategy[strategy]["wins" if is_win else "losses"] += 1
            by_strategy[strategy]["pnl"] += pnl

            # Parse entry time for time-of-day analysis
            entry_date = o.get("entry_date", "")
            if entry_date:
                try:
                    dt = datetime.fromisoformat(entry_date.replace("Z", "+00:00"))
                    by_hour[dt.hour]["wins" if is_win else "losses"] += 1
                    by_hour[dt.hour]["pnl"] += pnl
                    by_weekday[dt.strftime("%A")]["wins" if is_win else "losses"] += 1
                    by_weekday[dt.strftime("%A")]["pnl"] += pnl
                except (ValueError, TypeError):
                    pass

        # Calculate win rates
        stats = {}
        for strategy, data in by_strategy.items():
            total = data["wins"] + data["losses"]
            stats[strategy] = {
                "total": total,
                "wins": data["wins"],
                "losses": data["losses"],
                "win_rate": round(data["wins"] / total * 100, 1) if total > 0 else 0,
                "total_pnl": round(data["pnl"], 2),
            }

        return stats

    def _detect_behavioral_issues(self, todays_trades: list, outcomes: list) -> list:
        """Detect revenge trading and rapid-fire patterns."""
        flags = []

        # Revenge trading: quick trades after losses
        recent = sorted(outcomes[:10], key=lambda x: x.get("entry_date", ""))
        consecutive_losses = 0
        for o in reversed(recent):
            if float(o.get("realized_pnl", 0) or 0) < 0:
                consecutive_losses += 1
            else:
                break

        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES_BEFORE_COOLDOWN:
            flags.append({
                "type": "revenge_trading_risk",
                "message": f"{consecutive_losses} consecutive losses detected. "
                          f"Recommend cooldown period.",
                "severity": "warning",
            })

        # Check for rapid-fire trades (< 2 min apart)
        if len(todays_trades) >= 2:
            for i in range(1, len(todays_trades)):
                t1 = todays_trades[i - 1].get("created_at", "")
                t2 = todays_trades[i].get("created_at", "")
                try:
                    dt1 = datetime.fromisoformat(t1.replace("Z", "+00:00"))
                    dt2 = datetime.fromisoformat(t2.replace("Z", "+00:00"))
                    if (dt2 - dt1).total_seconds() < 120:
                        flags.append({
                            "type": "rapid_fire",
                            "message": "Trades placed less than 2 minutes apart",
                            "severity": "info",
                        })
                        break
                except (ValueError, TypeError):
                    pass

        return flags

    def _calibrate_stops(self, outcomes: list) -> list:
        """Check if stopped-out trades would have been profitable with wider stops."""
        adjustments = []
        by_strategy = defaultdict(list)

        for o in outcomes:
            if o.get("exit_reason") == "stop_loss":
                by_strategy[o.get("strategy", "unknown")].append(o)

        for strategy, stopped_trades in by_strategy.items():
            if len(stopped_trades) < 5:
                continue

            # Check how many would have hit target with wider stop
            would_have_won = sum(
                1 for t in stopped_trades if t.get("post_exit_hit_target")
            )
            rate = would_have_won / len(stopped_trades)

            if rate > 0.4:  # 40%+ of stops would have been winners
                current_config = self.db.get_adaptive_config(
                    ACCOUNT_ID, parameter="stop_pct", strategy=strategy
                )
                current_stop = float(current_config[0]["value"]) if current_config else 1.0
                new_stop = round(current_stop * 1.15, 2)  # Widen by 15%
                new_stop = min(new_stop, 3.0)  # Cap at 3%

                adjustments.append({
                    "strategy": strategy,
                    "old_stop": current_stop,
                    "new_stop": new_stop,
                    "reason": f"{rate:.0%} of stops would have been winners "
                             f"(sample: {len(stopped_trades)})",
                })
                logger.info(
                    f"Stop calibration for {strategy}: "
                    f"{current_stop}% -> {new_stop}%"
                )

        return adjustments

    def should_cooldown(self) -> bool:
        """Check if trading should pause due to behavioral flags."""
        outcomes = self.db.get_trade_outcomes(ACCOUNT_ID, limit=10)
        outcomes.sort(key=lambda o: o.get("exit_date", ""), reverse=True)
        consecutive_losses = 0
        for o in outcomes:
            if float(o.get("realized_pnl", 0) or 0) < 0:
                consecutive_losses += 1
            else:
                break

        return consecutive_losses >= MAX_CONSECUTIVE_LOSSES_BEFORE_COOLDOWN
