import logging
from datetime import date, datetime, timezone

import numpy as np

from src.shared.config import STARTING_CAPITAL, PAPER_RESERVE
from src.shared.database import Database
from src.shared.alpaca_client import AlpacaClient

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """Track portfolio snapshots and calculate performance metrics."""

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.db = Database()
        self.alpaca = AlpacaClient(account_id)

    def take_snapshot(self) -> dict:
        """Capture current portfolio state and save to database."""
        try:
            positions = self.alpaca.get_positions()

            # Calculate invested value and unrealized P&L from positions
            position_data = []
            total_invested = 0.0
            total_unrealized = 0.0
            for pos in positions:
                pos_dict = {
                    "symbol": pos.symbol,
                    "qty": str(pos.qty),
                    "market_value": str(pos.market_value),
                    "avg_entry_price": str(pos.avg_entry_price),
                    "current_price": str(pos.current_price),
                    "unrealized_pl": str(pos.unrealized_pl),
                    "unrealized_plpc": str(pos.unrealized_plpc),
                }
                position_data.append(pos_dict)
                total_invested += abs(float(pos.market_value))
                total_unrealized += float(pos.unrealized_pl)

            # Use Alpaca's actual equity as source of truth
            account = self.alpaca.get_account()
            alpaca_equity = round(float(account.equity), 2)
            alpaca_cash = round(float(account.cash), 2)

            equity = round(alpaca_equity - PAPER_RESERVE, 2)
            cash = round(alpaca_cash - PAPER_RESERVE, 2)
            total_pnl = equity - STARTING_CAPITAL

            # Daily P&L: compare to yesterday's snapshot
            daily_pnl = 0.0
            prev = self.db.get_latest_snapshot(self.account_id)
            if prev:
                prev_equity = float(prev.get("equity", STARTING_CAPITAL))
                daily_pnl = round(equity - prev_equity, 2)

            snapshot = {
                "account_id": self.account_id,
                "equity": equity,
                "cash": cash,
                "positions": position_data,
                "daily_pnl": daily_pnl,
                "total_pnl": round(total_pnl, 2),
                "snapshot_date": date.today().isoformat(),
                "alpaca_equity": alpaca_equity,
            }

            self.db.upsert_snapshot(snapshot)
            logger.info(
                f"Snapshot for {self.account_id}: equity=${equity:.2f}, "
                f"daily_pnl=${daily_pnl:.2f}, total_pnl=${total_pnl:.2f}, "
                f"alpaca_equity=${alpaca_equity}"
            )
            return snapshot

        except Exception as e:
            logger.error(f"Failed to take snapshot for {self.account_id}: {e}")
            return {}

    def get_performance_metrics(self) -> dict:
        """Calculate comprehensive performance metrics."""
        outcomes = self.db.get_trade_outcomes(self.account_id, limit=10000)
        snapshots = self.db.get_snapshots(self.account_id, limit=365)

        if not outcomes:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "sharpe_ratio": 0,
                "max_drawdown": 0,
                "profit_factor": 0,
                "avg_win": 0,
                "avg_loss": 0,
            }

        # Win/loss stats
        wins = [o for o in outcomes if float(o.get("realized_pnl", 0) or 0) > 0]
        losses = [o for o in outcomes if float(o.get("realized_pnl", 0) or 0) < 0]
        total_trades = len(outcomes)
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

        total_pnl = sum(float(o.get("realized_pnl", 0) or 0) for o in outcomes)
        avg_win = (
            np.mean([float(o["realized_pnl"]) for o in wins]) if wins else 0
        )
        avg_loss = (
            np.mean([float(o["realized_pnl"]) for o in losses]) if losses else 0
        )

        # Profit factor
        gross_profit = sum(float(o["realized_pnl"]) for o in wins)
        gross_loss = abs(sum(float(o["realized_pnl"]) for o in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Sharpe ratio from daily snapshots
        sharpe_ratio = 0.0
        max_drawdown = 0.0
        if len(snapshots) >= 2:
            equities = [float(s["equity"]) for s in reversed(snapshots)]
            daily_returns = []
            for i in range(1, len(equities)):
                ret = (equities[i] - equities[i - 1]) / equities[i - 1]
                daily_returns.append(ret)

            if daily_returns:
                mean_ret = np.mean(daily_returns)
                std_ret = np.std(daily_returns)
                sharpe_ratio = (
                    (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0
                )

            # Max drawdown
            peak = equities[0]
            for eq in equities:
                if eq > peak:
                    peak = eq
                drawdown = (peak - eq) / peak * 100
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        return {
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "return_pct": round(total_pnl / STARTING_CAPITAL * 100, 2),
        }
