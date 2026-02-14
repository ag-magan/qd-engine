import logging
from typing import Optional

from src.account2_daytrader.strategies.base import BaseStrategy
from src.account2_daytrader.config import STRATEGIES

logger = logging.getLogger(__name__)


class MomentumBreakout(BaseStrategy):
    """Momentum breakout strategy: stock breaks above resistance on high volume."""

    name = "momentum"

    def evaluate(self, candidate: dict) -> Optional[dict]:
        config = STRATEGIES["momentum"]
        if not config["enabled"]:
            return None

        if "momentum" not in candidate.get("setups", []):
            return None

        volume_ratio = candidate.get("volume_ratio", 0)
        if volume_ratio < config["min_volume_ratio"]:
            return None

        entry = candidate["current_price"]
        target = self.calculate_target(entry, config["target_pct"], "buy")
        stop = self.calculate_stop(entry, config["stop_pct"], "buy")

        # Confidence based on volume strength
        confidence = min(50 + int(volume_ratio * 10), 90)

        return {
            "symbol": candidate["symbol"],
            "side": "buy",
            "entry_price": entry,
            "target_price": target,
            "stop_price": stop,
            "target_pct": config["target_pct"],
            "stop_pct": config["stop_pct"],
            "strategy": self.name,
            "confidence": confidence,
            "reasoning": (
                f"Momentum breakout: volume {volume_ratio:.1f}x avg, "
                f"RSI {candidate.get('rsi', 'N/A')}"
            ),
        }
