import json
import logging
import time
from datetime import datetime, timedelta, timezone

from src.shared.alpaca_client import AlpacaClient
from src.shared.risk_manager import RiskManager
from src.shared.database import Database
from src.account1_quiver.config import (
    ACCOUNT_ID, SIGNAL_MAX_AGE_HOURS,
    DEFAULT_STOP_LOSS_PCT, DEFAULT_TARGET_RETURN_PCT, DEFAULT_TIME_HORIZON_DAYS,
)

logger = logging.getLogger(__name__)

QUEUE_MAX_AGE_HOURS = SIGNAL_MAX_AGE_HOURS


class Executor:
    """Execute trades for Account 1 against Alpaca."""

    def __init__(self):
        self.alpaca = AlpacaClient(ACCOUNT_ID)
        self.risk = RiskManager(ACCOUNT_ID)
        self.db = Database()

    def execute_signals(self, analyzed_signals: list) -> list:
        """Execute trades for signals that pass all checks.

        If the market is closed, queues approved signals for execution
        at the next market open.
        """
        if not self.alpaca.is_market_open():
            queued = self._queue_signals(analyzed_signals)
            logger.info(
                f"Market closed. Queued {len(queued)} signals for next open."
            )
            return []

        executed = []
        for signal in analyzed_signals:
            result = self._execute_single(signal)
            if result:
                executed.append(result)

        logger.info(f"Executed {len(executed)}/{len(analyzed_signals)} trades")
        return executed

    def execute_queued_orders(self) -> list:
        """Execute any pending queued orders if market is open."""
        if not self.alpaca.is_market_open():
            return []

        pending = self._get_pending_orders()
        if not pending:
            logger.info("No queued orders to execute")
            return []

        logger.info(f"Found {len(pending)} queued orders to execute")
        executed = []

        for order_row in pending:
            signal = order_row.get("signal_data", {})
            signal["symbol"] = order_row["symbol"]
            signal["confidence"] = order_row.get("confidence", 50)
            signal["position_size_pct"] = float(order_row.get("position_size_pct", 0.5))
            signal["decision"] = order_row["direction"]
            signal["thesis"] = order_row.get("reasoning", "")
            signal["composite_score"] = float(order_row.get("composite_score", 0))

            result = self._execute_single(signal)
            if result:
                self._mark_order_executed(order_row["id"])
                executed.append(result)
            else:
                self._mark_order_executed(order_row["id"], status="failed")

        logger.info(f"Executed {len(executed)}/{len(pending)} queued orders")
        return executed

    def _queue_signals(self, signals: list) -> list:
        """Save approved signals to pending_orders for later execution."""
        queued = []
        for signal in signals:
            symbol = signal.get("symbol", "")
            direction = signal.get("decision", signal.get("direction", "buy"))
            if direction == "skip":
                continue

            row = {
                "account_id": ACCOUNT_ID,
                "symbol": symbol,
                "direction": direction,
                "confidence": signal.get("confidence", 50),
                "position_size_pct": signal.get("position_size_pct", 0.5),
                "composite_score": signal.get("composite_score", 0),
                "sources": signal.get("sources", []),
                "signal_data": json.loads(json.dumps(signal, default=str)),
                "reasoning": signal.get("thesis", signal.get("reasoning", "")),
            }

            try:
                resp = self.db.client.table("pending_orders").insert(row).execute()
                queued.append(resp.data[0] if resp.data else row)
                logger.info(f"Queued {direction} {symbol} (confidence={row['confidence']})")
            except Exception as e:
                logger.error(f"Failed to queue {symbol}: {e}")

        return queued

    def _get_pending_orders(self) -> list:
        """Fetch pending orders that haven't expired."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=QUEUE_MAX_AGE_HOURS)
        ).isoformat()

        try:
            resp = (
                self.db.client.table("pending_orders")
                .select("*")
                .eq("account_id", ACCOUNT_ID)
                .eq("status", "pending")
                .gte("created_at", cutoff)
                .order("composite_score", desc=True)
                .execute()
            )
            return resp.data
        except Exception as e:
            logger.error(f"Failed to fetch pending orders: {e}")
            return []

    def _mark_order_executed(self, order_id: str, status: str = "executed") -> None:
        """Mark a pending order with the given status."""
        try:
            updates = {"status": status}
            if status == "executed":
                updates["executed_at"] = datetime.now(timezone.utc).isoformat()
            self.db.client.table("pending_orders").update(
                updates
            ).eq("id", order_id).execute()
        except Exception as e:
            logger.error(f"Failed to update pending order {order_id}: {e}")

    def _execute_single(self, signal: dict) -> dict:
        """Execute a single trade after risk checks."""
        symbol = signal["symbol"]
        direction = signal.get("decision", signal.get("direction", "buy"))

        if direction == "skip":
            self._record_skip(signal, "Claude recommended skip")
            return None

        # Calculate position size (use Claude's size_pct as sole scaler)
        confidence = signal.get("confidence", 50)
        size_pct = signal.get("position_size_pct", 0.5)
        max_position = self.risk.calculate_position_size(symbol, confidence=100)
        position_size = max_position * size_pct

        # Enforce minimum position size
        if position_size < 1.0:
            self._record_skip(signal, f"Position size too small: ${position_size:.2f}")
            return None

        # Risk check
        can_trade, reason = self.risk.can_open_position(symbol, position_size)
        if not can_trade:
            self._record_skip(signal, reason)
            return None

        # Submit order
        order = self.alpaca.submit_market_order(
            symbol=symbol,
            side=direction,
            notional=position_size,
        )

        if not order:
            self._record_skip(signal, "Order submission failed")
            return None

        # Record trade in DB
        trade_record = {
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "side": direction,
            "notional": round(position_size, 2),
            "order_type": "market",
            "alpaca_order_id": str(order.id),
            "status": str(order.status),
            "strategy": "quiver_composite",
            "signal_id": signal.get("signal_id"),
            "reasoning": signal.get("thesis", signal.get("reasoning", "")),
            "stop_loss_pct": signal.get("stop_loss_pct"),
            "target_return_pct": signal.get("target_return_pct"),
            "time_horizon_days": signal.get("time_horizon_days"),
        }
        db_trade = self.db.insert_trade(trade_record)

        # Sync fill status — market orders fill near-instantly
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
                    logger.info(f"Order filled: {symbol} @ ${float(order_info.filled_avg_price):.2f}")
            except Exception as e:
                logger.warning(f"Order sync failed for {symbol} (non-fatal): {e}")

        logger.info(
            f"Executed {direction} {symbol} for ${position_size:.2f} "
            f"(confidence={confidence})"
        )

        return {
            "trade": db_trade,
            "order_id": str(order.id),
            "symbol": symbol,
            "side": direction,
            "notional": position_size,
        }

    def _record_skip(self, signal: dict, reason: str) -> None:
        """Record a skipped signal in the database."""
        logger.info(f"Skipping {signal['symbol']}: {reason}")

        # Update signal as not acted on
        for raw_signal in signal.get("signals", [signal]):
            if "id" in raw_signal:
                self.db.client.table("signals").update(
                    {"acted_on": False, "skip_reason": reason}
                ).eq("id", raw_signal["id"]).execute()

    def check_exit_conditions(self) -> list:
        """Check open positions against stored stop/target/time parameters.

        Called every cron cycle. Exits positions that have:
        1. Hit their stop loss percentage
        2. Hit their target return percentage
        3. Exceeded their time horizon
        """
        positions = self.alpaca.get_positions()
        open_trades = self.db.get_open_trades(ACCOUNT_ID)
        closed = []

        for pos in positions:
            symbol = pos.symbol
            trade = next((t for t in open_trades if t["symbol"] == symbol), None)
            if not trade:
                continue

            unrealized_pnl_pct = float(pos.unrealized_plpc) * 100

            stop_pct = float(trade["stop_loss_pct"]) if trade.get("stop_loss_pct") else DEFAULT_STOP_LOSS_PCT
            target_pct = float(trade["target_return_pct"]) if trade.get("target_return_pct") else DEFAULT_TARGET_RETURN_PCT
            horizon_days = int(trade["time_horizon_days"]) if trade.get("time_horizon_days") else DEFAULT_TIME_HORIZON_DAYS

            exit_reason = None

            # Check stop loss
            if unrealized_pnl_pct <= -abs(stop_pct):
                exit_reason = "stop_loss"

            # Check target return
            elif unrealized_pnl_pct >= abs(target_pct):
                exit_reason = "target_hit"

            # Check time horizon expiry
            elif trade.get("created_at"):
                entry_time = datetime.fromisoformat(
                    str(trade["created_at"]).replace("Z", "+00:00")
                )
                days_held = (datetime.now(timezone.utc) - entry_time).days
                if days_held >= horizon_days:
                    exit_reason = "time_horizon_expired"

            if exit_reason:
                logger.info(
                    f"Exit triggered for {symbol}: {exit_reason} "
                    f"(pnl={unrealized_pnl_pct:.2f}%, stop=-{stop_pct}%, "
                    f"target=+{target_pct}%)"
                )
                self._close_and_record(pos, trade, exit_reason)
                closed.append({"symbol": symbol, "reason": exit_reason})

        if closed:
            logger.info(f"Exit check: closed {len(closed)} positions")
        else:
            logger.info(f"Exit check: {len(positions)} positions OK")

        return closed

    def _close_and_record(self, position, trade: dict, exit_reason: str) -> None:
        """Close a position and record the outcome.

        Note: P&L is recorded from unrealized_pl before the close order fills.
        Actual fill price may differ slightly due to slippage on market orders.
        """
        symbol = position.symbol
        entry_price = float(position.avg_entry_price)
        current_price = float(position.current_price)
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
            "strategy": trade.get("strategy", "quiver_composite") if trade else "quiver_composite",
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

    def execute_rebalance(self, actions: list) -> list:
        """Execute rebalancing trades."""
        if not self.alpaca.is_market_open():
            logger.warning("Market closed. Skipping rebalance.")
            return []

        working_capital = self.risk.get_working_capital()
        invested = self.risk.get_invested_amount()
        executed = []

        for action in actions:
            symbol = action["symbol"]
            target_weight = action["target_weight"]
            current_weight = action["current_weight"]

            # Calculate adjustment
            target_value = invested * target_weight
            current_value = invested * current_weight
            adjustment = target_value - current_value

            if abs(adjustment) < 10:  # Skip tiny adjustments
                continue

            side = "buy" if adjustment > 0 else "sell"
            notional = abs(adjustment)

            order = self.alpaca.submit_market_order(
                symbol=symbol, side=side, notional=notional
            )

            if order:
                trade_record = {
                    "account_id": ACCOUNT_ID,
                    "symbol": symbol,
                    "side": side,
                    "notional": round(notional, 2),
                    "order_type": "market",
                    "alpaca_order_id": str(order.id),
                    "status": str(order.status),
                    "strategy": "rebalance",
                    "reasoning": f"Rebalance: drift={action['drift']:.2%}",
                }
                self.db.insert_trade(trade_record)
                executed.append(trade_record)

        logger.info(f"Rebalance: executed {len(executed)}/{len(actions)} adjustments")
        return executed
