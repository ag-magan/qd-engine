import logging
from datetime import datetime, timezone

import pytz

from src.shared.alpaca_client import AlpacaClient
from src.shared.risk_manager import RiskManager
from src.shared.database import Database
from src.account2_daytrader.config import ACCOUNT_ID, STRATEGIES

logger = logging.getLogger(__name__)
ET = pytz.timezone("US/Eastern")


class DayTraderExecutor:
    """Execute day trades with tight risk controls and stop management."""

    def __init__(self):
        self.alpaca = AlpacaClient(ACCOUNT_ID)
        self.risk = RiskManager(ACCOUNT_ID)
        self.db = Database()
        self._high_water_marks = {}  # symbol -> highest unrealized P&L % seen

    def execute_setup(self, setup: dict) -> dict:
        """Execute a trading setup after all risk checks pass."""
        symbol = setup["symbol"]
        side = setup.get("side", "buy")
        strategy = setup.get("strategy", "unknown")

        # Guard: skip if market is closed (holidays, early closes)
        if not self.alpaca.is_market_open():
            logger.warning(f"Market closed. Skipping {symbol}.")
            return {"status": "blocked", "reason": "market_closed"}

        # Risk checks
        can_trade, daily_pnl = self.risk.check_daily_loss_limit()
        if not can_trade:
            logger.warning(f"Daily loss limit hit (P&L: ${daily_pnl:.2f}). No new trades.")
            return {"status": "blocked", "reason": "daily_loss_limit"}

        can_trade, trade_count = self.risk.check_max_trades_per_day()
        if not can_trade:
            logger.warning(f"Max trades reached ({trade_count}). No new trades.")
            return {"status": "blocked", "reason": "max_trades_reached"}

        # Position sizing based on confidence and strategy stops
        confidence = setup.get("confidence", 50)
        position_size = self.risk.calculate_position_size(symbol, confidence)

        can_open, reason = self.risk.can_open_position(symbol, position_size)
        if not can_open:
            logger.info(f"Cannot open {symbol}: {reason}")
            return {"status": "blocked", "reason": reason}

        # Submit order
        order = self.alpaca.submit_market_order(
            symbol=symbol, side=side, notional=position_size
        )

        if not order:
            return {"status": "failed", "reason": "order_submission_failed"}

        # Record trade
        trade_record = {
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "side": side,
            "notional": round(position_size, 2),
            "order_type": "market",
            "alpaca_order_id": str(order.id),
            "status": str(order.status),
            "strategy": strategy,
            "reasoning": setup.get("reasoning", ""),
        }
        db_trade = self.db.insert_trade(trade_record)

        logger.info(
            f"Day trade executed: {side} {symbol} ${position_size:.2f} "
            f"({strategy}, confidence={confidence})"
        )

        return {
            "status": "executed",
            "trade": db_trade,
            "setup": setup,
        }

    def manage_positions(self) -> list:
        """Check open positions against stops, targets, and trailing stops."""
        positions = self.alpaca.get_positions()
        open_trades = self.db.get_open_trades(ACCOUNT_ID)
        actions = []

        for pos in positions:
            symbol = pos.symbol
            unrealized_pnl_pct = float(pos.unrealized_plpc) * 100

            trade = next(
                (t for t in open_trades if t["symbol"] == symbol),
                None,
            )
            if not trade:
                continue

            strategy = trade.get("strategy", "unknown")
            config = STRATEGIES.get(strategy, {})
            target_pct = config.get("target_pct", 2.0)
            stop_pct = config.get("stop_pct", 1.0)
            trail_activate = config.get("trail_activate_pct")
            trail_offset = config.get("trail_offset_pct")

            # Check adaptive stop override
            adaptive = self.db.get_adaptive_config(
                ACCOUNT_ID, parameter="stop_pct", strategy=strategy
            )
            if adaptive:
                stop_pct = float(adaptive[0]["value"])

            # Update high-water mark
            prev_high = self._high_water_marks.get(symbol, 0)
            if unrealized_pnl_pct > prev_high:
                self._high_water_marks[symbol] = unrealized_pnl_pct
            current_high = self._high_water_marks.get(symbol, 0)

            # Determine effective stop (trailing or fixed)
            effective_stop = -stop_pct  # Default: fixed stop
            if (trail_activate and trail_offset
                    and current_high >= trail_activate):
                trailing_stop = current_high - trail_offset
                # Trailing stop can only be BETTER than fixed stop
                if trailing_stop > effective_stop:
                    effective_stop = trailing_stop

            # Check stop loss (fixed or trailing)
            if unrealized_pnl_pct <= effective_stop:
                reason = "trailing_stop" if effective_stop > -stop_pct else "stop_loss"
                logger.info(
                    f"{reason.upper()}: {symbol} at {unrealized_pnl_pct:.2f}% "
                    f"(effective stop: {effective_stop:.2f}%, "
                    f"high: {current_high:.2f}%)"
                )
                self._close_and_record(pos, trade, reason)
                self._high_water_marks.pop(symbol, None)
                actions.append({"symbol": symbol, "action": reason})

            # Check profit target
            elif unrealized_pnl_pct >= target_pct:
                logger.info(
                    f"TARGET HIT: {symbol} at {unrealized_pnl_pct:.2f}% "
                    f"(target: +{target_pct}%)"
                )
                self._close_and_record(pos, trade, "target_hit")
                self._high_water_marks.pop(symbol, None)
                actions.append({"symbol": symbol, "action": "target_hit"})

        # Clean up high-water marks for closed positions
        open_symbols = {pos.symbol for pos in positions}
        for sym in list(self._high_water_marks.keys()):
            if sym not in open_symbols:
                del self._high_water_marks[sym]

        return actions

    def force_close_all(self) -> list:
        """Force close all positions (EOD)."""
        self._high_water_marks.clear()
        positions = self.alpaca.get_positions()
        closed = []

        for pos in positions:
            symbol = pos.symbol
            trades = self.db.get_open_trades(ACCOUNT_ID)
            trade = next((t for t in trades if t["symbol"] == symbol), None)

            self._close_and_record(pos, trade, "eod_close")
            closed.append(symbol)

        if closed:
            logger.info(f"Force closed {len(closed)} positions: {closed}")

        return closed

    def _close_and_record(self, position, trade: dict, exit_reason: str) -> None:
        """Close a position and record the outcome."""
        symbol = position.symbol
        entry_price = float(position.avg_entry_price)
        current_price = float(position.current_price)
        qty = float(position.qty)
        realized_pnl = float(position.unrealized_pl)
        pnl_pct = float(position.unrealized_plpc) * 100

        # Close position via Alpaca
        self.alpaca.close_position(symbol)

        # Update trade status
        if trade and trade.get("id"):
            self.db.update_trade(trade["id"], {
                "status": "closed",
                "fill_price": current_price,
                "filled_at": datetime.now(timezone.utc).isoformat(),
            })

        # Record trade outcome
        outcome = {
            "trade_id": trade["id"] if trade else None,
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "strategy": trade.get("strategy", "unknown") if trade else "unknown",
            "entry_price": entry_price,
            "exit_price": current_price,
            "entry_date": trade.get("created_at") if trade else None,
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "realized_pnl": round(realized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "outcome": "win" if realized_pnl > 0 else "loss",
            "exit_reason": exit_reason,
        }
        self.db.insert_trade_outcome(outcome)

        logger.info(
            f"Closed {symbol}: P&L=${realized_pnl:.2f} ({pnl_pct:.2f}%), "
            f"reason={exit_reason}"
        )
