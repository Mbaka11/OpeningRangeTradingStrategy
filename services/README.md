# Services Directory

This directory contains independent service implementations.

## Structure

```
services/
├── trading/            # Opening Range trading bot
│   ├── run_bot.py         # Main entry point
│   ├── or_core.py         # Core strategy logic
│   ├── broker_oanda.py    # OANDA API wrapper
│   ├── data_feed.py       # M1 candle fetcher
│   ├── plotting.py        # Chart generation for tweets
│   ├── config.py          # Config loader (YAML + env)
│   ├── trade_types.py     # Data classes
│   ├── fetch_session.py   # Session data fetcher
│   └── test_logic.py      # Unit tests
└── govtrades/          # Congress trades monitor (future)
    └── __init__.py
```

## Running Services

### Trading Bot

```bash
# Live mode
python -m services.trading.run_bot

# Replay mode
REPLAY_FILE=data/trading/replay/replay_2025-01-02.csv python -m services.trading.run_bot
```

### GovTrades (Future)

```bash
python -m services.govtrades.main
```

## Adding a New Service

1. Create a new directory under `services/`
2. Add `__init__.py` and `main.py` entry point
3. Create corresponding config in `config/<service>/`
4. Create data directory `data/<service>/`
5. Create log directory `logs/<service>/`
6. Update Dockerfile with new CMD option if needed
