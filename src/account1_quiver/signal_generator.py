import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.shared.database import Database
from src.account1_quiver.config import ACCOUNT_ID, SIGNAL_MAX_AGE_HOURS, SIGNAL_SOURCES
from src.account1_quiver.quiver_client import QuiverClient

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Generate trading signals from QuiverQuant data sources."""

    def __init__(self):
        self.quiver = QuiverClient()
        self.db = Database()

    def generate_all_signals(self) -> list:
        """Pull data from all enabled sources and generate signals.

        Pre-fetches existing signal keys per source in one DB call each,
        then uses local set lookups for dedup instead of per-signal API calls.
        """
        all_signals = []

        source_methods = {
            "house_trading": self._process_house_trading,
            "senate_trading": self._process_senate_trading,
            "insider": self._process_insiders,
            "gov_contracts": self._process_gov_contracts,
            "gov_contracts_all": self._process_gov_contracts_all,
            "lobbying": self._process_lobbying,
            "off_exchange": self._process_off_exchange,
            "flights": self._process_flights,
            "wikipedia": self._process_wikipedia,
            "wsb": self._process_wsb,
        }

        for source_name, config in SIGNAL_SOURCES.items():
            if not config["enabled"]:
                continue

            processor = source_methods.get(source_name)
            if not processor:
                continue

            try:
                # Pre-fetch existing signals for this source (1 DB call)
                existing = self.db.get_existing_signal_keys(ACCOUNT_ID, source_name, since_hours=SIGNAL_MAX_AGE_HOURS)
                # gov_contracts_all also dedupes against gov_contracts
                if source_name == "gov_contracts_all":
                    existing |= self.db.get_existing_signal_keys(ACCOUNT_ID, "gov_contracts", since_hours=SIGNAL_MAX_AGE_HOURS)

                signals = processor(existing_keys=existing)
                if signals:
                    all_signals.extend(signals)
                    logger.info(f"Generated {len(signals)} signals from {source_name}")
                else:
                    logger.info(f"No signals from {source_name}")
            except Exception as e:
                logger.error(f"Failed to process {source_name}: {e}")

        return all_signals

    def _process_house_trading(self, existing_keys: set = None) -> list:
        """Process House representative trading data into signals."""
        data = self.quiver.get_house_trades()
        if not data:
            return []
        return self._process_congressional_trades(data, "house_trading", "house_trade", existing_keys or set())

    def _process_senate_trading(self, existing_keys: set = None) -> list:
        """Process Senate trading data into signals."""
        data = self.quiver.get_senate_trades()
        if not data:
            return []
        return self._process_congressional_trades(data, "senate_trading", "senate_trade", existing_keys or set())

    def _process_congressional_trades(self, data: list, source: str, signal_type: str,
                                      existing_keys: set = None) -> list:
        """Shared logic for House and Senate trade processing."""
        signals = []
        existing = existing_keys or set()
        config = SIGNAL_SOURCES[source]
        min_size = config.get("min_trade_size_usd", 15000)

        for trade in data:
            ticker = trade.get("Ticker") or trade.get("ticker")
            if not ticker or ticker == "--":
                continue

            # Determine trade size from Range field
            trade_size_str = trade.get("Trade_Size_USD") or trade.get("Range", "")
            trade_size = self._parse_trade_size(trade_size_str)

            if trade_size < min_size:
                continue

            transaction = (trade.get("Transaction") or trade.get("transaction", "")).lower()
            if "purchase" in transaction or "buy" in transaction:
                direction = "buy"
            elif "sale" in transaction or "sell" in transaction:
                direction = "sell"
            else:
                continue

            if (ticker.upper(), signal_type) in existing:
                continue

            strength = min(trade_size / 100000, 1.0)

            # Include representative/senator name for context
            official = (
                trade.get("Representative")
                or trade.get("Senator")
                or trade.get("representative")
                or trade.get("senator", "")
            )

            signal = {
                "account_id": ACCOUNT_ID,
                "source": source,
                "signal_type": signal_type,
                "symbol": ticker.upper(),
                "direction": direction,
                "strength": round(strength, 2),
                "signal_role": "primary",
                "raw_data": {**trade, "official": official},
            }
            signals.append(signal)

        return signals

    def _process_insiders(self, existing_keys: set = None) -> list:
        """Process insider trades, detecting clusters (2+ in 14 days)."""
        data = self.quiver.get_insider_trades()
        if not data:
            return []

        config = SIGNAL_SOURCES["insider"]
        window_days = config.get("cluster_window_days", 14)
        min_cluster = config.get("min_cluster_size", 2)

        # Group by ticker
        ticker_trades = defaultdict(list)
        for trade in data:
            ticker = trade.get("Ticker") or trade.get("ticker")
            if not ticker:
                continue
            ticker_trades[ticker.upper()].append(trade)

        signals = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        for ticker, trades in ticker_trades.items():
            # Filter recent buys
            recent_buys = []
            for t in trades:
                trans = (t.get("Transaction") or t.get("transaction_type", "")).lower()
                if "purchase" in trans or "buy" in trans:
                    trade_date_str = t.get("Date") or t.get("date", "")
                    try:
                        trade_date = datetime.strptime(trade_date_str[:10], "%Y-%m-%d")
                        trade_date = trade_date.replace(tzinfo=timezone.utc)
                        if trade_date >= cutoff:
                            recent_buys.append(t)
                    except (ValueError, TypeError):
                        recent_buys.append(t)  # Include if date can't be parsed

            if len(recent_buys) >= min_cluster:
                if (ticker, "insider_cluster") in (existing_keys or set()):
                    continue

                strength = min(len(recent_buys) / 5.0, 1.0)
                signal = {
                    "account_id": ACCOUNT_ID,
                    "source": "insider",
                    "signal_type": "insider_cluster",
                    "symbol": ticker,
                    "direction": "buy",
                    "strength": round(strength, 2),
                    "signal_role": "primary",
                    "raw_data": {"cluster_size": len(recent_buys), "trades": recent_buys[:5]},
                }
                signals.append(signal)

        return signals

    def _process_gov_contracts(self, existing_keys: set = None) -> list:
        """Process government contract awards."""
        data = self.quiver.get_gov_contracts()
        if not data:
            return []

        existing = existing_keys or set()
        config = SIGNAL_SOURCES["gov_contracts"]
        min_value = config.get("min_contract_value", 10_000_000)
        signals = []

        for contract in data:
            ticker = contract.get("Ticker") or contract.get("ticker")
            if not ticker:
                continue

            amount = self._parse_number(
                contract.get("Amount") or contract.get("amount", 0)
            )
            if amount < min_value:
                continue

            if (ticker.upper(), "gov_contract") in existing:
                continue

            strength = min(amount / 100_000_000, 1.0)
            signal = {
                "account_id": ACCOUNT_ID,
                "source": "gov_contracts",
                "signal_type": "gov_contract",
                "symbol": ticker.upper(),
                "direction": "buy",
                "strength": round(strength, 2),
                "signal_role": "primary",
                "raw_data": contract,
            }
            signals.append(signal)

        return signals

    def _process_gov_contracts_all(self, existing_keys: set = None) -> list:
        """Process all announced government contracts (broader dataset)."""
        data = self.quiver.get_gov_contracts_all()
        if not data:
            return []

        existing = existing_keys or set()
        config = SIGNAL_SOURCES["gov_contracts_all"]
        min_value = config.get("min_contract_value", 10_000_000)
        signals = []

        for contract in data:
            ticker = contract.get("Ticker") or contract.get("ticker")
            if not ticker:
                continue

            amount = self._parse_number(
                contract.get("Amount") or contract.get("amount", 0)
            )
            if amount < min_value:
                continue

            # Dedup against both gov_contracts and gov_contracts_all
            # (existing_keys already includes gov_contracts keys from generate_all_signals)
            if (ticker.upper(), "gov_contract_all") in existing:
                continue
            if (ticker.upper(), "gov_contract") in existing:
                continue

            strength = min(amount / 100_000_000, 1.0)
            signal = {
                "account_id": ACCOUNT_ID,
                "source": "gov_contracts_all",
                "signal_type": "gov_contract_all",
                "symbol": ticker.upper(),
                "direction": "buy",
                "strength": round(strength, 2),
                "signal_role": "primary",
                "raw_data": contract,
            }
            signals.append(signal)

        return signals

    def _process_lobbying(self, existing_keys: set = None) -> list:
        """Process lobbying data, detecting spending increases."""
        data = self.quiver.get_lobbying()
        if not data:
            return []

        existing = existing_keys or set()
        config = SIGNAL_SOURCES["lobbying"]
        min_increase = config.get("min_spending_increase_pct", 50)
        signals = []

        # Group by ticker to detect spending changes
        ticker_spending = defaultdict(list)
        for entry in data:
            ticker = entry.get("Ticker") or entry.get("ticker")
            if not ticker:
                continue
            amount = self._parse_number(entry.get("Amount") or entry.get("amount", 0))
            ticker_spending[ticker.upper()].append({
                "amount": amount,
                "data": entry,
            })

        for ticker, entries in ticker_spending.items():
            if len(entries) < 2:
                continue

            # Sort by amount and check if latest is significantly higher
            entries.sort(key=lambda x: x["amount"])
            latest = entries[-1]["amount"]
            previous_avg = sum(e["amount"] for e in entries[:-1]) / (len(entries) - 1)

            if previous_avg > 0:
                increase_pct = ((latest - previous_avg) / previous_avg) * 100
                if increase_pct >= min_increase:
                    if (ticker, "lobbying_change") in existing:
                        continue

                    strength = min(increase_pct / 200, 1.0)
                    signal = {
                        "account_id": ACCOUNT_ID,
                        "source": "lobbying",
                        "signal_type": "lobbying_change",
                        "symbol": ticker,
                        "direction": "buy",
                        "strength": round(strength, 2),
                        "signal_role": "primary",
                        "raw_data": {"increase_pct": round(increase_pct, 1), "latest_amount": latest},
                    }
                    signals.append(signal)

        return signals

    def _process_off_exchange(self, existing_keys: set = None) -> list:
        """Process off-exchange/dark pool short volume data (confirmation signal).

        High short volume ratio (OTC_Short / OTC_Total) can indicate institutional
        hedging activity or bearish pressure. We flag tickers with unusually high
        short ratios as confirmation signals.
        """
        data = self.quiver.get_off_exchange()
        if not data:
            return []

        existing = existing_keys or set()
        config = SIGNAL_SOURCES["off_exchange"]
        min_short_ratio = config.get("min_short_ratio", 0.60)
        signals = []

        for entry in data:
            ticker = entry.get("Ticker") or entry.get("ticker")
            if not ticker:
                continue

            otc_short = self._parse_number(entry.get("OTC_Short") or entry.get("otc_short", 0))
            otc_total = self._parse_number(entry.get("OTC_Total") or entry.get("otc_total", 0))

            if otc_total <= 0:
                continue

            short_ratio = otc_short / otc_total
            if short_ratio < min_short_ratio:
                continue

            dpi = self._parse_number(entry.get("DPI") or entry.get("dpi", 0))

            if (ticker.upper(), "off_exchange_short") in existing:
                continue

            strength = min(short_ratio, 1.0)
            signal = {
                "account_id": ACCOUNT_ID,
                "source": "off_exchange",
                "signal_type": "off_exchange_short",
                "symbol": ticker.upper(),
                "direction": "buy",  # High short volume can precede short squeezes
                "strength": round(strength, 2),
                "signal_role": "confirmation",
                "raw_data": {
                    "short_ratio": round(short_ratio, 4),
                    "otc_short": otc_short,
                    "otc_total": otc_total,
                    "dpi": dpi,
                },
            }
            signals.append(signal)

        return signals

    def _process_flights(self, existing_keys: set = None) -> list:
        """Process corporate flight data (confirmation signal).

        Unusual corporate jet activity can indicate M&A due diligence,
        deal-making, or major business developments.
        """
        data = self.quiver.get_flights()
        if not data:
            return []

        existing = existing_keys or set()
        config = SIGNAL_SOURCES["flights"]
        min_flights = config.get("min_flights", 3)
        signals = []

        # Group flights by ticker to count activity
        ticker_flights = defaultdict(list)
        for entry in data:
            ticker = entry.get("Ticker") or entry.get("ticker")
            if not ticker:
                continue
            ticker_flights[ticker.upper()].append(entry)

        for ticker, flights in ticker_flights.items():
            if len(flights) < min_flights:
                continue

            if (ticker, "corp_flight") in existing:
                continue

            strength = min(len(flights) / 10.0, 1.0)
            destinations = list({
                f.get("ArrivalCity") or f.get("arrival_city", "unknown")
                for f in flights
            })

            signal = {
                "account_id": ACCOUNT_ID,
                "source": "flights",
                "signal_type": "corp_flight",
                "symbol": ticker,
                "direction": "buy",
                "strength": round(strength, 2),
                "signal_role": "confirmation",
                "raw_data": {
                    "flight_count": len(flights),
                    "destinations": destinations[:5],
                },
            }
            signals.append(signal)

        return signals

    def _process_wikipedia(self, existing_keys: set = None) -> list:
        """Process Wikipedia traffic spikes (confirmation signal)."""
        data = self.quiver.get_wikipedia()
        if not data:
            return []

        existing = existing_keys or set()
        config = SIGNAL_SOURCES["wikipedia"]
        min_multiplier = config.get("min_traffic_multiplier", 3.0)
        signals = []

        for entry in data:
            ticker = entry.get("Ticker") or entry.get("ticker")
            if not ticker:
                continue

            views = self._parse_number(entry.get("Views") or entry.get("views", 0))
            avg_views = self._parse_number(
                entry.get("Monthly_Avg_Views") or entry.get("avg", 0)
            )

            if avg_views > 0 and views / avg_views >= min_multiplier:
                if (ticker.upper(), "wiki_traffic") in existing:
                    continue

                strength = min(views / avg_views / 10, 1.0)
                signal = {
                    "account_id": ACCOUNT_ID,
                    "source": "wikipedia",
                    "signal_type": "wiki_traffic",
                    "symbol": ticker.upper(),
                    "direction": "buy",
                    "strength": round(strength, 2),
                    "signal_role": "confirmation",
                    "raw_data": {"views": views, "avg_views": avg_views,
                                 "multiplier": round(views / avg_views, 1)},
                }
                signals.append(signal)

        return signals

    def _process_wsb(self, existing_keys: set = None) -> list:
        """Process WallStreetBets mention spikes (confirmation signal)."""
        data = self.quiver.get_wsb()
        if not data:
            return []

        existing = existing_keys or set()
        config = SIGNAL_SOURCES["wsb"]
        min_multiplier = config.get("min_mention_spike_multiplier", 2.0)
        signals = []

        for entry in data:
            ticker = entry.get("Ticker") or entry.get("ticker")
            if not ticker:
                continue

            mentions = self._parse_number(
                entry.get("Mentions") or entry.get("mentions", 0)
            )
            avg_mentions = self._parse_number(
                entry.get("Avg_Mentions") or entry.get("avg", 0)
            )

            if avg_mentions > 0 and mentions / avg_mentions >= min_multiplier:
                if (ticker.upper(), "wsb_mention") in existing:
                    continue

                sentiment = entry.get("Sentiment") or entry.get("sentiment", 0)
                direction = "buy" if float(sentiment or 0) >= 0 else "sell"

                strength = min(mentions / avg_mentions / 5, 1.0)
                signal = {
                    "account_id": ACCOUNT_ID,
                    "source": "wsb",
                    "signal_type": "wsb_mention",
                    "symbol": ticker.upper(),
                    "direction": direction,
                    "strength": round(strength, 2),
                    "signal_role": "confirmation",
                    "raw_data": {"mentions": mentions, "avg_mentions": avg_mentions,
                                 "sentiment": sentiment},
                }
                signals.append(signal)

        return signals

    @staticmethod
    def _parse_trade_size(size_str) -> float:
        """Parse trade size from various formats (e.g., '$1,001 - $15,000')."""
        if isinstance(size_str, (int, float)):
            return float(size_str)
        if not size_str:
            return 0
        size_str = str(size_str).replace("$", "").replace(",", "")
        # If range, take the midpoint
        if " - " in size_str:
            parts = size_str.split(" - ")
            try:
                low = float(parts[0].strip())
                high = float(parts[1].strip())
                return (low + high) / 2
            except ValueError:
                return 0
        try:
            return float(size_str)
        except ValueError:
            return 0

    @staticmethod
    def _parse_number(val) -> float:
        """Parse a number from various formats."""
        if isinstance(val, (int, float)):
            return float(val)
        if not val:
            return 0
        try:
            return float(str(val).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            return 0
