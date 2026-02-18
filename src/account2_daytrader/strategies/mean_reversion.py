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

        setups = candidate.get("setups", [])
        is_long = "mean_reversion" in setups
        is_short = "mean_reversion_short" in setups

        if not is_long and not is_short:
            return None

        rsi = candidate.get("rsi", 50)
        volume_ratio = candidate.get("volume_ratio", 0)
        if volume_ratio < config["min_volume_spike"]:
            return None

        if is_long and rsi > config["rsi_oversold"]:
            return None
        if is_short and rsi < config.get("rsi_overbought", 70):
            return None

        side = "buy" if is_long else "sell"
        entry = candidate["current_price"]
        target = self.calculate_target(entry, config["target_pct"], side)
        stop = self.calculate_stop(entry, config["stop_pct"], side)

        # Further from neutral RSI = higher confidence in reversal
        if is_long:
            confidence = min(50 + int((config["rsi_oversold"] - rsi) * 2), 85)
            condition = f"oversold RSI {rsi:.1f}"
        else:
            confidence = min(50 + int((rsi - config.get("rsi_overbought", 70)) * 2), 85)
            condition = f"overbought RSI {rsi:.1f}"

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
                f"Mean reversion: {condition}, "
                f"volume {volume_ratio:.1f}x avg"
            ),
        }
