import json
import logging

from src.shared.claude_client import ClaudeClient
from src.shared.database import Database
from src.shared.alerter import HealthTracker
from src.learning.performance_metrics import calculate_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

MONTHLY_SYSTEM = """You are conducting a deep monthly strategy review across three trading accounts. This is the most important analytical task in the system. Think deeply.

Your analysis should cover:
1. Cross-account performance comparison
2. Strategy effectiveness and market regime detection
3. Capital allocation recommendations
4. System-wide improvements
5. Code-level improvements that would make the system better

For code-level improvements, include them in the "code_recommendations" array.
These will be automatically implemented by the self-improvement workflow.

Respond with ONLY a valid JSON object:
{
    "monthly_summary": "<executive summary>",
    "market_regime": "trending_bull" | "trending_bear" | "sideways" | "volatile" | "mixed",
    "account_rankings": [
        {"account": "<id>", "grade": "A" | "B" | "C" | "D" | "F", "reasoning": "<why>"}
    ],
    "cross_account_insights": ["<insight 1>", "<insight 2>"],
    "strategy_recommendations": {
        "quiver_strat": ["<rec 1>"],
        "day_trader": ["<rec 1>"],
        "signal_echo": ["<rec 1>"]
    },
    "risk_assessment": {
        "overall_risk_level": "low" | "moderate" | "high" | "critical",
        "concerns": ["<concern 1>"]
    },
    "next_month_priorities": ["<priority 1>", "<priority 2>"],
    "system_improvements": ["<improvement 1>"],
    "code_recommendations": [
        {
            "recommendation": "<what should change in the code>",
            "reasoning": "<why this would improve the system>",
            "implementation_hint": "<specific files and approach for implementation>",
            "priority": "high" | "medium" | "low"
        }
    ]
}"""

ACCOUNT_IDS = ["quiver_strat", "day_trader", "signal_echo"]


def run_monthly_review():
    """Deep monthly strategy review across all accounts."""
    tracker = HealthTracker("monthly-review")

    try:
        logger.info("=== Monthly Review Starting ===")
        db = Database()

        # Gather metrics for all accounts
        all_metrics = {}
        all_learnings = {}
        for account_id in ACCOUNT_IDS:
            all_metrics[account_id] = calculate_metrics(account_id)
            all_learnings[account_id] = db.get_learnings(account_id)

        # Get strategy definitions and scoring rules
        strategy_defs = _get_all_strategy_definitions(db)
        scoring_rules = _get_all_scoring_rules(db)

        # Build comprehensive context
        context = "MONTHLY DEEP REVIEW\n\n"
        for account_id in ACCOUNT_IDS:
            context += f"=== {account_id} ===\n"
            context += f"Performance:\n{json.dumps(all_metrics[account_id], indent=2, default=str)}\n"
            context += f"Active Learnings ({len(all_learnings[account_id])}):\n"
            for l in all_learnings[account_id][:5]:
                context += f"  - [{l.get('category', '')}] {l['insight']}\n"
            context += "\n"

        if strategy_defs:
            context += f"STRATEGY DEFINITIONS:\n{json.dumps(strategy_defs, indent=2, default=str)}\n\n"
        if scoring_rules:
            context += f"SCORING RULES:\n{json.dumps(scoring_rules, indent=2, default=str)}\n\n"

        # Use Opus with max effort for monthly deep review
        claude = ClaudeClient(account_id="quiver_strat")
        try:
            review = claude.strategic_review(
                system_prompt=MONTHLY_SYSTEM,
                user_prompt=context,
                model="opus",
                effort="max",
                analysis_type="monthly_review",
            )
        except Exception as e:
            tracker.add_error("Claude", str(e), "Monthly review failed")
            tracker.finalize()
            return

        if review:
            # Store cross-account learnings
            for insight in review.get("cross_account_insights", []):
                for account_id in ACCOUNT_IDS:
                    db.insert_learning({
                        "account_id": account_id,
                        "learning_type": "monthly_review",
                        "category": "cross_account",
                        "insight": insight,
                    })

            # Store code-change recommendations
            for rec in review.get("code_recommendations", []):
                try:
                    db.client.table("recommendations").insert({
                        "account_id": None,
                        "review_type": "monthly",
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

            logger.info(
                f"Monthly review complete: "
                f"regime={review.get('market_regime')}, "
                f"risk={review.get('risk_assessment', {}).get('overall_risk_level')}, "
                f"code_recs={len(review.get('code_recommendations', []))}"
            )

        logger.info("=== Monthly Review Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Monthly review failed: {e}", "No review completed")
        logger.exception("Fatal error in monthly review")

    finally:
        tracker.finalize()


def _get_all_strategy_definitions(db: Database) -> list:
    """Get all strategy definitions."""
    try:
        resp = (
            db.client.table("strategy_definitions")
            .select("id, account_id, name, is_active, entry_rules, exit_rules, performance")
            .execute()
        )
        return resp.data
    except Exception:
        return []


def _get_all_scoring_rules(db: Database) -> list:
    """Get all scoring rules."""
    try:
        resp = (
            db.client.table("scoring_rules")
            .select("id, account_id, rule_type, rule_config, is_active, version")
            .execute()
        )
        return resp.data
    except Exception:
        return []


if __name__ == "__main__":
    run_monthly_review()
