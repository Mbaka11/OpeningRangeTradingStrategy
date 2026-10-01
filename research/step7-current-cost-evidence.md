# Step 7 — current metadata and recent observed costs (**not historical fee validation**)

The user explicitly authorized **at most eight OANDA PRACTICE GETs, no retries**, to check current account-scoped `NAS100_USD` settings/currency and recover cost fields for the **already-inspected 2026-08-20–2026-09-24 window**. This is not an untouched forward sample or a broker-order test. No candles, orders, stop amendments, Cloud job execution, X posts, live configuration, frozen exits, historical primary sample or cost scenarios are changed. API billing is **not independently verified**; no promise of $0.

## Why another narrowly bounded export is necessary

The original recent export kept **46 fills** but deliberately omitted `commission`, `financing`, `guaranteedExecutionFee` and `halfSpreadCost`. Omitted fields are **unknown**, not evidence of zero costs. Public regional fee pages and today's instrument metadata cannot establish this account's **2020–2024** terms. The new evidence collector retains selected cost fields while requiring every original fill ID/time/reason/price/unit/realized-P&L field to match the old saved export exactly.

## Safe entry point and private evidence

```bash
# Default: local preflight only, zero credentials/HTTP/writes.
python scripts/research/export_oanda_cost_evidence.py --folder 2026-08-20_2026-09-24

# Only after explicit authorization for this window:
python scripts/research/export_oanda_cost_evidence.py --folder 2026-08-20_2026-09-24 --fetch

# Recheck the generated snapshot bundle entirely OFFLINE (use the local bundle name):
python scripts/research/export_oanda_cost_evidence.py --audit START_END_snapshot_TIMESTAMP
```

The reader allows only practice account summary (retains **currency only**), the requested current instrument, the bounded transaction index and validated same-account transaction pages. Ambient proxy/`.netrc` authentication is disabled so it cannot redirect routing or replace the explicit Bearer header; unexpected URL path parameters are rejected. Failed requests consume the budget; no automatic retry, fallback, redirect following or extra pagination beyond **eight total attempts**. The documented `TransactionFilter` enum omits some newer transaction types, so the bounded date index is unfiltered, as in the old exporter; only target-instrument fills, allocated daily financing and dividend adjustments are retained. Funding/admin events, foreign instrument details, account IDs/user IDs, aliases, balances, credentials and raw responses are discarded, never saved or printed.

A unique, atomic ignored bundle under `data/raw/oanda_research/cost_evidence/` contains `snapshot.json`, `cost_audit.json` and SHA-256/source provenance. All requests, sanitization, old-fill identity checks and arithmetic must pass before publishing the bundle. Earlier exports and studies are **never overwritten**. `--audit` verifies both saved hashes, source code, the prior fill hash/identities and a fresh offline recomputation; it does not load credentials, send requests or replace evidence. Ignore rules prevent normal Git/Docker/Cloud inclusion, **not** access by other local users—do not share/upload these files.

## What the audit can and cannot establish

- **Field-level presence:** count explicit zero/nonzero versus missing/null for each reported component. Zero observations concern those records only; they do not certify a universal or historical tariff.
- **Signed components:** OANDA defines commission as a positive home-currency debit magnitude; financing can be paid or collected. Known fill components use top-level P&L **plus signed financing minus commission**, once. Missing components withhold that calculation. A nonzero guaranteed-execution fee also withholds a cash estimate pending confirmed sign conventions; we do not guess. Even complete components are **not a full account-balance/invoice reconciliation**.
- **No double charging:** nested realized P&L/financing/guaranteed-fee/half-spread values cross-check top-level totals; do not add/debit both. `halfSpreadCost` is a signed diagnostic already reflected by executable fill prices, **not another spread charge to subtract**.
- **Recent price × units:** join actual opening/closing trade legs using official trade-level prices, not the deprecated top-level fill price. Cumulative closing units are checked, including valid partial reductions; unknown entries or mismatched P&L are flagged, and inconsistent/overclosed units are refused. A recent USD match is evidence for that observed sample, not continuity of a 2020–2024 CFD multiplier.
- **Instrument versus bot:** daily financing is kept only from an explicit NAS100 position allocation; dividend events only for NAS100. Missing allocation is not silently zero; account-level amounts are not assigned to this strategy. Instrument-specific adjustments can concern other trades and are **not automatically bot-attributed**.
- **Current constraints:** precision, minimum size and a positive maximum order size can contextualize 80/40 model units. Absent/zero maximum or incomplete commission metadata remains unknown. Nominal current per-fill commissions are algebraic metadata checks, **not executed partial-order fees** or archival terms. Legal entity is not inferred from account ID or the instrument's “US” name.

