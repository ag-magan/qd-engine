import logging
import re
from datetime import datetime, timedelta

import numpy as np
import requests

import pytz

from src.shared.alpaca_client import AlpacaClient
from src.account2_daytrader.config import ACCOUNT_ID, SCANNER, STRATEGIES
from src.account2_daytrader.universe import SCAN_UNIVERSE

ET = pytz.timezone("US/Eastern")
from alpaca.data.timeframe import TimeFrame
from alpaca.data.requests import (
    StockBarsRequest,
    StockSnapshotRequest,
)

logger = logging.getLogger(__name__)


class Scanner:
    """Pre-market and intraday stock scanner using Alpaca market data."""

    def __init__(self):
        self.alpaca = AlpacaClient(ACCOUNT_ID)

    def _fetch_dynamic_movers(self) -> list:
        """Fetch dynamic pre-market movers from Alpaca screener + Yahoo Finance.

        Returns a list of ticker symbols. Failures are non-fatal —
        falls back to static universe only.
        """
        movers = set()

        # Source 1: Alpaca Screener — most actives + market movers
        try:
            data = self.alpaca.get_screener_movers(top=20)
            for key in ("most_actives", "gainers", "losers"):
                for sym in data.get(key, []):
                    movers.add(sym)
            logger.info(f"Alpaca screener returned {len(movers)} movers")
        except Exception as e:
            logger.warning(f"Alpaca screener failed (non-fatal): {e}")

        # Source 2: Yahoo Finance gainers (public JSON endpoint, no auth)
        yahoo_count = 0
        try:
            resp = requests.get(
                "https://finance.yahoo.com/markets/stocks/gainers/",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if resp.status_code == 200:
                # Extract ticker symbols from the page content
                symbols_found = re.findall(
                    r'/quote/([A-Z]{1,5})(?:/|\?|")', resp.text
                )
                for sym in set(symbols_found):
                    if sym not in ("USD", "US") and len(sym) <= 5:
                        movers.add(sym)
                        yahoo_count += 1
            logger.info(f"Yahoo Finance returned {yahoo_count} gainers")
        except Exception as e:
            logger.warning(f"Yahoo Finance scrape failed (non-fatal): {e}")

        logger.info(f"Dynamic movers total: {len(movers)} unique symbols")
        return list(movers)

    def premarket_scan(self) -> list:
        """Scan for stocks with significant pre-market gaps and volume."""
        logger.info("Running pre-market scan...")

        # Merge static universe with dynamic movers
        dynamic = self._fetch_dynamic_movers()
        combined = list(dict.fromkeys(SCAN_UNIVERSE + dynamic))  # dedup, preserve order
        logger.info(
            f"Scan universe: {len(SCAN_UNIVERSE)} static + "
            f"{len(dynamic)} dynamic = {len(combined)} unique symbols"
        )

        candidates = []

        # Get snapshots in batches
        batch_size = 20
        for i in range(0, len(combined), batch_size):
            batch = combined[i:i + batch_size]
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
        symbols = watchlist or SCAN_UNIVERSE[:50]
        candidates = []

        batch_size = 10
        bars_found = 0
        snaps_found = 0
        too_few_bars = 0
        setups_detected = {}

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            try:
                bars_data = self.alpaca.get_bars(
                    batch, TimeFrame.Minute, limit=200
                )
                if not bars_data:
                    logger.warning(f"No bars data for batch starting {batch[0]}")
                    continue

                snapshots = self.alpaca.get_snapshots(batch)

                for symbol in batch:
                    try:
                        symbol_bars = bars_data.get(symbol) if bars_data else None
                        snap = snapshots.get(symbol) if snapshots else None

                        if symbol_bars:
                            bars_found += 1
                        if snap:
                            snaps_found += 1

                        if not symbol_bars or not snap:
                            continue

                        bar_count = len(symbol_bars)
                        if bar_count < 20:
                            too_few_bars += 1
                            continue

                        setup = self._detect_intraday_setup(symbol, symbol_bars, snap)
                        if setup:
                            candidates.append(setup)
                            for s in setup.get("setups", []):
                                setups_detected[s] = setups_detected.get(s, 0) + 1
                    except Exception as e:
                        logger.info(f"Intraday eval failed for {symbol}: {e}")

            except Exception as e:
                logger.error(f"Intraday scan batch failed: {e}")

        if not candidates:
            logger.info(
                f"Scan diagnostics: {len(symbols)} symbols, "
                f"bars_found={bars_found}, snaps_found={snaps_found}, "
                f"too_few_bars={too_few_bars}"
            )

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

        # Calculate VWAP using today's session bars only
        today_open = datetime.now(ET).replace(hour=9, minute=30, second=0, microsecond=0)
        today_idx = []
        for idx, b in enumerate(bars):
            try:
                bar_time = b.timestamp
                if hasattr(bar_time, 'astimezone'):
                    bar_et = bar_time.astimezone(ET)
                else:
                    bar_et = datetime.fromisoformat(str(bar_time)).astimezone(ET)
                if bar_et >= today_open:
                    today_idx.append(idx)
            except Exception:
                pass

        if len(today_idx) >= 5:
            v_highs = [highs[i] for i in today_idx]
            v_lows = [lows[i] for i in today_idx]
            v_closes = [closes[i] for i in today_idx]
            v_volumes = [volumes[i] for i in today_idx]
        else:
            v_highs, v_lows, v_closes, v_volumes = highs, lows, closes, volumes

        typical_prices = [(h + l + c) / 3 for h, l, c in zip(v_highs, v_lows, v_closes)]
        cum_tp_vol = sum(tp * v for tp, v in zip(typical_prices, v_volumes))
        cum_vol = sum(v_volumes)
        vwap = cum_tp_vol / cum_vol if cum_vol > 0 else current_price

        # Calculate RSI
        rsi = self._calculate_rsi(closes)

        # Detect setups
        setups = []

        # Momentum: price near recent high/low with above-average volume
        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])
        if current_price > recent_high * 0.99 and current_volume > avg_volume * 1.5:
            setups.append("momentum")
        elif current_price < recent_low * 1.01 and current_volume > avg_volume * 1.5:
            setups.append("momentum_short")

        # Mean reversion: RSI oversold/overbought with volume confirmation
        mr_config = STRATEGIES.get("mean_reversion", {})
        if rsi < mr_config.get("rsi_oversold", 30) and current_volume > avg_volume * 1.2:
            setups.append("mean_reversion")
        elif rsi > mr_config.get("rsi_overbought", 70) and current_volume > avg_volume * 1.2:
            setups.append("mean_reversion_short")

        # VWAP bounce/rejection: price near VWAP
        vwap_dist = abs(current_price - vwap) / vwap * 100
        if vwap_dist < 1.0 and current_price > vwap:
            setups.append("vwap_bounce")
        elif vwap_dist < 1.0 and current_price < vwap:
            setups.append("vwap_rejection")

        # Gap fill opportunity
        prev_close = float(snapshot.previous_daily_bar.close) if snapshot.previous_daily_bar else None
        if prev_close:
            gap_pct = ((current_price - prev_close) / prev_close) * 100
            if abs(gap_pct) > 1.5:
                setups.append("gap_fill")

        # Trending: price following short MA vs longer MA
        sma_10 = np.mean(closes[-10:])
        sma_20 = np.mean(closes[-20:])
        if current_price > sma_10 > sma_20 and current_volume >= avg_volume:
            setups.append("trending")
        elif current_price < sma_10 < sma_20 and current_volume >= avg_volume:
            setups.append("trending_short")

        if not setups:
            return None

        logger.info(
            f"Setup detected {symbol}: price={current_price:.2f} RSI={rsi:.1f} "
            f"vol_ratio={current_volume / avg_volume:.1f}x "
            f"vwap_dist={vwap_dist:.2f}% setups={setups}"
        )

        return {
            "symbol": symbol,
            "current_price": current_price,
            "vwap": round(vwap, 2),
            "rsi": round(rsi, 1),
            "volume_ratio": round(current_volume / avg_volume, 2) if avg_volume > 0 else 0,
            "sma_10": round(sma_10, 2),
            "sma_20": round(sma_20, 2),
            "setups": setups,
            "prev_close": prev_close,
        }

    @staticmethod
    def _calculate_rsi(closes: list, period: int = 14) -> float:
        """Calculate RSI using Wilder's smoothing."""
        if len(closes) < period + 1:
            return 50.0  # Default neutral

        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        # Wilder's smoothing: seed with simple mean, then exponential
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
