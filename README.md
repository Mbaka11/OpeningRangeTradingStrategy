# Opening Range Trading Bot

> A modular Python trading bot running on GCP, with an Opening Range intraday strategy and extensible service architecture.

## Repository Structure

```
OpeningRange/
├── config/                     # YAML configuration files
│   ├── instruments.yml         # Market settings (instrument, session times)
│   ├── strategy.yml            # Strategy parameters (zones, SL/TP)
│   └── govtrades.yml           # GovTrades config (future)
├── services/                   # Independent service modules
│   ├── trading/                # Opening Range trading bot
│   │   ├── run_bot.py          # Main entry point
│   │   ├── broker_oanda.py     # OANDA API wrapper
│   │   ├── data_feed.py        # M1 candle fetcher
│   │   ├── config.py           # Config loader
│   │   ├── plotting.py         # Chart generation
│   │   ├── trade_types.py      # Type definitions
│   │   ├── fetch_session.py    # Historical data fetcher
│   │   ├── test_logic.py       # Unit tests
│   │   └── logs/               # Service logs
│   └── govtrades/              # Congress trades monitor (future)
├── shared/                     # Cross-service utilities
│   ├── logging_utils.py        # TZ-aware rotating logger
│   └── notifier.py             # Twitter/X posting
├── src/                        # Core strategy logic (used by notebooks)
│   └── or_core.py
├── notebooks/                  # Research & backtesting
├── scripts/                    # Utility scripts
├── data/raw/                   # Historical & replay data
├── reports/                    # Generated reports & figures
├── .env.example                # Environment template
├── Dockerfile                  # Container definition
├── DEPLOYMENT.md               # GCP deployment guide
└── requirements.txt            # Python dependencies
```

## Quick Start

### 1. Setup Environment

```bash
# Clone and enter repo
cd OpeningRange

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials
```

### 2. Run Trading Bot

```bash
# Live/Paper mode (connects to OANDA)
python -m services.trading.run_bot

# Replay mode (from historical file)
REPLAY_FILE=data/raw/replay_2025-01-02.csv python -m services.trading.run_bot

# Replay with tweets
REPLAY_TWEETS=true REPLAY_FILE=data/raw/replay_2025-01-02.csv python -m services.trading.run_bot
```

### 3. Fetch Historical Data

```bash
python -m services.trading.fetch_session 2025-01-15
# Saves to data/raw/replay_2025-01-15.csv
```

### 4. Run Tests

```bash
pytest services/trading/test_logic.py -v
```

---

## Strategy Summary

**Session window (New York time):**

- **Opening Range (OR):** 09:30–10:00 (first 30 minutes)
- **Entry time:** 10:22
- **Hard exit:** 12:00

**Position logic:**

- Compute OR High and OR Low from 09:30–10:00
- At 10:22, check price position relative to OR:
  - **Long** if price in top 35% of OR range
  - **Short** if price in bottom 35%
  - **No trade** if price in middle 30%
- **Stop Loss:** 25 points | **Take Profit:** 75 points
- **Point value:** $80/point

---

## Configuration

### config/instruments.yml

Controls market details, session times, and data policies.

### config/strategy.yml

Controls signal logic (zones), risk (SL/TP), and execution rules.

### Environment Variables (.env)

| Variable                | Description                     |
| ----------------------- | ------------------------------- |
| `OANDA_ACCOUNT_ID`      | OANDA account ID                |
| `OANDA_API_TOKEN`       | OANDA API token                 |
| `OANDA_ENV`             | `practice` or `live`            |
| `OANDA_INSTRUMENT`      | Instrument (e.g., `NAS100_USD`) |
| `TWITTER_API_KEY`       | Twitter API key                 |
| `TWITTER_API_SECRET`    | Twitter API secret              |
| `TWITTER_ACCESS_TOKEN`  | Twitter access token            |
| `TWITTER_ACCESS_SECRET` | Twitter access secret           |

---

## Docker Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for full GCP deployment instructions.

```bash
# Build
docker build -t trading-bot .

# Run trading bot
docker run --env-file .env trading-bot

# Run with volume mount for logs
docker run --env-file .env -v $(pwd)/logs:/app/services/trading/logs trading-bot
```

---

## Services

### Trading Service (`services/trading/`)

The Opening Range trading bot. Monitors OANDA for M1 candles, generates signals, and executes trades.

### GovTrades Service (`services/govtrades/`) — Coming Soon

Monitors US Congress PTR filings, extracts trades, and posts to Twitter.

---

## Verification Commands

```bash
# Verify OANDA connection
python scripts/verify_account.py

# List accessible accounts
python scripts/list_accounts.py
```

---

## Development

### Adding a New Service

1. Create directory: `services/your_service/`
2. Add `__init__.py`, `config.py`, `main.py`
3. Use `shared/logging_utils.py` for logging
4. Use `shared/notifier.py` for Twitter posting
5. Add config to `config/your_service.yml`
6. Update Dockerfile CMD or add docker-compose service

### Code Standards

- Python 3.10+
- Type hints required
- Use dataclasses/TypedDict for schemas
- Structured logging via `shared/logging_utils`
- Tests in `test_*.py` files

---

## License

Private repository.
