ACCOUNT_ID = "quiver_strat"

# Signal source configurations
SIGNAL_SOURCES = {
    "house_trading": {
        "endpoint": "/live/housetrading",
        "signal_type": "house_trade",
        "enabled": True,
        "min_trade_size_usd": 15000,
    },
    "senate_trading": {
        "endpoint": "/live/senatetrading",
        "signal_type": "senate_trade",
        "enabled": True,
        "min_trade_size_usd": 15000,
    },
    "gov_contracts": {
        "endpoint": "/live/govcontracts",
        "signal_type": "gov_contract",
        "enabled": True,
        "min_contract_value": 10_000_000,
    },
    "gov_contracts_all": {
        "endpoint": "/live/govcontractsall",
        "signal_type": "gov_contract_all",
        "enabled": True,
        "min_contract_value": 10_000_000,
    },
    "lobbying": {
        "endpoint": "/live/lobbying",
        "signal_type": "lobbying_change",
        "enabled": True,
        "min_spending_increase_pct": 50,
    },
    "off_exchange": {
        "endpoint": "/live/offexchange",
        "signal_type": "off_exchange_short",
        "enabled": True,
        "min_short_ratio": 0.60,
        "role": "confirmation",
    },
    "flights": {
        "endpoint": "/live/flights",
        "signal_type": "corp_flight",
        "enabled": True,
        "min_flights": 3,
        "role": "confirmation",
    },
    "insider": {
        "endpoint": "/live/insiders",
        "signal_type": "insider_trade",
        "enabled": False,  # Requires Tier 2
        "cluster_window_days": 14,
        "min_cluster_size": 2,
    },
    "wikipedia": {
        "endpoint": "/live/wikipedia",
        "signal_type": "wiki_traffic",
        "enabled": False,  # No live endpoint at current tier
        "min_traffic_multiplier": 3.0,
        "role": "confirmation",
    },
    "wsb": {
        "endpoint": "/live/wallstreetbets",
        "signal_type": "wsb_mention",
        "enabled": False,  # Requires Tier 3
        "min_mention_spike_multiplier": 2.0,
        "role": "confirmation",
    },
}

# Base score for each signal source (before weights)
BASE_SCORES = {
    "house_trading": 30,
    "senate_trading": 30,
    "gov_contracts": 25,
    "gov_contracts_all": 25,
    "lobbying": 20,
    "off_exchange": 10,
    "flights": 10,
    "insider": 35,
    "wikipedia": 10,
    "wsb": 10,
}

# Minimum composite score to send to Claude for analysis
MIN_COMPOSITE_SCORE = 15

# Maximum age of signals to consider (hours)
SIGNAL_MAX_AGE_HOURS = 48

# Default exit parameters (used when Claude doesn't specify or for pre-existing positions)
DEFAULT_STOP_LOSS_PCT = 8.0
DEFAULT_TARGET_RETURN_PCT = 15.0
DEFAULT_TIME_HORIZON_DAYS = 30
