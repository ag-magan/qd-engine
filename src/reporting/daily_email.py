import logging
from datetime import date

from src.shared.config import STARTING_CAPITAL
from src.shared.database import Database
from src.shared.notifier import send_email
from src.shared.alerter import HealthTracker
from src.shared.portfolio_tracker import PortfolioTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

ACCOUNT_IDS = ["quiver_strat", "day_trader", "signal_echo"]
ACCOUNT_NAMES = {
    "quiver_strat": "Signal Strategy",
    "day_trader": "Day Trader",
    "signal_echo": "Signal Echo",
}


def run_daily_report():
    """Generate and send daily performance email."""
    tracker = HealthTracker("daily-report")

    try:
        logger.info("=== Daily Report Starting ===")
        db = Database()

        # Gather data for all accounts
        account_data = []
        for account_id in ACCOUNT_IDS:
            try:
                data = _gather_account_data(account_id, db)
                account_data.append(data)
            except Exception as e:
                tracker.add_warning(
                    f"Failed to gather data for {account_id}: {e}",
                    service="Database",
                )
                account_data.append({
                    "account_id": account_id,
                    "name": ACCOUNT_NAMES.get(account_id, account_id),
                    "error": str(e),
                })

        # Build HTML email
        html = _build_email_html(account_data)

        # Send email
        today = date.today().strftime("%B %d, %Y")
        subject = f"QD Engine - Daily Report - {today}"
        success = send_email(subject, html)

        if success:
            logger.info("Daily report email sent successfully")
        else:
            tracker.add_error("Gmail", "Failed to send daily report email", "No report delivered")

        logger.info("=== Daily Report Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Daily report failed: {e}", "No report sent")
        logger.exception("Fatal error in daily report")

    finally:
        tracker.finalize()


def _gather_account_data(account_id: str, db: Database) -> dict:
    """Gather all data needed for one account's report section."""
    snapshot = db.get_latest_snapshot(account_id)
    todays_trades = db.get_todays_trades(account_id)
    pt = PortfolioTracker(account_id)
    metrics = pt.get_performance_metrics()

    equity = float(snapshot.get("equity", STARTING_CAPITAL)) if snapshot else STARTING_CAPITAL
    daily_pnl = float(snapshot.get("daily_pnl", 0)) if snapshot else 0
    total_pnl = equity - STARTING_CAPITAL
    return_pct = (total_pnl / STARTING_CAPITAL) * 100
    cash = float(snapshot.get("cash", STARTING_CAPITAL)) if snapshot else STARTING_CAPITAL
    positions = snapshot.get("positions", []) if snapshot else []

    return {
        "account_id": account_id,
        "name": ACCOUNT_NAMES.get(account_id, account_id),
        "equity": equity,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": (daily_pnl / (equity - daily_pnl) * 100) if equity - daily_pnl > 0 else 0,
        "total_pnl": total_pnl,
        "return_pct": return_pct,
        "cash": cash,
        "positions": positions,
        "position_count": len(positions),
        "todays_trades": todays_trades,
        "win_rate": metrics.get("win_rate", 0),
        "total_trades": metrics.get("total_trades", 0),
        "sharpe_ratio": metrics.get("sharpe_ratio", 0),
    }


