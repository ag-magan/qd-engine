import logging
from typing import Optional

from src.account2_daytrader.strategies.base import BaseStrategy
from src.account2_daytrader.config import STRATEGIES

logger = logging.getLogger(__name__)


class VWAPBounce(BaseStrategy):
    """VWAP bounce strategy: price touches VWAP and bounces with confirmation."""

    name = "vwap_bounce"

    def evaluate(self, candidate: dict) -> Optional[dict]:
        config = STRATEGIES["vwap_bounce"]
        if not config["enabled"]:
            return None

        if "vwap_bounce" not in candidate.get("setups", []):
            return None

        current_price = candidate.get("current_price")
        vwap = candidate.get("vwap")
        if not vwap or not current_price:
            return None

        # Price should be above VWAP (bounce confirmed)
        vwap_dist = (current_price - vwap) / vwap * 100
        if vwap_dist < 0 or vwap_dist > config["vwap_proximity_pct"]:
            return None

        entry = current_price
        target = self.calculate_target(entry, config["target_pct"], "buy")
        stop = self.calculate_stop(entry, config["stop_pct"], "buy")

        # Closer to VWAP = higher confidence
        confidence = min(60 + int((config["vwap_proximity_pct"] - vwap_dist) * 100), 80)

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
                f"VWAP bounce: price {vwap_dist:.2f}% above VWAP ${vwap}, "
                f"volume {candidate.get('volume_ratio', 'N/A')}x"
            ),
        }
