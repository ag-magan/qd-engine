import logging
from collections import defaultdict

import numpy as np

from src.shared.config import STARTING_CAPITAL
from src.shared.database import Database

logger = logging.getLogger(__name__)


def calculate_metrics(account_id: str) -> dict:
    """Calculate comprehensive performance metrics for an account."""
    db = Database()
    outcomes = db.get_trade_outcomes(account_id, limit=10000)
    snapshots = db.get_snapshots(account_id, limit=365)

    metrics = {
        "account_id": account_id,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0,
        "total_pnl": 0,
        "avg_win": 0,
        "avg_loss": 0,
        "profit_factor": 0,
        "sharpe_ratio": 0,
        "max_drawdown_pct": 0,
        "return_pct": 0,
        "avg_holding_hours": 0,
        "best_trade": None,
        "worst_trade": None,
        "by_strategy": {},
        "by_day_of_week": {},
    }

    if not outcomes:
        return metrics

    # Basic stats
    pnls = [float(o.get("realized_pnl", 0) or 0) for o in outcomes]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    metrics["total_trades"] = len(outcomes)
    metrics["wins"] = len(wins)
    metrics["losses"] = len(losses)
    metrics["win_rate"] = round(len(wins) / len(pnls) * 100, 1) if pnls else 0
    metrics["total_pnl"] = round(sum(pnls), 2)
    metrics["avg_win"] = round(np.mean(wins), 2) if wins else 0
    metrics["avg_loss"] = round(np.mean(losses), 2) if losses else 0
    metrics["return_pct"] = round(sum(pnls) / STARTING_CAPITAL * 100, 2)

    # Profit factor
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    metrics["profit_factor"] = (
        round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")
    )

    # Best/worst trades
    if outcomes:
        best = max(outcomes, key=lambda o: float(o.get("realized_pnl", 0) or 0))
        worst = min(outcomes, key=lambda o: float(o.get("realized_pnl", 0) or 0))
        metrics["best_trade"] = {
            "symbol": best.get("symbol"),
            "pnl": float(best.get("realized_pnl", 0) or 0),
            "strategy": best.get("strategy"),
        }
        metrics["worst_trade"] = {
            "symbol": worst.get("symbol"),
            "pnl": float(worst.get("realized_pnl", 0) or 0),
            "strategy": worst.get("strategy"),
        }

    # Average holding period
    holding_hours = [
        float(o.get("holding_period_hours", 0) or 0) for o in outcomes
        if o.get("holding_period_hours")
    ]
    metrics["avg_holding_hours"] = round(np.mean(holding_hours), 1) if holding_hours else 0

    # Sharpe ratio from snapshots
    if len(snapshots) >= 2:
        equities = [float(s["equity"]) for s in reversed(snapshots)]
        daily_returns = []
        for i in range(1, len(equities)):
            ret = (equities[i] - equities[i - 1]) / equities[i - 1]
            daily_returns.append(ret)
        if daily_returns:
            metrics["sharpe_ratio"] = round(
                (np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252)
                if np.std(daily_returns) > 0 else 0, 2
            )
        # Max drawdown
        peak = equities[0]
        max_dd = 0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
        metrics["max_drawdown_pct"] = round(max_dd, 2)

    # By strategy
    by_strategy = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0})
    for o in outcomes:
        strat = o.get("strategy", "unknown")
        pnl = float(o.get("realized_pnl", 0) or 0)
        by_strategy[strat]["wins" if pnl > 0 else "losses"] += 1
        by_strategy[strat]["pnl"] += pnl

    for strat, data in by_strategy.items():
        total = data["wins"] + data["losses"]
        metrics["by_strategy"][strat] = {
            "total": total,
            "wins": data["wins"],
            "losses": data["losses"],
            "win_rate": round(data["wins"] / total * 100, 1) if total > 0 else 0,
            "pnl": round(data["pnl"], 2),
        }

    return metrics
