import logging

from src.shared.portfolio_tracker import PortfolioTracker
from src.shared.alerter import HealthTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

ACCOUNT_IDS = ["quiver_strat", "day_trader", "autonomous"]


def run_daily_snapshot():
    """Take daily portfolio snapshot for all accounts."""
    tracker = HealthTracker("daily-snapshot")

    try:
        logger.info("=== Daily Snapshot Starting ===")

        for account_id in ACCOUNT_IDS:
            try:
                pt = PortfolioTracker(account_id)
                snapshot = pt.take_snapshot()
                logger.info(
                    f"Snapshot {account_id}: "
                    f"equity=${snapshot.get('equity', 0):.2f}, "
                    f"daily_pnl=${snapshot.get('daily_pnl', 0):.2f}"
                )
            except Exception as e:
                tracker.add_error(
                    "Alpaca", f"Snapshot failed for {account_id}: {e}",
                    f"No snapshot for {account_id}"
                )

        logger.info("=== Daily Snapshot Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Snapshot failed: {e}", "No snapshots taken")
        logger.exception("Fatal error in daily snapshot")

    finally:
        tracker.finalize()


if __name__ == "__main__":
    run_daily_snapshot()
