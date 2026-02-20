import unittest
from unittest.mock import patch, MagicMock

from src.shared.portfolio_tracker import PortfolioTracker
from src.shared.config import STARTING_CAPITAL, PAPER_RESERVE


class TestPortfolioTracker(unittest.TestCase):

    @patch("src.shared.portfolio_tracker.AlpacaClient")
    @patch("src.shared.portfolio_tracker.Database")
    def setUp(self, mock_db_cls, mock_alpaca_cls):
        self.mock_db = mock_db_cls.return_value
        self.mock_alpaca = mock_alpaca_cls.return_value
        self.mock_db.get_trade_outcomes.return_value = []
        self.mock_db.get_latest_snapshot.return_value = None
        self.mock_db.get_snapshots.return_value = []
        self.mock_db.upsert_snapshot.return_value = {}
        self.mock_alpaca.get_positions.return_value = []
        # Default: $100k paper account, no P&L
        mock_account = MagicMock()
        mock_account.equity = str(PAPER_RESERVE + STARTING_CAPITAL)
        mock_account.cash = str(PAPER_RESERVE + STARTING_CAPITAL)
        self.mock_alpaca.get_account.return_value = mock_account
        self.tracker = PortfolioTracker("quiver_strat")
        self.tracker.db = self.mock_db
        self.tracker.alpaca = self.mock_alpaca

    def test_snapshot_with_no_positions(self):
        snapshot = self.tracker.take_snapshot()
        self.assertEqual(snapshot["equity"], STARTING_CAPITAL)
        self.assertEqual(snapshot["cash"], STARTING_CAPITAL)
        self.assertEqual(snapshot["total_pnl"], 0)

    def test_snapshot_with_gains(self):
        # Simulate $500 realized gains in the Alpaca account
        mock_account = MagicMock()
        mock_account.equity = str(PAPER_RESERVE + STARTING_CAPITAL + 500)
        mock_account.cash = str(PAPER_RESERVE + STARTING_CAPITAL + 500)
        self.mock_alpaca.get_account.return_value = mock_account
        snapshot = self.tracker.take_snapshot()
        self.assertEqual(snapshot["equity"], STARTING_CAPITAL + 500)

    def test_metrics_empty_when_no_trades(self):
        metrics = self.tracker.get_performance_metrics()
        self.assertEqual(metrics["total_trades"], 0)
        self.assertEqual(metrics["win_rate"], 0)

    def test_metrics_with_trades(self):
        self.mock_db.get_trade_outcomes.return_value = [
            {"realized_pnl": 100, "pnl_pct": 2.0},
            {"realized_pnl": -50, "pnl_pct": -1.0},
            {"realized_pnl": 200, "pnl_pct": 4.0},
        ]
        metrics = self.tracker.get_performance_metrics()
        self.assertEqual(metrics["total_trades"], 3)
        self.assertEqual(metrics["wins"], 2)
        self.assertEqual(metrics["losses"], 1)
        self.assertAlmostEqual(metrics["win_rate"], 66.7, places=1)
        self.assertAlmostEqual(metrics["total_pnl"], 250, places=2)


if __name__ == "__main__":
    unittest.main()
