import unittest
from unittest.mock import patch, MagicMock

from src.shared.risk_manager import RiskManager
from src.shared.config import STARTING_CAPITAL


class TestRiskManager(unittest.TestCase):

    @patch("src.shared.risk_manager.AlpacaClient")
    @patch("src.shared.risk_manager.Database")
    def setUp(self, mock_db_cls, mock_alpaca_cls):
        self.mock_db = mock_db_cls.return_value
        self.mock_alpaca = mock_alpaca_cls.return_value
        self.mock_db.get_trade_outcomes.return_value = []
        self.mock_alpaca.get_positions.return_value = []
        self.mock_alpaca.get_invested_value.return_value = 0
        self.mock_alpaca.get_position_count.return_value = 0
        self.mock_alpaca.get_position.return_value = None
        self.risk = RiskManager("quiver_strat")
        self.risk.db = self.mock_db
        self.risk.alpaca = self.mock_alpaca

    def test_working_capital_starts_at_10k(self):
        wc = self.risk.get_working_capital()
        self.assertEqual(wc, STARTING_CAPITAL)

    def test_working_capital_with_realized_pnl(self):
        self.mock_db.get_trade_outcomes.return_value = [
            {"realized_pnl": 500},
            {"realized_pnl": -200},
        ]
        wc = self.risk.get_working_capital()
        self.assertEqual(wc, STARTING_CAPITAL + 300)

    def test_can_open_position_basic(self):
        can, reason = self.risk.can_open_position("AAPL", 500)
        self.assertTrue(can)
        self.assertEqual(reason, "OK")

    def test_cannot_exceed_max_invested(self):
        self.mock_alpaca.get_invested_value.return_value = 5500
        can, reason = self.risk.can_open_position("AAPL", 600)
        self.assertFalse(can)
        self.assertIn("max invested", reason.lower())

    def test_cannot_exceed_max_position_size(self):
        # Max position for quiver_strat is 8% of 10k = $800
        can, reason = self.risk.can_open_position("AAPL", 900)
        self.assertFalse(can)
        self.assertIn("exceeds max", reason.lower())

    def test_cannot_exceed_max_positions(self):
        self.mock_alpaca.get_position_count.return_value = 12
        can, reason = self.risk.can_open_position("AAPL", 500)
        self.assertFalse(can)
        self.assertIn("max positions", reason.lower())

    def test_cannot_open_duplicate_position(self):
        self.mock_alpaca.get_position.return_value = MagicMock()
        can, reason = self.risk.can_open_position("AAPL", 500)
        self.assertFalse(can)
        self.assertIn("already holding", reason.lower())

    def test_circuit_breaker(self):
        self.mock_alpaca.get_invested_value.return_value = 12000  # > working capital
        can, reason = self.risk.can_open_position("AAPL", 100)
        self.assertFalse(can)
        self.assertIn("circuit breaker", reason.lower())

    def test_position_size_scales_with_confidence(self):
        size_high = self.risk.calculate_position_size("AAPL", 100)
        size_low = self.risk.calculate_position_size("AAPL", 50)
        self.assertGreater(size_high, size_low)

    def test_position_size_respects_max(self):
        size = self.risk.calculate_position_size("AAPL", 100)
        max_pos = STARTING_CAPITAL * 0.08  # 8% for quiver_strat
        self.assertLessEqual(size, max_pos)


class TestDayTraderRisk(unittest.TestCase):

    @patch("src.shared.risk_manager.AlpacaClient")
    @patch("src.shared.risk_manager.Database")
    def setUp(self, mock_db_cls, mock_alpaca_cls):
        self.mock_db = mock_db_cls.return_value
        self.mock_alpaca = mock_alpaca_cls.return_value
        self.mock_db.get_trade_outcomes.return_value = []
        self.mock_db.get_todays_trades.return_value = []
        self.mock_alpaca.get_positions.return_value = []
        self.mock_alpaca.get_invested_value.return_value = 0
        self.mock_alpaca.get_position_count.return_value = 0
        self.mock_alpaca.get_position.return_value = None
        self.risk = RiskManager("day_trader")
        self.risk.db = self.mock_db
        self.risk.alpaca = self.mock_alpaca

    def test_max_daily_risk_2_percent(self):
        can, pnl = self.risk.check_daily_loss_limit()
        self.assertTrue(can)

    def test_max_trades_per_day(self):
        self.mock_db.get_todays_trades.return_value = [{}] * 8
        can, count = self.risk.check_max_trades_per_day()
        self.assertFalse(can)
        self.assertEqual(count, 8)


if __name__ == "__main__":
    unittest.main()
