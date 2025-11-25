# Opening Range Trading Strategy — NSXUSD (2020–2023)

> **Goal:** Present and rigorously test a simple Opening Range intraday strategy on NSXUSD (CFD/Index), with visuals that are understandable even for non-coders.

## TL;DR (to be filled after first pass)

- **Net performance (2020–2023):** _TBD_
- **Max drawdown:** _TBD_
- **Win rate:** _TBD_
- **Sample equity curve & drawdown:** _TBD (figure)_
- **Conclusion in one sentence:** _TBD_

---

## 1) Strategy Summary (plain English)

**Session window (market time):**

- **Opening Range (OR) window:** 09:30–10:00 (first 30 minutes after regular open).
- **Entry time:** **10:22** (exact minute; see open questions below).
- **Hard exit (time):** 12:00 (close any open position at market).

**Position logic (single trade per day):**

- Compute **OR High** and **OR Low** from 09:30–10:00.
- At the **entry time**, check where the price is relative to the OR:

  - **Long** if price is in the **top 35%** of the OR range.
  - **Short** if price is in the **bottom 35%**.
  - **No trade** if price is in the middle 30%.

- **Stops/Targets:**

  - **Stop Loss:** fixed **25 points**.
  - **Take Profit:** fixed **75 points**.
  - **Value per point:** **\$80**.

- **Forced exit:** Close any open trade at **12:00**.

**Capital:**

- Start with **\$100,000**. Update daily P\&L into equity curve.

**Configuration knobs (no code editing needed):**

- `config/instruments.yml` controls **market details** (point value, tick size), **session times** (OR window, entry, hard exit), **data format** (delimiter, datetime format, timezone) and **data-quality policies** (skip days with gaps, zero range).
- `config/strategy.yml` controls **signal logic** (top/bottom percentages), **risk** (stop/take-profit points), **execution assumptions** (one trade/day, fill rules), and **reporting metrics**. Open in any text editor; values are readable and documented inline.

> **Note:** We will finalize exact execution assumptions (use of OHLC for fills, slippage, fees, partial fills, tick size, timezone) before running the baseline.

---

## 2) Data Requirements

**Expected columns (semicolon “;” delimited, no header):**

```
datetime;open;high;low;close;volume
```

**Assumptions to confirm:**

- **Timezone of `datetime`:** currently treated as **America/New_York** (configurable via `source_timezone` if the CSV is in another tz).
- **Resolution:** 1-minute bars.
- **Session coverage:** Assume **regular session only**; pre/post is ignored. Set `has_premarket: true` if your data includes it.
- **Point definition & tick size:** Point value set to **\$80**; tick size currently `null` (set the minimum price increment once known, e.g., 0.25).
- **Holidays / half days:** Not encoded yet; half days will appear as missing minutes in QC.

We will create a small **data contract** validator in the data-audit notebook (column types, monotonic timestamps, missing bars, duplicated bars, session boundaries).

**Known quirks in the provided raw files:**

- Weekend gaps are expected (market closed). 2024 data is otherwise clean for intraday minutes. 2023 has extra intraday holes (missing 10:00-ish hours on some weekdays); consider backfilling before final stats.

---

## 3) Evaluation Metrics

- **Return:** Net P\&L, CAGR (if applicable), exposure/time-in-market.
- **Risk:** Max Drawdown, Ulcer Index, volatility, tail metrics.
- **Trade stats:** Win rate, Profit Factor, avg win/loss, expectancy.
- **Stability:** Performance by year/month/day-of-week/time-of-day.
- **Cost sensitivity:** Net vs. **fees + slippage** scenarios.
- **Robustness:** Parameter sensitivity (OR window, SL/TP), walk-forward, Monte Carlo re-ordering of trades.

---

## 4) Visuals (for non-coders)

- **Equity curve** and **drawdown** (same time axis).
- **Daily P\&L bars** with rolling stats.
- **Heatmaps** by weekday × time bucket (hit-rate / P\&L).
- **Distribution plots** (P\&L per trade, win/loss sizes).
- **Sensitivity lines** (e.g., SL/TP multiples, OR window alternatives).
- **Net vs. costs** curves.

All plots will include intuitive titles, units, and short captions.

**Reports folder structure (auto-created by notebooks):**
- `reports/tables/audit/` — data checks (`valid_days.csv`, `exclusion_log.csv`, schema/tz reports).
- `reports/tables/backtest/` — baseline backtest outputs (`backtest_daily*.csv`, summaries).
- `reports/tables/robustness/` — parameter sweeps (entry time, zones, SL/TP).
- `reports/tables/risk/` — performance/risk diagnostics (perf summary, MC reshuffle, regime stats).
- Matching `reports/figures/{audit,backtest,robustness,risk}/` for saved charts.

---

## Environment (for live/paper trading setup)

Create a `.env` (ignored by Git) from `.env.example` and fill in your broker creds:

```
cp .env.example .env
```

Variables:
- `OANDA_ACCOUNT_ID` — your OANDA account ID (use practice for paper).
- `OANDA_API_TOKEN` — API token for the account.
- `OANDA_ENV` — `practice` or `live` (start with `practice`).
- `OANDA_INSTRUMENT` — instrument symbol (e.g., `NAS100_USD`).
- `OANDA_TIMEZONE` — assumed local session timezone (default `America/New_York`).

Keep the `.env` file out of version control; `.gitignore` already excludes it.

### Suggested repo layout for live/paper bot
- `notebooks/` — research (keep as-is).
- `src/` — core strategy logic (reused by live runner).
- `config/` — YAML configs + `.env` for secrets (not committed).
- `live/` (new) — bot code:
  - `live/run_bot.py` — main loop (ingest prices, decide at 10:22, manage orders/flat at 12:00).
  - `live/broker_oanda.py` — thin OANDA client (paper/live toggle).
  - `live/data_feed.py` — OANDA candle/tick polling, UTC→NY conversion, minute bar assembly.
  - `live/logs/` — runtime logs; `live/state/` — checkpoints (e.g., last trade date).
- `scripts/` — helper scripts (deploy, restart service, download data).

### Deployment checklist (paper → live)
- Clock/timezone: sync NTP; convert OANDA UTC to NY; handle DST.
- Symbol mapping: `NAS100_USD` (or broker equivalent), tick size, min stop distance.
- Risk rails: one trade/day; skip if 10:22/12:00 missing or OR range ≤0; fail-safe flatten at 12:00; cap position size/daily loss.
- Logging/alerts: log every bar/decision/order/fill; alert on errors/missed exits; keep a heartbeat.
- Costs/size: use broker-accurate spread/fees in config; set fixed size or vol-based sizing if needed.
