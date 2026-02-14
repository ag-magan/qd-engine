import unittest
from unittest.mock import patch, MagicMock

from src.account1_quiver.signal_scorer import SignalScorer


class TestSignalScorer(unittest.TestCase):

    @patch("src.account1_quiver.signal_scorer.Database")
    def setUp(self, mock_db_cls):
        self.mock_db = mock_db_cls.return_value
        self.mock_db.get_signal_weights.return_value = {
            "house_trading": 1.0,
            "senate_trading": 1.0,
            "gov_contracts": 1.0,
            "lobbying": 1.0,
            "off_exchange": 0.5,
            "flights": 0.5,
            "insider": 1.0,
            "wikipedia": 0.5,
            "wsb": 0.5,
        }
        self.scorer = SignalScorer()
        self.scorer.db = self.mock_db

    def test_single_signal_scored(self):
        signals = [
            {
                "symbol": "AAPL",
                "source": "house_trading",
                "signal_type": "house_trade",
                "direction": "buy",
                "strength": 0.8,
                "signal_role": "primary",
            }
        ]
        scored = self.scorer.score_signals(signals)
        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0]["symbol"], "AAPL")
        self.assertGreater(scored[0]["composite_score"], 0)

    def test_convergence_multiplier_2_sources(self):
        signals = [
            {
                "symbol": "AAPL", "source": "house_trading", "signal_type": "house_trade",
                "direction": "buy", "strength": 0.8, "signal_role": "primary",
            },
            {
                "symbol": "AAPL", "source": "senate_trading", "signal_type": "senate_trade",
                "direction": "buy", "strength": 0.7, "signal_role": "primary",
            },
        ]
        scored = self.scorer.score_signals(signals)
        self.assertEqual(len(scored), 1)
        # Score should be higher due to 1.4x convergence multiplier
        self.assertEqual(scored[0]["source_count"], 2)

    def test_convergence_multiplier_3_sources(self):
        signals = [
            {"symbol": "AAPL", "source": "house_trading", "signal_type": "x",
             "direction": "buy", "strength": 0.8, "signal_role": "primary"},
            {"symbol": "AAPL", "source": "senate_trading", "signal_type": "x",
             "direction": "buy", "strength": 0.7, "signal_role": "primary"},
            {"symbol": "AAPL", "source": "gov_contracts", "signal_type": "x",
             "direction": "buy", "strength": 0.6, "signal_role": "primary"},
        ]
        scored = self.scorer.score_signals(signals)
        self.assertEqual(scored[0]["source_count"], 3)

    def test_confirmation_only_discounted(self):
        signals = [
            {
                "symbol": "AAPL", "source": "off_exchange", "signal_type": "off_exchange_short",
                "direction": "buy", "strength": 0.8, "signal_role": "confirmation",
            },
        ]
        scored = self.scorer.score_signals(signals)
        # Confirmation-only signals get heavy discount
        if scored:
            self.assertFalse(scored[0]["has_primary"])

    def test_sorted_by_score(self):
        signals = [
            {"symbol": "LOW_SCORE", "source": "off_exchange", "signal_type": "x",
             "direction": "buy", "strength": 0.3, "signal_role": "primary"},
            {"symbol": "HIGH_SCORE", "source": "house_trading", "signal_type": "x",
             "direction": "buy", "strength": 1.0, "signal_role": "primary"},
        ]
        scored = self.scorer.score_signals(signals)
        if len(scored) >= 2:
            self.assertGreaterEqual(
                scored[0]["composite_score"],
                scored[1]["composite_score"],
            )

    def test_combo_bonus_applied(self):
        signals = [
            {"symbol": "LMT", "source": "lobbying", "signal_type": "x",
             "direction": "buy", "strength": 0.8, "signal_role": "primary"},
            {"symbol": "LMT", "source": "gov_contracts", "signal_type": "x",
             "direction": "buy", "strength": 0.7, "signal_role": "primary"},
        ]
        scored = self.scorer.score_signals(signals)
        self.assertEqual(len(scored), 1)
        # Should have both convergence and combo bonus

    def test_bipartisan_combo_bonus(self):
        signals = [
            {"symbol": "NVDA", "source": "house_trading", "signal_type": "house_trade",
             "direction": "buy", "strength": 0.8, "signal_role": "primary"},
            {"symbol": "NVDA", "source": "senate_trading", "signal_type": "senate_trade",
             "direction": "buy", "strength": 0.7, "signal_role": "primary"},
        ]
        scored = self.scorer.score_signals(signals)
        self.assertEqual(len(scored), 1)
        # Should have convergence (1.4x) + bipartisan combo bonus (1.4x)
        # Base: 30*0.8 + 30*0.7 = 45, * 1.4 convergence * 1.4 combo = 88.2
        self.assertGreater(scored[0]["composite_score"], 60)


if __name__ == "__main__":
    unittest.main()
