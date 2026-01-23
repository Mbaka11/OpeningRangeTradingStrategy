# GovTrades Module Spec (Add-on to Existing Python Trading Bot)

## 0) Goal and constraints

### Goal

Add a **second, independent function** to the existing Python bot:

- Monitor official US government trade disclosures (Congress PTR filings)
- Extract qualifying transactions for **selected “top-tier” politicians**
- Generate a **single neutral, clinical informational tweet** per politician per new filing (or per “new event”), including:
  - The relevant trades (filtered)
  - Short context (past behavior / novelty / size / sector)
  - LLM-generated analysis summary + risk notes (no hype, no emojis)

### Non-goals (v1)

- No manual approval / no human in the loop
- No trading advice / no “BUY/SELL” recommendation language
- No spouse/dependent tracking (optional later)
- No options strategy deep dive (optional later)
- No paid data subscriptions (LLM tokens allowed; everything else free)

### Key constraints

- Runs as **separate service/module** from trading logic (does not “touch” the trading engine)
- Uses **one existing X/Twitter account** (already have API access)
- Uses free public sources (official House/Senate portals); aggregators may be used only as non-authoritative fallback if needed

---

## 1) High-level architecture

### Components

1. **Source Poller**

- Checks official disclosure portals on a schedule
- Detects “new filing posted” events

2. **Document Fetcher**

- Downloads filing documents (often PDF)
- Stores raw files (optional) and metadata

3. **Parser & Normalizer**

- Extracts trades from PDFs/structured pages
- Normalizes into a canonical `Trade` record schema

4. **Eligibility Filter**

- Filters by:
  - politician allowlist (“top-tier list”)
  - transaction type (v1: buys; optional ETFs/crypto)
  - amount threshold (configurable; e.g., ignore <$10k/$15k)

- Groups results by politician

5. **Context Builder**

- Pulls internal history from DB:
  - Has this politician traded this ticker before?
  - Recent activity frequency

- Optional: pulls free market metadata (sector, market cap proxy, price change since trade date) if available

6. **LLM Analyzer**

- Takes structured trade bundle + context
- Returns structured JSON: summary, bull/base/bear bullets, risk bullets, confidence score
- Strict neutral tone, no advice

7. **Tweet Composer**

- Produces one tweet per politician per filing:
  - header + trades summary
  - LLM summary (tight)
  - risk notes

- Must respect character limits; truncation rules

8. **X Publisher**

- Posts tweet
- Logs success/failure
- Retries with backoff on transient errors

9. **Storage (Postgres)**

- Prevent duplicates (idempotency)
- Keep history for context
- Track polling state / last seen filing

### Deployment

- Runs as a separate process/service on GCP (Cloud Run or VM cron is fine)
- Uses environment variables for secrets (X keys, DB URL, LLM key)
- Uses a config file for thresholds, lists, routing rules

---

## 2) Data sources (authoritative)

### Primary (authoritative)

- Official House disclosure portal (PTR filings)
- Official Senate disclosure portal (PTR filings)

### Optional (non-authoritative fallback)

- Public aggregators for discoverability only (do not treat as truth; always confirm via official filing before tweeting)

**Design requirement:** every tweet should include a reference to the official filing (URL or filing identifier) when possible.

---

## 3) Event model: what triggers a tweet

### Trigger

- A **new PTR filing** appears on an official portal

### Output granularity (v1 decision)

- **One tweet per politician per filing**
  - If a filing contains multiple trades for that politician, include only the trades that pass filters
  - If multiple politicians appear in one filing batch (rare depending on source), each gets their own tweet

### De-duplication rule

- A tweet is uniquely identified by:
  - (politician_id, filing_id, hash_of_filtered_trade_bundle)

- If the same filing is re-downloaded or amended:
  - If content changed materially, allow a new tweet labeled “amended filing” (optional later)
  - Otherwise skip

---

## 4) Canonical data model

### Politician

- `politician_id` (internal)
- `name`
- `chamber` (House/Senate)
- `party` (optional)
- `state` (optional)
- `committees` (optional, can be added later)
- `tier` (TopTier / Watchlist / Ignored)
- `aliases` (for matching inconsistent names in filings)

### Filing

- `filing_id` (source-derived stable ID if available)
- `source` (House/Senate)
- `posted_at` (time discovered)
- `document_url`
- `document_hash` (for change detection)
- `raw_storage_path` (optional)
- `parsed_status` (ok/failed)
- `failure_reason` (if any)

### Trade

- `trade_id` (internal)
- `filing_id`
- `politician_id`
- `trade_date`
- `posted_date` (if reported)
- `asset_type` (stock/etf/crypto/other)
- `ticker` (nullable if not available)
- `asset_name` (string)
- `direction` (buy/sell)
- `amount_range_min` / `amount_range_max` (nullable)
- `amount_band_raw` (original text)
- `notes_raw`

### TweetLog

- `tweet_id` (X tweet id)
- `filing_id`
- `politician_id`
- `tweet_fingerprint`
- `posted_at`
- `status` (posted/failed)
- `error_code` / `error_message`

### PollState

- `source`
- `cursor` / `last_seen_posted_at` / `last_seen_filing_id`
- `updated_at`

---

## 5) Configuration design (config.yaml + env vars)

### config.yaml (non-secret)

