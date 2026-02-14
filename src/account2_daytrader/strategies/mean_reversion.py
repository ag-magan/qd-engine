import logging
from typing import Optional

from src.account2_daytrader.strategies.base import BaseStrategy
from src.account2_daytrader.config import STRATEGIES

logger = logging.getLogger(__name__)


class MeanReversion(BaseStrategy):
    """Mean reversion on oversold conditions with volume confirmation."""

    name = "mean_reversion"

    def evaluate(self, candidate: dict) -> Optional[dict]:
        config = STRATEGIES["mean_reversion"]
        if not config["enabled"]:
            return None

        if "mean_reversion" not in candidate.get("setups", []):
            return None

        rsi = candidate.get("rsi", 50)
        if rsi > config["rsi_oversold"]:
            return None

        volume_ratio = candidate.get("volume_ratio", 0)
        if volume_ratio < config["min_volume_spike"]:
            return None

        entry = candidate["current_price"]
        target = self.calculate_target(entry, config["target_pct"], "buy")
        stop = self.calculate_stop(entry, config["stop_pct"], "buy")

        # Lower RSI = higher confidence in reversal
        confidence = min(50 + int((config["rsi_oversold"] - rsi) * 2), 85)

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
                f"Mean reversion: RSI {rsi:.1f} (oversold), "
                f"volume {volume_ratio:.1f}x avg"
            ),
        }
