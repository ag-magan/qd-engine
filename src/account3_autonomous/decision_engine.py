import json
import logging

from src.shared.claude_client import ClaudeClient
from src.shared.config import ACCOUNT_CONFIGS
from src.account3_autonomous.config import ACCOUNT_ID

logger = logging.getLogger(__name__)

DECISION_SYSTEM = """You are an autonomous portfolio strategist with full discretion over trading decisions. You receive comprehensive market context and must decide what to trade, hold, or close.

RULES:
- You manage $10,000 working capital (grows/shrinks with P&L)
- Max 75% invested at any time
- Max 15% per position ($1,500 max)
- Max 8 positions, max 6 new trades per day
- Min 6h holding period (allows tactical exits on thesis invalidation)
- Max 30 day holding period
- Every trade needs a thesis (min 50 chars) and invalidation condition
- Only trade with confidence >= 50

Respond with ONLY a valid JSON object:
{
    "market_stance": "bullish" | "bearish" | "neutral",
    "market_analysis": "<brief market assessment>",
    "new_positions": [
        {
            "symbol": "<ticker>",
            "side": "buy" | "sell",
            "confidence": <0-100>,
            "position_size_pct": <0.0-1.0 of max position>,
            "thesis": "<detailed thesis, min 50 chars>",
            "target_price": <target>,
            "stop_loss": <stop>,
            "invalidation": "<what would invalidate this thesis>",
            "time_horizon_days": <expected holding period>,
            "reasoning": "<detailed reasoning>"
        }
    ],
    "position_reviews": [
        {
            "symbol": "<ticker>",
            "action": "hold" | "close" | "add",
            "reasoning": "<why>",
            "updated_target": <new target or null>,
            "updated_stop": <new stop or null>
        }
    ],
    "watchlist": ["<ticker1>", "<ticker2>"],
    "self_reflection": "<honest assessment of your reasoning and biases>",
    "lessons_learned": ["<lesson1>", "<lesson2>"]
}"""

MONITOR_SYSTEM = """You are monitoring open positions for an autonomous portfolio. Check each position against its thesis and invalidation conditions.

Respond with ONLY a valid JSON object:
{
    "position_updates": [
        {
            "symbol": "<ticker>",
            "action": "hold" | "close",
            "thesis_still_valid": true | false,
            "reasoning": "<brief reasoning>",
            "urgency": "low" | "medium" | "high"
        }
    ]
}"""


class DecisionEngine:
    """Claude makes all trading decisions autonomously."""

    def __init__(self):
        self.claude = ClaudeClient(account_id=ACCOUNT_ID)
        self.config = ACCOUNT_CONFIGS[ACCOUNT_ID]

    def make_daily_decisions(self, briefing: str) -> dict:
        """Morning decision: Claude reviews everything and decides what to trade."""
        result = self.claude.strategic_review(
            system_prompt=DECISION_SYSTEM,
            user_prompt=briefing,
            model="opus",
            effort="high",
            analysis_type="daily_decision",
        )

        if result:
            new_positions = result.get("new_positions", [])
            # Filter out low-confidence positions
            result["new_positions"] = [
                p for p in new_positions
                if p.get("confidence", 0) >= self.config.get("min_confidence", 60)
            ]

            # Validate thesis length and stop/target prices
            for pos in result["new_positions"]:
                if len(pos.get("thesis", "")) < 100:
                    logger.warning(
                        f"Thesis too short for {pos['symbol']}, skipping"
                    )
                    pos["confidence"] = 0  # Disable
                elif not pos.get("target_price") or not pos.get("stop_loss"):
                    logger.warning(
                        f"Missing stop/target for {pos['symbol']}, skipping "
                        f"(guardian needs prices to enforce)"
                    )
                    pos["confidence"] = 0  # Disable

            result["new_positions"] = [
                p for p in result["new_positions"] if p.get("confidence", 0) > 0
            ]

            logger.info(
                f"Claude decisions: stance={result.get('market_stance')}, "
                f"new_positions={len(result.get('new_positions', []))}, "
                f"reviews={len(result.get('position_reviews', []))}"
            )

        return result or {}

    def monitor_positions(self, portfolio_summary: str) -> dict:
        """Midday check: review open positions against theses."""
        result = self.claude.analyze(
            system_prompt=MONITOR_SYSTEM,
            user_prompt=portfolio_summary,
            model="haiku",
            analysis_type="position_monitor",
            max_tokens=2048,
        )

        if result:
            close_actions = [
                u for u in result.get("position_updates", [])
                if u.get("action") == "close"
            ]
            if close_actions:
                logger.info(
                    f"Monitor: {len(close_actions)} positions flagged for closure"
                )

        return result or {}
