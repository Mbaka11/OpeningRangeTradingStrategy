# OpeningRange

A multi-service Python project running on GCP, featuring:

- **Trading Bot** - Opening Range strategy on NSXUSD (NAS100)
- **GovTrades** - (Coming Soon) Congressional PTR filing monitor

## Project Structure

```
OpeningRange/
├── config/                          # Configuration files
│   ├── trading/                        # Trading service configs
│   │   ├── instruments.yml               # Market/session settings
│   │   └── strategy.yml                  # Strategy parameters
│   └── govtrades/                      # GovTrades configs (future)
│
├── data/                            # Data files
│   ├── trading/                        # Trading data
│   │   ├── historical/                   # Backtest data (DAT_ASCII_*.csv)
│   │   └── replay/                       # Paper trading replays
│   └── govtrades/                      # GovTrades data (future)
│
├── docs/                            # Documentation
│   ├── trading/                        # Trading strategy docs
│   └── govtrades/                      # GovTrades specification
│       └── GovTrades.md
│
├── logs/                            # Runtime logs
│   ├── trading/                        # Trading bot logs
│   └── govtrades/                      # GovTrades logs (future)
│
├── notebooks/                       # Jupyter notebooks
│   ├── trading/                        # Strategy analysis notebooks
│   │   ├── 01_spec_strategy.ipynb
│   │   ├── 02_data_audit.ipynb
│   │   ├── 03_baseline_backtest.ipynb
│   │   ├── 04_parameter_robustness.ipynb
│   │   ├── 05_performance_risk.ipynb
│   │   └── 99_compare_replay_vs_backtest.ipynb
│   └── govtrades/                      # GovTrades notebooks (future)
│
├── reports/                         # Generated reports
│   ├── trading/                        # Trading reports
│   │   ├── figures/                      # Charts (audit, backtest, risk)
│   │   └── tables/                       # CSV exports
│   └── govtrades/                      # GovTrades reports (future)
│
├── scripts/                         # Utility scripts
│   ├── trading/                        # Trading utilities
│   │   ├── verify_account.py
│   │   ├── list_accounts.py
│   │   └── analyze_json_logs.py
│   └── govtrades/                      # GovTrades utilities (future)
│
├── services/                        # Service implementations
│   ├── trading/                        # Opening Range trading bot
│   │   ├── run_bot.py                    # Main entry point
│   │   ├── or_core.py                    # Strategy logic
│   │   ├── broker_oanda.py               # OANDA API wrapper
│   │   ├── data_feed.py                  # M1 candle fetcher
│   │   ├── plotting.py                   # Chart generation
│   │   ├── config.py                     # Config loader
│   │   ├── trade_types.py                # Data classes
│   │   ├── fetch_session.py              # Session data fetcher
│   │   └── test_logic.py                 # Unit tests
│   └── govtrades/                      # GovTrades service (future)
│
├── shared/                          # Cross-service utilities
│   ├── logging_utils.py                # TZ-aware rotating logger
│   └── notifier.py                     # Twitter/X posting
│
├── Dockerfile                       # Container definition
├── DEPLOYMENT.md                    # Deployment guide
├── COPILOT_INSTRUCTIONS.md          # Development workflow
├── requirements.txt                 # Python dependencies
└── .env.example                     # Environment template
```

## Quick Start

### 1. Environment Setup

```bash
# Clone and enter directory
git clone <repo> && cd OpeningRange

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### 2. Verify OANDA Connection

```bash
python scripts/trading/verify_account.py
```

### 3. Run Trading Bot

**Live Mode:**

```bash
python -m services.trading.run_bot
```

**Replay Mode (paper trading):**

```bash
REPLAY_FILE=data/trading/replay/replay_2025-01-02.csv python -m services.trading.run_bot
```

**Fetch Session Data:**

```bash
# Saves to data/trading/replay/replay_YYYY-MM-DD.csv
python -m services.trading.fetch_session 2025-01-15
```

## Services

### Trading Bot

The Opening Range strategy trades NSXUSD (NAS100) on OANDA:

- **Session**: 09:30–12:00 New York time
- **Opening Range**: 09:30–10:00 (first 30 minutes)
- **Entry**: 10:22 based on price position in OR
- **Exit**: SL/TP or hard exit at 12:00
- **Posting**: Tweets trade entries/exits with charts

### GovTrades (Coming Soon)

Congressional stock trade monitoring via PTR filings:

- Poll House/Senate disclosure websites
- Parse PDF filings, extract trade data
- Filter by insider-ness, materiality, timeliness
- Post notable trades to Twitter with LLM context

## Configuration

### Environment Variables (`.env`)

```bash
# === Trading Service ===
OANDA_ACCOUNT_ID=xxx-xxx-xxxxxxx-xxx
OANDA_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OANDA_ENV=practice  # practice | live
OANDA_INSTRUMENT=NAS100_USD
OANDA_TIMEZONE=America/New_York

# === Twitter/X API (shared) ===
TWITTER_CONSUMER_KEY=...
TWITTER_CONSUMER_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...
TWITTER_BEARER_TOKEN=...

# === Logging ===
LOG_LEVEL=INFO
```

### Strategy Configuration

| File                             | Purpose                                      |
| -------------------------------- | -------------------------------------------- |
| `config/trading/instruments.yml` | Market settings, session times, data format  |
| `config/trading/strategy.yml`    | Entry zones, SL/TP, capital, execution rules |

## Development

### Run Tests

```bash
pytest services/trading/test_logic.py -v
```

### Run Notebooks

```bash
jupyter lab notebooks/trading/
```

### Docker Build

```bash
docker build -t openingrange .
docker run --env-file .env openingrange
```

## Folder Reference

| Folder                 | Purpose                                |
| ---------------------- | -------------------------------------- |
| `config/<service>/`    | YAML configuration per service         |
| `data/<service>/`      | Data files (historical, replay, cache) |
| `docs/<service>/`      | Technical documentation                |
| `logs/<service>/`      | Runtime logs                           |
| `notebooks/<service>/` | Jupyter notebooks for analysis         |
| `reports/<service>/`   | Generated reports and figures          |
| `scripts/<service>/`   | Utility scripts                        |
| `services/<service>/`  | Service implementation code            |
| `shared/`              | Cross-service utilities                |

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for GCP deployment instructions.

## License

Private - All rights reserved.
