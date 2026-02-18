ACCOUNT_ID = "day_trader"

# Scanner settings
SCANNER = {
    "min_price": 5.0,
    "max_price": 500.0,
    "min_gap_pct": 3.0,
    "min_volume_multiplier": 1.5,
    "scan_interval_seconds": 120,  # 2 minutes
}

# Strategy configurations
STRATEGIES = {
    "momentum": {
        "enabled": True,
        "target_pct": 3.0,
        "stop_pct": 1.5,
        "trail_activate_pct": 1.0,
        "trail_offset_pct": 0.5,
        "min_volume_ratio": 1.5,
        "timeframe": "5Min",
    },
    "gap_fill": {
        "enabled": True,
        "min_gap_pct": 3.0,
        "target_fill_pct": 70.0,  # Target: gap fills 70%
        "stop_pct": 2.0,
        "trail_activate_pct": 1.5,
        "trail_offset_pct": 0.75,
    },
    "mean_reversion": {
        "enabled": True,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "target_pct": 2.5,
        "stop_pct": 1.0,
        "trail_activate_pct": 0.75,
        "trail_offset_pct": 0.4,
        "min_volume_spike": 1.5,
    },
    "vwap_bounce": {
        "enabled": True,
        "vwap_proximity_pct": 1.0,  # Within 1.0% of VWAP
        "target_pct": 1.75,
        "stop_pct": 0.75,
        "trail_activate_pct": 0.5,
        "trail_offset_pct": 0.3,
    },
    "trending": {
        "enabled": True,
        "target_pct": 2.0,
        "stop_pct": 1.0,
        "trail_activate_pct": 0.75,
        "trail_offset_pct": 0.4,
        "min_sma_spread_pct": 0.1,  # SMA10 must be 0.1%+ from SMA20
    },
}

# Time windows (Eastern Time)
PREMARKET_START = "08:30"
TRADING_START = "09:31"
NO_NEW_TRADES = "15:30"
FORCE_CLOSE = "15:50"
EOD_REVIEW = "16:00"

# Behavioral detection thresholds
MAX_CONSECUTIVE_LOSSES_BEFORE_COOLDOWN = 5
COOLDOWN_MINUTES = 30
OVERTRADING_THRESHOLD = 25
