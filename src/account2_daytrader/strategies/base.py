import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Base class for day trading strategies."""

    name: str = "base"

    @abstractmethod
    def evaluate(self, candidate: dict) -> Optional[dict]:
        """Evaluate a candidate and return a trade setup or None.

        Returns:
            dict with keys: symbol, side, entry_price, target_price,
            stop_price, strategy, confidence, reasoning
        """
        pass

    def calculate_target(self, entry: float, target_pct: float, side: str) -> float:
        if side == "buy":
            return round(entry * (1 + target_pct / 100), 2)
        return round(entry * (1 - target_pct / 100), 2)

    def calculate_stop(self, entry: float, stop_pct: float, side: str) -> float:
        if side == "buy":
            return round(entry * (1 - stop_pct / 100), 2)
        return round(entry * (1 + stop_pct / 100), 2)
