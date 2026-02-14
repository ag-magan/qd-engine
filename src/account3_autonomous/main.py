import logging
import sys

from src.shared.alerter import HealthTracker
from src.account3_autonomous.config import ACCOUNT_ID
from src.account3_autonomous.market_briefing import MarketBriefing
from src.account3_autonomous.decision_engine import DecisionEngine
from src.account3_autonomous.thesis_tracker import ThesisTracker
from src.account3_autonomous.executor import AutonomousExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_decision():
    """Morning decision phase: gather context, let Claude decide."""
    tracker = HealthTracker("autonomous-decision", ACCOUNT_ID)
    try:
        logger.info("=== Account 3: Autonomous Decision Phase ===")

        # Build comprehensive briefing
        briefing_builder = MarketBriefing()
        try:
            briefing = briefing_builder.build_briefing()
        except Exception as e:
            tracker.add_error("Market Data", str(e), "Cannot build briefing")
            tracker.finalize()
            return

        # Get Claude's decisions
        engine = DecisionEngine()
        try:
            decisions = engine.make_daily_decisions(briefing)
        except Exception as e:
            tracker.add_error("Claude", str(e), "No trading decisions made")
            tracker.finalize()
            return

        if not decisions:
            logger.info("No decisions returned by Claude")
            tracker.finalize()
            return

        # Execute decisions
        executor = AutonomousExecutor()
        results = executor.execute_decisions(decisions)

        if results.get("errors"):
            for err in results["errors"]:
                tracker.add_warning(
                    f"Error for {err['symbol']}: {err['error']}",
                    service="Alpaca",
                )

        logger.info(f"Decision phase complete: {results}")
        logger.info("=== Account 3: Decision Phase Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Unexpected error: {e}", "Decision phase failed")
        logger.exception("Fatal error in autonomous decision phase")

    finally:
        tracker.finalize()


def run_monitor():
    """Midday monitoring: check positions against theses and stops."""
    tracker = HealthTracker("autonomous-monitor", ACCOUNT_ID)
    try:
        logger.info("=== Account 3: Position Monitor ===")

        # Build portfolio summary for monitoring
        briefing_builder = MarketBriefing()
        portfolio_summary = (
            briefing_builder._get_portfolio_state() + "\n\n" +
            briefing_builder._get_open_theses()
        )

        # Get Claude's monitoring assessment
        engine = DecisionEngine()
        try:
            monitor_result = engine.monitor_positions(portfolio_summary)
        except Exception as e:
            tracker.add_error("Claude", str(e), "Position monitoring failed")
            tracker.finalize()
            return

        # Execute any close actions
        if monitor_result:
            executor = AutonomousExecutor()
            closed = executor.execute_monitor_actions(monitor_result)
            if closed:
                logger.info(f"Monitor closed {len(closed)} positions")

        logger.info("=== Account 3: Monitor Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Unexpected error: {e}", "Monitor phase failed")
        logger.exception("Fatal error in autonomous monitor")

    finally:
        tracker.finalize()


def run_eod():
    """End of day: evaluate closed theses and reflect."""
    tracker = HealthTracker("autonomous-eod", ACCOUNT_ID)
    try:
        logger.info("=== Account 3: EOD Review ===")

        # Evaluate any theses for recently closed trades
        thesis_tracker = ThesisTracker()
        try:
            evaluations = thesis_tracker.evaluate_closed_theses()
            if evaluations:
                logger.info(f"Evaluated {len(evaluations)} theses")
                for ev in evaluations:
                    logger.info(
                        f"  {ev['symbol']}: {ev['classification']} - {ev['lesson']}"
                    )
        except Exception as e:
            tracker.add_warning(f"Thesis evaluation failed: {e}", service="Claude")

        # Get thesis accuracy stats
        stats = thesis_tracker.get_thesis_accuracy_stats()
        logger.info(f"Thesis accuracy: {stats}")

        logger.info("=== Account 3: EOD Review Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Unexpected error: {e}", "EOD review failed")
        logger.exception("Fatal error in autonomous EOD")

    finally:
        tracker.finalize()


def run():
    """Entry point with mode selection."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "decision"

    if mode == "decision":
        run_decision()
    elif mode == "monitor":
        run_monitor()
    elif mode == "eod":
        run_eod()
    else:
        logger.error(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    run()
