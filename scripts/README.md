# Script map (run from repository root)

| Location | Purpose | Network / side effects |
| --- | --- | --- |
| `research/export_oanda_research.py` | Bounded practice-only broker transactions + M1 candles to **ignored private** `data/raw/` | OANDA **GET only**; no orders or posts. |
| `research/export_oanda_cost_evidence.py` | Current NAS100 account-scoped metadata + cost fields for an existing, inspected fill window | **Dry-run default**; separately authorized `--fetch` allows **<=8 practice GET attempts, no retries/redirects/candles/orders/posts**. Private atomic bundle; exact old-fill identity check. `--audit` is offline. NOT 2020–2024 fees or forward confirmation. |
| `research/export_oanda_history.py` | 2020–2024 NAS100_USD practice M1 quote source; private per-batch provenance, checksum and gap audit | **Dry-run default**; `--fetch` performs at most 10 practice-candle GETs, no retries/orders/posts. `--audit` is offline. NOT the old NSXUSD CSVs. |
| `research/backfill_oanda_history.py` | Controlled, resumable approved five-year quote backfill into checksum-audited small private batches | **Dry-run default**; explicit `--year/--max-requests/--fetch` permits up to 262 practice GETs per year/run; no retries/orders/posts. Saved days never refetched. |
| `research/audit_oanda_history_baseline.py` | Distinct **hypothetical** 2020–2024 OANDA-feed -25/+75 baseline and quote exclusions | **No network**; writes ignored private `historical_baseline.json`; NOT old-vendor parity or validated historical fills. |
| `research/run_historical_exit_study.py` | Frozen nine-rule retrospective 2020–21→2022, 2020–22→2023, 2020–23→2024 paired diagnostics | **No network**; re-audits saved source/baseline, writes ignored private `rolling_exit_study.json`; no ranking, new live rule or posts. |
| `research/audit_historical_execution.py` | Post-hoc mechanism, quote-gap calendar/halt context and modeled unit/fee audit of the existing study | **No network**; writes ignored private `execution_audit.json`, keeps the frozen sample/rules unchanged. No fill certification, fee estimation, ranking or broker-order test. |
| `research/audit_backtest_parity.py` | Offline baseline and optional saved Cloud session-balance audit | **No network**; updates ignored private `baseline.json`. |
| `research/run_exit_study.py` | Nine predeclared exits on private candles; insufficient-history Monte Carlo gate | **No network**; writes ignored `exit_study.json`, does **not** pick/deploy a winner. |
| `research/fetch_session.py` | Legacy single-day **mid-only** replay CSV fetcher | OANDA GET; obeys configured environment, so check `.env` first. Does **not** place orders; `REPLAY_TWEETS=true` in a *separate* replay command posts to X. |
| `account/list_accounts.py`, `account/verify_account.py` | Read account identity/balance/margin | OANDA GET; **prints private account information**. |
| `assets/generate_example_assets.py` | Regenerate illustrative charts | Writes tracked `docs/assets/` images; no X posts. |
| `deploy_cloud_run_job.sh` | **Production deployment entry point (path intentionally unchanged)** | Builds and deploys image, changes Cloud resources/secrets/scheduler; may incur cost. Never run for offline analysis. |
| `analyze_json_logs.py`, `run_analysis_cron.sh` | **Legacy posting/cron entry points (paths intentionally unchanged)** | `analyze_json_logs.py` **posts to X** and may use paid API credits. Do not use for research or run as a smoke test. |

See [`../research/README.md`](../research/README.md) for the predeclared exit-study protocol. Research artifacts under `data/` and `reports/` are Git- and Cloud-Build-ignored; never move private trade exports into this script tree.