- `poll_interval_minutes`
- `amount_threshold_min_usd` (e.g., 15000)
- `asset_types_allowed` (stocks, etfs, crypto)
- `directions_allowed` (buy only v1)
- `max_trades_in_tweet` (e.g., 6; summarize remainder)
- `top_tier_politicians` (seed list)
- `watchlist_politicians` (optional)
- `politician_aliases` (matching)
- `llm_enabled` true/false
- `llm_trade_filter` (rules for when to call LLM)
- `tweet_style` (clinical, no emojis, no advice)
- `tweet_templates` (header/body structure rules)

### env vars (secrets)

- `DATABASE_URL`
- `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` (or OAuth2 variant)
- `LLM_API_KEY`
- optional: `RAW_DOC_BUCKET` if storing PDFs

---

## 6) External enrichment (free-only options)

### v1 recommended: minimal + robust

- Use only:
  - filing contents
  - internal DB history for politician/ticker novelty

- This is most reliable and cheapest.

### v1 optional enrichment (free, but can break)

- Price change since trade date (via free endpoints)
- Sector mapping (free static mapping by ticker, maintained manually)

**Spec principle:** external enrichment must be strictly “best-effort.” If it fails, tweet still posts with core filing info.

---

## 7) LLM Analyzer contract

### Inputs (structured)

- Politician profile snapshot:
  - name, chamber, tier, recent trading frequency

- Trade bundle:
  - list of filtered trades (buy-only v1)
  - novelty flags (new ticker for this politician?)
  - size bands

- Optional market/context snippets (if available)

### Output (strict JSON)

- `confidence`: integer 0–100
- `summary`: 1–2 sentences, neutral
- `key_points`: 2–3 bullets (why notable)
- `bull_case`: 1–2 bullets (neutral, “could indicate…”)
- `base_case`: 1 bullet
- `bear_case`: 1 bullet
- `risks`: 2–3 bullets (liquidity, concentration, timing, sector/regulatory risk)
- `limitations`: 1 bullet (“disclosures delayed; ranges not exact”)

### Tone rules

- No emojis
- No hype words (“moon”, “insane”, “guaranteed”)
- No explicit advice (“you should buy”)
- Allowed framing: “potential signal”, “worth monitoring”, “informational”

### Cost control rules

- Only call LLM if:
  - politician is TopTier AND
  - at least one trade above threshold AND
  - trade bundle is not empty

- Cache LLM results keyed by `tweet_fingerprint` to avoid re-charging

### Failure behavior

- If LLM fails:
  - Tweet still posts using deterministic template (no analysis), and logs “LLM unavailable”

---

## 8) Tweet composition rules (one tweet)

### Required content

1. Header:

- `{Politician} — New disclosed buys (PTR filing)`

2. Trades summary (compact):

- `BUY: TICKER (amount band) on DATE; ...`
- If > `max_trades_in_tweet`:
  - include top N by amount band max, then “+X more”

3. Context (from DB):

- `Novelty: first time disclosed in {ticker} (in our history)` OR `Repeat buy (seen before)`

4. LLM section (tight):

- `Summary: ...`
- `Risks: ...` (compressed)

5. Reference:

- `Source: official filing link/ID`

### Truncation strategy

- Hard priority order:
  1. politician + trades summary
  2. filing reference
  3. 1-sentence LLM summary
  4. risks bullets

If length too long, drop lower priority parts first.

---

## 9) Ranking / “Top-tier” selection (v1 hybrid)

### v1 approach

- Start with a **manual seed list** (TopTier)
- Add a **suggester** that proposes candidates (does NOT auto-add)
  - Suggestions are written to a DB table or logs for review later

### Suggester signals (free-only)

- Filing frequency / activity level
- Concentration of trades
- Repeated trading in “sensitive sectors” (defense/health/energy/tech) based on simple mapping
- (Optional later) committee relevance if you add that dataset

**Important:** v1 should not depend on committee datasets if it slows you down.

---

## 10) Reliability and safety

### Idempotency

- Every pipeline stage must be safe to rerun.
- Use `document_hash` and `tweet_fingerprint` to avoid duplicates.

### Retries

- Network downloads: retry 3x
- X posting: retry with exponential backoff on transient errors
- Permanent errors: log + store in `TweetLog` as failed

### Observability

- Structured logs: poll results, parse success rate, tweets posted, failures
- Simple metrics: #filings detected/day, #tweets/day, parse error rate

---

## 11) Development plan (AI-driven, step-by-step)

### Phase 0 — Repo & environment discovery (NO coding changes yet)

Deliverables:

- Current repo tree summary
- Where the existing Twitter posting logic lives
- How secrets/config are handled today
- Decide where the new service will live: `services/govtrades/` (recommended)

### Phase 1 — Architecture + interfaces (NO parsing yet)

Deliverables:

- Final module tree
- DB schema migration plan
- Config format
- Stub pipeline with dry-run output (prints composed tweet text, no posting)

### Phase 2 — Minimal vertical slice (authoritative source only)

Deliverables:

- Poll official source
- Detect one new filing
- Download PDF
- Parse enough fields to identify politician + at least one trade
- Store in DB
- Compose tweet in dry-run

### Phase 3 — Robust parsing + filtering

Deliverables:

- Handle multiple trades per filing
- Apply thresholds
- De-dupe
- Post to X for real

### Phase 4 — LLM integration

Deliverables:

- JSON output contract enforced
- Caching
- Fallback behavior

### Phase 5 — Suggester + polish

Deliverables:

- Candidate suggestion output
- Better context (novelty, frequency)
- Operational hardening (alerts/logs)

---
