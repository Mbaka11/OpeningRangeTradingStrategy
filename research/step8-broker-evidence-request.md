# Step 8 — request missing broker evidence (**draft only; gate still open**)

The user does not know the legal entity named in their agreement. We will **not infer it** from their country, account ID, instrument name, API host or another regional website. The [step-7 snapshot](step7-current-cost-evidence.md) supports current/recent observations only. No further authenticated reads, broker messages, orders, account changes, Cloud executions or X posts were made for this step.

## Copy-ready request

Send this yourself through OANDA's **official signed-in support channel**. No account number or API token belongs in this public template; identify the relevant practice account privately within that channel if needed.

> **Subject: v20 practice NAS100_USD — applicable entity and dated instrument/cost evidence**
>
> I use the v20 API with a USD practice account and `NAS100_USD`. I am evaluating 2020–2024 historical bid/ask candles offline, but do not want to assume today's terms applied in those years or that demo and live execution/costs are identical.
>
> Please help establish:
>
> 1. **Entity/platform:** the legal entity or division serving this practice account, whether a demo account has a contractual counterparty at all, and which offering the v20 `NAS100_USD` history represents. If the account or offering did not exist in some of 2020–2024, please say so; do not substitute another regional/platform product.
> 2. **Dated specifications and fees:** applicable 2020–2024 instrument specification/fee documents or written confirmation, with effective dates and any changes. Please cover USD per index-price point per v20 unit, unit precision/minimum size, per-fill commission/minimum charges (including partial closes), and financing/dividend/other adjustments and booking times. Also distinguish practice reporting from applicable live charges.
> 3. **API omissions versus zero:** today's instrument response omitted `commission` metadata, while sampled practice `ORDER_FILL` records explicitly report zero commission, financing and guaranteed-execution fees. What can these fields establish about the account's tariff? Can demo values or omitted fields differ from the actual fee schedule? Please clarify nonzero guaranteed-fee cash-sign conventions and any separate charges not recorded in these fill fields.
> 4. **Historical quote context:** archived NAS100 hours/holiday schedules and known quote interruptions/halts for 2020–2024, with timezones. In particular, did the March 9/12/16/18, 2020 US cash-market circuit breakers affect this CFD feed, and how are minutes without quotes represented? A cash-equity holiday calendar is not sufficient to establish CFD availability.
>
> Please provide dated references or explicitly identify what cannot be established from available records. Current pages alone cannot certify historical terms; the historical candles are not proof of fills, liquidity or order latency.
>
> **Information only: please do not place, close, cancel or amend any order, or alter my account settings.**

## What to bring back safely

Only the **legal entity/offering name, relevant public document URLs, effective dates and redacted technical answers** are needed here. Do not paste account IDs, tokens, names/addresses, balances, statements, transaction histories or unredacted support correspondence into chat/Git. Keep full correspondence locally under ignored `data/raw/oanda_research/` if needed; ignore rules are not local access controls. We have not contacted support or shared any private evidence on your behalf.

For each answer, distinguish:

| Evidence | Acceptance boundary |
| --- | --- |
| Current entity/division or demo routing | Identifies the offering to research; does **not** attest its 2020–2024 existence or terms. |
| Dated contract/fee documents or explicit broker confirmation | Record platform, entity, instrument/unit mapping, practice/live distinction and exact effective dates. A missing year remains unknown. |
| Omitted API field explanation | Scope to the relevant account/API version. Do not retroactively convert every omission into zero. |
| Historical hours/outage records | Match timezone and dates; contextualize gaps without fabricating missing candles or fills. |
| Unsupported or unavailable historical evidence | Record **unverified/unavailable**; do not replace it with another region's tariff. |

The research gate remains **unresolved**, not passed by drafting this request. If reliable archival evidence is unavailable, the five-year USD/cost study remains hypothetical; any proposal to pivot to a current-terms prospective study requires a separate decision and must not call the old years an untouched holdout. Alternative partial fills/stop amendments still need separately authorized, crash-safe execution validation. The missing original `NSXUSD` vendor files also remain a distinct blocker.

**The practice 25/75 bot, frozen research sample/scenarios and X cadence are unchanged. No winning exit or broker test is authorized here.**
