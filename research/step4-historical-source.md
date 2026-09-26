# Step 4: five-year quote collection and baseline — **not** a strategy selection

The user chose a free historical source and explicitly approved a **controlled full 2020–2024 OANDA PRACTICE quote backfill**. This is a **new `NAS100_USD` feed-based study**: the original `DAT_ASCII_NSXUSD_M1_YYYY.csv` vendor files are still absent. No production order, Cloud Run Job/schedule, X post or trading configuration was touched. No historical broker fills for 2020–2024 were downloaded, so historical outcomes are **hypothetical** and unverified against actual broker executions.

## Source, terms and provenance

- OANDA's [v20 introduction](https://developer.oanda.com/rest-live-v20/introduction/) describes a free practice/demo account and historical pricing. OANDA's [v20 Python client](https://github.com/oanda/v20-python/blob/master/src/v20/instrument.py) documents the **GET** `/v3/instruments/{instrument}/candles` endpoint and `M` (mid), `B` (bid), `A` (ask), `smooth`, `from`/`to`. Its [API comparison](https://developer.oanda.com/rest-live-v20/api-comparison/) says up to 5,000 history records per page; the [development guide](https://developer.oanda.com/rest-live-v20/development-guide/) lists HTTP 429 above 120 requests/sec and two new connections/sec. We used **one ~190-bar M1 `price=MBA`, `smooth=false` GET per weekday**, with one attempt per day and 0.55-second pauses across requests/batches. No separate per-candle price was identified in those docs, but **billing was not independently verified**; do not promise $0 for different account types or larger future usage. Review OANDA access/data terms before redistributing raw quotes.
- Dukascopy USA 100 Technical Index is an alternative **different feed**, not OANDA or the missing NSXUSD vendor files. Its [XML-data terms](https://www.dukascopy.com/plugins/cont.php?ref_id=1273) include registration, non-commercial/non-redistribution restrictions and a warning that derivative index quotes are statistical one-minute averages, not official index prints. No Dukascopy data were downloaded. **Do not silently mix feeds or relabel one as another.**
- `config/instruments.yml` calls the old research symbol `NSXUSD` with mid OHLC; the bot uses OANDA `NAS100_USD` with bid/ask and potentially different contract, history and hours. **Do not convert/rename the OANDA data into old yearly CSV filenames or claim old notebook rankings have been reproduced.**

## Collection, quotes and known gaps (locally audited)

Private source: `data/raw/oanda_research/history/`, ignored by Git, Cloud Build and Docker. Four bounded pilot sessions confirmed 2020/2024 winter/summer NY offsets before full collection. Then the read-only resumable annual backfill skipped those four; **1,301 additional** OANDA practice candle GETs were completed across **265 small private, atomic batches** (about **108 MiB** uncompressed). Every batch stores only `candles.json` (time/complete/mid/bid/ask) and `provenance.json` (source, time, parameters, all day quality flags, SHA-256); neither token, account ID nor broker trade history is saved. `index.json` is a private per-year coverage index. Re-auditing every batch verifies hashes, source parameters and unique NY weekdays. **All 1,305 calendar weekdays were requested**, including market closures; a requested day does not imply a complete market day.

| NY year | Weekdays requested | Complete 09:30–12:00 M1 MBA sessions | Incomplete quote sessions | No session quotes |
| --- | ---: | ---: | ---: | ---: |
| 2020 | 262 | 252 | 7 | 3 |
| 2021 | 261 | 256 | 2 | 3 |
| 2022 | 260 | 256 | 2 | 2 |
| 2023 | 260 | 257 | 0 | 3 |
| 2024 | 262 | 259 | 0 | 3 |
| **Total** | **1,305** | **1,280** | **11** | **14** |

A complete day has **151 consecutive one-minute bars** from 09:30 through 12:00 NY (inclusive), each flagged complete with structurally valid mid/bid/ask OHLC. All **11 incomplete** sessions have *missing minutes* (including some 2020 high-volatility/DST-adjacent sessions and partial holiday hours); the 14 no-session days may reflect exchange holidays, but need calendar verification. **Neither category is silently counted as a zero-P&L no-trade day**. No missing quotes are interpolated, no invalid quote-day partial trades are simulated, and no re-fetch is silently attempted. Minute OHLC cannot establish true tick ordering or hypothetical broker partial-order fills.

### Safe reproducibility commands (repo root)

```bash
# One year's planning: zero credentials, zero HTTP. Default hard limit is five requests.
python scripts/research/backfill_oanda_history.py --year 2020 --max-requests 262
# Only with explicit permission, <=262 GETs for ONE year, atomic <=5-day batches:
python scripts/research/backfill_oanda_history.py --year 2020 --max-requests 262 --fetch
# Safe resume: rechecks all saved hashes; already saved days are skipped, never re-requested.
# Inspect/re-audit a smaller existing batch entirely offline:
python scripts/research/export_oanda_history.py --audit 2020-09-24_2020-09-24
# Run the corrected OANDA-feed -25/+75 simulator on all audited sessions, OFFLINE:
python scripts/research/audit_oanda_history_baseline.py
```

The annual orchestrator (`scripts/research/backfill_oanda_history.py`) is dry-run by default, budgeted per run, and stops on any HTTP error; it never automatically retries, posts, sends orders or launches a Cloud job. The small importer (`scripts/research/export_oanda_history.py`) also remains useful for <=10 GETs per explicit `--fetch` run. Both refuse untrusted folders, other years/instruments, changed provenance or duplicate days. Outputs are private/ignored. For baseline reruns, review changes and specify `--replace-private` before replacing the existing private simulation.

## Distinct OANDA historical **baseline**, not old-vendor parity

Running `scripts/research/audit_oanda_history_baseline.py` offline with the current explicit `StrategyParams` (-25/+75, 10:22 completed signal, next-bar bid/ask open, 12:00 NY hard exit, 80 model units, **zero *extra* slippage/commission**) produced **1,046 hypothetical trade days, 234 true no-trade signal days, and 25 excluded quote days** across five years. No simulated trade had a stop-and-target same-minute tie in this baseline pass. The ignored `historical_baseline.json` contains per-day hypothetical paths, not observed fill proofs; only coverage/status counts print to the console. **Do not interpret dollar results as broker account history, live profit, or validated fees.** The recent 2026 practice fill audit (steps 1–2) is a different window and does not verify 2020–2024 fills.

## Gate before treating nine-policy comparisons as evidence

The retrospective nine-policy run and its exclusions are documented in [step 5](step5-rolling-diagnostics.md). It does **not** resolve the original-vendor, execution or prospective-data gates below.

1. Document actual historical **instrument specifications, spreads, quote coverage/closures, costs/slippage** and exclusions; inspect the 11 incomplete sessions and 14 no-session days against the market calendar. In particular, do not assume a 2020/2024 `NAS100_USD` CFD point and USD conversion identical to old `NSXUSD`.
2. Freeze chronological development/validation windows **before** comparing rules. Old historical notebook rankings were previously viewed and their underlying CSVs are absent, so 2020–2024 cannot be called an untouched holdout. Use identical eligible days, preserve no-trade days, stress costs and plausible same-minute ordering, and avoid automatically selecting the largest hypothetical result.
3. Use genuinely **new prospective paper sessions** and independent broker-side partial/stop amendment analysis before any proposal for live changes. Recover the original vendor files if old notebook reproduction is specifically required. No automatic strategy promotion, new paid posts or changed 25/75 practice rule follows from this backfill.
