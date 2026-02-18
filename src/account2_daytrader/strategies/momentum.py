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

        setups = candidate.get("setups", [])
        is_long = "momentum" in setups
        is_short = "momentum_short" in setups

        if not is_long and not is_short:
            return None

        volume_ratio = candidate.get("volume_ratio", 0)
        if volume_ratio < config["min_volume_ratio"]:
            return None

        side = "buy" if is_long else "sell"
        entry = candidate["current_price"]
        target = self.calculate_target(entry, config["target_pct"], side)
        stop = self.calculate_stop(entry, config["stop_pct"], side)

        # Confidence based on volume strength
        confidence = min(50 + int(volume_ratio * 10), 90)

        direction = "breakout" if is_long else "breakdown"
        return {
            "symbol": candidate["symbol"],
            "side": side,
            "entry_price": entry,
            "target_price": target,
            "stop_price": stop,
            "target_pct": config["target_pct"],
            "stop_pct": config["stop_pct"],
            "strategy": self.name,
            "confidence": confidence,
            "reasoning": (
                f"Momentum {direction}: volume {volume_ratio:.1f}x avg, "
                f"RSI {candidate.get('rsi', 'N/A')}"
            ),
        }
