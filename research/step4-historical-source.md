# Step 4 (in progress): historical *source* and quote-quality gate

**Decision:** The original 2020–2024 `DAT_ASCII_NSXUSD_M1_YYYY.csv` files are not in this checkout (nor are any other historical CSV/Parquet files). The user chose to investigate a **free historical source**. This step finds and audits **OANDA PRACTICE `NAS100_USD` M1 mid/bid/ask history**, keeping it separate from the missing `NSXUSD` vendor series. There is **no new profit result, no backtest winner and no live strategy/deployment/X change**.

## Source, license, and limits

- OANDA's [v20 API introduction](https://developer.oanda.com/rest-live-v20/introduction/) describes a free **practice/demo account** and historical price access. OANDA's own [v20 Python client](https://github.com/oanda/v20-python/blob/master/src/v20/instrument.py) confirms the **GET** `/v3/instruments/{instrument}/candles` endpoint and price components `M` (mid), `B` (bid), `A` (ask), `smooth` and `from`/`to`. The [API comparison](https://developer.oanda.com/rest-live-v20/api-comparison/) says up to 5,000 history records per page; the [development guide](https://developer.oanda.com/rest-live-v20/development-guide/) notes HTTP 429 above 120 requests/second and no more than two new connections/second. **The docs do not establish a separate price for every historical request or promise NAS100 existed in every year.** No invoice or account billing was checked during this practice pilot, so do not infer a guaranteed $0 cost for other account types or larger volumes. Do not expose the personal API token or publish raw quotes without reviewing OANDA's access/data terms.
- An alternative is Dukascopy's USA 100 Technical Index history, **not** the OANDA instrument nor the missing NSXUSD files. Its [XML-data terms](https://www.dukascopy.com/plugins/cont.php?ref_id=1273) include registration, noncommercial/non-redistribution conditions and a warning that derivative-index quotes are *statistical one-minute averages*, not official exchange index prints. Do **not** silently switch feeds or download/redistribute that product without checking which specific access license applies. No Dukascopy download was attempted.
- `config/instruments.yml` called the old vendor symbol `NSXUSD` with mid OHLC; the live practice bot trades OANDA `NAS100_USD` with different bid/ask, entry price, spreads, possible CFD settings and trading hours. **Do not rename or reshape OANDA prices into the old yearly CSV names, or claim the old notebook rankings have been reproduced.** New OANDA history can support a distinct, consistent modern simulator once we have broad quote coverage, provenance, cost models and chronological validation.

## Small bounded pilot (read-only)

One past weekday each on **2020-01-15, 2020-09-24, 2024-03-11 and 2024-09-24** returned **190** 09:00–12:10 NY one-minute records with `smooth=false`, including all **151** expected, complete, structurally valid mid/bid/ask candles for 09:30–12:00. This checks both winter/summer offsets and sample endpoint availability only. **Four deliberately sampled days cannot establish continuous five-year coverage or profitability**; US holidays, half days, outages, bad bars, and changed instrument specifications remain unverified. The pilots made no broker transaction queries, order requests, Cloud job executions or X posts.

Pilot data are local and **Git/Cloud Build/Docker ignored** under `data/raw/oanda_research/history/DATE_DATE/`. Each batch contains only `candles.json` (time/complete/mid/bid/ask) and `provenance.json` (no token, account ID, fills, balance or trade history). Provenance records endpoint, requested time/format, retrieval timestamp, SHA-256, **all** requested weekday quality flags and summary. No private data are committed or uploaded.

## Safely collecting / auditing a batch

The CLI is **dry-run by default** (zero credentials, zero requests) and rejects years outside 2020–2024, ranges longer than 14 calendar days, empty weekday ranges, and budgets above **10 authenticated GETs per invocation**. The default budget is **five GETs**. `--fetch` is explicit; it performs **one GET per weekday, zero automatic retries**, spaces requests, and aborts on HTTP errors without writing a partial batch. `--audit` runs offline, checks checksum, schema and all minute bars; a missing session is **not** recorded as a no-trade day. An existing batch is never overwritten/refetched automatically.

```bash
# Run from project root with OANDA_ENV=practice credentials in local .env:
python scripts/research/export_oanda_history.py --start 2020-09-21 --end 2020-09-25
# Only after reviewing the printed five-GET budget, intentionally fetch:
python scripts/research/export_oanda_history.py --start 2020-09-21 --end 2020-09-25 --max-requests 5 --fetch
# Offline check on an existing saved batch:
python scripts/research/export_oanda_history.py --audit 2020-09-24_2020-09-24
```

`src/research_history.py` audits session minutes 09:30–12:00 inclusive, duplicates, incomplete bars, malformed OHLC, crossed bid/ask opens/closes, response timestamps outside the requested NY window and weekends. Every weekday—including closures—gets an explicit status: `complete`, `incomplete`, or `no_session_data`. No synthetic candles, broker trade attribution, profitability, or policy ranking are produced.

## Outstanding gate / next decision

To evaluate 2020–2024 meaningfully would require **roughly 1,300 weekday historical requests** and potentially tens of megabytes of privately stored quotes, not the four pilots. The importer deliberately has **no one-command bulk mode**; additional batches require explicit bounded invocation (and any large-scale collection should be approved first for API load/storage/account terms). Then audit *all* planned calendar days and any missing/no-session days, check contract/spread and chronology, reproduce a **new OANDA-feed** 25/75 baseline, and only then consider comparable nine-policy rolling evaluations. Recovering the original vendor files remains necessary to reproduce the **old** notebooks. This step is **source discovery and data-quality proof-of-concept, not completion of historical validation**.
