import logging
from typing import Optional

from src.account2_daytrader.strategies.base import BaseStrategy
from src.account2_daytrader.config import STRATEGIES

logger = logging.getLogger(__name__)


class GapFill(BaseStrategy):
    """Gap fill strategy: stock gaps up/down >3% at open, target 50% fill."""

    name = "gap_fill"

    def evaluate(self, candidate: dict) -> Optional[dict]:
        config = STRATEGIES["gap_fill"]
        if not config["enabled"]:
            return None

        if "gap_fill" not in candidate.get("setups", []):
            return None

        prev_close = candidate.get("prev_close")
        current_price = candidate.get("current_price")
        if not prev_close or not current_price:
            return None

        gap_pct = ((current_price - prev_close) / prev_close) * 100

        if abs(gap_pct) < config["min_gap_pct"]:
            return None

        # Gap up = short (sell into gap fill), gap down = buy the dip
        if gap_pct > 0:
            side = "sell"
            # Target: price fills 50% of the gap
            gap_amount = current_price - prev_close
            target_price = round(current_price - (gap_amount * config["target_fill_pct"] / 100), 2)
            stop_price = self.calculate_stop(current_price, config["stop_pct"], "sell")
        else:
            side = "buy"
            gap_amount = prev_close - current_price
            target_price = round(current_price + (gap_amount * config["target_fill_pct"] / 100), 2)
            stop_price = self.calculate_stop(current_price, config["stop_pct"], "buy")

        # Larger gaps = higher confidence (to a point)
        confidence = min(50 + int(abs(gap_pct) * 5), 85)

        setup = {
            "symbol": candidate["symbol"],
            "side": side,
            "entry_price": current_price,
            "target_price": target_price,
            "stop_price": stop_price,
            "target_pct": config["target_pct"],
            "stop_pct": config["stop_pct"],
            "strategy": self.name,
            "confidence": confidence,
            "reasoning": (
                f"Gap {'up' if gap_pct > 0 else 'down'} {abs(gap_pct):.1f}%, "
                f"targeting {config['target_fill_pct']}% fill"
            ),
        }
        return self.apply_catalyst_boost(setup, candidate)
