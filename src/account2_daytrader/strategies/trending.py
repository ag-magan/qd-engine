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

        setups = candidate.get("setups", [])
        is_long = "trending" in setups
        is_short = "trending_short" in setups

        if not is_long and not is_short:
            return None

        sma_10 = candidate.get("sma_10", 0)
        sma_20 = candidate.get("sma_20", 0)
        if not sma_10 or not sma_20:
            return None

        # SMA spread measures trend strength (absolute value for both directions)
        sma_spread_pct = abs((sma_10 - sma_20) / sma_20) * 100
        if sma_spread_pct < config.get("min_sma_spread_pct", 0.1):
            return None

        side = "buy" if is_long else "sell"
        entry = candidate["current_price"]
        target = self.calculate_target(entry, config["target_pct"], side)
        stop = self.calculate_stop(entry, config["stop_pct"], side)

        # Stronger trends (bigger SMA spread) = higher confidence
        volume_ratio = candidate.get("volume_ratio", 1.0)
        confidence = min(50 + int(sma_spread_pct * 20) + int(volume_ratio * 5), 85)

        direction = "uptrend" if is_long else "downtrend"
        sma_rel = "SMA10 > SMA20" if is_long else "SMA10 < SMA20"
        setup = {
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
                f"Trend following ({direction}): {sma_rel} by {sma_spread_pct:.2f}%, "
                f"volume {volume_ratio:.1f}x, RSI {candidate.get('rsi', 'N/A')}"
            ),
        }
        return self.apply_catalyst_boost(setup, candidate)
