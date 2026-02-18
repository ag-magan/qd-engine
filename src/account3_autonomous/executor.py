import json
import logging
from datetime import datetime, timedelta, timezone

from src.shared.alpaca_client import AlpacaClient
from src.shared.risk_manager import RiskManager
from src.shared.database import Database
from src.account3_autonomous.config import ACCOUNT_ID
from src.account3_autonomous.thesis_tracker import ThesisTracker

logger = logging.getLogger(__name__)

QUEUE_MAX_AGE_HOURS = 48


class AutonomousExecutor:
    """Execute Claude's autonomous trading decisions."""

    def __init__(self):
        self.alpaca = AlpacaClient(ACCOUNT_ID)
        self.risk = RiskManager(ACCOUNT_ID)
        self.db = Database()
        self.thesis_tracker = ThesisTracker()

    def execute_decisions(self, decisions: dict) -> dict:
        """Execute new positions and position reviews from Claude's decisions.

        If the market is closed, queues new positions for execution
        at the next market open. Position reviews (closes) are skipped
        since they require live positions.
        """
        results = {
            "opened": [],
            "closed": [],
            "held": [],
            "errors": [],
        }

        # Store learnings regardless of market status
        for lesson in decisions.get("lessons_learned", []):
            self.db.insert_learning({
                "account_id": ACCOUNT_ID,
                "learning_type": "self_reflection",
                "category": "daily_decision",
                "insight": lesson,
            })

        if not self.alpaca.is_market_open():
            # Queue new positions for later execution
            new_positions = decisions.get("new_positions", [])
            if new_positions:
                queued = self._queue_positions(new_positions)
                logger.info(
                    f"Market closed. Queued {len(queued)} positions for next open."
                )
            else:
                logger.info("Market closed. No new positions to queue.")

            # Position reviews require live market — skip them
            reviews = decisions.get("position_reviews", [])
            if reviews:
                logger.info(
                    f"Market closed. Skipping {len(reviews)} position reviews."
                )

            return results

        # Execute new positions
        for position in decisions.get("new_positions", []):
            try:
                result = self._open_position(position)
                if result:
                    results["opened"].append(result)
            except Exception as e:
                logger.error(f"Failed to open {position['symbol']}: {e}")
                results["errors"].append({"symbol": position["symbol"], "error": str(e)})

        # Execute position reviews
        for review in decisions.get("position_reviews", []):
            try:
                if review["action"] == "close":
                    result = self._close_position(review)
                    if result:
                        results["closed"].append(result)
                elif review["action"] == "add":
                    logger.warning(
                        f"'add' action requested for {review['symbol']} "
                        f"but position scaling not yet supported. Treating as hold."
                    )
                    results["held"].append(review["symbol"])
                else:
                    if review["action"] != "hold":
                        logger.warning(
                            f"Unrecognized action '{review['action']}' for "
                            f"{review['symbol']}, treating as hold."
                        )
                    results["held"].append(review["symbol"])
            except Exception as e:
                logger.error(f"Failed to process review for {review['symbol']}: {e}")
                results["errors"].append({"symbol": review["symbol"], "error": str(e)})

        logger.info(
            f"Execution results: opened={len(results['opened'])}, "
            f"closed={len(results['closed'])}, held={len(results['held'])}"
        )
        return results

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
            position = order_row.get("signal_data", {})
            position["symbol"] = order_row["symbol"]
            position["confidence"] = order_row.get("confidence", 50)
            position["position_size_pct"] = float(order_row.get("position_size_pct", 0.5))
            position["side"] = order_row["direction"]
            position["thesis"] = order_row.get("reasoning", "")

            result = self._open_position(position)
            if result:
                self._mark_order_executed(order_row["id"])
                executed.append(result)
            else:
                self._mark_order_executed(order_row["id"], status="failed")

        logger.info(f"Executed {len(executed)}/{len(pending)} queued orders")
        return executed

    def _queue_positions(self, positions: list) -> list:
        """Save new position decisions to pending_orders for later execution."""
        queued = []
        for position in positions:
            symbol = position.get("symbol", "")
            side = position.get("side", "buy")

            row = {
                "account_id": ACCOUNT_ID,
                "symbol": symbol,
                "direction": side,
                "confidence": position.get("confidence", 50),
                "position_size_pct": position.get("position_size_pct", 0.5),
                "composite_score": position.get("confidence", 50),
                "sources": ["autonomous"],
                "signal_data": json.loads(json.dumps(position, default=str)),
                "reasoning": position.get("thesis", ""),
            }

            try:
                resp = self.db.client.table("pending_orders").insert(row).execute()
                queued.append(resp.data[0] if resp.data else row)
                logger.info(f"Queued {side} {symbol} (confidence={row['confidence']})")
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

    def _open_position(self, position: dict) -> dict:
        """Open a new position based on Claude's decision."""
        symbol = position["symbol"]
        confidence = position.get("confidence", 0)
        size_pct = position.get("position_size_pct", 0.5)

        # Check max trades per day
        can_trade, count = self.risk.check_max_trades_per_day()
        if not can_trade:
            logger.info(f"Max daily trades reached ({count}). Skipping {symbol}.")
            return None

        # Calculate position size (use Claude's size_pct as sole scaler)
        max_position = self.risk.calculate_position_size(symbol, confidence=100)
        position_size = max_position * size_pct

        if position_size < 1.0:
            logger.info(f"Position too small for {symbol}: ${position_size:.2f}")
            return None

        # Risk check
        can_open, reason = self.risk.can_open_position(symbol, position_size)
        if not can_open:
            logger.info(f"Cannot open {symbol}: {reason}")
            return None

        # Submit order
        side = position.get("side", "buy")
        order = self.alpaca.submit_market_order(
            symbol=symbol, side=side, notional=position_size
        )

        if not order:
            return None

        # Record trade
        trade_record = {
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "side": side,
            "notional": round(position_size, 2),
            "order_type": "market",
            "alpaca_order_id": str(order.id),
            "status": str(order.status),
            "strategy": "autonomous",
            "reasoning": position.get("thesis", ""),
        }
        db_trade = self.db.insert_trade(trade_record)

        # Record thesis
        if db_trade:
            self.thesis_tracker.record_thesis(
                trade_id=db_trade["id"],
                symbol=symbol,
                thesis=position.get("thesis", ""),
                target_price=position.get("target_price", 0),
                stop_loss=position.get("stop_loss", 0),
                invalidation=position.get("invalidation", ""),
                time_horizon_days=position.get("time_horizon_days", 7),
                confidence=confidence,
            )

        logger.info(
            f"Opened {side} {symbol}: ${position_size:.2f} "
            f"(confidence={confidence})"
        )

        return {
            "symbol": symbol,
            "side": side,
            "notional": position_size,
            "confidence": confidence,
        }

    def _close_position(self, review: dict) -> dict:
        """Close an existing position.

        Note: P&L is recorded from unrealized_pl before the close order fills.
        Actual fill price may differ slightly due to slippage on market orders.
        """
        symbol = review["symbol"]

        # Get current position info before closing
        position = self.alpaca.get_position(symbol)
        if not position:
            logger.info(f"No position found for {symbol}")
            return None

        entry_price = float(position.avg_entry_price)
        exit_price = float(position.current_price)
        realized_pnl = float(position.unrealized_pl)
        pnl_pct = float(position.unrealized_plpc) * 100

        # Close position
        result = self.alpaca.close_position(symbol)
        if not result:
            return None

        # Find the trade record
        trades = self.db.get_open_trades(ACCOUNT_ID)
        trade = next((t for t in trades if t["symbol"] == symbol), None)

        # Update trade status
        if trade:
            self.db.update_trade(trade["id"], {
                "status": "closed",
                "fill_price": exit_price,
                "filled_at": datetime.now(timezone.utc).isoformat(),
            })

        # Record outcome
        self.db.insert_trade_outcome({
            "trade_id": trade["id"] if trade else None,
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "strategy": "autonomous",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_date": trade.get("created_at") if trade else None,
            "exit_date": datetime.now(timezone.utc).isoformat(),
            "realized_pnl": round(realized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "outcome": "win" if realized_pnl > 0 else "loss",
            "exit_reason": review.get("reasoning", "autonomous_decision"),
        })

        logger.info(
            f"Closed {symbol}: P&L=${realized_pnl:.2f} ({pnl_pct:.2f}%)"
        )

        return {
            "symbol": symbol,
            "pnl": realized_pnl,
            "reason": review.get("reasoning", ""),
        }

    def check_thesis_exits(self) -> list:
        """Mechanical enforcement of thesis stop/target prices.

        No Claude calls. Checks current price against the stop_loss and
        target_price stored in the theses table at entry time.
        Also checks time_horizon_days for stale positions.
        """
        if not self.alpaca.is_market_open():
            return []

        positions = self.alpaca.get_positions()
        open_theses = self.db.get_open_theses(ACCOUNT_ID)
        thesis_map = {t["symbol"]: t for t in open_theses}
        open_trades = self.db.get_open_trades(ACCOUNT_ID)
        trade_map = {t["symbol"]: t for t in open_trades}
        closed = []

        for pos in positions:
            symbol = pos.symbol
            current_price = float(pos.current_price)
            thesis = thesis_map.get(symbol)

            if not thesis:
                continue

            stop_price = float(thesis.get("stop_loss") or 0)
            target_price = float(thesis.get("target_price") or 0)
            horizon_days = thesis.get("time_horizon_days")

            # Determine trade direction for correct stop/target comparison
            trade = trade_map.get(symbol)
            side = trade.get("side", "buy") if trade else "buy"

            exit_reason = None

            if side == "buy":  # Long position
                if stop_price > 0 and current_price <= stop_price:
                    exit_reason = "guardian_stop_loss"
                elif target_price > 0 and current_price >= target_price:
                    exit_reason = "guardian_target_hit"
            else:  # Short position
                if stop_price > 0 and current_price >= stop_price:
                    exit_reason = "guardian_stop_loss"
                elif target_price > 0 and current_price <= target_price:
                    exit_reason = "guardian_target_hit"

            # Check time horizon (independent of stop/target)
            if not exit_reason and horizon_days:
                entry_date = thesis.get("entry_date")
                if entry_date:
                    entry_dt = datetime.fromisoformat(
                        str(entry_date).replace("Z", "+00:00")
                    )
                    days_held = (datetime.now(timezone.utc) - entry_dt).days
                    if days_held >= int(horizon_days):
                        exit_reason = "guardian_time_expired"

            if exit_reason:
                logger.info(
                    f"Guardian exit: {symbol} {exit_reason} "
                    f"(price={current_price}, stop={stop_price}, "
                    f"target={target_price})"
                )
                review = {
                    "symbol": symbol,
                    "action": "close",
                    "reasoning": (
                        f"Guardian auto-exit: {exit_reason} "
                        f"(price={current_price}, stop={stop_price}, "
                        f"target={target_price})"
                    ),
                }
                result = self._close_position(review)
                if result:
                    closed.append(result)

        if closed:
            logger.info(f"Guardian closed {len(closed)} positions")
        else:
            logger.info(f"Guardian check: {len(positions)} positions OK")

        return closed

    def execute_monitor_actions(self, monitor_result: dict) -> list:
        """Execute actions from midday position monitoring."""
        closed = []
        for update in monitor_result.get("position_updates", []):
            if update.get("action") == "close":
                result = self._close_position(update)
                if result:
                    closed.append(result)

        return closed
