# Step 2 — explicit baseline and account P&L checks (research-only)

**Purpose:** prove that changing a labeled backtest parameter actually changes its calculation, and verify that observed OANDA practice P&L agrees with fill prices/size. This step **does not choose or deploy a new exit rule**.

## Inputs → code → output

| Input | Code | Output |
| --- | --- | --- |
| Private, ignored `data/raw/oanda_research/START_END/{fills,candles}.json` from [step 1](step1-data-export.md) | `src/research_backtest.py` and `scripts/audit_backtest_parity.py` | Private, ignored `data/raw/oanda_research/START_END/baseline.json`: parameter snapshot, per-session signal/simulated exit, per-broker-trade USD check, aggregate counters. |
| Optional local, ignored `session_end_logs.json` with **filtered** Cloud Logging `SESSION_END` lines | `compare_cloud_balances` in the audit script | Account balance change vs. sum of OANDA realized P&L for covered days, inside the same private `baseline.json`. |
| Original older yearly CSV files (**not available in this checkout**) | `src/or_core.py` (historical, mid-only), `notebooks/04_parameter_robustness.ipynb` | Future rerun of the old baseline/sweeps; no historical ranking can currently be reproduced. |

Run against the already saved private export, **offline** (no new GET requests or token needed):

```bash
python scripts/audit_backtest_parity.py --folder 2026-08-20_2026-09-24
```

To check account changes as well, first obtain *only* session-end log entries while Cloud Logging still retains them. In a shell with an authenticated `gcloud` CLI **and the local private export folder**, run:

```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="opening-range-bot" AND textPayload:"SESSION_END" AND timestamp>="2026-08-20T00:00:00Z" AND timestamp<"2026-09-25T00:00:00Z"' \
  --project=onyx-seeker-479417-d5 --limit=100 --format=json \
  > data/raw/oanda_research/2026-08-20_2026-09-24/session_end_logs.json
python scripts/audit_backtest_parity.py --folder 2026-08-20_2026-09-24 --session-logs
```

Do **not** post/share `session_end_logs.json` or `baseline.json`; account balances are private. Both Git and Cloud Build ignore the entire `data/` directory. You can rerun the offline audit after simulator changes; it updates **only** the ignored `baseline.json` in that export folder.

## What the two simulators mean

- **New practice-data simulator:** `src/research_backtest.py` uses immutable `StrategyParams` (default OR 09:30–10:00 NY inclusive, completed 10:22 signal candle, zones .35/.35, 25-point stop, 75-point target, noon exit). It **requires every minute of complete M1 mid/bid/ask OHLC through noon**, rejecting missing/no-quote sessions instead of recording zero P&L. It selects a signal from mid candle closes, assumes execution at the *next minute's* ask open (long) or bid open (short), attaches fixed distances relative to that hypothetical fill, checks long exits on bid/short exits on ask, handles same-bar stop/TP conservatively (stop first **and flagged ambiguous**), and exits at the bid/ask **open** of the hard-exit minute. Optional per-side commission and adverse entry/exit slippage are explicit; default zero means a *baseline assumption*, not free real execution. The opening fill and intra-minute order sequence cannot be reconstructed exactly from M1.
- **Old CSV simulator:** `src/or_core.py` now takes explicit `entry_time`, `bot_pct`, `top_pct`, `sl_pts`, and `tp_pts` per `execute_day` call. Its earlier notebook changed different YAML keys while this module held risk values in import-time constants, so labeled sweeps could repeat the same baseline. `notebooks/04_parameter_robustness.ipynb` now passes overrides directly and no longer mutates `or_core.ENTRY_T`; the non-causal 10:00 entry (inside the inclusive OR) was removed. Synthetic tests demonstrate that each of entry time, both zones, SL and TP changes the expected signal or exit without changing globals. **Previously cached notebook plots/rankings were stale and have been removed; do not cite them from earlier Git revisions.** Old CSV bars are mid-only, with historical signal-close fill, so even rerunning them will not prove executable bid/ask performance; the newer OANDA simulator does not retroactively repair old vendor data.

## First audit, not a performance claim (Aug 20–Sep 24, 2026)

| Check | Observed |
| --- | ---: |
| Complete NY weekday sessions in private export | 26 |
| Simulated trade vs. no-trade direction agrees with broker activity | **26 / 26** (23 trade days, 3 no-trade days) |
| Broker realized trade P&L equals `(close price − open price) × signed units` within $0.01 | **23 / 23** (80 units each in this window) |
| Hypothetical next-bar-fill simulator vs. broker *exit reason* | **22 agree**, **1 noon market-close candidate**; 0 same-bar ties in this sample |
| Session balance change vs. broker realized trade P&L where filtered Cloud logs remain | **21 / 21** (includes no-trade sessions) |

The broker exit-path audit from step 1 is **more conservative** about exact hit timing: 21 stop/TP matches, 1 noon *candidate*, 1 unresolved trade closed inside its entry minute. The new 22-reason count includes that fast broker exit but does **not** establish its intraminute path or fill timing. Do not confuse signal/point-value consistency with a fully validated counterfactual exit strategy. The account-balance comparison covers only Cloud-retained session lines; historical session logs can expire. Other deposits, financing, positions or instruments in future windows would require separate attribution.

**Validation:** synthetic tests for parameter effects, causal minute gating, spread side, adverse simultaneous touch, DST, missing minutes, per-side costs, broker realized P&L and account changes; run `python -m pytest -q`. No changes to `opening_range_bot/run_bot.py`, Cloud Run Job, scheduler, trading config, OANDA orders or X posts.

**Next gate before studying +40/partial TP:** source and audit the original 2020–2024 minute CSVs (not present here); reproduce old baseline under known data/timezone/fee assumptions, document where mid-only CSV and executable practice bid/ask differ, and create a frozen prospective sample. Until then, 26 recent sessions and stale cached notebook outputs cannot justify an optimizer or a strategy promotion.
