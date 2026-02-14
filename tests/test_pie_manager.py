import unittest
from unittest.mock import patch, MagicMock

from src.account1_quiver.pie_manager import PieManager


class TestPieManager(unittest.TestCase):

    @patch("src.account1_quiver.pie_manager.RiskManager")
    @patch("src.account1_quiver.pie_manager.AlpacaClient")
    @patch("src.account1_quiver.pie_manager.Database")
    def setUp(self, mock_db_cls, mock_alpaca_cls, mock_risk_cls):
        self.mock_db = mock_db_cls.return_value
        self.mock_alpaca = mock_alpaca_cls.return_value
        self.mock_risk = mock_risk_cls.return_value
        self.mock_risk.get_working_capital.return_value = 10000
        self.mock_risk.config = {
            "max_invested_pct": 0.60,
            "max_position_pct": 0.08,
            "rebalance_drift_threshold": 0.10,
        }
        self.pie_mgr = PieManager()
        self.pie_mgr.db = self.mock_db
        self.pie_mgr.alpaca = self.mock_alpaca
        self.pie_mgr.risk = self.mock_risk

    def test_create_pie_from_signals(self):
        self.mock_db.create_pie.return_value = {"id": 1}
        signals = [
            {"symbol": "AAPL", "confidence": 80, "position_size_pct": 0.5, "sources": ["house_trading"]},
            {"symbol": "MSFT", "confidence": 70, "position_size_pct": 0.5, "sources": ["insider"]},
        ]
        result = self.pie_mgr.create_pie_from_signals(signals)
        self.assertIsNotNone(result.get("pie"))
        self.assertEqual(len(result.get("allocations", [])), 2)

    def test_empty_signals_returns_empty(self):
        result = self.pie_mgr.create_pie_from_signals([])
        self.assertEqual(result, {})

    def test_respects_max_invested(self):
        self.mock_db.create_pie.return_value = {"id": 1}
        # Many signals should be capped by max invested
        signals = [
            {"symbol": f"SYM{i}", "confidence": 80, "position_size_pct": 1.0, "sources": ["house_trading"]}
            for i in range(20)
        ]
        result = self.pie_mgr.create_pie_from_signals(signals)
        total = result.get("total_allocated", 0)
        max_investable = 10000 * 0.60
        self.assertLessEqual(total, max_investable + 1)  # +1 for rounding


if __name__ == "__main__":
    unittest.main()
