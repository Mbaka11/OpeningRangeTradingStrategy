# Notebooks Directory

Jupyter notebooks for analysis and research, organized by service.

## Structure

```
notebooks/
├── trading/                          # Opening Range strategy notebooks
│   ├── 01_spec_strategy.ipynb           # Strategy specification & logic
│   ├── 02_data_audit.ipynb              # Data quality checks
│   ├── 03_baseline_backtest.ipynb       # Baseline backtest results
│   ├── 04_parameter_robustness.ipynb    # Parameter sensitivity analysis
│   ├── 05_performance_risk.ipynb        # Risk metrics & Monte Carlo
│   └── 99_compare_replay_vs_backtest.ipynb  # Replay validation
└── govtrades/                        # (Future) GovTrades analysis notebooks
```

## Trading Notebooks

| #   | Notebook                     | Purpose                                          |
| --- | ---------------------------- | ------------------------------------------------ |
| 01  | `spec_strategy`              | Define OR strategy rules, entry/exit logic       |
| 02  | `data_audit`                 | Validate historical data quality, gaps, timezone |
| 03  | `baseline_backtest`          | Run baseline backtest, generate trade log        |
| 04  | `parameter_robustness`       | Sweep SL/TP, zones, entry times                  |
| 05  | `performance_risk`           | Calculate Sharpe, Sortino, max DD, Monte Carlo   |
| 99  | `compare_replay_vs_backtest` | Verify replay matches backtest                   |

## Running Notebooks

```bash
# From project root
jupyter lab notebooks/trading/
```

Notebooks depend on:

- `services/trading/` for core logic (via `src/or_core.py`)
- `config/trading/` for parameters
- `data/trading/historical/` for backtest data
