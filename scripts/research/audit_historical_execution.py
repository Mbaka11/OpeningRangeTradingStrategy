"""OFFLINE post-hoc execution/quote-gap/cost-ledger audit of the saved study.

No OANDA requests, account records, secrets, orders, Cloud execution or X posts.
Does not change/recompute the frozen exit study or recommend a trading rule.
"""

from __future__ import annotations

import argparse
import json
import sys

import yaml

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research import run_historical_exit_study as study_runner
from scripts.research.export_oanda_research import ResearchDownloadError, _private_json, _safe_output
from src.research_execution_audit import ExecutionAuditError, audit_execution
from src.research_history import HistoryAuditError
from src.research_rolling import RollingProtocolError

CONTEXT = ROOT / "research" / "execution-audit.yml"
OUTPUT = study_runner.history.HISTORY_ROOT / "execution_audit.json"


def read_inputs() -> tuple:
    # This loader is OFFLINE: verifies all batch checksums, protocol and baseline
    # metadata. Importing a historical exporter does not invoke its --fetch path.
    market, quality, experiments, rolling, _, digests = study_runner.read_private_inputs()
    try:
        raw = study_runner.OUTPUT.read_bytes()
        context_raw = CONTEXT.read_bytes()
        study = json.loads(raw)
        context = yaml.safe_load(context_raw)
    except (OSError, ValueError, yaml.YAMLError):
        raise ExecutionAuditError("Missing or invalid saved study/context") from None
    if study.get("provenance_digests") != digests:
        raise ExecutionAuditError("Saved study fingerprints differ from current quotes/baseline/protocol/code")
    provenance = {"study_sha256": study_runner._hash(raw), "study_input_digests": digests,
                  "audit_context_sha256": study_runner._hash(context_raw),
                  "audit_source_sha256": study_runner._hash("\n".join(
                      f"{p}:{study_runner._hash((ROOT / p).read_bytes())}" for p in
                      ("src/research_execution_audit.py", "scripts/research/audit_historical_execution.py")
                  ).encode("utf-8"))}
    return market, quality, study, experiments, rolling, context, provenance


def main() -> int:
    parser = argparse.ArgumentParser(description="OFFLINE private execution diagnostic; no rule selection")
    parser.add_argument("--replace-private", action="store_true", help="Explicitly replace the ignored audit only, after review")
    args = parser.parse_args()
    try:
        _safe_output(OUTPUT)
        if OUTPUT.exists() and not args.replace_private:
            raise ExecutionAuditError("Private execution audit exists; refusing overwrite")
        market, quality, study, experiments, rolling, context, provenance = read_inputs()
        report = audit_execution(market, quality, study, experiments, rolling, context)
        report["provenance_digests"] = provenance
        _private_json(OUTPUT, report)
    except (ExecutionAuditError, ResearchDownloadError, HistoryAuditError, RollingProtocolError,
            ValueError, KeyError, TypeError, StopIteration):
        # Never print candle contents, hypothetical P&L, paths or account data.
        parser.exit(1, "Offline execution audit refused; check source/protocol/sample consistency privately.\n")
    print("Private execution diagnostic:", OUTPUT.relative_to(ROOT))
    print("Original primary sample unchanged:", report["original_clean_paired_days"], "days;")
    print("Original any-policy minute flags:", report["original_any_policy_ambiguous_days"], "days")
    print("Mechanism unique-day counts (overlap; not fill proofs):")
    for row in report["mechanisms_in_fixed_order"]:
        print(" ", row["reason"], row["unique_days_across_costs_and_policies"])
    print("Quote gaps remain excluded:", report["quote_excluded_days"], "; CASH calendar context only:",
          report["quote_gap_calendar_context_counts"])
    print("Modeled unit/fee ledgers reconcile; actual historical costs and executions remain unverified.")
    print("No strategy selected. No network, orders, X posts or live changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
