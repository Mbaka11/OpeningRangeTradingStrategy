"""OFFLINE retrospective nine-policy evaluation on authenticated private quotes.

No requests, orders, Cloud Run execution, X posts, live rule changes, winner
selection or public account/broker history. Results stay under ignored data/raw/.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research import export_oanda_history as history
from scripts.research.backfill_oanda_history import audited_batches, build_index
from scripts.research.export_oanda_research import ResearchDownloadError, _private_json, _safe_output
from src.research_backtest import StrategyParams
from src.research_rolling import RollingProtocolError, run_rolling, validate_protocol

PROTOCOL = ROOT / "research" / "experiments.yml"
FOLDS = ROOT / "research" / "rolling-origin.yml"
BASELINE = history.HISTORY_ROOT / "historical_baseline.json"
OUTPUT = history.HISTORY_ROOT / "rolling_exit_study.json"
SOURCE_FILES = (
    "src/research_backtest.py", "src/research_exits.py", "src/research_parity.py",
    "src/research_uncertainty.py", "src/research_rolling.py", "src/research_history.py",
    "scripts/research/run_historical_exit_study.py", "scripts/research/audit_oanda_history_baseline.py",
    "scripts/research/export_oanda_history.py", "scripts/research/backfill_oanda_history.py",
)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _code_digest() -> str:
    return _hash("\n".join(f"{name}:{_hash((ROOT / name).read_bytes())}" for name in SOURCE_FILES).encode("utf-8"))


def _batch_digest(batch_names: list[str]) -> str:
    hashes = []
    for name in sorted(batch_names):
        try:
            provenance = json.loads((history.HISTORY_ROOT / name / "provenance.json").read_text(encoding="utf-8"))
            hashes.append(name + ":" + provenance["candles_sha256"])
        except (OSError, KeyError, ValueError):
            raise ResearchDownloadError("Missing historical batch checksum") from None
    return _hash("\n".join(hashes).encode("utf-8"))


def current_provenance_digests() -> tuple[dict, set[str]]:
    """Recheck all saved raw SHA-256s, baseline, protocols and source bytes; no HTTP or tokens."""
    covered = audited_batches()
    index = build_index(covered)
    if not covered or any(row["not_downloaded"] for row in index["years"].values()):
        raise ResearchDownloadError("Five-year private quote history is not fully audited")
    try:
        exp_raw, fold_raw, base_raw = PROTOCOL.read_bytes(), FOLDS.read_bytes(), BASELINE.read_bytes()
    except OSError:
        raise ResearchDownloadError("Missing historical baseline/protocol for freshness check") from None
    return ({"raw_quote_batch_digest": _batch_digest(index["batches"]),
             "prior_baseline_sha256": _hash(base_raw),
             "candidate_protocol_sha256": _hash(exp_raw),
             "fold_protocol_sha256": _hash(fold_raw),
             "simulator_code_sha256": _code_digest()},
            {day.isoformat() for day in covered})


def verify_private_report_freshness(report: dict) -> None:
    """Fail closed if the local private notebook would chart stale data or code."""
    current, dates = current_provenance_digests()
    included = report.get("common_eligible_dates", [])
    excluded = set(report.get("excluded_dates_with_reasons", {}))
    if (report.get("status") != "retrospective_diagnostics_only"
            or report.get("provenance_digests") != current
            or len(included) != len(set(included)) or set(included) & excluded
            or (set(included) | excluded) != dates):
        raise ResearchDownloadError("Retrospective report is stale; review and re-run the offline study")


def read_private_inputs() -> tuple[dict, dict, dict, dict, dict, dict]:
    """Every batch is checksum re-audited before any hypothetical comparison."""
    covered = audited_batches()
    index = build_index(covered)
    if not covered or any(y["not_downloaded"] for y in index["years"].values()):
        raise ResearchDownloadError("Full five-year quote coverage required; no partial historical inference")
    try:
        exp_raw = PROTOCOL.read_bytes()
        fold_raw = FOLDS.read_bytes()
        base_raw = BASELINE.read_bytes()
        experiments = yaml.safe_load(exp_raw)
        rolling = yaml.safe_load(fold_raw)
        baseline = json.loads(base_raw)
    except (OSError, ValueError, yaml.YAMLError):
        raise ResearchDownloadError("Missing or invalid private baseline / research-only protocols") from None
    validate_protocol(experiments, rolling)
    if (baseline.get("source") != "historical OANDA PRACTICE NAS100_USD M1 MBA; NOT original NSXUSD vendor CSV"
            or baseline.get("parameters") != asdict(StrategyParams())
            or set(baseline.get("daily_hypothetical", {})) != {d.isoformat() for d in covered}):
        raise ResearchDownloadError("Prior offline baseline is missing or differs from the frozen 25/75 parameters")
    quotes, quality, hashes = {}, {}, []
    for folder_name in index["batches"]:
        folder, _ = history.audit_existing(folder_name)
        try:
            batch = json.loads((folder / "candles.json").read_text(encoding="utf-8"))
            provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ResearchDownloadError("Invalid private historical quote batch") from None
        hashes.append(folder_name + ":" + provenance["candles_sha256"])
        for day, candles in batch.items():
            if day in quotes or day not in provenance["quality"]["sessions"]:
                raise ResearchDownloadError("Duplicate or unmapped historical quote date")
            quotes[day] = candles
            quality[day] = provenance["quality"]["sessions"][day]["status"]
    if set(quotes) != {d.isoformat() for d in covered}:
        raise ResearchDownloadError("Missing historical quote days after reading audited batches")
    digests = {"raw_quote_batch_digest": _hash("\n".join(sorted(hashes)).encode("utf-8")),
               "prior_baseline_sha256": _hash(base_raw),
               "candidate_protocol_sha256": _hash(exp_raw), "fold_protocol_sha256": _hash(fold_raw),
               "simulator_code_sha256": _code_digest()}
    return quotes, quality, experiments, rolling, baseline["daily_hypothetical"], digests


def main() -> int:
    parser = argparse.ArgumentParser(description="OFFLINE, PRIVATE rolling-origin diagnostics, not live trading")
    parser.add_argument("--replace-private", action="store_true", help="Explicitly replace an existing ignored study after review")
    args = parser.parse_args()
    try:
        _safe_output(OUTPUT)
        if OUTPUT.exists() and not args.replace_private:
            raise ResearchDownloadError("Private rolling report already exists; refusing overwrite")
        quotes, quality, experiments, rolling, baseline, digests = read_private_inputs()
        report = run_rolling(quotes, quality, experiments, rolling, baseline)
        report["provenance_digests"] = digests
        _private_json(OUTPUT, report)
    except (ResearchDownloadError, RollingProtocolError, ValueError, KeyError) as error:
        # Never print raw broker data, quotes, performance rankings or API IDs.
        parser.exit(1, f"Offline historical comparison refused: {type(error).__name__}\n")
    print("Private retrospective diagnostic:", OUTPUT.relative_to(ROOT))
    print("Common paired sample:", len(report["common_eligible_dates"]),
          "of", len(quality), "requested weekdays;")
    print("Exclusion categories/counts:", report["exclusion_reason_counts"])
    for fold in rolling["folds"]:
        case = report["cases"][report["cost_case_order"][0]]["folds"][fold["id"]]
        gate = case["evaluation_bootstrap_in_fixed_policy_order"][0]["status"]
        print(fold["id"], "evaluation eligible days:", len(case["evaluation_eligible_dates"]),
              "uncertainty status:", gate)
    print("No exit rule selected: old years were previously inspected, modeled costs are unverified,")
    print("and true forward practice sessions remain the only prospective confirmation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
