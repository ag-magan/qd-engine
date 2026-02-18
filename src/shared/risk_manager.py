import logging
import time
from typing import Tuple, Optional

from src.shared.config import STARTING_CAPITAL, ACCOUNT_CONFIGS
from src.shared.database import Database
from src.shared.alpaca_client import AlpacaClient

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforces position sizing, exposure limits, and capital isolation.

    Each account operates with exactly $10,000 starting capital.
    Working capital = starting_capital + cumulative realized P&L + unrealized P&L.
    The remaining $90k in each paper account is OFF LIMITS.
    """

    _REALIZED_PNL_CACHE_TTL = 300  # 5 minutes

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.config = ACCOUNT_CONFIGS[account_id]
        self.db = Database()
        self.alpaca = AlpacaClient(account_id)
        self._realized_pnl_cache = None
        self._realized_pnl_cache_time = 0.0

    def _get_realized_pnl(self) -> float:
        """Get realized P&L with in-memory TTL cache.

        The expensive DB query (fetches all trade outcomes) only runs
        once per TTL period. Safe because realized P&L only changes
        when a trade closes, which is infrequent relative to the
        2-minute check cycles.
        """
        now = time.monotonic()
        if (self._realized_pnl_cache is not None
                and now - self._realized_pnl_cache_time < self._REALIZED_PNL_CACHE_TTL):
            return self._realized_pnl_cache

        try:
            outcomes = self.db.get_trade_outcomes(self.account_id, limit=10000)
            pnl = sum(float(o.get("realized_pnl", 0) or 0) for o in outcomes)
        except Exception as e:
            logger.error(f"Failed to calculate realized P&L: {e}")
            return self._realized_pnl_cache if self._realized_pnl_cache is not None else 0.0

        self._realized_pnl_cache = pnl
        self._realized_pnl_cache_time = now
        return pnl

    def get_working_capital(self) -> float:
        """Calculate working capital: starting_capital + cumulative P&L."""
        starting = self.config["starting_capital"]
        realized_pnl = self._get_realized_pnl()

        # Unrealized P&L from current positions (always live)
        unrealized_pnl = 0.0
        try:
            positions = self.alpaca.get_positions()
            unrealized_pnl = sum(
                float(pos.unrealized_pl) for pos in positions
            )
        except Exception as e:
            logger.error(f"Failed to calculate unrealized P&L: {e}")

        working_capital = starting + realized_pnl + unrealized_pnl
        logger.info(
            f"Working capital for {self.account_id}: "
            f"${working_capital:.2f} (start={starting}, "
            f"realized={realized_pnl:.2f}, unrealized={unrealized_pnl:.2f})"
        )
        return working_capital

    def get_invested_amount(self) -> float:
        """Get total market value of current positions."""
        return self.alpaca.get_invested_value()

    def can_open_position(self, symbol: str, notional: float) -> Tuple[bool, str]:
        """Check if a new position can be opened within risk limits."""
        working_capital = self.get_working_capital()
        invested = self.get_invested_amount()

        # Circuit breaker: invested should never exceed working capital
        if invested > working_capital * 1.05:
            msg = (
                f"CIRCUIT BREAKER: Invested ${invested:.2f} exceeds "
                f"working capital ${working_capital:.2f}. Halting all trading."
            )
            logger.critical(msg)
            return False, msg

        # Check max invested percentage
        max_invested_pct = self.config.get("max_invested_pct", 0.60)
        max_invested = working_capital * max_invested_pct
        if invested + notional > max_invested:
            return False, (
                f"Would exceed max invested: "
                f"${invested + notional:.2f} > ${max_invested:.2f} "
                f"({max_invested_pct * 100:.0f}% of ${working_capital:.2f})"
            )

        # Check max per position
        max_position_pct = self.config.get("max_position_pct",
                                           self.config.get("max_per_trade_pct", 0.10))
        max_position = working_capital * max_position_pct
        if notional > max_position:
            return False, (
                f"Position size ${notional:.2f} exceeds max "
                f"${max_position:.2f} ({max_position_pct * 100:.0f}% of capital)"
            )

        # Check max positions count
        max_positions = self.config.get("max_positions",
                                        self.config.get("max_concurrent_positions", 12))
        current_count = self.alpaca.get_position_count()
        if current_count >= max_positions:
            return False, (
                f"Max positions reached: {current_count}/{max_positions}"
            )

        # Check if already holding this symbol
        existing = self.alpaca.get_position(symbol)
        if existing:
            return False, f"Already holding position in {symbol}"

        return True, "OK"

    def calculate_position_size(
        self,
        symbol: str,
        confidence: int,
        max_override: float = None,
    ) -> float:
        """Calculate position size based on confidence and risk limits."""
        working_capital = self.get_working_capital()
        max_position_pct = self.config.get("max_position_pct",
                                           self.config.get("max_per_trade_pct", 0.10))
        max_position = working_capital * max_position_pct

        if max_override:
            max_position = min(max_position, max_override)

        # Scale position by confidence (50-100 maps to 50%-100% of max)
        confidence_scale = max(0.5, min(confidence / 100.0, 1.0))
        position_size = max_position * confidence_scale

        # Check adaptive config for overrides
        try:
            overrides = self.db.get_adaptive_config(
                self.account_id, parameter="max_position_pct"
            )
            if overrides:
                adaptive_pct = float(overrides[0]["value"])
                adaptive_max = working_capital * adaptive_pct
                position_size = min(position_size, adaptive_max)
        except Exception:
            pass

        return round(position_size, 2)

    def check_daily_loss_limit(self) -> Tuple[bool, float]:
        """Check if daily loss limit has been hit (for day trader)."""
        max_daily_risk_pct = self.config.get("max_daily_risk_pct")
        if max_daily_risk_pct is None:
            return True, 0.0

        working_capital = self.get_working_capital()
        max_daily_loss = working_capital * max_daily_risk_pct

        # Realized P&L from today's closed trades
        from datetime import date
        todays_pnl = 0.0
        try:
            outcomes = self.db.get_trade_outcomes(self.account_id, limit=100)
            today_str = date.today().isoformat()
            todays_pnl = sum(
                float(o.get("realized_pnl", 0) or 0)
                for o in outcomes
                if (o.get("exit_date") or "")[:10] == today_str
            )
        except Exception as e:
            logger.error(f"Failed to get today's realized P&L: {e}")

        # Also include unrealized from open positions
        unrealized = 0.0
        try:
            for pos in self.alpaca.get_positions():
                unrealized += float(pos.unrealized_intraday_pl)
        except Exception:
            pass

        total_daily_pnl = todays_pnl + unrealized

        if total_daily_pnl < -max_daily_loss:
            return False, total_daily_pnl

        return True, total_daily_pnl

    def check_max_trades_per_day(self) -> Tuple[bool, int]:
        """Check if max trades per day limit has been reached."""
        max_trades = self.config.get("max_trades_per_day")
        if max_trades is None:
            return True, 0

        todays_trades = self.db.get_todays_trades(self.account_id)
        count = len(todays_trades)

        if count >= max_trades:
            return False, count

        return True, count
