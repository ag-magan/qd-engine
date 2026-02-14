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

MONTHLY_SYSTEM = """You are conducting a deep monthly strategy review across three trading accounts. This is a comprehensive analysis looking at:
1. Cross-account performance comparison
2. Strategy effectiveness and market regime detection
3. Capital allocation recommendations
4. System-wide improvements

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
        "autonomous": ["<rec 1>"]
    },
    "risk_assessment": {
        "overall_risk_level": "low" | "moderate" | "high" | "critical",
        "concerns": ["<concern 1>"]
    },
    "next_month_priorities": ["<priority 1>", "<priority 2>"],
    "system_improvements": ["<improvement 1>"]
}"""

ACCOUNT_IDS = ["quiver_strat", "day_trader", "autonomous"]


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

        # Build comprehensive context
        context = "MONTHLY DEEP REVIEW\n\n"
        for account_id in ACCOUNT_IDS:
            context += f"=== {account_id} ===\n"
            context += f"Performance:\n{json.dumps(all_metrics[account_id], indent=2, default=str)}\n"
            context += f"Active Learnings ({len(all_learnings[account_id])}):\n"
            for l in all_learnings[account_id][:5]:
                context += f"  - [{l.get('category', '')}] {l['insight']}\n"
            context += "\n"

        # Get Claude's deep review
        claude = ClaudeClient(account_id="quiver_strat")  # Use any account for logging
        try:
            review = claude.analyze(
                system_prompt=MONTHLY_SYSTEM,
                user_prompt=context,
                analysis_type="monthly_review",
                max_tokens=4096,
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

            logger.info(
                f"Monthly review complete: "
                f"regime={review.get('market_regime')}, "
                f"risk={review.get('risk_assessment', {}).get('overall_risk_level')}"
            )

        logger.info("=== Monthly Review Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Monthly review failed: {e}", "No review completed")
        logger.exception("Fatal error in monthly review")

    finally:
        tracker.finalize()


if __name__ == "__main__":
    run_monthly_review()
