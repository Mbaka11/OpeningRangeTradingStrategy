# Configuration Files

This directory contains configuration files organized by service.

## Structure

```
config/
├── trading/           # Opening Range trading bot configuration
│   ├── instruments.yml   # Market/instrument settings (NSXUSD)
│   └── strategy.yml      # Strategy parameters (zones, risk, capital)
└── govtrades/         # (Future) GovTrades service configuration
```

## Usage

Each service loads its own configuration from its subdirectory.
Environment-specific secrets (API keys, tokens) are stored in `.env` files,
not in these YAML configs.

### Trading Service

- `instruments.yml` - Market settings, session times, data format
- `strategy.yml` - Strategy parameters, risk settings, evaluation metrics

### GovTrades Service (Future)

- Will contain source polling intervals, LLM settings, filtering rules
