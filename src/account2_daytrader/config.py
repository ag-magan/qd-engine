ACCOUNT_ID = "day_trader"

# Scanner settings
SCANNER = {
    "min_price": 5.0,
    "max_price": 500.0,
    "min_gap_pct": 3.0,
    "min_volume_multiplier": 2.0,
    "scan_interval_seconds": 300,  # 5 minutes
}

# Strategy configurations
STRATEGIES = {
    "momentum": {
        "enabled": True,
        "target_pct": 2.0,
        "stop_pct": 1.0,
        "min_volume_ratio": 2.0,
        "timeframe": "5Min",
    },
    "gap_fill": {
        "enabled": True,
        "min_gap_pct": 3.0,
        "target_fill_pct": 50.0,  # Target: gap fills 50%
        "stop_pct": 1.5,
    },
    "mean_reversion": {
        "enabled": True,
        "rsi_oversold": 30,
        "target_pct": 1.5,
        "stop_pct": 0.75,
        "min_volume_spike": 1.5,
    },
    "vwap_bounce": {
        "enabled": True,
        "vwap_proximity_pct": 0.3,  # Within 0.3% of VWAP
        "target_pct": 1.0,
        "stop_pct": 0.5,
    },
}

# Time windows (Eastern Time)
PREMARKET_START = "08:30"
TRADING_START = "09:35"
NO_NEW_TRADES = "15:30"
FORCE_CLOSE = "15:50"
EOD_REVIEW = "16:00"

# Behavioral detection thresholds
MAX_CONSECUTIVE_LOSSES_BEFORE_COOLDOWN = 3
COOLDOWN_MINUTES = 30
OVERTRADING_THRESHOLD = 6  # Performance degrades after this many trades
