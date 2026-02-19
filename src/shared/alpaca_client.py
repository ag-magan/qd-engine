import logging
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockSnapshotRequest,
    StockLatestQuoteRequest,
    MostActivesRequest,
    MarketMoversRequest,
)
from alpaca.data.historical.screener import ScreenerClient
from alpaca.data.timeframe import TimeFrame

from src.shared.config import ALPACA_ACCOUNTS, TRADING_MODE

logger = logging.getLogger(__name__)


def get_trading_client(account_id: str) -> TradingClient:
    """Create a TradingClient for the specified account."""
    creds = ALPACA_ACCOUNTS[account_id]
    is_paper = TRADING_MODE == "paper"
    return TradingClient(
        api_key=creds["key"],
        secret_key=creds["secret"],
        paper=is_paper,
    )


def get_data_client(account_id: str) -> StockHistoricalDataClient:
    """Create a StockHistoricalDataClient for market data."""
    creds = ALPACA_ACCOUNTS[account_id]
    return StockHistoricalDataClient(
        api_key=creds["key"],
        secret_key=creds["secret"],
    )


def get_screener_client(account_id: str) -> ScreenerClient:
    """Create a ScreenerClient for market movers data."""
    creds = ALPACA_ACCOUNTS[account_id]
    return ScreenerClient(
        api_key=creds["key"],
        secret_key=creds["secret"],
    )


