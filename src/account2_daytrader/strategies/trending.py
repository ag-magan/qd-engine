import logging
from typing import Optional

from src.account2_daytrader.strategies.base import BaseStrategy
from src.account2_daytrader.config import STRATEGIES

logger = logging.getLogger(__name__)


class TrendFollowing(BaseStrategy):
    """Trend following strategy: price riding above rising moving averages."""

    name = "trending"

    def evaluate(self, candidate: dict) -> Optional[dict]:
        config = STRATEGIES["trending"]
        if not config["enabled"]:
            return None

        if "trending" not in candidate.get("setups", []):
            return None

        sma_10 = candidate.get("sma_10", 0)
        sma_20 = candidate.get("sma_20", 0)
        if not sma_10 or not sma_20:
            return None

        # SMA spread measures trend strength
        sma_spread_pct = ((sma_10 - sma_20) / sma_20) * 100
        if sma_spread_pct < config.get("min_sma_spread_pct", 0.1):
            return None

        entry = candidate["current_price"]
        target = self.calculate_target(entry, config["target_pct"], "buy")
        stop = self.calculate_stop(entry, config["stop_pct"], "buy")

        # Stronger trends (bigger SMA spread) = higher confidence
        volume_ratio = candidate.get("volume_ratio", 1.0)
        confidence = min(50 + int(sma_spread_pct * 20) + int(volume_ratio * 5), 85)

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
                f"Trend following: SMA10 > SMA20 by {sma_spread_pct:.2f}%, "
                f"volume {volume_ratio:.1f}x, RSI {candidate.get('rsi', 'N/A')}"
            ),
        }