def _build_email_html(accounts: list) -> str:
    """Build the HTML email body."""
    today = date.today().strftime("%B %d, %Y")

    # Calculate totals
    total_equity = sum(a.get("equity", STARTING_CAPITAL) for a in accounts if "error" not in a)
    total_daily = sum(a.get("daily_pnl", 0) for a in accounts if "error" not in a)
    total_return = total_equity - (STARTING_CAPITAL * 3)

    account_sections = ""
    for acct in accounts:
        if "error" in acct:
            account_sections += f"""
            <div style="background:#2a2a4a;border-radius:8px;padding:20px;margin:15px 0;">
                <h3 style="color:#ff6b6b;margin:0 0 10px 0;">{acct['name']}</h3>
                <p style="color:#ff6b6b;">Error: {acct['error']}</p>
            </div>"""
            continue

        pnl_color = "#4ecdc4" if acct["daily_pnl"] >= 0 else "#ff6b6b"
        total_color = "#4ecdc4" if acct["total_pnl"] >= 0 else "#ff6b6b"
        pnl_sign = "+" if acct["daily_pnl"] >= 0 else ""
        total_sign = "+" if acct["total_pnl"] >= 0 else ""

        # Trades table
        trades_html = ""
        if acct.get("todays_trades"):
            trades_html = """
            <table style="width:100%;border-collapse:collapse;margin:10px 0;">
                <tr style="background:#1a1a2e;">
                    <th style="padding:6px;text-align:left;border:1px solid #444;">Symbol</th>
                    <th style="padding:6px;text-align:left;border:1px solid #444;">Side</th>
                    <th style="padding:6px;text-align:right;border:1px solid #444;">Amount</th>
                    <th style="padding:6px;text-align:left;border:1px solid #444;">Strategy</th>
                    <th style="padding:6px;text-align:left;border:1px solid #444;">Status</th>
                </tr>"""
            for t in acct["todays_trades"]:
                trades_html += f"""
                <tr>
                    <td style="padding:6px;border:1px solid #444;">{t.get('symbol', 'N/A')}</td>
                    <td style="padding:6px;border:1px solid #444;">{t.get('side', 'N/A')}</td>
                    <td style="padding:6px;text-align:right;border:1px solid #444;">${float(t.get('notional', 0)):.2f}</td>
                    <td style="padding:6px;border:1px solid #444;">{t.get('strategy', 'N/A')}</td>
                    <td style="padding:6px;border:1px solid #444;">{t.get('status', 'N/A')}</td>
                </tr>"""
            trades_html += "</table>"
        else:
            trades_html = '<p style="color:#888;">No trades today.</p>'

        # Positions
        positions_html = ""
        if acct.get("positions"):
            for pos in acct["positions"]:
                pos_pnl = float(pos.get("unrealized_pl", 0))
                pos_color = "#4ecdc4" if pos_pnl >= 0 else "#ff6b6b"
                positions_html += (
                    f'<span style="color:{pos_color};margin-right:10px;">'
                    f'{pos.get("symbol", "?")} '
                    f'${pos_pnl:+.2f}</span>'
                )

        account_sections += f"""
        <div style="background:#2a2a4a;border-radius:8px;padding:20px;margin:15px 0;">
            <h3 style="color:#e2e8f0;margin:0 0 15px 0;">{acct['name']}</h3>
            <div style="display:flex;flex-wrap:wrap;gap:20px;margin-bottom:15px;">
                <div>
                    <div style="color:#888;font-size:11px;">Starting Capital</div>
                    <div style="color:#e2e8f0;font-size:18px;">$10,000</div>
                </div>
                <div>
                    <div style="color:#888;font-size:11px;">Current</div>
                    <div style="color:#e2e8f0;font-size:18px;">${acct['equity']:,.2f}</div>
                </div>
                <div>
                    <div style="color:#888;font-size:11px;">Today</div>
                    <div style="color:{pnl_color};font-size:18px;">{pnl_sign}${acct['daily_pnl']:,.2f} ({pnl_sign}{acct['daily_pnl_pct']:.2f}%)</div>
                </div>
                <div>
                    <div style="color:#888;font-size:11px;">Since Inception</div>
                    <div style="color:{total_color};font-size:18px;">{total_sign}${acct['total_pnl']:,.2f} ({total_sign}{acct['return_pct']:.2f}%)</div>
                </div>
                <div>
                    <div style="color:#888;font-size:11px;">Cash</div>
                    <div style="color:#e2e8f0;font-size:18px;">${acct['cash']:,.2f}</div>
                </div>
                <div>
                    <div style="color:#888;font-size:11px;">Positions</div>
                    <div style="color:#e2e8f0;font-size:18px;">{acct['position_count']}</div>
                </div>
            </div>
            <div style="margin-bottom:10px;">{positions_html}</div>
            <div style="color:#888;font-size:12px;">
                Win Rate: {acct['win_rate']:.1f}% | Trades: {acct['total_trades']} | Sharpe: {acct['sharpe_ratio']:.2f}
            </div>
            <h4 style="color:#a0aec0;margin:15px 0 5px 0;">Today's Trades</h4>
            {trades_html}
        </div>"""

    total_daily_color = "#4ecdc4" if total_daily >= 0 else "#ff6b6b"
    total_return_color = "#4ecdc4" if total_return >= 0 else "#ff6b6b"
    td_sign = "+" if total_daily >= 0 else ""
    tr_sign = "+" if total_return >= 0 else ""

    html = f"""
    <html>
    <body style="background:#0f0f23;color:#e2e8f0;font-family:'SF Mono',Monaco,monospace;padding:20px;max-width:800px;margin:0 auto;">
        <h1 style="color:#e2e8f0;border-bottom:1px solid #333;padding-bottom:10px;">
            QD Engine - Daily Report
        </h1>
        <p style="color:#888;">{today}</p>

        <div style="background:#1a1a3e;border-radius:8px;padding:15px;margin:15px 0;text-align:center;">
            <div style="color:#888;font-size:12px;">COMBINED PORTFOLIO</div>
            <div style="color:#e2e8f0;font-size:24px;">${total_equity:,.2f}</div>
            <div style="color:{total_daily_color};font-size:16px;">Today: {td_sign}${total_daily:,.2f}</div>
            <div style="color:{total_return_color};font-size:14px;">Total: {tr_sign}${total_return:,.2f}</div>
        </div>

        {account_sections}

        <p style="color:#555;font-size:11px;text-align:center;margin-top:30px;">
            QD Engine | Automated Portfolio Management
        </p>
    </body>
    </html>"""

    return html


if __name__ == "__main__":
    run_daily_report()
