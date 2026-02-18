import logging
import sys

from src.shared.config import ACCOUNT_CONFIGS
from src.shared.alerter import HealthTracker
from src.shared.risk_manager import RiskManager
from src.account1_quiver.config import ACCOUNT_ID
from src.account1_quiver.signal_generator import SignalGenerator
from src.account1_quiver.signal_scorer import SignalScorer
from src.account1_quiver.claude_analyzer import ClaudeAnalyzer
from src.account1_quiver.pie_manager import PieManager
from src.account1_quiver.executor import Executor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run():
    """Main entry point for Account 1 QuiverQuant strategy."""
    tracker = HealthTracker("quiver-strategy", ACCOUNT_ID)

    try:
        logger.info("=== Account 1: Signal Strategy Starting ===")

        risk = RiskManager(ACCOUNT_ID)
        config = ACCOUNT_CONFIGS[ACCOUNT_ID]
        min_confidence = config.get("min_claude_confidence", 65)

        # Step 0: Execute any queued orders from previous off-hours runs
        executor = Executor()
        queued_executed = executor.execute_queued_orders()
        if queued_executed:
            logger.info(f"Executed {len(queued_executed)} queued orders from previous run")

        # Step 0.5: Check exit conditions on existing positions
        exit_actions = executor.check_exit_conditions()
        if exit_actions:
            logger.info(f"Exit conditions triggered: {exit_actions}")

        # Step 1: Generate signals from all sources
        generator = SignalGenerator()
        try:
            raw_signals = generator.generate_all_signals()
            logger.info(f"Generated {len(raw_signals)} raw signals")
        except Exception as e:
            tracker.add_error("QuiverQuant", str(e), "No signals generated this cycle")
            raw_signals = []

        if not raw_signals:
            logger.info("No signals generated. Checking for rebalance...")
            # Check rebalance even if no new signals
            pie_mgr = PieManager()
            rebalance_actions = pie_mgr.check_rebalance_needed()
            if rebalance_actions:
                executor = Executor()
                executor.execute_rebalance(rebalance_actions)
            tracker.finalize()
            return

        # Step 2: Save raw signals to DB (batched)
        db = generator.db
        saved_rows = db.insert_signals_batch(raw_signals)
        # Map returned IDs back to raw_signals by index
        for i, saved in enumerate(saved_rows):
            if i < len(raw_signals):
                raw_signals[i]["id"] = saved["id"]
                raw_signals[i]["signal_id"] = saved["id"]
        logger.info(f"Saved {len(saved_rows)} signals to DB")

        # Step 3: Score and rank signals
        scorer = SignalScorer()
        scored_signals = scorer.score_signals(raw_signals)
        logger.info(f"Scored {len(scored_signals)} symbols above threshold")

        if not scored_signals:
            logger.info("No signals above scoring threshold")
            tracker.finalize()
            return

        # Step 4: Get portfolio state for Claude context
        working_capital = risk.get_working_capital()
        invested = risk.get_invested_amount()
        portfolio_state = {
            "working_capital": round(working_capital, 2),
            "invested": round(invested, 2),
            "position_count": risk.alpaca.get_position_count(),
            "daily_pnl": 0,
        }

        # Step 5: Claude analyzes top signals
        analyzer = ClaudeAnalyzer()
        approved_signals = []

        for scored in scored_signals[:20]:  # Analyze top 20 at most
            try:
                analysis = analyzer.analyze_signal(scored, portfolio_state)
                if not analysis:
                    tracker.add_warning(
                        f"Claude returned empty analysis for {scored['symbol']}",
                        service="Claude",
                    )
                    continue

                confidence = analysis.get("confidence", 0)
                decision = analysis.get("decision", "skip")

                # Update signals with analysis results
                for sig in scored.get("signals", []):
                    if sig.get("id"):
                        db.client.table("signals").update({
                            "confidence": confidence,
                            "composite_score": scored["composite_score"],
                            "acted_on": confidence >= min_confidence and decision != "skip",
                            "skip_reason": (
                                f"Confidence {confidence} < {min_confidence}"
                                if confidence < min_confidence
                                else None
                            ),
                        }).eq("id", sig["id"]).execute()

                if confidence >= min_confidence and decision != "skip":
                    # Merge scored signal data with Claude analysis
                    analysis["sources"] = scored["sources"]
                    analysis["composite_score"] = scored["composite_score"]
                    analysis["signals"] = scored["signals"]
                    approved_signals.append(analysis)
                    logger.info(
                        f"APPROVED: {scored['symbol']} "
                        f"(confidence={confidence}, score={scored['composite_score']})"
                    )
                else:
                    logger.info(
                        f"REJECTED: {scored['symbol']} "
                        f"(confidence={confidence}, decision={decision})"
                    )

            except Exception as e:
                tracker.add_error(
                    "Claude", f"Analysis failed for {scored['symbol']}: {e}",
                    f"Signal {scored['symbol']} skipped"
                )

        # Step 6: Execute approved trades
        if approved_signals:
            executor = Executor()
            executed = executor.execute_signals(approved_signals)
            logger.info(f"Executed {len(executed)} trades")

            # Update pie allocations
            pie_mgr = PieManager()
            pie_mgr.create_pie_from_signals(approved_signals)
        else:
            logger.info("No signals approved by Claude")

        # Step 7: Check for rebalance on existing positions
        pie_mgr = PieManager()
        rebalance_actions = pie_mgr.check_rebalance_needed()
        if rebalance_actions:
            executor = Executor()
            executor.execute_rebalance(rebalance_actions)

        logger.info("=== Account 1: Signal Strategy Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Unexpected error: {e}", "Strategy run failed")
        logger.exception("Fatal error in Account 1 strategy")

    finally:
        tracker.finalize()


if __name__ == "__main__":
    run()
