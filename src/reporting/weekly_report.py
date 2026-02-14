import logging
from datetime import date

from src.shared.config import STARTING_CAPITAL
from src.shared.database import Database
from src.shared.notifier import send_email
from src.learning.performance_metrics import calculate_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

ACCOUNT_IDS = ["quiver_strat", "day_trader", "autonomous"]
ACCOUNT_NAMES = {
    "quiver_strat": "Signal Strategy",
    "day_trader": "Day Trader",
    "autonomous": "Autonomous AI",
}


def send_weekly_performance_report():
    """Send weekly performance comparison email."""
    all_metrics = {}
    for account_id in ACCOUNT_IDS:
        try:
            all_metrics[account_id] = calculate_metrics(account_id)
        except Exception as e:
            logger.error(f"Failed to get metrics for {account_id}: {e}")
            all_metrics[account_id] = {}

    html = _build_weekly_html(all_metrics)
    today = date.today().strftime("%B %d, %Y")
    subject = f"QD Engine - Weekly Performance Report - {today}"
    send_email(subject, html)


def _build_weekly_html(all_metrics: dict) -> str:
    """Build weekly comparison HTML."""
    rows = ""
    for account_id in ACCOUNT_IDS:
        m = all_metrics.get(account_id, {})
        pnl = m.get("total_pnl", 0)
        pnl_color = "#4ecdc4" if pnl >= 0 else "#ff6b6b"
        rows += f"""
        <tr>
            <td style="padding:8px;border:1px solid #444;">{ACCOUNT_NAMES.get(account_id, account_id)}</td>
            <td style="padding:8px;border:1px solid #444;color:{pnl_color};">${pnl:,.2f}</td>
            <td style="padding:8px;border:1px solid #444;color:{pnl_color};">{m.get('return_pct', 0):.2f}%</td>
            <td style="padding:8px;border:1px solid #444;">{m.get('win_rate', 0):.1f}%</td>
            <td style="padding:8px;border:1px solid #444;">{m.get('total_trades', 0)}</td>
            <td style="padding:8px;border:1px solid #444;">{m.get('sharpe_ratio', 0):.2f}</td>
            <td style="padding:8px;border:1px solid #444;">{m.get('max_drawdown_pct', 0):.2f}%</td>
            <td style="padding:8px;border:1px solid #444;">{m.get('profit_factor', 0):.2f}</td>
        </tr>"""

    html = f"""
    <html>
    <body style="background:#0f0f23;color:#e2e8f0;font-family:'SF Mono',Monaco,monospace;padding:20px;">
        <h1 style="color:#e2e8f0;">Weekly Performance Comparison</h1>
        <table style="width:100%;border-collapse:collapse;">
            <tr style="background:#1a1a3e;">
                <th style="padding:8px;border:1px solid #444;text-align:left;">Account</th>
                <th style="padding:8px;border:1px solid #444;text-align:left;">P&L</th>
                <th style="padding:8px;border:1px solid #444;text-align:left;">Return</th>
                <th style="padding:8px;border:1px solid #444;text-align:left;">Win Rate</th>
                <th style="padding:8px;border:1px solid #444;text-align:left;">Trades</th>
                <th style="padding:8px;border:1px solid #444;text-align:left;">Sharpe</th>
                <th style="padding:8px;border:1px solid #444;text-align:left;">Max DD</th>
                <th style="padding:8px;border:1px solid #444;text-align:left;">PF</th>
            </tr>
            {rows}
        </table>
        <p style="color:#555;font-size:11px;text-align:center;margin-top:30px;">
            QD Engine | Automated Portfolio Management
        </p>
    </body>
    </html>"""

    return html


if __name__ == "__main__":
    send_weekly_performance_report()
