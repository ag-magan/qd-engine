import json
import logging

from src.shared.claude_client import ClaudeClient
from src.shared.database import Database
from src.shared.alerter import HealthTracker
from src.learning.performance_metrics import calculate_metrics
from src.learning.signal_scorecard import update_scorecard
from src.learning.adaptive_weights import update_signal_weights

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

REVIEW_SYSTEM = """You are reviewing a trading account's weekly performance. Analyze the data and provide actionable insights.

Respond with ONLY a valid JSON object:
{
    "summary": "<1-2 sentence week summary>",
    "performance_assessment": "excellent" | "good" | "average" | "poor" | "critical",
    "key_observations": ["<observation 1>", "<observation 2>"],
    "new_learnings": [
        {
            "category": "<category>",
            "insight": "<actionable insight>",
            "confidence": <0.0-1.0>
        }
    ],
    "learnings_to_retire": [<learning_id_1>, <learning_id_2>],
    "strategy_adjustments": ["<adjustment 1>"],
    "risk_concerns": ["<concern 1>"],
    "next_week_focus": "<what to focus on next week>"
}"""

ACCOUNT_IDS = ["quiver_strat", "day_trader", "autonomous"]


def run_weekly_review():
    """Run weekly review for all accounts."""
    tracker = HealthTracker("weekly-review")

    try:
        logger.info("=== Weekly Review Starting ===")
        db = Database()

        for account_id in ACCOUNT_IDS:
            try:
                _review_account(account_id, db, tracker)
            except Exception as e:
                tracker.add_error(
                    "Review", f"Failed to review {account_id}: {e}",
                    f"Weekly review incomplete for {account_id}"
                )

        logger.info("=== Weekly Review Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Weekly review failed: {e}", "No review completed")
        logger.exception("Fatal error in weekly review")

    finally:
        tracker.finalize()


def _review_account(account_id: str, db: Database, tracker: HealthTracker):
    """Review a single account's weekly performance."""
    logger.info(f"--- Reviewing {account_id} ---")

    # Calculate metrics
    metrics = calculate_metrics(account_id)

    # Update signal scorecard
    scorecard = update_scorecard(account_id)

    # Update adaptive weights (Account 1 only has signal weights)
    weight_adjustments = {}
    if account_id == "quiver_strat":
        weight_adjustments = update_signal_weights(account_id)

    # Get current learnings
    learnings = db.get_learnings(account_id)

    # Build context for Claude
    context = f"""WEEKLY REVIEW FOR: {account_id}

PERFORMANCE METRICS:
{json.dumps(metrics, indent=2, default=str)}

SIGNAL SCORECARD:
{json.dumps(scorecard, indent=2, default=str)}

WEIGHT ADJUSTMENTS THIS WEEK:
{json.dumps(weight_adjustments, indent=2, default=str)}

CURRENT ACTIVE LEARNINGS ({len(learnings)}):
"""
    for l in learnings:
        context += f"  [{l['id']}] [{l.get('category', '')}] {l['insight']}\n"

    # Get Claude's review
    claude = ClaudeClient(account_id=account_id)
    try:
        review = claude.analyze(
            system_prompt=REVIEW_SYSTEM,
            user_prompt=context,
            analysis_type="weekly_review",
            max_tokens=4096,
        )
    except Exception as e:
        tracker.add_warning(f"Claude review failed for {account_id}: {e}", service="Claude")
        return

    if not review:
        return

    # Store new learnings
    for learning in review.get("new_learnings", []):
        db.insert_learning({
            "account_id": account_id,
            "learning_type": "weekly_review",
            "category": learning.get("category", "general"),
            "insight": learning["insight"],
            "confidence": learning.get("confidence", 0.5),
        })

    # Retire old learnings
    for learning_id in review.get("learnings_to_retire", []):
        db.deactivate_learning(learning_id)

    logger.info(
        f"Review for {account_id}: "
        f"assessment={review.get('performance_assessment')}, "
        f"new_learnings={len(review.get('new_learnings', []))}, "
        f"retired={len(review.get('learnings_to_retire', []))}"
    )


if __name__ == "__main__":
    run_weekly_review()
