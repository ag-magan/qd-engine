import os
from dotenv import load_dotenv

load_dotenv()

# Trading mode: "paper" or "live"
TRADING_MODE = os.getenv("TRADING_MODE", "paper")

# Alpaca credentials per account
ALPACA_ACCOUNTS = {
    "quiver_strat": {
        "key": os.getenv("ALPACA_ACCT1_PAPER_KEY", ""),
        "secret": os.getenv("ALPACA_ACCT1_PAPER_SECRET", ""),
    },
    "day_trader": {
        "key": os.getenv("ALPACA_ACCT2_PAPER_KEY", ""),
        "secret": os.getenv("ALPACA_ACCT2_PAPER_SECRET", ""),
    },
    "autonomous": {
        "key": os.getenv("ALPACA_ACCT3_PAPER_KEY", ""),
        "secret": os.getenv("ALPACA_ACCT3_PAPER_SECRET", ""),
    },
    "signal_echo": {
        "key": os.getenv("ALPACA_ACCT3_PAPER_KEY", ""),
        "secret": os.getenv("ALPACA_ACCT3_PAPER_SECRET", ""),
    },
}

# QuiverQuant
QUIVER_API_TOKEN = os.getenv("QUIVER_API_TOKEN", "")
QUIVER_BASE_URL = "https://api.quiverquant.com/beta"

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}
CLAUDE_MODEL = CLAUDE_MODELS["sonnet"]  # Default for backward compat

# Gmail
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Capital isolation: each account uses exactly $10,000
STARTING_CAPITAL = 10_000
PAPER_RESERVE = 90_000  # Paper accounts start at $100k; we only trade $10k

# Reviews and self-improve ignore data before this date (pre-March is testing)
DATA_START_DATE = "2026-03-01"

# Account-specific configuration
ACCOUNT_CONFIGS = {
    "quiver_strat": {
        "starting_capital": STARTING_CAPITAL,
        "max_invested_pct": 0.85,
        "max_position_pct": 0.15,
        "max_positions": 12,
        "min_claude_confidence": 55,
        "check_frequency_hours": 6,
        "rebalance_drift_threshold": 0.10,
    },
    "day_trader": {
        "starting_capital": STARTING_CAPITAL,
        "max_invested_pct": 0.90,
        "max_daily_risk_pct": 0.03,
        "max_per_trade_pct": 0.12,
        "max_concurrent_positions": 10,
        "no_new_trades_after": "15:30",
        "force_close_at": "15:50",
        "skip_first_minutes": 5,
    },
    "autonomous": {
        "starting_capital": STARTING_CAPITAL,
        "max_invested_pct": 0.85,
        "max_position_pct": 0.20,
        "max_positions": 10,
        "max_trades_per_day": 8,
        "min_holding_hours": 6,
        "max_holding_days": 30,
        "min_confidence": 50,
    },
    "signal_echo": {
        "starting_capital": STARTING_CAPITAL,
        "max_invested_pct": 0.85,
        "max_position_pct": 0.15,
        "max_positions": 12,
        "max_trades_per_day": 20,
        "max_daily_risk_pct": 0.03,
        "min_composite_score": 15,
    },
}

# Convergence multipliers for composite scoring
CONVERGENCE_MULTIPLIERS = {
    2: 1.4,
    3: 1.8,
    4: 2.3,
}

# Special combo bonuses
COMBO_BONUSES = {
    frozenset(["lobbying", "gov_contracts"]): 1.5,
    frozenset(["lobbying", "gov_contracts_all"]): 1.5,
    frozenset(["house_trading", "senate_trading"]): 1.4,
}
