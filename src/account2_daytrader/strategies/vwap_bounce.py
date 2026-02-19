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

        setups = candidate.get("setups", [])
        is_long = "vwap_bounce" in setups
        is_short = "vwap_rejection" in setups

        if not is_long and not is_short:
            return None

        current_price = candidate.get("current_price")
        vwap = candidate.get("vwap")
        if not vwap or not current_price:
            return None

        vwap_dist = (current_price - vwap) / vwap * 100
        abs_dist = abs(vwap_dist)

        # Validate proximity
        if abs_dist > config["vwap_proximity_pct"]:
            return None

        side = "buy" if is_long else "sell"
        entry = current_price
        target = self.calculate_target(entry, config["target_pct"], side)
        stop = self.calculate_stop(entry, config["stop_pct"], side)

        # Closer to VWAP = higher confidence (scale by proximity)
        confidence = min(60 + int((config["vwap_proximity_pct"] - abs_dist) * 30), 80)

        direction = "bounce" if is_long else "rejection"
        position = "above" if vwap_dist > 0 else "below"
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
                f"VWAP {direction}: price {abs_dist:.2f}% {position} VWAP ${vwap}, "
                f"volume {candidate.get('volume_ratio', 'N/A')}x"
            ),
        }
        return self.apply_catalyst_boost(setup, candidate)
