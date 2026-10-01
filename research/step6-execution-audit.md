# Step 6 — execution, quote-gap and cost audit (**no rule selected**)

This is a **post-hoc diagnostic** after the step-5 exclusions were observed, not a new performance test, execution bound, altered primary sample or prospective validation. [`execution-audit.yml`](execution-audit.yml) records the scope and public calendar evidence levels. We did not change the frozen nine exits, two modeled cost cases, simulator, **1,129 clean paired days**, **151 flagged complete days**, or **25 quote exclusions**. The practice **25-point stop / 75-point target**, Cloud job and X cadence are unchanged.

## What was checked OFFLINE

```bash
python scripts/research/audit_historical_execution.py
# Only after reviewing changes, explicitly replace the ignored audit (not the original study):
python scripts/research/audit_historical_execution.py --replace-private
```

The runner rechecks all saved raw quote-batch SHA-256s, baseline/protocol/simulator fingerprints, source dates and quote-quality flags. It then audits the existing private `rolling_exit_study.json`; **no new OANDA calls, `.env`, broker/account history, orders, Cloud execution, X posts or candidate ranking**. It reconciles **23,040 policy-day ledgers** (1,280 quote-complete days × 9 rules × 2 cost cases), checking entry side/time/penalty, conserved units, chronological closing legs, weighted exit prices, gross-to-net arithmetic, additional partial-fill fees and flags. This establishes **internal model arithmetic only**, not actual execution. The ignored `data/raw/oanda_research/history/execution_audit.json` contains detailed local checks and quote-gap times; keep it private. Prior research reports are not overwritten.

## 1. Most flags concern **when a replacement stop would exist**

Unique NY dates across both costs and all rules; counts **overlap**:

| Flag mechanism | Unique days | What remains unknown |
| --- | ---: | --- |
| Working stop and target touch the same M1 bar (fixed/time rules) | 0 | No such tie in these saved modeled paths; not a proof of all fills. |
| Working stop and favorable activation/partial touch in one bar | 1 | Order of quotes/triggers and response latency. |
| Runner target crossed during the first partial's bar, deferred by model | 1 | Whether an actual runner order was installed and executable in time. |
| Entry-price replacement stop also touched the activation bar | 20 | Intrabar activation vs completed-bar amendment semantics. |
| Suggested trailing stop also touched its own update bar | 143 | Native tick-trailing vs completed-bar replacements and acknowledgments. |

The union of **amendment-timing sensitivity** is **150 of the 151 flagged days**. Under the frozen simulator, a new stop becomes effective **next minute**, so touching a *not-yet-installed* stop in the activation candle does not create two simultaneous working orders. These flags principally warn about changing implementation semantics, not a resolved causal broker sequence. A native OANDA trailing stop follows market prices, whereas the study's trail is recomputed from a **completed minute's** favorable extreme. They are **not interchangeable**. Even the delayed model assumes next-minute effectiveness without measuring network latency, rejects or stale price handling. We have **not** relabeled/reincluded any of these days in the frozen primary sample, optimized an alternate schedule, or quoted best/worst fill bounds. Clarifying semantics can narrow the question; it cannot certify the fills from M1 OHLC.

## 2. Quote gaps have contextual evidence, not established broker causes

Public **cash-equity** calendars are a reference, **not an OANDA NAS100 CFD trading schedule**:

- Of **14 no-session-quote days**, **11 coincide with holidays in transcribed official 2021–2024 tables**. Three 2020 dates fit standard New Year/Good Friday/Christmas hypotheses, but the earlier official notice returned HTTP 403; we explicitly mark the 2020 calendar **not independently transcribed**, not verified.
- Of **11 incomplete days**, two coincide with verified 2021 equity holidays and two with unverified 2020 holiday hypotheses. The other seven are not listed holidays in the corresponding reference/hypothesis calendar. Sparse CFD quotes on an equity holiday are not proof of the broker's closure hours.
- The [official NYSE market-wide circuit-breaker report](https://www.nyse.com/publicdocs/nyse/markets/nyse/Report_of_the_Market-Wide_Circuit_Breaker_Working_Group.pdf), printed pp. 4–5 (PDF pp. 5–6), documents **2020-03-09 09:34:13–09:49:13**, **2020-03-12 09:35:44–09:50:44**, and **2020-03-16 09:30:01–09:45:01**, Eastern Time. **15 of 19, 13 of 14, and 16 of 16** missing M1 candle *intervals*, respectively, overlap those cash-market halts. An interval may overlap only partly; these counts are **not halt durations**. There are gaps outside the halt intervals too.
- The **March 18** halt was **12:56:17–13:11:17**, **after** our noon flat; it cannot explain that day's missing **09:30 and 09:31** candles. The March 3 and two ordinary 2022 gap days likewise lack a matched halt in this reference. Do not casually label all March gaps circuit breakers or DST errors.

All **25 quote days remain excluded**; no interpolation, fabricated flat returns, calendar-based filter change or automatic re-fetch. Need OANDA's historical entity-specific hours and outage/quote records to establish causes. Current [OANDA holiday hours](https://www.oanda.com/uk-en/trading/holiday-trading-hours/) illustrate why cash exchange closure does not imply full morning CFD closure; current schedules do **not** attest 2020–2024.

Calendar sources: [ICE's 2021–2023 notice republished by Nasdaq](https://www.nasdaq.com/press-release/nyse-group-announces-2021-2022-and-2023-holiday-and-early-closings-calendar-2020-12) and [ICE's later 2022–2024 PDF](https://s2.q4cdn.com/154085107/files/doc_news/NYSE-Group-Announces-2022-2023-and-2024-Holiday-and-Early-Closings-Calendar-2021.pdf). The later PDF includes Juneteenth from 2022; the earlier notice did not. NYSE observes **no New-Year holiday for Jan 1, 2022** under its Rule 7.2, so we do not invent Dec 31, 2021 / Jan 3, 2022 closures. See the manifest for provisional 2020 references.

## 3. Modeled friction is not the broker's fee schedule

- Bid/ask quote spread is **already in** executable-side entry/exits; never deduct another full spread. Quoted opens and spread observations do not show depth, latency, partial-order fills or total realized costs.
- A split **40 + 40** closing position incurs unit-weighted point drag on **80 total units**, not 160, while the extra *flat per-order* fee is charged for each closing leg. Both cases reconcile to their declared arithmetic.
- Entry slippage changes the **filled entry and attached price levels**. The second frozen cost scenario is therefore not merely the first case minus a constant cash charge; modeled exit times/structures can change. The audit records that distinction without ranking outcomes.
- A stop at the **filled entry price** is gross breakeven only. Educational arithmetic under the stress assumption (80 model units, 1 exit-slippage point, $2 per side): a full close at that nominal trigger nets **−$84**, not zero; a **1.05-point** favorable offset would offset *those exact modeled exit/flat fees*, ignoring any other charges. Entry slippage is already inside the entry fill and must not be charged again when measuring break-even **from that fill**. These are algebraic examples, **not a proposed stop rule** or historical account result.
- OANDA's [order definitions](https://developer.oanda.com/rest-live-v20/order-df/) state a dependent TP closes at a price **“equal to or better than”** its threshold, an ordinary SL **“equal to or worse than”** its threshold. Penalizing modeled TP prices below their trigger with one adverse point is an **extra cost stress**, **not an admissible resting-TP fill reconstruction**. A market partial close after noticing a touch has different latency/slippage semantics. An ordinary dependent SL is not guaranteed and does not expose the entry-STOP order's `priceBound` cancellation mechanism.
- Current [UK instrument/hours tables](https://www.oanda.com/uk-en/trading/hours-of-operation/) display US Nas 100 currency USD and lot/unit equivalence; they do not independently establish this account's **2020–2024** contractual USD/point/unit mapping or fee plan. The recent practice fill-price × units parity is evidence for that **recent sample**, not five years of historical terms. No legal entity is inferred from the instrument's “US” name; regional/platform tariffs must not be silently substituted.

## 4. Current API capability is not a tested partial-order implementation

The [v20 trade endpoint](https://developer.oanda.com/rest-live-v20/trade-ep/) documents partial market closes with **positive close units for long AND short trades**, `tradeReduced` versus `tradesClosed`, and dependent-stop replacement. It does not make a hypothetical half-position TP limit leg identical to noticing a price touch then submitting a market close. A dependent TP is trade-specific, not a demonstrated two-tier partial TP mechanism; splitting entries would be another experiment with additional costs/state.

Partial close and a following stop replacement are **separate requests**, not one documented atomic operation. Omitted stop fields leave the order unchanged; `stopLoss: null` cancels it. Replacement responses can contain cancellation, creation, immediate fill/cancellation or reject evidence. [Transaction batches](https://developer.oanda.com/rest-live-v20/transaction-df/) are applied simultaneously, but this is not proof of exactly-once retries. A lost response is an **unknown outcome**, not permission to repeat an order. Before any broker-side test or deployed amendment, require durable intents/idempotency and read-back reconciliation, retained crash-safe protection, unit/precision/minimum-distance checks and partial-vs-full-close race handling. **No such order tests or infrastructure changes were authorized or performed here.**

## Next safe gates

The separately authorized [step-7 current/recent cost snapshot](step7-current-cost-evidence.md) obtains selected account-scoped metadata and previously inspected fill-cost fields. It can improve recent evidence, but does **not** establish the 2020–2024 terms or test broker-side amendments/partials.

1. Obtain entity/account-specific **historical** NAS100 specifications, commissions/adjustments and hours/outage records (private evidence or OANDA confirmation). Current public docs cannot close these gates. Finer quotes/ticks alone still do not prove request latency or partial fills.
2. Before testing an alternative, explicitly specify **completed-bar vs intrabar/native** amendments and partial market-vs-limit semantics, then propose a separate authorized broker-practice test with crash-safe/idempotent protection. This is not authorization to amend existing practice trades or start another trading bot.
3. Once semantics/costs are credible, review the original primary and post-hoc inclusive evidence, multiple comparisons, and drawdown **without retuning the already-viewed years**. Any candidate freeze and genuinely new prospective shadow protocol need a separate decision. No winner, forecast probability, extra X posts or automatic strategy promotion follows from this audit.
