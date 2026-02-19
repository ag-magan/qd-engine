ACCOUNT_ID = "autonomous"

# Decision schedule (Eastern Time)
MORNING_DECISION = "10:00"
MIDDAY_MONITOR = "13:00"
EOD_REVIEW = "16:30"

# Position constraints
MIN_THESIS_LENGTH = 100  # Characters
MIN_CONFIDENCE = 50

# Thesis classification labels
THESIS_CLASSIFICATIONS = [
    "right_reason_win",
    "wrong_reason_win",
    "right_reason_loss",
    "wrong_reason_loss",
]
