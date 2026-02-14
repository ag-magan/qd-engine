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
    """Composite scoring with convergence bonuses and adaptive weights.

    Reads scoring rules from the database when available,
    falls back to hardcoded constants.
    """

    def __init__(self):
        self.db = Database()
        self.weights = self.db.get_signal_weights(ACCOUNT_ID)
        self.convergence_multipliers, self.combo_bonuses = self._load_scoring_rules()

    def _load_scoring_rules(self) -> tuple:
        """Load scoring rules from DB, falling back to hardcoded defaults."""
        convergence = dict(CONVERGENCE_MULTIPLIERS)
        combos = dict(COMBO_BONUSES)

        try:
            resp = (
                self.db.client.table("scoring_rules")
                .select("*")
                .eq("account_id", ACCOUNT_ID)
                .eq("is_active", True)
                .execute()
            )
            rules = resp.data
        except Exception:
            logger.debug("No scoring rules in DB, using hardcoded defaults")
            return convergence, combos

        if not rules:
            return convergence, combos

        # Build from DB rules
        db_convergence = {}
        db_combos = {}

        for rule in rules:
            config = rule.get("rule_config", {})
            if rule["rule_type"] == "convergence_multiplier":
                count = config.get("source_count")
                mult = config.get("multiplier")
                if count is not None and mult is not None:
                    db_convergence[int(count)] = float(mult)
            elif rule["rule_type"] == "source_combo_bonus":
                combo = config.get("combo", [])
                bonus = config.get("bonus")
                if combo and bonus is not None:
                    db_combos[frozenset(combo)] = float(bonus)

        if db_convergence:
            convergence = db_convergence
            logger.info(f"Loaded {len(db_convergence)} convergence multipliers from DB")
        if db_combos:
            combos = db_combos
            logger.info(f"Loaded {len(db_combos)} combo bonuses from DB")

        return convergence, combos

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
        if unique_sources in self.convergence_multipliers:
            multiplier = self.convergence_multipliers[unique_sources]
            total_score *= multiplier
            logger.debug(
                f"{symbol}: {unique_sources} sources, "
                f"convergence multiplier {multiplier}x"
            )

        # Apply combo bonuses
        for combo_sources, bonus in self.combo_bonuses.items():
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
