import logging
from collections import defaultdict

from src.shared.database import Database
from src.account1_quiver.config import (
    ACCOUNT_ID,
    BASE_SCORES,
    MIN_COMPOSITE_SCORE,
)
from src.shared.config import CONVERGENCE_MULTIPLIERS, COMBO_BONUSES

logger = logging.getLogger(__name__)


class SignalScorer:
    """Composite scoring with convergence bonuses and adaptive weights."""

    def __init__(self):
        self.db = Database()
        self.weights = self.db.get_signal_weights(ACCOUNT_ID)

    def score_signals(self, signals: list) -> list:
        """Score individual signals and apply convergence bonuses.

        Returns signals grouped by symbol with composite scores.
        """
        # Group signals by symbol
        by_symbol = defaultdict(list)
        for signal in signals:
            by_symbol[signal["symbol"]].append(signal)

        scored = []
        for symbol, symbol_signals in by_symbol.items():
            composite = self._compute_composite(symbol, symbol_signals)
            scored.append(composite)

        # Sort by composite score descending
        scored.sort(key=lambda x: x["composite_score"], reverse=True)

        # Filter below minimum threshold
        scored = [s for s in scored if s["composite_score"] >= MIN_COMPOSITE_SCORE]

        logger.info(
            f"Scored {len(scored)} symbols above threshold "
            f"(from {len(signals)} raw signals)"
        )
        return scored

    def _compute_composite(self, symbol: str, signals: list) -> dict:
        """Compute composite score for a symbol from its signals."""
        total_score = 0.0
        sources = set()
        primary_direction = "buy"  # Default
        primary_signals = []
        confirmation_signals = []

        for signal in signals:
            source = signal["source"]
            sources.add(source)

            # Base score from source type
            base = BASE_SCORES.get(source, 10)

            # Apply signal strength
            strength = float(signal.get("strength", 0.5))
            signal_score = base * strength

            # Apply adaptive weight from DB
            weight = self.weights.get(source, 1.0)
            signal_score *= float(weight)

            # Track direction from primary signals
            if signal.get("signal_role") != "confirmation":
                primary_direction = signal["direction"]
                primary_signals.append(signal)
            else:
                confirmation_signals.append(signal)

            total_score += signal_score
            signal["composite_score"] = round(signal_score, 2)

        # Apply convergence multiplier
        unique_sources = len(sources)
        if unique_sources in CONVERGENCE_MULTIPLIERS:
            multiplier = CONVERGENCE_MULTIPLIERS[unique_sources]
            total_score *= multiplier
            logger.debug(
                f"{symbol}: {unique_sources} sources, "
                f"convergence multiplier {multiplier}x"
            )

        # Apply combo bonuses
        for combo_sources, bonus in COMBO_BONUSES.items():
            if combo_sources.issubset(sources):
                total_score *= bonus
                logger.debug(f"{symbol}: combo bonus {bonus}x for {combo_sources}")

        # Confirmation signals boost score but don't generate trades alone
        has_primary = len(primary_signals) > 0
        if not has_primary and confirmation_signals:
            total_score *= 0.3  # Heavy discount for confirmation-only

        composite_score = round(total_score, 2)

        return {
            "symbol": symbol,
            "composite_score": composite_score,
            "direction": primary_direction,
            "sources": list(sources),
            "source_count": unique_sources,
            "signals": signals,
            "has_primary": has_primary,
        }
