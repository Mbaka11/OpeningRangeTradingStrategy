"""Synthetic execution diagnostics; no private broker or historical quote inputs."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from scripts.research import audit_historical_execution as cli
from scripts.research.export_oanda_research import ResearchDownloadError
from src.research_backtest import StrategyParams
from src.research_execution_audit import ExecutionAuditError, audit_execution
from src.research_exits import run_policy_session
from src.research_history import audit_day

ROOT = Path(__file__).resolve().parents[1]
EXP = yaml.safe_load((ROOT / "research/experiments.yml").read_text(encoding="utf-8"))
FOLDS = yaml.safe_load((ROOT / "research/rolling-origin.yml").read_text(encoding="utf-8"))
CONTEXT = yaml.safe_load((ROOT / "research/execution-audit.yml").read_text(encoding="utf-8"))
NY = ZoneInfo("America/New_York")


def bars(day, *, side="long", timing_flag=False):
    start = datetime.combine(date.fromisoformat(day), datetime.strptime("09:30", "%H:%M").time(), tzinfo=NY)
    result = []
    for n in range(151):
        t = start + timedelta(minutes=n)
        close = (105 if side == "long" else 95 if side == "short" else 100) if n == 52 else 100
        mid = {"o": "100", "h": str(110 if n == 0 else max(100, close)),
               "l": str(90 if n == 0 else min(100, close)), "c": str(close)}
        bid = {"o": "99", "h": "100", "l": "98", "c": "99"}
        if timing_flag and n == 54:
            bid = {"o": "101", "h": "145", "l": "100", "c": "140"}
            mid = {k: str(float(v) + 1) for k, v in bid.items()}
        ask = {k: str(float(v) + 2) for k, v in bid.items()}
        result.append({"time": t.astimezone(timezone.utc).isoformat(), "complete": True,
                       "mid": mid, "bid": bid, "ask": ask})
    return result


def inputs():
    market = {"2024-09-23": bars("2024-09-23", timing_flag=True),
              "2024-09-24": bars("2024-09-24", side="short"),
              "2024-09-25": bars("2024-09-25", side="none"),
              "2024-03-29": [],  # sourced equity holiday, still not CFD cause proof
              "2020-01-01": [],  # untranscribed earlier calendar hypothesis
              "2020-03-09": [c for c in bars("2020-03-09")
                             if not "09:35" <= datetime.fromisoformat(c["time"]).astimezone(NY).strftime("%H:%M") <= "09:49"],
              "2020-03-18": [c for c in bars("2020-03-18")
                             if datetime.fromisoformat(c["time"]).astimezone(NY).strftime("%H:%M") != "10:22"]}
    quality = {d: audit_day(date.fromisoformat(d), c)["status"] for d, c in market.items()}
    complete = {d for d, flag in quality.items() if flag == "complete"}
    cases, ambiguous = {}, set()
    for cost in EXP["common"]["cost_cases"]:
        p = replace(StrategyParams(), **{k: cost[k] for k in
                                       ("entry_slippage_points", "exit_slippage_points", "commission_per_side_usd")})
        paths = {d: {rule["id"]: run_policy_session(d, market[d], p, rule)
                     for rule in EXP["candidates"]} for d in complete}
        cases[cost["id"]] = {"assumptions": deepcopy(cost), "daily_policy_paths": paths}
        ambiguous.update(d for d, policies in paths.items() if any(r.get("ambiguous_same_bar", False) for r in policies.values()))
    excluded = {d: ["quote_" + flag] for d, flag in quality.items() if flag != "complete"}
    excluded.update({d: ["one_minute_ordering_ambiguous"] for d in ambiguous})
    study = {"status": "retrospective_diagnostics_only", "candidate_order": [r["id"] for r in EXP["candidates"]],
             "cost_case_order": list(cases), "common_eligible_dates": sorted(complete - ambiguous),
             "excluded_dates_with_reasons": excluded, "cases": cases}
    return market, quality, study, EXP, FOLDS, CONTEXT


def test_counts_deduplicate_costs_policies_and_keep_the_frozen_sample():
    out = audit_execution(*inputs())
    assert out["original_any_policy_ambiguous_days"] == 1
    assert out["original_clean_paired_days"] == 2  # short plus genuine no-trade
    assert out["quote_excluded_days"] == 4
    assert out["category_unique_day_counts"]["amendment_timing_sensitivity"] == 1
    assert out["primary_sample_unchanged"] and not out["execution_verified"]
    assert not out["historical_costs_verified"] and out["selection"] == "none"
    for case in out["cost_cases_in_fixed_order"]:
        assert all(p["trade_days"] == 2 and p["no_trade_days"] == 1 for p in case["policy_counts_in_fixed_order"])
        assert case["daily_ledger_checks"]["2024-09-25"]["baseline_25_75"] == {"status": "no_trade"}


def test_calendar_holiday_context_never_repairs_quotes_or_implies_broker_cause():
    out = audit_execution(*inputs())
    gaps = {r["day_ny"]: r for r in out["quote_gap_context_private"]}
    assert gaps["2024-03-29"]["cash_calendar_classification"] == "verified_cash_equity_holiday_context"
    assert gaps["2020-01-01"]["cash_calendar_classification"] == "unverified_cash_equity_holiday_hypothesis"
    assert all(r["oanda_gap_cause"] == "unverified" and r["kept_excluded"] for r in gaps.values())
    assert gaps["2020-03-09"]["missing_candle_intervals_overlapping_cash_halt"] == 15
    assert gaps["2020-03-18"]["missing_candle_intervals_overlapping_cash_halt"] == 0  # halt is AFTER noon
    assert gaps["2020-03-18"]["missing_decision_minute"]
    assert out["gap_days_with_missing_candle_intervals_overlapping_cash_halts"] == 1
    assert "2022-01-03" not in CONTEXT["calendar_years"]["2022"]["full_cash_equity_closures"]
    assert "2021-12-31" not in CONTEXT["calendar_years"]["2021"]["full_cash_equity_closures"]
    assert "2021-06-18" not in CONTEXT["calendar_years"]["2021"]["full_cash_equity_closures"]
    assert "2022-06-20" in CONTEXT["calendar_years"]["2022"]["full_cash_equity_closures"]


def test_cost_bookkeeping_weights_split_units_and_does_not_double_charge_entry_at_breakeven():
    out = audit_execution(*inputs())
    case = out["cost_cases_in_fixed_order"][1]
    partial = case["daily_ledger_checks"]["2024-09-23"]["half_30_runner_75"]
    assert partial["modeled_fill_count"] == 3
    assert partial["modeled_commission_usd"] == 6
    assert partial["unit_weighted_exit_penalty_usd"] == 80  # 40+40 units, NOT 80+80
    assert partial["unit_weighted_entry_penalty_usd"] == 80
    assert case["full_size_entry_price_stop_net_usd_model"] == -84  # fill-anchored: 80 exit penalty + 4 fees
    assert case["full_size_net_zero_trigger_offset_from_filled_entry_points_model"] == 1.05
    assert partial["modeled_tp_legs_with_adverse_penalty"] == 1


@pytest.mark.parametrize("mutation", ["fee", "unit", "nan", "mechanism", "sample", "quote_quality", "calendar",
                                      "no_trade_points", "no_trade_reasons", "early_time_exit", "same_bar_runner", "wrong_family"])
def test_fail_closed_on_corrupted_path_context_or_sample(mutation):
    market, quality, study, exp, folds, context = deepcopy(inputs())
    row = study["cases"]["bid_ask_only"]["daily_policy_paths"]["2024-09-23"]["half_30_runner_75"]
    if mutation == "fee":
        row["net_usd"] += 2
    elif mutation == "unit":
        row["legs"][0]["units"] -= 1
    elif mutation == "nan":
        row["entry_price"] = float("nan")
    elif mutation == "mechanism":
        row["ambiguous_same_bar"] = True
        row["ambiguity_reasons"] = ["unknown_private_reason"]
    elif mutation == "sample":
        study["common_eligible_dates"].append("2024-09-23")
        study["excluded_dates_with_reasons"].pop("2024-09-23")
    elif mutation == "quote_quality":
        quality["2024-03-29"] = "complete"
    elif mutation == "calendar":
        context["calendar_years"]["2020"]["verification"] = "official_table_transcribed"
    elif mutation == "no_trade_points":
        study["cases"]["bid_ask_only"]["daily_policy_paths"]["2024-09-25"]["baseline_25_75"]["gross_points"] = float("nan")
    elif mutation == "no_trade_reasons":
        study["cases"]["bid_ask_only"]["daily_policy_paths"]["2024-09-25"]["baseline_25_75"]["ambiguity_reasons"] = ["unknown"]
    elif mutation == "early_time_exit":
        row = study["cases"]["bid_ask_only"]["daily_policy_paths"]["2024-09-24"]["full_time_1115"]
        row["legs"][0]["minute"] = row["exit_minute"] = row["entry_minute"]
    elif mutation == "same_bar_runner":
        row["legs"][1]["minute"] = row["exit_minute"] = row["legs"][0]["minute"]
    elif mutation == "wrong_family":
        row = study["cases"]["bid_ask_only"]["daily_policy_paths"]["2024-09-23"]["baseline_25_75"]
        row["ambiguous_same_bar"] = True
        row["ambiguity_reasons"] = ["trail_would_touch_in_same_bar_before_amendment"]
    with pytest.raises(ExecutionAuditError):
        audit_execution(market, quality, study, exp, folds, context)


def test_cli_offline_private_refuses_overwrite_and_never_prints_values(monkeypatch, tmp_path, capsys):
    data = inputs()
    monkeypatch.setattr(cli, "read_inputs", lambda: (*data, {"test_provenance": True}))
    monkeypatch.setattr(cli.study_runner.history, "credentials", lambda: pytest.fail("No .env/token access"))
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("No HTTP allowed"))
    # Output guard is exercised separately; this CLI test intercepts private I/O.
    monkeypatch.setattr(cli, "OUTPUT", tmp_path / "execution_audit.json")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_safe_output", lambda _: None)
    monkeypatch.setattr("sys.argv", ["audit_historical_execution.py"])
    assert cli.main() == 0
    text = capsys.readouterr().out
    assert "No strategy selected" in text and "primary sample unchanged: 2" in text
    assert "2024-09-23" not in text and "net_usd" not in text
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "privately" in capsys.readouterr().err


def test_private_path_guard_and_stale_inputs(monkeypatch):
    with pytest.raises(ResearchDownloadError, match="Unsafe local output"):
        cli._safe_output(ROOT / "research/private_results.json")
    # Loader declines old code/data hashes before doing any diagnostic arithmetic.
    monkeypatch.setattr(cli.study_runner, "read_private_inputs", lambda: ({}, {}, {}, {}, {}, {"current": "digest"}))
    class Saved:
        def read_bytes(self):
            return b'{"provenance_digests": {"old": "digest"}}'
    monkeypatch.setattr(cli.study_runner, "OUTPUT", Saved())
    with pytest.raises(ExecutionAuditError, match="fingerprints"):
        cli.read_inputs()
