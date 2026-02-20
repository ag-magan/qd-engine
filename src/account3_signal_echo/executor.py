import logging
import time
from datetime import datetime, timezone

from src.shared.alpaca_client import AlpacaClient
from src.shared.risk_manager import RiskManager
from src.shared.database import Database
from src.account3_signal_echo.config import (
    ACCOUNT_ID, TRAIL_ACTIVATE_PCT, TRAIL_OFFSET_PCT,
)

logger = logging.getLogger(__name__)


class SignalEchoExecutor:
    """Execute Signal Echo trades with trailing stops and EOD close."""

    def __init__(self):
        self.alpaca = AlpacaClient(ACCOUNT_ID)
        self.risk = RiskManager(ACCOUNT_ID)
        self.db = Database()
        self._high_water_marks = {}

    def open_positions(self, signals: list) -> list:
        """Open positions for eligible signals."""
        opened = []
        for signal in signals:
            symbol = signal["symbol"]
            composite_score = signal["composite_score"]
            sources = signal.get("sources", [])

            # Daily loss check
            can_trade, daily_pnl = self.risk.check_daily_loss_limit()
            if not can_trade:
                logger.warning(f"Daily loss limit hit (${daily_pnl:.2f}). Stopping.")
                break

            # Max trades check
            can_trade, trade_count = self.risk.check_max_trades_per_day()
            if not can_trade:
                logger.warning(f"Max trades reached ({trade_count}). Stopping.")
                break

            # Position sizing: map composite_score to confidence
            score_as_confidence = min(int(composite_score), 100)
            position_size = self.risk.calculate_position_size(
                symbol, confidence=score_as_confidence,
            )

            if position_size < 1.0:
                logger.info(f"Position too small for {symbol}: ${position_size:.2f}")
                continue

            # Risk check
            can_open, reason = self.risk.can_open_position(symbol, position_size)
            if not can_open:
                logger.info(f"Cannot open {symbol}: {reason}")
                continue

            # Submit market order
            side = signal.get("direction", "buy")
            order = self.alpaca.submit_market_order(
                symbol=symbol, side=side, notional=position_size,
            )
            if not order:
                logger.warning(f"Order submission failed for {symbol}")
                continue

            # Record trade in DB
            trade_record = {
                "account_id": ACCOUNT_ID,
                "symbol": symbol,
                "side": side,
                "notional": round(position_size, 2),
                "order_type": "market",
                "alpaca_order_id": str(order.id),
                "status": str(order.status),
                "strategy": "signal_echo",
                "reasoning": (
                    f"Signal Echo: {', '.join(sources)} "
                    f"(score={composite_score})"
                ),
            }
            db_trade = self.db.insert_trade(trade_record)

            # Sync fill status
            if db_trade:
                try:
                    time.sleep(1)
                    order_info = self.alpaca.get_order(str(order.id))
                    if order_info and "filled" in str(order_info.status).lower():
                        self.db.update_trade(db_trade["id"], {
                            "status": "filled",
                            "fill_price": float(order_info.filled_avg_price),
                            "filled_at": str(order_info.filled_at),
                        })
                        logger.info(
                            f"Filled: {symbol} @ ${float(order_info.filled_avg_price):.2f}"
                        )
                except Exception as e:
                    logger.warning(f"Order sync failed for {symbol} (non-fatal): {e}")

            logger.info(
                f"Opened {side} {symbol}: ${position_size:.2f} "
                f"(score={composite_score}, sources={sources})"
            )
            opened.append({"symbol": symbol, "notional": position_size, "score": composite_score})

        return opened

    def manage_positions(self) -> list:
        """Trailing stop management on open positions."""
        positions = self.alpaca.get_positions()
        open_trades = self.db.get_open_trades(ACCOUNT_ID)
        actions = []

        # Index trades by symbol, keeping the most recent per symbol
        trades_by_symbol = {}
        for t in sorted(open_trades, key=lambda x: x.get("created_at", "")):
            trades_by_symbol[t["symbol"]] = t

        for pos in positions:
            symbol = pos.symbol
            unrealized_pnl_pct = float(pos.unrealized_plpc) * 100

            trade = trades_by_symbol.get(symbol)
            if not trade:
                continue

            # Update high-water mark
            prev_high = self._high_water_marks.get(symbol, 0)
            if unrealized_pnl_pct > prev_high:
                self._high_water_marks[symbol] = unrealized_pnl_pct
            current_high = self._high_water_marks.get(symbol, 0)

            # Check trailing stop
            if (TRAIL_ACTIVATE_PCT and TRAIL_OFFSET_PCT
                    and current_high >= TRAIL_ACTIVATE_PCT):
                trailing_stop = current_high - TRAIL_OFFSET_PCT
                if unrealized_pnl_pct <= trailing_stop:
                    logger.info(
                        f"TRAILING STOP: {symbol} at {unrealized_pnl_pct:.2f}% "
                        f"(high={current_high:.2f}%, trail={trailing_stop:.2f}%)"
                    )
                    self._close_and_record(pos, trade, "trailing_stop")
                    self._high_water_marks.pop(symbol, None)
                    actions.append({"symbol": symbol, "action": "trailing_stop"})

        # Clean up high-water marks for closed positions
        open_symbols = {pos.symbol for pos in positions}
        for sym in list(self._high_water_marks.keys()):
            if sym not in open_symbols:
                del self._high_water_marks[sym]

        return actions

    def force_close_all(self) -> list:
        """Force close ALL positions at EOD."""
        self._high_water_marks.clear()
        positions = self.alpaca.get_positions()
        trades = self.db.get_open_trades(ACCOUNT_ID)
        closed = []

        trades_by_symbol = {}
        for t in sorted(trades, key=lambda x: x.get("created_at", "")):
            trades_by_symbol[t["symbol"]] = t

        for pos in positions:
            symbol = pos.symbol
            trade = trades_by_symbol.get(symbol)
            self._close_and_record(pos, trade, "eod_close")
            closed.append({
                "symbol": symbol,
                "pnl": float(pos.unrealized_pl),
                "pnl_pct": float(pos.unrealized_plpc) * 100,
            })

        if closed:
            logger.info(f"Force closed {len(closed)} positions")
        return closed

    def _close_and_record(self, position, trade: dict, exit_reason: str) -> None:
        """Close a position and record the outcome."""
        symbol = position.symbol
        entry_price = float(position.avg_entry_price)
        current_price = float(position.current_price)
        realized_pnl = float(position.unrealized_pl)
        pnl_pct = float(position.unrealized_plpc) * 100

        self.alpaca.close_position(symbol)

        if trade and trade.get("id"):
            self.db.update_trade(trade["id"], {
                "status": "closed",
                "fill_price": current_price,
                "filled_at": datetime.now(timezone.utc).isoformat(),
            })

        outcome = {
            "trade_id": trade["id"] if trade else None,
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "strategy": "signal_echo",
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
