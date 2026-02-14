# QD Engine

Automated portfolio management system.

## Setup

```bash
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

Configure `.env` with required credentials, then add them as GitHub Secrets for CI/CD.

## Tests

```bash
python -m pytest tests/
```
