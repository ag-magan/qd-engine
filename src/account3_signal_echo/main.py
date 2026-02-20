import logging
import sys
from datetime import date

from src.shared.alerter import HealthTracker
from src.shared.notifier import send_email
from src.account3_signal_echo.config import ACCOUNT_ID, SIGNAL_LOOKBACK_HOURS
from src.account3_signal_echo.signal_reader import SignalReader
from src.account3_signal_echo.executor import SignalEchoExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_morning():
    """Morning: read signals, open positions."""
    tracker = HealthTracker("signal-echo-morning", ACCOUNT_ID)
    try:
        logger.info("=== Signal Echo: Morning Open ===")

        reader = SignalReader()
        signals = reader.get_eligible_signals(since_hours=SIGNAL_LOOKBACK_HOURS)

        if not signals:
            logger.info("No eligible signals. Done.")
            tracker.finalize()
            return

        executor = SignalEchoExecutor()
        opened = executor.open_positions(signals)

        logger.info(
            f"Morning: {len(signals)} eligible signals, "
            f"{len(opened)} positions opened"
        )
        logger.info("=== Signal Echo: Morning Open Complete ===")

    except Exception as e:
        tracker.add_error("System", str(e), "Morning phase failed")
        logger.exception("Fatal error in Signal Echo morning phase")
    finally:
        tracker.finalize()


def run_midday():
    """Midday: catch new signals from Process A's latest cycle, manage stops."""
    tracker = HealthTracker("signal-echo-midday", ACCOUNT_ID)
    try:
        logger.info("=== Signal Echo: Midday Check ===")

        reader = SignalReader()
        new_signals = reader.get_eligible_signals(since_hours=4)

        executor = SignalEchoExecutor()

        opened = []
        if new_signals:
            opened = executor.open_positions(new_signals)

        actions = executor.manage_positions()

        logger.info(
            f"Midday: {len(opened)} new positions, "
            f"{len(actions)} stop actions"
        )
        logger.info("=== Signal Echo: Midday Check Complete ===")

    except Exception as e:
        tracker.add_error("System", str(e), "Midday phase failed")
        logger.exception("Fatal error in Signal Echo midday phase")
    finally:
        tracker.finalize()


def run_eod():
    """EOD: close everything, send daily summary."""
    tracker = HealthTracker("signal-echo-eod", ACCOUNT_ID)
    try:
        logger.info("=== Signal Echo: EOD Close ===")

        executor = SignalEchoExecutor()
        closed = executor.force_close_all()

        _send_daily_summary(closed)

        logger.info(f"EOD: closed {len(closed)} positions")
        logger.info("=== Signal Echo: EOD Close Complete ===")

    except Exception as e:
        tracker.add_error("System", str(e), "EOD phase failed")
        logger.exception("Fatal error in Signal Echo EOD phase")
    finally:
        tracker.finalize()


def _send_daily_summary(closed: list) -> None:
    """Send a simple daily summary email."""
    if not closed:
        return

    winners = [c for c in closed if c["pnl"] > 0]
    losers = [c for c in closed if c["pnl"] <= 0]
    total_pnl = sum(c["pnl"] for c in closed)

    best = max(closed, key=lambda c: c["pnl_pct"])
    worst = min(closed, key=lambda c: c["pnl_pct"])

    today = date.today().strftime("%B %d, %Y")
    pnl_sign = "+" if total_pnl >= 0 else ""

    body = f"""
    <html><body style="background:#0f0f23;color:#e2e8f0;font-family:monospace;padding:20px;">
    <h2 style="color:#e2e8f0;">Signal Echo Daily Summary &mdash; {today}</h2>
    <p>Positions closed: {len(closed)}</p>
    <p>Winners: {len(winners)} | Losers: {len(losers)}</p>
    <p style="color:{'#4ecdc4' if total_pnl >= 0 else '#ff6b6b'};font-size:18px;">
        Total P&amp;L: {pnl_sign}${total_pnl:.2f}
    </p>
    <p>Best: {best['symbol']} {best['pnl_pct']:+.1f}% | Worst: {worst['symbol']} {worst['pnl_pct']:+.1f}%</p>
    </body></html>
    """
    send_email(f"Signal Echo \u2014 {today} \u2014 {pnl_sign}${total_pnl:.2f}", body)


def run_manage():
    """Manage positions only — trailing stop checks.

    Fills the gap between morning open and midday check so positions
    aren't left unmanaged for hours.
    """
    tracker = HealthTracker("signal-echo-manage", ACCOUNT_ID)
    try:
        logger.info("=== Signal Echo: Position Management ===")
        executor = SignalEchoExecutor()
        actions = executor.manage_positions()
        logger.info(f"Manage: {len(actions)} stop actions")
        logger.info("=== Signal Echo: Position Management Complete ===")
    except Exception as e:
        tracker.add_error("System", str(e), "Position management failed")
        logger.exception("Fatal error in Signal Echo position management")
    finally:
        tracker.finalize()


def run():
    """Entry point with mode selection."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    modes = {
        "morning": run_morning,
        "midday": run_midday,
        "eod": run_eod,
        "manage": run_manage,
    }

    if mode not in modes:
        logger.error(f"Unknown mode: {mode}. Valid: {list(modes.keys())}")
        sys.exit(1)

    modes[mode]()


if __name__ == "__main__":
    run()
