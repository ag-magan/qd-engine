import logging

from src.shared.database import Database

logger = logging.getLogger(__name__)

MIN_SAMPLE_SIZE = 20  # Minimum trades before adjusting weights


def update_signal_weights(account_id: str) -> dict:
    """Dynamically adjust signal weights based on performance.

    Only adjusts weights when we have sufficient sample size (20+ trades).
    """
    db = Database()
    scorecards = db.get_scorecard(account_id)

    if not scorecards:
        return {}

    # Calculate performance-based weights
    adjustments = {}
    for sc in scorecards:
        source = sc["signal_source"]
        acted_on = sc.get("acted_on", 0)

        if acted_on < MIN_SAMPLE_SIZE:
            logger.info(
                f"Skipping weight adjustment for {source}: "
                f"only {acted_on} trades (need {MIN_SAMPLE_SIZE})"
            )
            continue

        win_rate = float(sc.get("win_rate", 50) or 50)
        avg_return = float(sc.get("avg_return_pct", 0) or 0)

        # Weight formula: combine win rate and return quality
        # Base weight = 1.0. Adjust up/down based on performance.
        # Win rate component: 50% = neutral, >50% = bonus, <50% = penalty
        win_rate_factor = (win_rate - 50) / 50  # -1.0 to +1.0

        # Return component: positive returns = bonus
        return_factor = min(max(avg_return / 5.0, -0.5), 0.5)  # Clamp to [-0.5, 0.5]

        # Combined weight (0.3 to 2.0 range)
        new_weight = 1.0 + (win_rate_factor * 0.4) + (return_factor * 0.3)
        new_weight = max(0.3, min(2.0, new_weight))

        # Get current weight
        current_weights = db.get_signal_weights(account_id)
        current = current_weights.get(source, 1.0)

        # Only adjust if meaningful change (>10%)
        if abs(new_weight - current) / current > 0.10:
            db.upsert_signal_weight({
                "account_id": account_id,
                "signal_source": source,
                "weight": round(new_weight, 3),
                "sample_size": acted_on,
            })
            adjustments[source] = {
                "old_weight": current,
                "new_weight": round(new_weight, 3),
                "win_rate": win_rate,
                "avg_return": avg_return,
                "sample_size": acted_on,
            }
            logger.info(
                f"Weight adjusted for {source}: "
                f"{current:.3f} -> {new_weight:.3f} "
                f"(win_rate={win_rate}%, avg_return={avg_return}%)"
            )

    return adjustments
