# Scripts Directory

Utility scripts organized by service.

## Structure

```
scripts/
├── trading/                    # Opening Range trading utilities
│   ├── verify_account.py          # Verify OANDA account connection
│   ├── list_accounts.py           # List available OANDA accounts
│   ├── analyze_json_logs.py       # Analyze trading JSON logs
│   └── run_analysis_cron.sh       # Cron job for weekly analysis
└── govtrades/                  # (Future) GovTrades utilities
```

## Trading Scripts

### `verify_account.py`

Verify OANDA account connection, currency, and margin availability.

```bash
python scripts/trading/verify_account.py
```

### `list_accounts.py`

List all OANDA accounts accessible with the current API token.

```bash
python scripts/trading/list_accounts.py
```

### `analyze_json_logs.py`

Analyze daily JSON logs to produce quantitative metrics and tweet summaries.

```bash
python scripts/trading/analyze_json_logs.py
```

### `run_analysis_cron.sh`

Bash script for scheduling weekly performance analysis via cron.

## Note

All scripts expect to be run from the project root directory.
