# Step 1: private broker evidence and baseline parity (2026-09-26)

This step is **read-only**. The research exporter never invokes the Cloud Run Job, OANDA order/close/amend endpoints or X. The live bot and its 25/75 rules remain unchanged.

## Run and re-check

From the repository root, with the existing **practice** credentials in local `.env` (or `DOTENV_PATH`):

```bash
python scripts/export_oanda_research.py --start 2026-08-20 --end 2026-09-24
# After editing only the offline reconciliation logic, no network/token required:
python scripts/export_oanda_research.py --recheck 2026-08-20_2026-09-24
```

Use completed **New York** dates only, no more than 62 calendar days at once. The exporter refuses live credentials, untrusted transaction-page URLs, redirects, overwrites of an existing export, and non-ignored output paths. On transient failure it retries GET only; if it still fails, it does not save a new export. `--recheck` recalculates the report from previously exported private files without network calls. To extend the sample later, use a **new** nonoverlapping date range.

**Local private outputs (never stage/push/share):** `data/raw/oanda_research/START_END/{fills,candles,parity}.json`. Fill records contain only transaction/trade IDs, fill reasons, fill prices, size and realized trade P&L; no account ID or token. Candles contain M1 mid, bid and ask. Even these sanitized files are sensitive account history and are protected by `.gitignore`, `.dockerignore`, and `.gcloudignore` (the last prevents uploads to Cloud Build source archives). `git status --short` should not show them. Git only contains this procedure, the exporter, the pure reconciliation code and offline tests.

The script gets time-bounded OANDA practice transaction **page URLs** and each page via HTTPS GET; it queries M1 `price=MBA`, `smooth=false` from 09:00 to 12:10 NY for each weekday. It does not fetch tick-by-tick spreads or reconstruct activity outside the requested dates. Reconcile on broker `tradeID` and *per-trade* opening/closing prices; the old OANDA top-level fill price is deprecated. The baseline simulation starts on the first full minute after the actual fill (the entry minute can be ambiguous), uses **bid for a long exit and ask for a short exit**, and excludes the 12:00 candle (which covers price action after the hard exit). A missing/incomplete bar or same-bar stop/target tie is **unknown**, not assumed profitable. A market close near noon is only a `candidate_match`, not proof the bot requested the close.

## First read-only observation

A completed export for **Aug 20–Sep 24, 2026** (26 NY weekdays) retrieved **4,940 candles, 46 order-fill transactions, 23 opened-and-closed trades** on the configured practice instrument. Exit-reason/minute-path audit: **21 matches, one candidate noon market-close match, zero definite mismatches, one unresolved exit inside the entry minute**. Matched stop/target fill prices differ from nominal 25/75 levels by roughly **−1.7 to +0.4 points**. These are *classification* checks, not a verified P&L parity or an estimate of future performance. The report remains private; no account transaction IDs or raw records are committed.

## Limitations and next gate

- The comparison uses one-minute bid/ask OHLC, **not** tick sequence; it cannot resolve a stop inside the entry minute, simultaneous touches, true broker order amendments, or a market order's initiator. `smooth=false` is not identical to the live polling feed (`smooth=true`). A matched exit reason does not prove that hypothetical partials/stop adjustments would execute at these highs.
- We still need to audit *all* no-trade/skipped session logs, account balance vs. total transaction P&L including other positions/financing, symbol/contract and dollar-per-point mapping, missing days, and historical 2020–2024 raw-data provenance. Avoid counting other same-instrument discretionary trades as strategy trades (multiple same-day trades are flagged). A recent 23-trade sample alone cannot establish a new strategy edge.
- **Next:** build an explicit-parameter historical simulator and synthetic tests proving a change in SL/TP/entry/zone changes simulated behavior; reproduce the current historical baseline, then validate broker USD/point and costs. Only after those gates should we run the predeclared `research/experiments.yml` and paired Monte Carlo. No new live/paper exit rule is approved by this report.

API reference: [OANDA v20 transaction pages / ID ranges](https://developer.oanda.com/rest-live-v20/transaction-ep/); [OANDA v20 fill fields](https://developer.oanda.com/rest-live-v20/transaction-df/).
