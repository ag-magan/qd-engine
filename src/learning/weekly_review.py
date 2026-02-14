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

You have the ability to modify the system by:
1. Creating/updating/disabling strategy_definitions (Account 2 day_trader strategies)
2. Creating/versioning scoring_rules (Account 1 quiver_strat scoring rules)
3. Generating recommendations for code changes

For database changes you want to make, include them in the "database_changes" array.
For code-level changes, include them in the "code_recommendations" array.

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
    "next_week_focus": "<what to focus on next week>",
    "database_changes": [
        {
            "table": "strategy_definitions" | "scoring_rules",
            "action": "insert" | "update" | "deactivate",
            "data": {},
            "reasoning": "<why this change>"
        }
    ],
    "code_recommendations": [
        {
            "recommendation": "<what should change>",
            "reasoning": "<why>",
            "implementation_hint": "<how to implement>",
            "priority": "high" | "medium" | "low"
        }
    ]
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

    # Get current strategy definitions and scoring rules for context
    strategy_defs = _get_strategy_definitions(db, account_id)
    scoring_rules = _get_scoring_rules(db, account_id)

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

    if strategy_defs:
        context += f"\nACTIVE STRATEGY DEFINITIONS:\n{json.dumps(strategy_defs, indent=2, default=str)}\n"

    if scoring_rules:
        context += f"\nACTIVE SCORING RULES:\n{json.dumps(scoring_rules, indent=2, default=str)}\n"

    # Use Opus with adaptive thinking for weekly review
    claude = ClaudeClient(account_id=account_id)
    try:
        review = claude.strategic_review(
            system_prompt=REVIEW_SYSTEM,
            user_prompt=context,
            model="opus",
            effort="high",
            analysis_type="weekly_review",
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

    # Apply database changes
    _apply_database_changes(db, account_id, review.get("database_changes", []))

    # Store code recommendations
    _store_code_recommendations(db, account_id, review.get("code_recommendations", []))

    logger.info(
        f"Review for {account_id}: "
        f"assessment={review.get('performance_assessment')}, "
        f"new_learnings={len(review.get('new_learnings', []))}, "
        f"retired={len(review.get('learnings_to_retire', []))}, "
        f"db_changes={len(review.get('database_changes', []))}, "
        f"code_recs={len(review.get('code_recommendations', []))}"
    )


def _get_strategy_definitions(db: Database, account_id: str) -> list:
    """Get active strategy definitions for an account."""
    try:
        resp = (
            db.client.table("strategy_definitions")
            .select("id, name, is_active, entry_rules, exit_rules, filters, performance")
            .eq("account_id", account_id)
            .eq("is_active", True)
            .execute()
        )
        return resp.data
    except Exception:
        return []


def _get_scoring_rules(db: Database, account_id: str) -> list:
    """Get active scoring rules for an account."""
    try:
        resp = (
            db.client.table("scoring_rules")
            .select("id, rule_type, rule_config, version, is_active")
            .eq("account_id", account_id)
            .eq("is_active", True)
            .execute()
        )
        return resp.data
    except Exception:
        return []


def _apply_database_changes(db: Database, account_id: str, changes: list):
    """Apply database changes recommended by Claude."""
    for change in changes:
        table = change.get("table")
        action = change.get("action")
        data = change.get("data", {})

        try:
            if table == "strategy_definitions":
                if action == "insert":
                    data["account_id"] = account_id
                    data["created_by"] = "weekly_review"
                    db.client.table("strategy_definitions").insert(data).execute()
                    logger.info(f"Inserted new strategy: {data.get('name')}")
                elif action == "update" and data.get("id"):
                    row_id = data.pop("id")
                    data["updated_at"] = "now()"
                    db.client.table("strategy_definitions").update(data).eq("id", row_id).execute()
                    logger.info(f"Updated strategy {row_id}")
                elif action == "deactivate" and data.get("id"):
                    db.client.table("strategy_definitions").update(
                        {"is_active": False, "updated_at": "now()"}
                    ).eq("id", data["id"]).execute()
                    logger.info(f"Deactivated strategy {data['id']}")

            elif table == "scoring_rules":
                if action == "insert":
                    data["account_id"] = account_id
                    data["created_by"] = "weekly_review"
                    db.client.table("scoring_rules").insert(data).execute()
                    logger.info(f"Inserted new scoring rule: {data.get('rule_type')}")
                elif action == "deactivate" and data.get("id"):
                    db.client.table("scoring_rules").update(
                        {"is_active": False}
                    ).eq("id", data["id"]).execute()
                    logger.info(f"Deactivated scoring rule {data['id']}")

            # Record as implemented recommendation
            db.client.table("recommendations").insert({
                "account_id": account_id,
                "review_type": "weekly",
                "category": "database_change",
                "recommendation": change.get("reasoning", "Database change"),
                "reasoning": json.dumps(change),
                "status": "implemented",
                "implemented_at": "now()",
            }).execute()

        except Exception as e:
            logger.error(f"Failed to apply database change: {e}")


def _store_code_recommendations(db: Database, account_id: str, recommendations: list):
    """Store code-change recommendations for the self-improvement workflow."""
    for rec in recommendations:
        try:
            db.client.table("recommendations").insert({
                "account_id": account_id,
                "review_type": "weekly",
                "category": "code_change",
                "priority": rec.get("priority", "medium"),
                "recommendation": rec["recommendation"],
                "reasoning": rec.get("reasoning"),
                "implementation_hint": rec.get("implementation_hint"),
                "status": "pending",
            }).execute()
            logger.info(f"Stored code recommendation: {rec['recommendation'][:80]}")
        except Exception as e:
            logger.error(f"Failed to store code recommendation: {e}")


if __name__ == "__main__":
    run_weekly_review()
