"""OFFLINE smoke comparison of the nine predeclared exit candidates.

Usage: python scripts/research/run_exit_study.py --folder 2026-08-20_2026-09-24
Requires existing private step-1/2 parity files, makes NO network calls,
and saves only ignored private data/raw/oanda_research/.../exit_study.json.
No performance ranking/promotion from the recent small sample.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.export_oanda_research import OUTPUT_ROOT, ResearchDownloadError, _private_json, _safe_output
from src.research_backtest import StrategyParams
from src.research_exits import run_policy_session, validate_policy
from src.research_uncertainty import paired_week_bootstrap

PROTOCOL = ROOT / "research" / "experiments.yml"


def _read_files(folder_name: str) -> tuple[Path, dict, list, dict, list]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}", folder_name):
        raise ResearchDownloadError("Expected a generated START_END folder name")
    folder = OUTPUT_ROOT / folder_name
    _safe_output(folder / "exit_study.json")
    try:
        candles = json.loads((folder / "candles.json").read_text(encoding="utf-8"))
        parity = json.loads((folder / "parity.json").read_text(encoding="utf-8"))
        baseline = json.loads((folder / "baseline.json").read_text(encoding="utf-8"))
        manifest = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        raise ResearchDownloadError("Missing or invalid private baseline/export or experiment protocol") from None
    if not isinstance(candles, dict) or not isinstance(parity, list) or not isinstance(baseline, dict):
        raise ResearchDownloadError("Unexpected private export structure")
    return folder, candles, parity, baseline, manifest


def _validated_manifest(manifest: dict) -> list[dict]:
    if not isinstance(manifest, dict) or manifest.get("protocol_version") != 2 or manifest.get("status") != "research_only":
        raise ResearchDownloadError("Unexpected research-only protocol version")
    policies = manifest.get("candidates")
    if not isinstance(policies, list) or len(policies) != 9 or policies[0].get("id") != "baseline_25_75":
        raise ResearchDownloadError("Protocol must contain the nine predeclared candidates, baseline first")
    if len({p["id"] for p in policies}) != len(policies):
        raise ResearchDownloadError("Duplicate candidate ids")
    common = manifest.get("common", {})
    if common.get("initial_stop_points") != 25 or common.get("initial_units_fraction") != 1:
        raise ResearchDownloadError("Initial risk/size differs from audited baseline")
    for policy in policies:
        validate_policy(policy, StrategyParams())
    costs = common.get("cost_cases")
    if (not isinstance(costs, list) or [x.get("id") for x in costs] !=
            ["bid_ask_only", "adverse_extra_1pt_per_fill"]):
        raise ResearchDownloadError("Unexpected cost-case protocol")
    for cost in costs:
        if any(not isinstance(cost.get(k), (int, float)) or cost[k] < 0 for k in
               ("entry_slippage_points", "exit_slippage_points", "commission_per_side_usd")):
            raise ResearchDownloadError("Invalid adverse cost inputs")
    return costs


def run_study(candles_by_day: dict, parity: list, baseline_report: dict, manifest: dict) -> dict:
    """Paired descriptive smoke run, with no inference on inadequate history."""
    costs = _validated_manifest(manifest)
    signal_counts = baseline_report.get("summary", {}).get("signal_comparison", {})
    pl_counts = baseline_report.get("summary", {}).get("broker_pl_check", {})
    if (signal_counts.get("match") != len(candles_by_day)
            or pl_counts.get("match") != baseline_report.get("summary", {}).get("broker_trades_on_exported_days")):
        raise ResearchDownloadError("Baseline trade/no-trade or broker P&L gate not passed")
    by_day = {row["day_ny"]: row["status"] for row in parity}
    if len(by_day) != len(parity) or len(by_day) != pl_counts["match"]:
        raise ResearchDownloadError("Broker trade days missing/duplicated; cannot form paired sessions")
    policies = manifest["candidates"]
    bootstrap = manifest["validation"]["paired_block_bootstrap"]
    result = {"protocol_version": manifest["protocol_version"],
              "caveat": "Exploratory hypothetical M1 open fills only; no rule selected or approved for deployment.",
              "cost_cases": {}}
    for cost in costs:
        case_id = cost["id"]
        params = replace(StrategyParams(), **{k: cost[k] for k in
                          ("entry_slippage_points", "exit_slippage_points", "commission_per_side_usd")})
        all_days = {}
        eligible = {}
        excluded = {}
        for day, candles in sorted(candles_by_day.items()):
            per_policy = {p["id"]: run_policy_session(day, candles, params, p) for p in policies}
            all_days[day] = per_policy
            reasons = []
            if day in by_day and by_day[day] != "match":
                reasons.append("broker_exit_not_definitively_reconciled")
            if any(r["status"] == "excluded" for r in per_policy.values()):
                reasons.append("incomplete_or_ineligible_market_path")
            if any(r.get("ambiguous_same_bar") for r in per_policy.values()):
                reasons.append("OHLC_ordering_ambiguous")
            if reasons:
                excluded[day] = reasons
            else:
                eligible[day] = per_policy
        baseline_id = policies[0]["id"]
        daily_by_policy = {}
        descriptions = []
        for policy in policies:
            candidate = policy["id"]
            paired = [{"day_ny": day,
                       "baseline_usd": float(results[baseline_id].get("net_usd", 0)),
                       "candidate_usd": float(results[candidate].get("net_usd", 0)),
                       "baseline_trade": results[baseline_id]["status"] == "trade"}
                      for day, results in sorted(eligible.items())]
            daily_by_policy[candidate] = paired
            total = sum(r["candidate_usd"] for r in paired)
            difference = sum(r["candidate_usd"] - r["baseline_usd"] for r in paired)
            descriptions.append({"id": candidate, "paired_sessions": len(paired),
                                 "total_net_usd": round(total, 2),
                                 "paired_difference_vs_baseline_usd": round(difference, 2),
                                 "extra_fill_count_all_sessions": sum(max(0, len(r[candidate].get("legs", [])) - 1)
                                                                       for r in all_days.values())})
        uncertainty = {p["id"]: paired_week_bootstrap(daily_by_policy[p["id"]],
                       iterations=bootstrap["repetitions"], seed=bootstrap["seed"],
                       minimum_weeks=bootstrap["minimum_distinct_weeks"],
                       minimum_trades=bootstrap["minimum_baseline_trade_days"])
                       for p in policies}
        result["cost_cases"][case_id] = {
            "assumptions": cost, "eligible_dates": sorted(eligible), "excluded_days": excluded,
            "counts": {"exported_sessions": len(candles_by_day), "paired_unambiguous_sessions": len(eligible),
                       "excluded_reasons": dict(Counter(reason for reasons in excluded.values() for reason in reasons))},
            "candidate_descriptions_in_predeclared_order": descriptions,
            "uncertainty": uncertainty, "daily_policy_paths": all_days,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline-only, private exit policy research (no orders/posts)")
    parser.add_argument("--folder", required=True, help="Existing private research export folder name")
    args = parser.parse_args()
    try:
        folder, candles, parity, baseline, manifest = _read_files(args.folder)
        report = run_study(candles, parity, baseline, manifest)
        _private_json(folder / "exit_study.json", report)
    except (ResearchDownloadError, ValueError, KeyError) as error:
        # Never display raw broker JSON, token or account in error text.
        parser.exit(1, f"Offline exit study refused: {type(error).__name__}\n")
    print("Private exploratory report:", (folder / "exit_study.json").relative_to(ROOT))
    for case_id, case in report["cost_cases"].items():
        print(case_id, "eligible unambiguous days:", case["counts"]["paired_unambiguous_sessions"],
              "of", case["counts"]["exported_sessions"],
              "Monte Carlo:", case["uncertainty"]["baseline_25_75"]["status"])
    print("No policy has been selected; historical source data and prospective validation are still needed.")


if __name__ == "__main__":
    main()
