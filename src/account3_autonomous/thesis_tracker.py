import logging
from datetime import datetime, timezone

from src.shared.claude_client import ClaudeClient
from src.shared.database import Database
from src.account3_autonomous.config import ACCOUNT_ID, THESIS_CLASSIFICATIONS

logger = logging.getLogger(__name__)

EVALUATION_SYSTEM = """You are evaluating the accuracy of a trading thesis, separate from whether the trade was profitable.

A thesis can be CORRECT even if the trade lost money (right_reason_loss):
- Example: "Oil prices will rise due to OPEC cuts" - oil did rise, but the stock fell due to company-specific issues

A thesis can be WRONG even if the trade made money (wrong_reason_win):
- Example: "Stock will rise on earnings beat" - earnings missed, but stock rose on acquisition rumors

Classify the thesis and provide a brief lesson learned.

Respond with ONLY a valid JSON object:
{
    "thesis_correct": true | false,
    "classification": "right_reason_win" | "wrong_reason_win" | "right_reason_loss" | "wrong_reason_loss",
    "lesson": "<what can be learned from this thesis outcome>",
    "reasoning": "<why you classified it this way>"
}"""


class ThesisTracker:
    """Track thesis accuracy separately from P&L."""

    def __init__(self):
        self.claude = ClaudeClient(account_id=ACCOUNT_ID)
        self.db = Database()

    def record_thesis(self, trade_id: int, symbol: str, thesis: str,
                      target_price: float, stop_loss: float,
                      invalidation: str, time_horizon_days: int,
                      confidence: int) -> dict:
        """Record a new thesis for a trade."""
        thesis_record = {
            "account_id": ACCOUNT_ID,
            "trade_id": trade_id,
            "symbol": symbol,
            "entry_date": datetime.now(timezone.utc).isoformat(),
            "thesis": thesis,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "invalidation": invalidation,
            "time_horizon_days": time_horizon_days,
            "confidence_at_entry": confidence,
        }
        return self.db.insert_thesis(thesis_record)

    def evaluate_closed_theses(self) -> list:
        """Evaluate theses for trades that have been closed."""
        # Find theses without evaluations for closed trades
        open_theses = self.db.get_open_theses(ACCOUNT_ID)
        evaluated = []

        for thesis in open_theses:
            trade_id = thesis.get("trade_id")
            if not trade_id:
                continue

            # Check if trade is closed
            try:
                resp = (
                    self.db.client.table("trades")
                    .select("*")
                    .eq("id", trade_id)
                    .execute()
                )
                trade = resp.data[0] if resp.data else None
            except Exception:
                continue

            if not trade or trade.get("status") != "closed":
                continue

            # Get trade outcome
            try:
                resp = (
                    self.db.client.table("trade_outcomes")
                    .select("*")
                    .eq("trade_id", trade_id)
                    .execute()
                )
                outcome = resp.data[0] if resp.data else None
            except Exception:
                continue

            if not outcome:
                continue

            # Have Claude evaluate the thesis
            evaluation = self._evaluate_thesis(thesis, trade, outcome)
            if evaluation:
                self.db.update_thesis(thesis["id"], {
                    "outcome": outcome.get("outcome"),
                    "thesis_correct": evaluation.get("thesis_correct"),
                    "thesis_classification": evaluation.get("classification"),
                    "thesis_lesson": evaluation.get("lesson"),
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                })
                evaluated.append({
                    "symbol": thesis["symbol"],
                    "classification": evaluation.get("classification"),
                    "lesson": evaluation.get("lesson"),
                })

                # Store lesson as a learning
                if evaluation.get("lesson"):
                    self.db.insert_learning({
                        "account_id": ACCOUNT_ID,
                        "learning_type": "thesis_evaluation",
                        "category": evaluation.get("classification"),
                        "insight": evaluation["lesson"],
                        "data": {
                            "symbol": thesis["symbol"],
                            "thesis": thesis["thesis"],
                            "pnl": outcome.get("realized_pnl"),
                        },
                    })

        if evaluated:
            logger.info(f"Evaluated {len(evaluated)} theses")

        return evaluated

    def _evaluate_thesis(self, thesis: dict, trade: dict, outcome: dict) -> dict:
        """Have Claude evaluate a thesis against its outcome."""
        prompt = f"""THESIS EVALUATION

Symbol: {thesis['symbol']}
Original Thesis: {thesis['thesis']}
Invalidation Condition: {thesis.get('invalidation', 'N/A')}
Target Price: ${thesis.get('target_price', 'N/A')}
Stop Loss: ${thesis.get('stop_loss', 'N/A')}

TRADE OUTCOME:
Entry Price: ${outcome.get('entry_price', 'N/A')}
Exit Price: ${outcome.get('exit_price', 'N/A')}
P&L: ${outcome.get('realized_pnl', 'N/A')} ({outcome.get('pnl_pct', 'N/A')}%)
Exit Reason: {outcome.get('exit_reason', 'N/A')}
Holding Period: {outcome.get('holding_period_hours', 'N/A')} hours

Was the thesis correct? Classify and provide a lesson."""

        return self.claude.analyze(
            system_prompt=EVALUATION_SYSTEM,
            user_prompt=prompt,
            analysis_type="thesis_evaluation",
            max_tokens=1024,
        )

    def get_thesis_accuracy_stats(self) -> dict:
        """Get overall thesis accuracy statistics."""
        try:
            resp = (
                self.db.client.table("theses")
                .select("*")
                .eq("account_id", ACCOUNT_ID)
                .not_.is_("thesis_classification", "null")
                .execute()
            )
            theses = resp.data

            if not theses:
                return {"total": 0, "accuracy": 0}

            total = len(theses)
            correct = sum(1 for t in theses if t.get("thesis_correct"))

            from collections import Counter
            classifications = Counter(t["thesis_classification"] for t in theses)

            return {
                "total": total,
                "correct": correct,
                "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
                "classifications": dict(classifications),
            }
        except Exception as e:
            logger.error(f"Failed to get thesis stats: {e}")
            return {"total": 0, "accuracy": 0}