Source definitions: [OANDA account endpoints](https://developer.oanda.com/rest-live-v20/account-ep/), [instrument/commission primitives](https://developer.oanda.com/rest-live-v20/primitives-df/), and [fill/trade/financing/dividend transaction definitions](https://developer.oanda.com/rest-live-v20/transaction-df/). These document schemas/semantics, not this account's past contractual fee schedule or counterfactual fills.

## Collection outcome

The authorized collection completed with **4 GETs out of the 8-attempt ceiling, zero retries**. All **46/46** original fill identities/prices/units/realized-P&L records matched exactly, and **23/23** joined closing legs again matched price difference × observed units in USD. The saved bundle then passed a zero-HTTP offline checksum/source/identity/recomputation check.

| Reported fill field | Explicit zero records | Explicit nonzero records | Missing/null records |
| --- | ---: | ---: | ---: |
| Commission | 46 | 0 | 0 |
| Financing at fill | 46 | 0 | 0 |
| Guaranteed-execution fee | 46 | 0 | 0 |
| Half-spread diagnostic | 0 | 46 | 0 |

This closes the **missing-field evidence gap for these specific fills**, not the historical tariff or execution gates. All 46 fills have the components needed for the limited reported-fill arithmetic; we still do **not** claim complete account balance/invoice reconciliation or zero trading cost. Nonzero half-spread diagnostics are kept separate, not charged again over executed prices. The bounded response contained **zero target-instrument daily-financing allocations, zero target dividend events and zero unattributed nonzero/missing-allocation financing events**; this does not prove future or historical adjustments cannot occur.

Today's USD NAS100 instrument metadata supports **80 and 40 units** under the returned precision/minimum/positive maximum-order constraints, but **no order was tested**. The instrument response omitted its commission structure, so current tariff metadata remains **unknown**, even though the sampled fills explicitly report zero commission. Legal entity, historical contract/fees/hours, alternative partial fills and stop-amendment latency remain unresolved. No measured amounts, fee estimates or current metadata were substituted into the predeclared historical scenarios.

## Remaining historical and execution gates

The current/recent snapshot cannot close the step-6 historical or amendment/partial-order gates. Because the user does not know their agreement's entity, [step 8](step8-broker-evidence-request.md) supplies a copy-ready support request and redaction/evidence boundaries; **it has not been sent and passes no historical gate**. Seek **private, dated evidence or written OANDA confirmation** for:

1. This account's legal counterparty/entity, v20 platform offering and **2020–2024** NAS100 contract multiplier/quote currency/units, precision/minimum-size changes and commissions/minimum fees. No other regional/platform tariff should be substituted.
2. Whether an absent cost field means unsupported/not reported/zero for the relevant API/account version; guaranteed-fee cash sign, financing/dividend booking modes and any separate adjustments not visible in fill components.
3. Archived entity-specific NAS100 hours/holiday schedules and quote availability/halts/outages for the 25 excluded historical days, with timezones. Cash-market calendars alone are not cause proof.
4. Before proposing any order test: completed-bar versus native/intrabar amendment semantics, actual positive-unit partial market close versus hypothetical limit partials, remaining protective order behavior, replacement rejection/immediate-fill handling and durable idempotent read-back after lost responses.

Keep account IDs, tokens, balances, statements and transaction histories private. Only after credible semantics/cost evidence and independent retrospective/multiple-comparison review could a candidate and genuinely new forward shadow protocol be frozen for a separate decision. **No winning exit, additional trading process or production promotion follows from this snapshot. The practice 25/75 rule and X cadence stay unchanged.**
