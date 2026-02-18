import json
import logging

from src.shared.claude_client import ClaudeClient
from src.shared.database import Database
from src.shared.alpaca_client import AlpacaClient
from src.account1_quiver.config import ACCOUNT_ID

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a quantitative trading analyst evaluating signals from multiple alternative data sources. You must respond with ONLY a valid JSON object (no markdown, no explanation outside JSON).

Your analysis should consider:
1. Signal quality and reliability of each data source
2. Historical performance of similar signals (provided in context)
3. Risk factors and potential downsides
4. Current market conditions
5. Position sizing recommendation

Respond with this exact JSON structure:
{
    "confidence": <0-100>,
    "decision": "buy" | "sell" | "skip",
    "thesis": "<your investment thesis in 2-3 sentences>",
    "position_size_pct": <suggested % of max position, 0.0-1.0>,
    "risks": ["<risk 1>", "<risk 2>"],
    "time_horizon_days": <suggested holding period>,
    "target_return_pct": <expected return percentage>,
    "stop_loss_pct": <suggested stop loss percentage>,
    "reasoning": "<detailed reasoning>"
}"""


class ClaudeAnalyzer:
    """Use Claude to evaluate scored signals with full context."""

    def __init__(self):
        self.claude = ClaudeClient(account_id=ACCOUNT_ID)
        self.db = Database()
        self.alpaca = AlpacaClient(ACCOUNT_ID)

    def analyze_signal(self, scored_signal: dict, portfolio_state: dict) -> dict:
        """Analyze a scored signal with Claude, providing full context."""
        symbol = scored_signal["symbol"]

        # Gather context
        scorecard = self.db.get_scorecard(ACCOUNT_ID)
        learnings = self.db.get_learnings(ACCOUNT_ID)
        past_trades = self.db.get_trade_outcomes(ACCOUNT_ID, limit=20)

        # Fetch current market data for the symbol
        price_context = ""
        try:
            snapshots = self.alpaca.get_snapshots([symbol])
            snap = snapshots.get(symbol) if snapshots else None
            if snap and snap.latest_trade:
                current_price = float(snap.latest_trade.price)
                prev_close = float(snap.previous_daily_bar.close) if snap.previous_daily_bar else None
                if prev_close:
                    daily_change = ((current_price - prev_close) / prev_close) * 100
                    price_context = (
                        f"Current Price: ${current_price:.2f}\n"
                        f"Previous Close: ${prev_close:.2f}\n"
                        f"Daily Change: {daily_change:+.2f}%"
                    )
                else:
                    price_context = f"Current Price: ${current_price:.2f}"
        except Exception as e:
            logger.debug(f"Failed to fetch price data for {symbol}: {e}")

        # Filter past trades for this symbol
        symbol_trades = [t for t in past_trades if t.get("symbol") == symbol]

        context = self._build_context(
            scored_signal, portfolio_state, scorecard, learnings, symbol_trades,
            price_context=price_context,
        )

        result = self.claude.analyze(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=context,
            model="sonnet",
            analysis_type="signal_evaluation",
        )

        if result:
            result["symbol"] = symbol
            logger.info(
                f"Claude analysis for {symbol}: "
                f"confidence={result.get('confidence')}, "
                f"decision={result.get('decision')}"
            )
        else:
            logger.warning(f"Claude analysis returned None for {symbol}")

        return result or {}

    def _build_context(
        self,
        scored_signal: dict,
        portfolio_state: dict,
        scorecard: list,
        learnings: list,
        symbol_trades: list,
        price_context: str = "",
    ) -> str:
        """Build the full context prompt for Claude."""
        # Signal details
        signal_summary = (
            f"Symbol: {scored_signal['symbol']}\n"
            f"Direction: {scored_signal['direction']}\n"
            f"Composite Score: {scored_signal['composite_score']}\n"
            f"Sources ({scored_signal['source_count']}): {', '.join(scored_signal['sources'])}\n"
        )

        # Raw signal data
        raw_details = ""
        for sig in scored_signal.get("signals", []):
            raw_details += (
                f"\n  - {sig['source']} ({sig['signal_type']}): "
                f"strength={sig.get('strength')}, "
                f"data={json.dumps(sig.get('raw_data', {}), default=str)[:300]}"
            )

        # Signal source performance
        scorecard_summary = ""
        if scorecard:
            for sc in scorecard:
                scorecard_summary += (
                    f"\n  - {sc['signal_source']}: "
                    f"win_rate={sc.get('win_rate', 'N/A')}%, "
                    f"avg_return={sc.get('avg_return_pct', 'N/A')}%, "
                    f"sample_size={sc.get('total_signals', 0)}"
                )

        # Past trades on this symbol
        symbol_history = ""
        if symbol_trades:
            for t in symbol_trades[:5]:
                symbol_history += (
                    f"\n  - {t.get('entry_date', 'N/A')}: "
                    f"P&L={t.get('realized_pnl', 'N/A')}, "
                    f"outcome={t.get('outcome', 'N/A')}"
                )

        # Active learnings
        learnings_summary = ""
        if learnings:
            for l in learnings[:10]:
                learnings_summary += f"\n  - [{l.get('category', '')}] {l['insight']}"

        # Portfolio state
        portfolio_summary = (
            f"Working Capital: ${portfolio_state.get('working_capital', 'N/A')}\n"
            f"Current Invested: ${portfolio_state.get('invested', 'N/A')}\n"
            f"Open Positions: {portfolio_state.get('position_count', 'N/A')}\n"
            f"Today's P&L: ${portfolio_state.get('daily_pnl', 'N/A')}"
        )

        prompt = f"""SIGNAL EVALUATION REQUEST

{signal_summary}
Signal Details:{raw_details}

CURRENT MARKET DATA:
{price_context or '  Price data unavailable.'}

SIGNAL SOURCE TRACK RECORD:
{scorecard_summary or '  No historical data yet.'}

PAST TRADES ON {scored_signal['symbol']}:
{symbol_history or '  No prior trades on this symbol.'}

ACTIVE LEARNINGS:
{learnings_summary or '  No learnings accumulated yet.'}

CURRENT PORTFOLIO:
{portfolio_summary}

Evaluate this signal and provide your analysis as JSON."""

        return prompt
