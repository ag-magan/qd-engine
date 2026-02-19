import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Base class for day trading strategies.

    Supports DB parameter overrides: when a strategy_definitions row exists,
    its exit_rules and filters override the hardcoded config values.
    """

    name: str = "base"

    def __init__(self, db_overrides: dict = None):
        """Initialize with optional DB overrides from strategy_definitions.

        db_overrides: {
            "exit_rules": {"take_profit_pct": 2.0, "stop_loss_pct": 1.0, ...},
            "filters": {"min_volume_ratio": 2.0, ...},
            "position_rules": {"confidence_minimum": 60, ...},
        }
        """
        self.db_overrides = db_overrides or {}

    def get_config_value(self, config: dict, key: str, default=None):
        """Get a config value, checking DB overrides first.

        Checks exit_rules, filters, and position_rules from DB overrides.
        Falls back to the hardcoded config dict.
        """
        for section in ["exit_rules", "filters", "position_rules"]:
            override_section = self.db_overrides.get(section, {})
            if override_section and key in override_section:
                return override_section[key]
        return config.get(key, default)

    @abstractmethod
    def evaluate(self, candidate: dict) -> Optional[dict]:
        """Evaluate a candidate and return a trade setup or None.

        Returns:
            dict with keys: symbol, side, entry_price, target_price,
            stop_price, strategy, confidence, reasoning
        """
        pass

    def apply_catalyst_boost(self, setup: dict, candidate: dict) -> dict:
        """Boost confidence if the candidate has QuiverQuant catalyst data."""
        boost = candidate.get("catalyst_boost", 0)
        if boost and setup:
            setup["confidence"] = min(setup["confidence"] + boost, 95)
            sources = ", ".join(candidate.get("catalyst_sources", []))
            setup["reasoning"] += f" [CATALYST: {sources} boost=+{boost}]"
            setup["has_catalyst"] = True
            setup["catalyst_score"] = candidate.get("catalyst_score", 0)
        return setup

    def calculate_target(self, entry: float, target_pct: float, side: str) -> float:
        if side == "buy":
            return round(entry * (1 + target_pct / 100), 2)
        return round(entry * (1 - target_pct / 100), 2)

    def calculate_stop(self, entry: float, stop_pct: float, side: str) -> float:
        if side == "buy":
            return round(entry * (1 - stop_pct / 100), 2)
        return round(entry * (1 + stop_pct / 100), 2)
