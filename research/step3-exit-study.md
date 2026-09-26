# Step 3 — offline candidate exit engine, **not** a strategy change

The research scripts were grouped under [`../scripts/README.md`](../scripts/README.md); Cloud deployment (`scripts/deploy_cloud_run_job.sh`) and legacy paid X analysis (`scripts/analyze_json_logs.py` / cron) stay at their existing locations. **No production bot, config, Cloud Run Job, schedule, OANDA order, or X posting behavior changes.**

## Purpose / inputs / outputs

- **Input:** ignored, private step-1 `candles.json` (OANDA M1 mid/bid/ask), `parity.json` (definite broker exit checks), step-2 `baseline.json` (signal & broker P&L reconciliations), and versioned [`experiments.yml`](experiments.yml) (nine predeclared exit rules). Original historical 2020–2024 minute CSVs are still **absent**.
- **Code:** pure offline `src/research_exits.py` and `src/research_uncertainty.py`, runner `scripts/research/run_exit_study.py`.
- **Output:** ignored, **private** `data/raw/oanda_research/START_END/exit_study.json` containing day-by-day hypothetical paths, cost cases, shared paired eligibility, counts and descriptive outcomes. Only the **counts/status**, never private trade paths or a winner, print to the console. The report is not pushed to Git or uploaded in Cloud Build.

From the repository root, after the step-1 exporter and step-2 baseline have completed:

```bash
python scripts/research/run_exit_study.py --folder 2026-08-20_2026-09-24
python -m pytest -q
```

The runner makes **no network requests**. It refuses to proceed unless all exported sessions' trade/no-trade signals and broker trade P&L pass the step-2 audit. An incomplete or unresolved practice broker exit is excluded from **every** candidate's paired comparison for that day; a candidate-specific same-bar ambiguity also excludes that day across **all** candidates in that cost case. No-trade days stay in the paired sample as zero-P&L days. Excluded/ambiguous counts and full private per-day records remain visible for audit—dropping these days can bias performance, so we do not infer profitability from the small clean subset.

## Exactly which rules are modeled

The matrix in `research/experiments.yml` (protocol **v2**, revised *before* the first candidate run to name explicit cost cases and sample-size gates; no target levels changed) tests: baseline 25-stop/75-target, fixed +40/+50, half-off at +30/+40 with the remainder at +75 or the original −25 stop, full-size +75 with stop moved to gross entry after +30/+40, trailing by 20 after +40 (full-size +75 TP remains attached), and a full 11:15 hard exit. Initial unit exposure, signal and OR do not change.

**Execution assumptions (not promises about OANDA):** signal is from a *completed* 10:22 mid candle; hypothetical entry is at the **next minute's** ask open for long, bid open for short. Exit barriers use the executable bid for long / ask for short. An existing stop takes priority when both stop and favorable threshold touch within a minute. A stop-market gap fills at the *worse bar open*; a target gets no favorable gap improvement. First partial size is rounded down to whole units. After a partial target, the runner's TP activates on the **next** bar; protective/trailing amendments take effect only on the **next completed minute**, never retrospectively in the activation bar. Trailing levels use previously completed candle extremes. Possible alternative intrabar ordering is flagged; one-minute OHLC cannot establish a true tick/limit-order fill, amendment timing, or the mechanics of placing OANDA partial orders safely.

Partial exits create an **additional closing fill**. The model deducts one fixed per-order fee on entry and on **each** exit. Protocol v2 specifies two *assumptions* rather than falsely labeling them broker-measured costs: `bid_ask_only` (observed candle spread, **zero extra** slippage/fee) and `adverse_extra_1pt_per_fill` (one adverse point at entry and exit plus $2 per order). These are not estimates of actual live partial-fill commissions, stop slippage, guaranteed-stop fees, financing or OANDA order amendment support; investigate cost realism before considering any production design. Example: half off at +30 then the other half at −25 yields only **+2.5 points gross** before extra fills/costs.

## Initial bounded smoke result — not an optimization

On the **26** NY weekday sessions exported for Aug 20–Sep 24, 2026: two trade days are excluded because step 1 could not definitively attribute/reconstruct their broker exits; another **five** have at least one policy with minute-bar ordering uncertainty. This leaves **19 clean paired sessions** (including no-trade days), **16 baseline trade days** spanning only **six calendar weeks**. Both cost cases trigger the *insufficient-history* gate. **No Monte Carlo probabilities, confidence intervals, rule ranking, deployment recommendation or claim of improved profits are issued.** The private file contains descriptive arithmetic for audit only, not a valid selection signal.

The paired week-block bootstrap is implemented and synthetically tested, but **requires at least 26 distinct calendar weeks and 100 baseline trade days** before producing descriptive uncertainty values. It resamples identical calendar-week blocks for baseline and candidate, preserving within-week order and no-trade days, and reports paired net/session and path drawdown quantiles under fixed seed/2,000 draws. Even when this gate passes, bootstrap intervals on previously tuned rules are **not** multiple-testing-corrected or evidence of future profit; walk-forward and a genuinely unseen prospective paper period remain mandatory.

## What must happen before choosing a new take-profit

1. Obtain and audit the original multi-year raw data; establish symbol/contract and bid/ask comparability and historical cost assumptions. If only mid CSVs exist, they cannot validate executable partials or trailing stops—source finer quote/tick data, bound fill outcomes, or leave conclusions inconclusive.
2. Run identical eligible dates for all nine rules across chronological development/validation periods; predeclare a final frozen candidate, consider costs/gaps/missing days and compare broad parameter robustness. The older cached notebook plots were invalid and have been cleared.
3. Collect sufficient **new** forward paper sessions to meet uncertainty gates; independently review any broker-side partial/stop amendment design, crash recovery, idempotency and X post cadence before seeking explicit approval for a deployed change. Research code must never submit or amend orders.
