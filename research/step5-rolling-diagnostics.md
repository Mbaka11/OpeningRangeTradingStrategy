# Step 5 — five-year rolling-origin diagnostics, **no new trading rule**

**Protocol frozen first:** [`rolling-origin.yml`](rolling-origin.yml) was committed as `28484ff` **before** the nine-policy historical run. It fixes the retrospective windows **2020–21 → 2022**, **2020–22 → 2023**, **2020–23 → 2024**; every candidate, threshold, initial risk and both modeled cost cases are checked against the predeclared [`experiments.yml`](experiments.yml). We did **not** choose the best policy in the development windows before inspecting an independent future year: prior 2020–2024 notebook results had already been viewed and old CSV results are invalidated. All three windows are **retrospective diagnostics**, not an untouched holdout or a reason to change the live bot.

## How to reproduce locally (OFFLINE)

```bash
# First complete the private 2020–2024 OANDA quote backfill and offline baseline from step 4.
python scripts/research/run_historical_exit_study.py
# If a private report already exists, review code/protocol changes before explicitly replacing it:
python scripts/research/run_historical_exit_study.py --replace-private
```

The runner re-audits **every** private history batch SHA-256, protocol/source fields and unique date, requires all 1,305 NY weekdays and an unchanged audited historical **25/75** baseline, then runs the nine policies on the complete 09:30–12:00 OANDA `NAS100_USD` mid/bid/ask minute bars. **No network, `.env`, historical broker fills, OANDA orders, Cloud job execution, X post, live configuration change, or policy selection.** Full day-level model paths and fold arithmetic are in **Git/Cloud-Build-ignored private** `data/raw/oanda_research/history/rolling_exit_study.json`; keep it private. The public code only prints counts and uncertainty *status*, not private trade P&L or a winner. For five private charts, use the blank [`../notebooks/07_historical_rolling_diagnostics.ipynb`](../notebooks/07_historical_rolling_diagnostics.ipynb) template via [`../notebooks/README.md`](../notebooks/README.md); it rechecks the saved local quote/baseline, frozen protocols **and simulator-code fingerprints** before charting. This check reads private quotes only to verify their hashes—no HTTP. If anything changed, review/re-run the offline study rather than trust stale plots. Never commit executed outputs.

## Same dates, two cost assumptions, adverse-first minute logic

For **each** cost case and **each** of the nine rules, use the identical signal and hypothetical next-minute entry. Compare paired **net per eligible NY session**, retaining genuine no-trade signals as zero. Reject a date across **all** policies and both cost cases if any requested minute quote is absent/invalid or any candidate flags minute-ordering ambiguity. Stop gaps fill at the worse bar open; partial closing legs incur an additional modeled per-fill fee. This is a **conservative common sample, not missing-at-random**: ambiguous days may be volatile and informative, so dropping them can bias results.

- `bid_ask_only`: historical candle bid/ask spread is included, **zero extra** slippage/commission assumed.
- `adverse_extra_1pt_per_fill`: **one extra adverse point at entry and each exit + $2 per fill**. These are **stress assumptions**, not observed OANDA historical commissions, actual partial-order fills or guaranteed stop execution. Bid/ask spread is **already in the feed**; don't add it again. Sample quoted 10:23 spread medians ranged from about 0.5 to 0.8 index points by year; the upper tail varied. Market quote spread is not total realized order cost or a validated $80/point contract mapping for every past year.

| Year | Requested weekdays | Primary clean paired sessions | Baseline trade signals in clean sample | True no-trade signals in clean sample | Quote exclusions | Any-policy minute ambiguity exclusions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2020 | 262 | 229 | 179 | 50 | 10 | 23 |
| 2021 | 261 | 231 | 186 | 45 | 5 | 25 |
| 2022 | 260 | 211 | 168 | 43 | 4 | 45 |
| 2023 | 260 | 234 | 177 | 57 | 3 | 23 |
| 2024 | 262 | 224 | 185 | 39 | 3 | 35 |
| **Total** | **1,305** | **1,129** | **895** | **234** | **25** | **151** |

All complete quote dates with a baseline signal total 1,046; **151 (about 14%)** were excluded from the *primary* comparisons for at least one candidate's minute-bar ordering uncertainty. These are **not** relabeled as losses, wins or no-trade days. After seeing this exclusion count, we added a **clearly post-hoc descriptive sensitivity** that retains those flagged days under the model's adverse-first/deferred-amendment assumptions: **1,280 modelled quote-complete days**, but no tick-order proof and **no best/worst fill bound**. This is **not a replacement for the predeclared clean paired sample**, nor a second opportunity to select a winner. If an apparent advantage depends on these exclusions, the result remains inconclusive until finer execution data or defensible bounds are available.

## What the fold/uncertainty output actually means

The evaluation-year primary samples contain **211 (2022), 234 (2023) and 224 (2024)** clean sessions. Their **52, 52 and 53** distinct calendar-week blocks and baseline trade counts (168/177/185) meet the predeclared minimum of 26 weeks and 100 trades, so the private report computes 2,000-draw *paired week-block descriptive* ranges for **each** candidate in original fixed order. It also records peak-to-trough drawdown, worst week/tail-day measures, additional closing fills and stop amendments. It is **not multiple-testing corrected** and is **not** a probability of future profit; it cannot repair previously inspected years, absent actual broker fills, minute OHLC ordering or uncertain cost/unit assumptions. We publish **no ranked performance table or recommended take-profit** from these data.

## Remaining gate before any strategy discussion

1. Independently check the 11 incomplete and 14 no-quote historical weekdays against actual OANDA market-hours/holiday records; confirm **2020–2024** CFD contract USD/point and realistic spreads/fees/slippage. Recover original `NSXUSD` vendor CSVs if reproducing old notebooks is required; OANDA history is a **different** dataset.
2. Resolve or bound **partial/stop amendment feasibility and the 151 ambiguous days** with finer quote/tick/execution evidence. M1 highs do not prove that a broker would fill those hypothetical orders; simulated gross entry-price stop is not net breakeven after costs.
3. Freeze a simple candidate **only after** evidence survives common-sample and inclusive sensitivity, credible costs, drawdown and multiple-comparison review; then collect genuinely **new** prospective paper sessions (the previously examined 2026 practice sample is not an untouched holdout). Any production change needs explicit approval, broker-side crash-safe stops, durable idempotency, and unchanged X posting cadence unless separately approved. **The live 25/75 practice bot stays unchanged.**
