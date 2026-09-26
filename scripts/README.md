# Script map (run from repository root)

| Location | Purpose | Network / side effects |
| --- | --- | --- |
| `research/export_oanda_research.py` | Bounded practice-only broker transactions + M1 candles to **ignored private** `data/raw/` | OANDA **GET only**; no orders or posts. |
| `research/audit_backtest_parity.py` | Offline baseline and optional saved Cloud session-balance audit | **No network**; updates ignored private `baseline.json`. |
| `research/run_exit_study.py` | Nine predeclared exits on private candles; insufficient-history Monte Carlo gate | **No network**; writes ignored `exit_study.json`, does **not** pick/deploy a winner. |
| `research/fetch_session.py` | Legacy single-day **mid-only** replay CSV fetcher | OANDA GET; obeys configured environment, so check `.env` first. Does **not** place orders; `REPLAY_TWEETS=true` in a *separate* replay command posts to X. |
| `account/list_accounts.py`, `account/verify_account.py` | Read account identity/balance/margin | OANDA GET; **prints private account information**. |
| `assets/generate_example_assets.py` | Regenerate illustrative charts | Writes tracked `docs/assets/` images; no X posts. |
| `deploy_cloud_run_job.sh` | **Production deployment entry point (path intentionally unchanged)** | Builds and deploys image, changes Cloud resources/secrets/scheduler; may incur cost. Never run for offline analysis. |
| `analyze_json_logs.py`, `run_analysis_cron.sh` | **Legacy posting/cron entry points (paths intentionally unchanged)** | `analyze_json_logs.py` **posts to X** and may use paid API credits. Do not use for research or run as a smoke test. |

See [`../research/README.md`](../research/README.md) for the predeclared exit-study protocol. Research artifacts under `data/` and `reports/` are Git- and Cloud-Build-ignored; never move private trade exports into this script tree.
