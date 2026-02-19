ACCOUNT_ID = "signal_echo"

# Signal reading
SIGNAL_LOOKBACK_HOURS = 24
MIN_COMPOSITE_SCORE = 15

# Time windows (Eastern Time)
NO_NEW_TRADES = "15:30"
FORCE_CLOSE = "15:50"

# Trailing stop
TRAIL_ACTIVATE_PCT = 1.5   # Activate trailing stop after +1.5% unrealized gain
TRAIL_OFFSET_PCT = 0.75    # Trail 0.75% below high-water mark
