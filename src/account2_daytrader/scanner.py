import logging
from datetime import datetime, timedelta

import numpy as np

from src.shared.alpaca_client import AlpacaClient
from src.account2_daytrader.config import ACCOUNT_ID, SCANNER
from alpaca.data.timeframe import TimeFrame
from alpaca.data.requests import (
    StockBarsRequest,
    StockSnapshotRequest,
)

logger = logging.getLogger(__name__)

# Universe of liquid stocks to scan
SCAN_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "NFLX",
    "BABA", "DIS", "BA", "NIO", "PLTR", "SOFI", "RIVN", "LCID", "COIN",
    "SNAP", "SQ", "SHOP", "ROKU", "UBER", "LYFT", "DKNG", "HOOD", "MARA",
    "RIOT", "INTC", "MU", "QCOM", "AVGO", "CRM", "ORCL", "PYPL", "V",
    "JPM", "BAC", "GS", "WFC", "XOM", "CVX", "PFE", "MRNA", "JNJ",
    "UNH", "LLY", "ABBV", "BMY", "COST", "WMT", "HD", "LOW", "TGT",
    "F", "GM", "AAL", "DAL", "UAL", "CCL", "RCL", "ABNB", "MAR",
    "SPY", "QQQ", "IWM", "DIA", "ARKK",
]


class Scanner:
    """Pre-market and intraday stock scanner using Alpaca market data."""

    def __init__(self):
        self.alpaca = AlpacaClient(ACCOUNT_ID)

    def premarket_scan(self) -> list:
        """Scan for stocks with significant pre-market gaps and volume."""
        logger.info("Running pre-market scan...")
        candidates = []

        # Get snapshots in batches
        batch_size = 20
        for i in range(0, len(SCAN_UNIVERSE), batch_size):
            batch = SCAN_UNIVERSE[i:i + batch_size]
            try:
                snapshots = self.alpaca.get_snapshots(batch)
                if not snapshots:
                    continue

                for symbol, snap in snapshots.items():
                    try:
                        candidate = self._evaluate_premarket(symbol, snap)
                        if candidate:
                            candidates.append(candidate)
                    except Exception as e:
                        logger.debug(f"Failed to evaluate {symbol}: {e}")

            except Exception as e:
                logger.error(f"Failed to get snapshots for batch: {e}")

        candidates.sort(key=lambda x: abs(x.get("gap_pct", 0)), reverse=True)
        logger.info(f"Pre-market scan found {len(candidates)} candidates")
        return candidates

    def _evaluate_premarket(self, symbol: str, snapshot) -> dict:
        """Evaluate a stock from its snapshot data."""
        try:
            if not snapshot.latest_trade or not snapshot.previous_daily_bar:
                return None

            current_price = float(snapshot.latest_trade.price)
            prev_close = float(snapshot.previous_daily_bar.close)

            if current_price < SCANNER["min_price"] or current_price > SCANNER["max_price"]:
                return None

            gap_pct = ((current_price - prev_close) / prev_close) * 100

            # Check volume
            if snapshot.minute_bar and snapshot.previous_daily_bar:
                # Compare current volume pace to average
                current_vol = float(snapshot.daily_bar.volume) if snapshot.daily_bar else 0
                prev_vol = float(snapshot.previous_daily_bar.volume)
                vol_ratio = current_vol / prev_vol if prev_vol > 0 else 0
            else:
                vol_ratio = 1.0

            if abs(gap_pct) < SCANNER["min_gap_pct"] and vol_ratio < SCANNER["min_volume_multiplier"]:
                return None

            return {
                "symbol": symbol,
                "current_price": current_price,
                "prev_close": prev_close,
                "gap_pct": round(gap_pct, 2),
                "volume_ratio": round(vol_ratio, 2),
                "has_gap": abs(gap_pct) >= SCANNER["min_gap_pct"],
                "has_volume": vol_ratio >= SCANNER["min_volume_multiplier"],
            }
        except Exception as e:
            logger.debug(f"Error evaluating {symbol}: {e}")
            return None

    def intraday_scan(self, watchlist: list = None) -> list:
        """Scan for intraday setups on watchlist or full universe."""
        symbols = watchlist or SCAN_UNIVERSE[:30]  # Limit to top 30 for speed
        candidates = []

        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            try:
                bars_data = self.alpaca.get_bars(
                    batch, TimeFrame.Minute, limit=100
                )
                if not bars_data:
                    continue

                snapshots = self.alpaca.get_snapshots(batch)

                for symbol in batch:
                    try:
                        symbol_bars = bars_data.get(symbol) if bars_data else None
                        snap = snapshots.get(symbol) if snapshots else None
                        if symbol_bars and snap:
                            setup = self._detect_intraday_setup(symbol, symbol_bars, snap)
                            if setup:
                                candidates.append(setup)
                    except Exception as e:
                        logger.debug(f"Intraday eval failed for {symbol}: {e}")

            except Exception as e:
                logger.error(f"Intraday scan batch failed: {e}")

        logger.info(f"Intraday scan found {len(candidates)} setups")
        return candidates

    def _detect_intraday_setup(self, symbol: str, bars, snapshot) -> dict:
        """Detect potential intraday trading setups."""
        if not bars or len(bars) < 20:
            return None

        closes = [float(b.close) for b in bars]
        volumes = [float(b.volume) for b in bars]
        highs = [float(b.high) for b in bars]
        lows = [float(b.low) for b in bars]

        current_price = closes[-1]
        current_volume = volumes[-1]
        avg_volume = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)

        # Calculate VWAP
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        cum_tp_vol = sum(tp * v for tp, v in zip(typical_prices, volumes))
        cum_vol = sum(volumes)
        vwap = cum_tp_vol / cum_vol if cum_vol > 0 else current_price

        # Calculate RSI
        rsi = self._calculate_rsi(closes)

        # Detect setups
        setups = []

        # Momentum: price breaking recent high with volume
        recent_high = max(highs[-20:])
        if current_price > recent_high * 0.998 and current_volume > avg_volume * 2:
            setups.append("momentum")

        # Mean reversion: RSI oversold with volume spike
        if rsi < 30 and current_volume > avg_volume * 1.5:
            setups.append("mean_reversion")

        # VWAP bounce: price near VWAP
        vwap_dist = abs(current_price - vwap) / vwap * 100
        if vwap_dist < 0.3 and current_price > vwap:
            setups.append("vwap_bounce")

        # Gap fill opportunity
        prev_close = float(snapshot.previous_daily_bar.close) if snapshot.previous_daily_bar else None
        if prev_close:
            gap_pct = ((current_price - prev_close) / prev_close) * 100
            if abs(gap_pct) > 3.0:
                setups.append("gap_fill")

        if not setups:
            return None

        return {
            "symbol": symbol,
            "current_price": current_price,
            "vwap": round(vwap, 2),
            "rsi": round(rsi, 1),
            "volume_ratio": round(current_volume / avg_volume, 2) if avg_volume > 0 else 0,
            "setups": setups,
            "prev_close": prev_close,
        }

    @staticmethod
    def _calculate_rsi(closes: list, period: int = 14) -> float:
        """Calculate RSI from closing prices."""
        if len(closes) < period + 1:
            return 50.0  # Default neutral

        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
