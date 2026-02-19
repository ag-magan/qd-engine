import logging
import sys
import time
from datetime import datetime

import pytz

from src.shared.alerter import HealthTracker
from src.shared.database import Database
from src.shared.risk_manager import RiskManager
from src.account2_daytrader.config import (
    ACCOUNT_ID, TRADING_START, NO_NEW_TRADES, FORCE_CLOSE, EOD_REVIEW,
    SCANNER as SCANNER_CONFIG,
)
from src.account2_daytrader.scanner import Scanner
from src.account2_daytrader.claude_analyzer import DayTraderClaudeAnalyzer
from src.account2_daytrader.adaptive_engine import AdaptiveEngine
from src.account2_daytrader.executor import DayTraderExecutor
from src.account2_daytrader.strategies.momentum import MomentumBreakout
from src.account2_daytrader.strategies.mean_reversion import MeanReversion
from src.account2_daytrader.strategies.gap_fill import GapFill
from src.account2_daytrader.strategies.vwap_bounce import VWAPBounce
from src.account2_daytrader.strategies.trending import TrendFollowing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)
ET = pytz.timezone("US/Eastern")

# Map strategy names to classes
STRATEGY_CLASSES = {
    "momentum_breakout": MomentumBreakout,
    "gap_fill": GapFill,
    "mean_reversion": MeanReversion,
    "vwap_bounce": VWAPBounce,
    "trending": TrendFollowing,
}


def load_strategies() -> list:
    """Load strategies from DB definitions, falling back to hardcoded defaults.

    Active strategy_definitions rows control which strategies run and with what parameters.
    If no DB rows exist, all hardcoded strategies run with default params.
    """
    try:
        db = Database()
        resp = (
            db.client.table("strategy_definitions")
            .select("*")
            .eq("account_id", ACCOUNT_ID)
            .eq("is_active", True)
            .execute()
        )
        defs = resp.data
    except Exception:
        defs = []

    if not defs:
        logger.info("No strategy definitions in DB, using hardcoded defaults")
        return [MomentumBreakout(), MeanReversion(), GapFill(), VWAPBounce(), TrendFollowing()]

    strategies = []
    for defn in defs:
        name = defn["name"]
        cls = STRATEGY_CLASSES.get(name)
        if cls is None:
            logger.warning(f"Unknown strategy name in DB: {name}, skipping")
            continue

        overrides = {
            "exit_rules": defn.get("exit_rules") or {},
            "filters": defn.get("filters") or {},
            "position_rules": defn.get("position_rules") or {},
        }
        strategies.append(cls(db_overrides=overrides))
        logger.info(f"Loaded strategy from DB: {name} (id={defn['id']})")

    if not strategies:
        logger.warning("All DB strategies unrecognized, falling back to defaults")
        return [MomentumBreakout(), MeanReversion(), GapFill(), VWAPBounce(), TrendFollowing()]

    logger.info(f"Active strategies: {[s.name for s in strategies]}")
    return strategies


def get_et_now():
    return datetime.now(ET)


def time_str_to_today(time_str: str) -> datetime:
    h, m = map(int, time_str.split(":"))
    now = get_et_now()
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def run_premarket():
    """Pre-market scan and Claude briefing."""
    tracker = HealthTracker("day-trader-premarket", ACCOUNT_ID)
    try:
        logger.info("=== Day Trader: Pre-Market Phase ===")
        scanner = Scanner()
        candidates = scanner.premarket_scan()

        if not candidates:
            logger.info("No pre-market candidates found")
            tracker.finalize()
            return {}, []

        analyzer = DayTraderClaudeAnalyzer()
        try:
            briefing = analyzer.premarket_briefing(candidates)
        except Exception as e:
            tracker.add_error("Claude", str(e), "No pre-market briefing available")
            briefing = {}

        # Build watchlist: Claude's picks + all pre-market candidates
        claude_picks = [s["symbol"] for s in briefing.get("top_setups", [])]
        all_candidate_symbols = [c["symbol"] for c in candidates]
        watchlist = claude_picks + [s for s in all_candidate_symbols if s not in claude_picks]
        if not watchlist:
            watchlist = [c["symbol"] for c in candidates[:30]]

        logger.info(f"Watchlist: {watchlist}")
        tracker.finalize()
        return briefing, watchlist

    except Exception as e:
        tracker.add_error("System", str(e), "Pre-market phase failed")
        tracker.finalize()
        return {}, []


