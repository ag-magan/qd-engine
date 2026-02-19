import logging

from src.shared.database import Database
from src.account3_signal_echo.config import ACCOUNT_ID, MIN_COMPOSITE_SCORE

logger = logging.getLogger(__name__)


class SignalReader:
    """Read scored signals from Process A's pipeline. Read-only access."""

    def __init__(self):
        self.db = Database()

    def get_eligible_signals(self, since_hours: int = 24) -> list:
        """Get Process A's signals, filtered for Signal Echo eligibility.

        Calls Database.get_quiver_signals() which queries:
            signals table WHERE account_id = 'quiver_strat'
            AND created_at >= cutoff AND composite_score >= min_score

        Filters out:
        1. Symbols already held by Account 3 (no self-doubling)
        2. Symbols currently held by Account 1 (avoid correlated exposure)
        """
        signals = self.db.get_quiver_signals(
            since_hours=since_hours,
            min_score=MIN_COMPOSITE_SCORE,
        )

        if not signals:
            logger.info("No eligible signals from Process A")
            return []

        logger.info(f"Raw signals from Process A: {len(signals)} symbols")

        # Get symbols currently held by Account 3 (Signal Echo)
        acct3_trades = self.db.get_open_trades(ACCOUNT_ID)
        acct3_symbols = {t["symbol"] for t in acct3_trades}

        # Get symbols currently held by Account 1 (Process A)
        acct1_trades = self.db.get_open_trades("quiver_strat")
        acct1_symbols = {t["symbol"] for t in acct1_trades}

        eligible = []
        for sig in signals:
            symbol = sig["symbol"]
            if symbol in acct3_symbols:
                logger.info(f"Skipping {symbol}: already held by Account 3")
                continue
            if symbol in acct1_symbols:
                logger.info(f"Skipping {symbol}: held by Account 1 (avoid correlation)")
                continue
            eligible.append(sig)

        logger.info(
            f"Eligible signals: {len(eligible)} "
            f"(filtered {len(signals) - len(eligible)}: "
            f"{len(acct3_symbols)} self-held, {len(acct1_symbols)} acct1-held)"
        )
        return eligible
