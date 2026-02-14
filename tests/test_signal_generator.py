import unittest
from unittest.mock import patch, MagicMock

from src.account1_quiver.signal_generator import SignalGenerator


class TestSignalGenerator(unittest.TestCase):

    @patch("src.account1_quiver.signal_generator.Database")
    @patch("src.account1_quiver.signal_generator.QuiverClient")
    def setUp(self, mock_quiver_cls, mock_db_cls):
        self.mock_quiver = mock_quiver_cls.return_value
        self.mock_db = mock_db_cls.return_value
        self.mock_db.signal_exists.return_value = False
        self.generator = SignalGenerator()
        self.generator.quiver = self.mock_quiver
        self.generator.db = self.mock_db

    def test_house_trade_buy(self):
        self.mock_quiver.get_house_trades.return_value = [
            {
                "Ticker": "AAPL",
                "Transaction": "Purchase",
                "Range": "$50,001 - $100,000",
                "Representative": "Test Representative",
            }
        ]
        signals = self.generator._process_house_trading()
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol"], "AAPL")
        self.assertEqual(signals[0]["direction"], "buy")
        self.assertEqual(signals[0]["source"], "house_trading")

    def test_senate_trade_buy(self):
        self.mock_quiver.get_senate_trades.return_value = [
            {
                "Ticker": "MSFT",
                "Transaction": "Purchase",
                "Range": "$100,001 - $250,000",
                "Senator": "Test Senator",
            }
        ]
        signals = self.generator._process_senate_trading()
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol"], "MSFT")
        self.assertEqual(signals[0]["direction"], "buy")
        self.assertEqual(signals[0]["source"], "senate_trading")

    def test_house_filters_small_trades(self):
        self.mock_quiver.get_house_trades.return_value = [
            {
                "Ticker": "AAPL",
                "Transaction": "Purchase",
                "Range": "$1,001 - $5,000",  # Below $15k threshold
            }
        ]
        signals = self.generator._process_house_trading()
        self.assertEqual(len(signals), 0)

    def test_insider_cluster_detection(self):
        self.mock_quiver.get_insider_trades.return_value = [
            {"Ticker": "TSLA", "Transaction": "Purchase", "Date": "2026-02-10"},
            {"Ticker": "TSLA", "Transaction": "Purchase", "Date": "2026-02-08"},
            {"Ticker": "AAPL", "Transaction": "Purchase", "Date": "2026-02-10"},
        ]
        signals = self.generator._process_insiders()
        # TSLA should have a cluster signal (2 buys), AAPL should not (only 1)
        tsla_signals = [s for s in signals if s["symbol"] == "TSLA"]
        aapl_signals = [s for s in signals if s["symbol"] == "AAPL"]
        self.assertEqual(len(tsla_signals), 1)
        self.assertEqual(len(aapl_signals), 0)

    def test_gov_contracts_min_value(self):
        self.mock_quiver.get_gov_contracts.return_value = [
            {"Ticker": "LMT", "Amount": 50000000},
            {"Ticker": "BA", "Amount": 5000000},  # Below $10M threshold
        ]
        signals = self.generator._process_gov_contracts()
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol"], "LMT")

    def test_dedup_prevents_duplicate_signals(self):
        self.mock_db.signal_exists.return_value = True
        self.mock_quiver.get_house_trades.return_value = [
            {"Ticker": "AAPL", "Transaction": "Purchase", "Range": "$50,001 - $100,000"}
        ]
        signals = self.generator._process_house_trading()
        self.assertEqual(len(signals), 0)

    def test_off_exchange_short_ratio(self):
        self.mock_quiver.get_off_exchange.return_value = [
            {"Ticker": "GME", "OTC_Short": 700000, "OTC_Total": 1000000, "DPI": 0.5},
            {"Ticker": "AAPL", "OTC_Short": 400000, "OTC_Total": 1000000, "DPI": 0.3},
        ]
        signals = self.generator._process_off_exchange()
        # GME has 70% short ratio (above 60% threshold), AAPL has 40%
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol"], "GME")
        self.assertEqual(signals[0]["signal_role"], "confirmation")

    def test_flights_min_threshold(self):
        self.mock_quiver.get_flights.return_value = [
            {"Ticker": "NVDA", "ArrivalCity": "Austin", "Date": "2026-02-10"},
            {"Ticker": "NVDA", "ArrivalCity": "DC", "Date": "2026-02-11"},
            {"Ticker": "NVDA", "ArrivalCity": "NYC", "Date": "2026-02-12"},
            {"Ticker": "AAPL", "ArrivalCity": "LA", "Date": "2026-02-10"},
        ]
        signals = self.generator._process_flights()
        # NVDA has 3 flights (meets threshold), AAPL has only 1
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol"], "NVDA")
        self.assertEqual(signals[0]["signal_role"], "confirmation")

    def test_parse_trade_size_range(self):
        result = SignalGenerator._parse_trade_size("$15,001 - $50,000")
        self.assertEqual(result, 32500.5)

    def test_parse_trade_size_number(self):
        result = SignalGenerator._parse_trade_size(50000)
        self.assertEqual(result, 50000)

    def test_empty_data_returns_empty(self):
        self.mock_quiver.get_house_trades.return_value = None
        signals = self.generator._process_house_trading()
        self.assertEqual(len(signals), 0)


if __name__ == "__main__":
    unittest.main()