def run_intraday_cycle(watchlist: list, market_context: dict,
                       executor: DayTraderExecutor, strategies: list):
    """Single intraday scan and trade cycle."""
    scanner = Scanner()
    adaptive = AdaptiveEngine()

    # Check for cooldown
    if adaptive.should_cooldown():
        logger.warning("Cooldown active due to consecutive losses. Skipping cycle.")
        return

    # Scan for setups
    candidates = scanner.intraday_scan(watchlist)
    if not candidates:
        return

    # Evaluate each candidate against strategies
    for candidate in candidates:
        for strategy in strategies:
            setup = strategy.evaluate(candidate)
            if setup:
                min_conf = strategy.get_config_value({}, "confidence_minimum", 60)
                if setup["confidence"] < min_conf:
                    continue
                if setup["confidence"] < 70:
                    analyzer = DayTraderClaudeAnalyzer()
                    try:
                        evaluation = analyzer.evaluate_setup(setup, market_context)
                        if evaluation.get("decision") == "no":
                            logger.info(
                                f"Claude rejected {setup['symbol']} "
                                f"({setup['strategy']}): {evaluation.get('reason')}"
                            )
                            continue
                    except Exception as e:
                        logger.warning(f"Claude eval failed, proceeding with setup: {e}")
                else:
                    logger.info(
                        f"Auto-executing high-confidence setup: {setup['symbol']} "
                        f"({setup['strategy']}, confidence={setup['confidence']})"
                    )

                result = executor.execute_setup(setup)
                if result.get("status") == "executed":
                    logger.info(f"Executed: {setup['symbol']} via {setup['strategy']}")
                elif result.get("status") == "blocked":
                    if result.get("reason") in ["daily_loss_limit", "max_trades_reached"]:
                        return  # Stop scanning this cycle


def run_eod():
    """End-of-day review and close positions."""
    tracker = HealthTracker("day-trader-eod", ACCOUNT_ID)
    try:
        logger.info("=== Day Trader: EOD Phase ===")
        executor = DayTraderExecutor()

        # Force close all positions
        closed = executor.force_close_all()
        logger.info(f"EOD: Closed {len(closed)} positions")

        # Run adaptive engine review
        adaptive = AdaptiveEngine()
        review = adaptive.eod_review()
        logger.info(f"EOD Review: {review}")

        tracker.finalize()
        return review

    except Exception as e:
        tracker.add_error("System", str(e), "EOD review failed")
        tracker.finalize()
        return {}


def run_loop():
    """Main market-hours loop (runs as a single long-running GitHub Actions job)."""
    tracker = HealthTracker("day-trader-loop", ACCOUNT_ID)
    logger.info("=== Day Trader: Starting Market Hours Loop ===")

    try:
        # Load strategies from DB (or defaults)
        strategies = load_strategies()

        # Phase 1: Pre-market scan
        briefing, watchlist = run_premarket()
        market_context = briefing or {}

        executor = DayTraderExecutor()
        scan_interval = SCANNER_CONFIG.get("scan_interval_seconds", 300)

        # Phase 2: Wait for trading to start
        trading_start = time_str_to_today(TRADING_START)
        while get_et_now() < trading_start:
            remaining = (trading_start - get_et_now()).total_seconds()
            logger.info(f"Waiting for trading start... {remaining:.0f}s remaining")
            time.sleep(min(remaining, 60))

        # Phase 3: Intraday loop
        no_new_trades_time = time_str_to_today(NO_NEW_TRADES)
        force_close_time = time_str_to_today(FORCE_CLOSE)
        last_watchlist_refresh = get_et_now()
        WATCHLIST_REFRESH_SECONDS = 1800  # 30 minutes

        while get_et_now() < force_close_time:
            now = get_et_now()

            # Refresh watchlist with mid-day movers periodically
            if (now < no_new_trades_time
                    and (now - last_watchlist_refresh).total_seconds() >= WATCHLIST_REFRESH_SECONDS):
                try:
                    refresh_scanner = Scanner()
                    quiver_syms = refresh_scanner._fetch_quiver_signals()
                    new_movers = refresh_scanner._fetch_dynamic_movers()
                    fresh = quiver_syms + new_movers
                    added = [s for s in fresh if s not in watchlist]
                    if added:
                        watchlist.extend(added)
                        logger.info(f"Watchlist refresh: added {len(added)} symbols "
                                    f"({len(quiver_syms)} quiver, {len(new_movers)} dynamic)")
                except Exception as e:
                    logger.warning(f"Watchlist refresh failed: {e}")
                last_watchlist_refresh = now

            if now < no_new_trades_time:
                # Scan for new setups
                try:
                    run_intraday_cycle(watchlist, market_context, executor, strategies)
                except Exception as e:
                    tracker.add_warning(f"Intraday cycle error: {e}", service="Scanner")

            # Always manage existing positions
            try:
                actions = executor.manage_positions()
                if actions:
                    logger.info(f"Position management: {actions}")
            except Exception as e:
                tracker.add_warning(f"Position management error: {e}", service="Alpaca")

            # Sleep until next scan
            time.sleep(scan_interval)

        # Phase 4: Force close
        logger.info("Market close approaching - force closing positions")
        executor.force_close_all()

        # Phase 5: EOD review
        eod_review = run_eod()

        logger.info("=== Day Trader: Market Hours Loop Complete ===")

    except Exception as e:
        tracker.add_error("System", f"Loop error: {e}", "Day trader loop crashed")
        logger.exception("Fatal error in day trader loop")
        # Emergency close all positions
        try:
            executor = DayTraderExecutor()
            executor.force_close_all()
        except Exception:
            tracker.add_error("Alpaca", "Emergency close failed", "Positions may be open")

    finally:
        tracker.finalize()


def run():
    """Entry point with mode selection."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "loop"

    if mode == "premarket":
        run_premarket()
    elif mode == "intraday":
        strategies = load_strategies()
        executor = DayTraderExecutor()
        run_intraday_cycle([], {}, executor, strategies)
    elif mode == "eod":
        run_eod()
    elif mode == "loop":
        run_loop()
    else:
        logger.error(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    run()
