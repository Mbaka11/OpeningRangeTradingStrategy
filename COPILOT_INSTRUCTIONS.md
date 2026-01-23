# 📘 COPILOT_INSTRUCTIONS.md

## Purpose

These instructions apply to **every prompt, task, and code change** in this repository.

Copilot (or any LLM agent) must:

- proceed in **phases**
- ask clarifying questions when needed
- never jump straight to implementation without a plan
- preserve existing functionality
- document all changes
- optimize for reliability and maintainability over speed

---

## 1. Development Workflow (MANDATORY)

Every feature or change must follow this lifecycle:

### Phase 0 — Repository Understanding

Before coding:

- summarize current repo structure
- identify entry points
- identify config handling
- identify secret management
- identify existing services/modules
- identify test setup
- identify deployment flow

Output:

- repo map
- dependency summary
- risk points
- where the new feature should live

---

### Phase 1 — Design & Planning (NO CODE)

Deliver:

- architecture proposal
- module responsibilities
- file tree
- interfaces between modules
- config/env changes
- DB schema or migrations
- error handling plan
- idempotency strategy
- test plan

Ask clarifying questions **before continuing**.

---

### Phase 2 — Minimal Vertical Slice

Implement the smallest working version:

- single happy path
- dry-run mode if relevant
- logs instead of destructive actions
- no premature optimization

Deliver:

- runnable code
- instructions to execute
- example output

---

### Phase 3 — Hardening

Add:

- retries
- validation
- edge-case handling
- deduplication
- rate-limit protection
- observability
- structured logs
- metrics if applicable

---

### Phase 4 — Expansion

Only after stability:

- enrichments
- ranking systems
- agents
- optimizations
- UI/UX
- automation improvements

---

### Phase 5 — Documentation & Review

Update:

- README
- architecture docs
- diagrams if needed
- `.env.example`
- changelog
- runbooks

---

## 2. Core Principles

### ✅ Preserve Existing Behavior

- Never break current features.
- Trading logic must remain isolated from new services.
- If refactoring is needed, justify it first.

---

### ✅ Ask Before Assuming

If anything is ambiguous:

- ask concise questions
- do not invent requirements
- do not guess data sources
- do not change APIs silently

---

### ✅ Configuration First

- thresholds, toggles, lists must live in config files
- secrets must be env vars
- provide `.env.example`
- no hard-coded credentials
- no magic constants

---

### ✅ Deterministic & Idempotent

- pipelines must be safe to rerun
- use fingerprints / hashes
- dedupe external events
- DB constraints for uniqueness

---

### ✅ Cost-Aware

- minimize LLM calls
- cache results
- batch operations
- log token usage when possible
- allow disabling LLM via config

---

### ✅ Production Hygiene

- structured logging
- typed interfaces
- error codes
- retry/backoff
- graceful degradation
- fail open only when safe

---

### ✅ No Silent Changes

Always report:

- files added/changed
- migrations added
- configs updated
- behavior differences
- breaking changes

---

## 3. Coding Standards

- Python only unless approved otherwise
- type hints required
- dataclasses / pydantic for schemas
- no large functions (>80 lines)
- pure functions when possible
- side-effects isolated
- consistent naming
- avoid global state

---

## 4. Testing Rules

Every module must include:

- unit tests
- mocked network calls
- sample fixture files
- parser test cases if PDFs involved
- integration tests for pipelines
- dry-run mode for tweeting/posting

Coverage should focus on:

- parsing correctness
- filtering
- deduplication
- error paths
- config loading

---

## 5. LLM Usage Rules

When integrating LLMs:

- outputs must be structured JSON
- schemas validated
- retries on malformed output
- strict prompts
- temperature conservative
- no hallucinated facts
- explicitly state uncertainty
- never fabricate filings, trades, or prices

---

## 6. Git & PR Discipline

Each change must include:

- atomic commits
- descriptive messages
- updated docs
- migration notes
- rollback plan if relevant

---

## 7. Security Rules

- never log secrets
- sanitize logs
- validate external inputs
- treat PDFs as untrusted
- sandbox parsers
- pin dependency versions
- document new dependencies

---

## 8. Prompt Behavior Rules

Copilot must:

- summarize understanding before acting
- restate goals & constraints
- list risks
- confirm assumptions
- ask questions at phase boundaries
- never output large code dumps unless explicitly asked

---

## 9. When in Doubt

Default to:

- simpler architecture
- fewer dependencies
- smaller steps
- slower rollout
- more logging
- stronger validation

---

## 10. Final Output Format

For every response:

1. What you understood
2. What phase we are in
3. What you will deliver next
4. Questions blocking progress
