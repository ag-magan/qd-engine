# QD Engine

Automated portfolio management system.

## Setup

### Prerequisites

- Python 3.11+
- Alpaca paper trading accounts
- Supabase project
- Anthropic API key
- Gmail account with app password

### Local Development

```bash
# Clone and install
git clone <repo-url>
cd qd-engine
pip install -r requirements.txt
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run individual strategies
python -m src.account1_quiver.main
python -m src.account2_daytrader.main loop
python -m src.account3_autonomous.main decision

# Run reports
python -m src.reporting.snapshot
python -m src.reporting.daily_email

# Run tests
python -m pytest tests/
```

### GitHub Actions

1. Create a public GitHub repository
2. Add all environment variables as GitHub Secrets (Settings > Secrets > Actions)
3. Push code - workflows auto-register from `.github/workflows/`
4. Trigger any workflow manually via Actions tab > workflow > Run workflow

### Required GitHub Secrets

```
ALPACA_ACCT1_PAPER_KEY
ALPACA_ACCT1_PAPER_SECRET
ALPACA_ACCT2_PAPER_KEY
ALPACA_ACCT2_PAPER_SECRET
ALPACA_ACCT3_PAPER_KEY
ALPACA_ACCT3_PAPER_SECRET
QUIVER_API_TOKEN
ANTHROPIC_API_KEY
SUPABASE_URL
SUPABASE_KEY
GMAIL_ADDRESS
GMAIL_APP_PASSWORD
```

## Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| Signal Strategy | Every 6h weekdays | Process alternative data signals |
| Day Trader | 8:30 AM ET weekdays | Intraday trading loop |
| Autonomous Strategy | 10 AM, 1 PM, 4:30 PM ET | AI-driven decisions |
| Daily Snapshot | 4:00 PM ET | Portfolio state capture |
| Daily Report | 4:15 PM ET | Email performance report |
| Weekly Review | Sunday 8 PM ET | Learning and weight updates |
| Monthly Review | 1st of month | Deep strategy review |