class AlpacaClient:
    """Unified Alpaca client for a specific account."""

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.trading = get_trading_client(account_id)
        self.data = get_data_client(account_id)
        self._screener = None  # lazy init

    def get_account(self):
        """Get account information."""
        return self.trading.get_account()

    def get_positions(self) -> list:
        """Get all open positions."""
        try:
            return self.trading.get_all_positions()
        except Exception as e:
            logger.error(f"Failed to get positions for {self.account_id}: {e}")
            return []

    def get_position(self, symbol: str):
        """Get position for a specific symbol."""
        try:
            return self.trading.get_open_position(symbol)
        except Exception:
            return None

    def is_market_open(self) -> bool:
        """Check if the market is currently open."""
        try:
            clock = self.trading.get_clock()
            return clock.is_open
        except Exception as e:
            logger.error(f"Failed to check market clock: {e}")
            return False

    def get_clock(self):
        """Get market clock."""
        return self.trading.get_clock()

    def get_order(self, order_id: str):
        """Get order details by ID (for fill price/status sync)."""
        try:
            return self.trading.get_order_by_id(order_id)
        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return None

    def submit_market_order(
        self,
        symbol: str,
        side: str,
        notional: float = None,
        qty: float = None,
    ) -> Optional[object]:
        """Submit a market order by notional amount or quantity."""
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

            # Alpaca doesn't support notional short sells — convert to qty
            if notional is not None and side.lower() == "sell":
                try:
                    quotes = self.get_latest_quotes([symbol])
                    price = float(quotes[symbol].ask_price or quotes[symbol].bid_price)
                    qty = int(notional / price)
                    if qty < 1:
                        logger.warning(f"Short sell qty < 1 for {symbol} (${notional}/{price}), skipping")
                        return None
                    logger.info(f"Converted ${notional:.0f} to {qty} shares for short sell {symbol} @ ${price:.2f}")
                    notional = None
                except Exception as e:
                    logger.error(f"Cannot convert notional to qty for short {symbol}: {e}")
                    return None

            params = {
                "symbol": symbol,
                "side": order_side,
                "time_in_force": TimeInForce.DAY,
            }
            if notional is not None:
                params["notional"] = round(notional, 2)
            elif qty is not None:
                params["qty"] = qty
            else:
                logger.error("Must specify either notional or qty")
                return None

            order = MarketOrderRequest(**params)
            result = self.trading.submit_order(order_data=order)
            logger.info(
                f"Order submitted: {side} {symbol} "
                f"{'$' + str(notional) if notional else str(qty) + ' shares'} "
                f"order_id={result.id}"
            )
            return result
        except Exception as e:
            logger.error(f"Failed to submit order {side} {symbol}: {e}")
            return None

    def submit_limit_order(
        self,
        symbol: str,
        side: str,
        limit_price: float,
        notional: float = None,
        qty: float = None,
    ) -> Optional[object]:
        """Submit a limit order."""
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            params = {
                "symbol": symbol,
                "side": order_side,
                "time_in_force": TimeInForce.DAY,
                "limit_price": round(limit_price, 2),
            }
            if notional is not None:
                params["notional"] = round(notional, 2)
            elif qty is not None:
                params["qty"] = qty
            else:
                logger.error("Must specify either notional or qty")
                return None

            order = LimitOrderRequest(**params)
            result = self.trading.submit_order(order_data=order)
            logger.info(f"Limit order submitted: {side} {symbol} @ {limit_price}")
            return result
        except Exception as e:
            logger.error(f"Failed to submit limit order {side} {symbol}: {e}")
            return None

    def close_position(self, symbol: str) -> Optional[object]:
        """Close an entire position."""
        try:
            result = self.trading.close_position(symbol)
            logger.info(f"Closed position: {symbol}")
            return result
        except Exception as e:
            logger.error(f"Failed to close position {symbol}: {e}")
            return None

    def close_all_positions(self) -> bool:
        """Close all positions (used for EOD day trading)."""
        try:
            self.trading.close_all_positions(cancel_orders=True)
            logger.info(f"Closed all positions for {self.account_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to close all positions: {e}")
            return False

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        try:
            self.trading.cancel_orders()
            logger.info(f"Cancelled all orders for {self.account_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return False

    def get_bars(self, symbols: list, timeframe: TimeFrame,
                 start: str = None, end: str = None, limit: int = 100):
        """Get historical bars for given symbols."""
        try:
            params = {
                "symbol_or_symbols": symbols,
                "timeframe": timeframe,
            }
            if start:
                params["start"] = start
            if end:
                params["end"] = end
            if limit:
                params["limit"] = limit
            request = StockBarsRequest(**params)
            return self.data.get_stock_bars(request)
        except Exception as e:
            logger.error(f"Failed to get bars: {e}")
            return None

    def get_snapshots(self, symbols: list):
        """Get latest snapshots for symbols."""
        try:
            request = StockSnapshotRequest(symbol_or_symbols=symbols)
            return self.data.get_stock_snapshot(request)
        except Exception as e:
            logger.error(f"Failed to get snapshots: {e}")
            return None

    def get_latest_quotes(self, symbols: list):
        """Get latest quotes for symbols."""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
            return self.data.get_stock_latest_quote(request)
        except Exception as e:
            logger.error(f"Failed to get latest quotes: {e}")
            return None

    def get_screener_movers(self, top: int = 20) -> dict:
        """Get most active stocks and top gainers/losers from Alpaca Screener.

        Returns dict with keys 'most_actives', 'gainers', 'losers',
        each a list of symbol strings.
        """
        try:
            if self._screener is None:
                self._screener = get_screener_client(self.account_id)

            result = {"most_actives": [], "gainers": [], "losers": []}

            actives = self._screener.get_most_actives(
                MostActivesRequest(top=top)
            )
            if actives and actives.most_actives:
                result["most_actives"] = [s.symbol for s in actives.most_actives]

            movers = self._screener.get_market_movers(
                MarketMoversRequest(top=top)
            )
            if movers:
                result["gainers"] = [m.symbol for m in (movers.gainers or [])]
                result["losers"] = [m.symbol for m in (movers.losers or [])]

            return result
        except Exception as e:
            logger.warning(f"Screener API failed (non-fatal): {e}")
            return {"most_actives": [], "gainers": [], "losers": []}

    def get_invested_value(self) -> float:
        """Calculate total market value of current positions."""
        positions = self.get_positions()
        total = 0.0
        for pos in positions:
            total += abs(float(pos.market_value))
        return total

    def get_position_count(self) -> int:
        """Get number of open positions."""
        return len(self.get_positions())
