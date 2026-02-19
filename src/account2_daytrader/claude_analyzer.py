import json
import logging

from src.shared.claude_client import ClaudeClient
from src.shared.database import Database
from src.account2_daytrader.config import ACCOUNT_ID

logger = logging.getLogger(__name__)

BRIEFING_SYSTEM = """You are an intraday trading analyst providing a pre-market briefing. Respond with ONLY a valid JSON object.

Your briefing should:
1. Rank the candidate stocks by trade quality
2. Identify your best setups for the day (up to 15)
3. Note any market conditions that affect strategy selection
4. Flag stocks to avoid

Respond with this JSON structure:
{
    "market_outlook": "bullish" | "bearish" | "neutral" | "volatile",
    "outlook_reasoning": "<brief market assessment>",
    "top_setups": [
        {
            "symbol": "<ticker>",
            "strategy": "<recommended strategy>",
            "confidence": <0-100>,
            "entry_zone": "<price range>",
            "reasoning": "<why this is a good setup>"
        }
    ],
    "avoid_list": ["<ticker1>", "<ticker2>"],
    "avoid_reasons": {"<ticker>": "<reason>"},
    "strategy_bias": "<which strategy type to favor today>",
    "max_risk_today": "<conservative/normal/aggressive>"
}"""


class DayTraderClaudeAnalyzer:
    """Pre-market briefing and setup evaluation using Claude."""

    def __init__(self):
        self.claude = ClaudeClient(account_id=ACCOUNT_ID)
        self.db = Database()

    def premarket_briefing(self, candidates: list) -> dict:
        """Get Claude's pre-market analysis of scanning candidates."""
        if not candidates:
            return {}

        learnings = self.db.get_learnings(ACCOUNT_ID)
        outcomes = self.db.get_trade_outcomes(ACCOUNT_ID, limit=20)

        # Build context
        candidates_summary = ""
        for c in candidates[:30]:  # Show Claude up to 30 candidates
            line = (
                f"  {c['symbol']}: gap={c.get('gap_pct', 'N/A')}%, "
                f"vol_ratio={c.get('volume_ratio', 'N/A')}, "
                f"price=${c.get('current_price', 'N/A')}, "
                f"setups={c.get('setups', [])}"
            )
            if c.get("has_catalyst"):
                sources = ", ".join(c.get("catalyst_sources", []))
                line += f" [CATALYST: {sources} (score={c.get('catalyst_score', 0)})]"
            candidates_summary += line + "\n"

        recent_performance = ""
        if outcomes:
            wins = sum(1 for o in outcomes if float(o.get("realized_pnl", 0) or 0) > 0)
            total_pnl = sum(float(o.get("realized_pnl", 0) or 0) for o in outcomes)
            recent_performance = (
                f"Last {len(outcomes)} trades: {wins} wins, "
                f"P&L: ${total_pnl:.2f}"
            )

        learnings_text = ""
        if learnings:
            for l in learnings[:5]:
                learnings_text += f"  - [{l.get('category', '')}] {l['insight']}\n"

        prompt = f"""PRE-MARKET BRIEFING REQUEST

SCAN CANDIDATES:
{candidates_summary}

RECENT PERFORMANCE:
{recent_performance or '  No recent trades.'}

ACTIVE LEARNINGS:
{learnings_text or '  No learnings yet.'}

Analyze these candidates and provide your pre-market briefing as JSON."""

        result = self.claude.analyze(
            system_prompt=BRIEFING_SYSTEM,
            user_prompt=prompt,
            model="sonnet",
            analysis_type="premarket_briefing",
            thinking=True,
            thinking_budget=4096,
        )

        if result:
            logger.info(
                f"Pre-market briefing: outlook={result.get('market_outlook')}, "
                f"top_setups={len(result.get('top_setups', []))}"
            )

        return result or {}

    def evaluate_setup(self, setup: dict, market_context: dict) -> dict:
        """Quick evaluation of a specific intraday setup."""
        prompt = (
            f"Quick trade evaluation:\n"
            f"Symbol: {setup['symbol']}\n"
            f"Strategy: {setup['strategy']}\n"
            f"Entry: ${setup['entry_price']}\n"
            f"Target: ${setup['target_price']} ({setup.get('target_pct', 'N/A')}%)\n"
            f"Stop: ${setup['stop_price']} ({setup.get('stop_pct', 'N/A')}%)\n"
            f"Market outlook: {market_context.get('market_outlook', 'unknown')}\n"
            f"Strategy bias: {market_context.get('strategy_bias', 'none')}\n"
        )
        if setup.get("has_catalyst"):
            prompt += (
                f"Catalyst: QuiverQuant signal (score={setup.get('catalyst_score', 0)}) — "
                f"this stock has a fundamental catalyst from government/political data\n"
            )
        prompt += "\nShould we take this trade?"

        return self.claude.quick_decision(prompt, model="haiku") or {}
