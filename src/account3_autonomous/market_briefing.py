import json
import logging
from datetime import datetime, timedelta, timezone

from src.shared.alpaca_client import AlpacaClient
from src.shared.database import Database
from src.shared.portfolio_tracker import PortfolioTracker
from src.account3_autonomous.config import ACCOUNT_ID

logger = logging.getLogger(__name__)

# Market index ETFs for context
MARKET_INDICES = ["SPY", "QQQ", "IWM", "DIA", "VIX"]


class MarketBriefing:
    """Gather full market context for Claude's daily decision."""

    def __init__(self):
        self.alpaca = AlpacaClient(ACCOUNT_ID)
        self.db = Database()
        self.tracker = PortfolioTracker(ACCOUNT_ID)

    def build_briefing(self) -> str:
        """Build comprehensive market briefing for Claude."""
        sections = []

        # 1. Market overview
        market_overview = self._get_market_overview()
        sections.append(f"## MARKET OVERVIEW\n{market_overview}")

        # 2. Current portfolio
        portfolio = self._get_portfolio_state()
        sections.append(f"## CURRENT PORTFOLIO\n{portfolio}")

        # 3. Performance metrics
        metrics = self.tracker.get_performance_metrics()
        metrics_text = self._format_metrics(metrics)
        sections.append(f"## PERFORMANCE METRICS\n{metrics_text}")

        # 4. Trade history
        history = self._get_trade_history()
        sections.append(f"## RECENT TRADE HISTORY\n{history}")

        # 5. Thesis accuracy
        thesis_stats = self._get_thesis_stats()
        sections.append(f"## THESIS ACCURACY\n{thesis_stats}")

        # 6. Active learnings
        learnings = self._get_learnings()
        sections.append(f"## ACCUMULATED LEARNINGS\n{learnings}")

        # 7. Open theses to review
        open_theses = self._get_open_theses()
        sections.append(f"## OPEN POSITIONS & THESES\n{open_theses}")

        return "\n\n".join(sections)

    def _get_market_overview(self) -> str:
        """Get current market data for major indices."""
        try:
            snapshots = self.alpaca.get_snapshots(MARKET_INDICES)
            if not snapshots:
                return "Market data unavailable."

            lines = []
            for symbol in MARKET_INDICES:
                snap = snapshots.get(symbol)
                if snap and snap.latest_trade and snap.previous_daily_bar:
                    price = float(snap.latest_trade.price)
                    prev = float(snap.previous_daily_bar.close)
                    change = ((price - prev) / prev) * 100
                    lines.append(f"  {symbol}: ${price:.2f} ({change:+.2f}%)")

            return "\n".join(lines) if lines else "Market data unavailable."
        except Exception as e:
            logger.error(f"Failed to get market overview: {e}")
            return "Market data unavailable."

    def _get_portfolio_state(self) -> str:
        """Get current portfolio positions and cash."""
        try:
            positions = self.alpaca.get_positions()
            from src.shared.risk_manager import RiskManager
            risk = RiskManager(ACCOUNT_ID)
            working_capital = risk.get_working_capital()
            invested = risk.get_invested_amount()

            lines = [
                f"  Working Capital: ${working_capital:.2f}",
                f"  Invested: ${invested:.2f} ({invested/working_capital*100:.1f}%)"
                if working_capital > 0 else f"  Invested: ${invested:.2f}",
                f"  Cash Available: ${working_capital - invested:.2f}",
                f"  Open Positions: {len(positions)}",
            ]

            if positions:
                lines.append("  Positions:")
                for pos in positions:
                    lines.append(
                        f"    {pos.symbol}: {pos.qty} shares @ ${float(pos.avg_entry_price):.2f} "
                        f"(current: ${float(pos.current_price):.2f}, "
                        f"P&L: ${float(pos.unrealized_pl):.2f})"
                    )

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Failed to get portfolio state: {e}")
            return "Portfolio data unavailable."

    def _format_metrics(self, metrics: dict) -> str:
        return (
            f"  Total Trades: {metrics.get('total_trades', 0)}\n"
            f"  Win Rate: {metrics.get('win_rate', 0)}%\n"
            f"  Total P&L: ${metrics.get('total_pnl', 0):.2f}\n"
            f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}\n"
            f"  Max Drawdown: {metrics.get('max_drawdown_pct', 0):.2f}%\n"
            f"  Return: {metrics.get('return_pct', 0):.2f}%"
        )

    def _get_trade_history(self) -> str:
        outcomes = self.db.get_trade_outcomes(ACCOUNT_ID, limit=15)
        if not outcomes:
            return "  No trade history yet."

        lines = []
        for o in outcomes:
            lines.append(
                f"  {o.get('symbol')}: {o.get('outcome')} "
                f"P&L=${float(o.get('realized_pnl', 0) or 0):.2f} "
                f"({o.get('exit_reason', 'N/A')})"
            )
        return "\n".join(lines)

    def _get_thesis_stats(self) -> str:
        """Get thesis accuracy statistics."""
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
                return "  No evaluated theses yet."

            from collections import Counter
            classifications = Counter(t["thesis_classification"] for t in theses)
            total = len(theses)
            correct = sum(1 for t in theses if t.get("thesis_correct"))

            lines = [
                f"  Total Evaluated: {total}",
                f"  Thesis Accuracy: {correct/total*100:.1f}%" if total > 0 else "",
            ]
            for cls, count in classifications.items():
                lines.append(f"    {cls}: {count} ({count/total*100:.1f}%)")

            return "\n".join(lines)
        except Exception:
            return "  Thesis data unavailable."

    def _get_learnings(self) -> str:
        learnings = self.db.get_learnings(ACCOUNT_ID)
        if not learnings:
            return "  No learnings accumulated yet."

        lines = []
        for l in learnings[:10]:
            lines.append(f"  - [{l.get('category', 'general')}] {l['insight']}")
        return "\n".join(lines)

    def _get_open_theses(self) -> str:
        theses = self.db.get_open_theses(ACCOUNT_ID)
        if not theses:
            return "  No open positions with theses."

        lines = []
        for t in theses:
            lines.append(
                f"  {t['symbol']}: {t['thesis'][:100]}...\n"
                f"    Target: ${t.get('target_price', 'N/A')}, "
                f"Stop: ${t.get('stop_loss', 'N/A')}, "
                f"Invalidation: {t.get('invalidation', 'N/A')}"
            )
        return "\n".join(lines)
