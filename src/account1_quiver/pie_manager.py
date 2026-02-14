import logging
from datetime import date

from src.shared.database import Database
from src.shared.alpaca_client import AlpacaClient
from src.shared.risk_manager import RiskManager
from src.account1_quiver.config import ACCOUNT_ID

logger = logging.getLogger(__name__)


class PieManager:
    """Manage target allocations (pie) for Account 1."""

    def __init__(self):
        self.db = Database()
        self.alpaca = AlpacaClient(ACCOUNT_ID)
        self.risk = RiskManager(ACCOUNT_ID)

    def create_pie_from_signals(self, analyzed_signals: list) -> dict:
        """Create a new target allocation pie from analyzed signals.

        analyzed_signals: list of dicts with symbol, confidence, position_size_pct, etc.
        """
        working_capital = self.risk.get_working_capital()
        max_invested_pct = self.risk.config.get("max_invested_pct", 0.60)
        max_investable = working_capital * max_invested_pct

        # Build allocations from approved signals
        allocations = []
        total_allocated = 0.0

        for signal in analyzed_signals:
            symbol = signal["symbol"]
            confidence = signal.get("confidence", 0)
            size_pct = signal.get("position_size_pct", 0.5)

            # Calculate target weight within the investable portion
            max_pos = self.risk.config.get("max_position_pct", 0.08) * working_capital
            target_notional = max_pos * size_pct

            if total_allocated + target_notional > max_investable:
                target_notional = max_investable - total_allocated
                if target_notional <= 0:
                    break

            target_weight = target_notional / max_investable
            total_allocated += target_notional

            allocations.append({
                "symbol": symbol,
                "target_weight": round(target_weight, 4),
                "source": ", ".join(signal.get("sources", [])),
                "signal_date": date.today().isoformat(),
            })

        if not allocations:
            logger.info("No allocations to create pie")
            return {}

        # Save pie to DB
        pie = self.db.create_pie(
            {"account_id": ACCOUNT_ID, "name": f"Pie {date.today().isoformat()}"},
            allocations,
        )

        logger.info(
            f"Created pie with {len(allocations)} allocations, "
            f"total allocated: ${total_allocated:.2f}"
        )
        return {"pie": pie, "allocations": allocations, "total_allocated": total_allocated}

    def check_rebalance_needed(self) -> list:
        """Check if current positions have drifted from target allocation."""
        active_pie = self.db.get_active_pie(ACCOUNT_ID)
        if not active_pie or not active_pie.get("pie_allocations"):
            return []

        drift_threshold = self.risk.config.get("rebalance_drift_threshold", 0.10)
        positions = self.alpaca.get_positions()
        position_map = {pos.symbol: float(pos.market_value) for pos in positions}
        total_invested = sum(position_map.values())

        if total_invested == 0:
            return []

        rebalance_actions = []
        for alloc in active_pie["pie_allocations"]:
            symbol = alloc["symbol"]
            target_weight = float(alloc["target_weight"])
            current_value = position_map.get(symbol, 0)
            current_weight = current_value / total_invested if total_invested > 0 else 0

            drift = abs(current_weight - target_weight)
            if drift > drift_threshold:
                action = "buy" if current_weight < target_weight else "sell"
                rebalance_actions.append({
                    "symbol": symbol,
                    "action": action,
                    "target_weight": target_weight,
                    "current_weight": round(current_weight, 4),
                    "drift": round(drift, 4),
                })

        if rebalance_actions:
            logger.info(f"Rebalance needed for {len(rebalance_actions)} positions")

        return rebalance_actions
