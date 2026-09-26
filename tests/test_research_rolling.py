"""Synthetic, causal fixed-fold historical study tests; no broker/network data."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import nbformat
import pytest
import yaml

from src.research_backtest import StrategyParams, run_session
from scripts.research import run_historical_exit_study as runner
from scripts.research.export_oanda_research import ResearchDownloadError
from src import research_rolling
from src.research_rolling import RollingProtocolError, run_rolling, validate_protocol
from src.research_uncertainty import paired_week_bootstrap as real_bootstrap

ROOT = Path(__file__).resolve().parents[1]
EXP = yaml.safe_load((ROOT / "research" / "experiments.yml").read_text(encoding="utf-8"))
FOLDS = yaml.safe_load((ROOT / "research" / "rolling-origin.yml").read_text(encoding="utf-8"))
NY = ZoneInfo("America/New_York")


def day_bars(day: str, *, trade=True, activation_ambiguity=False):
    start = datetime.combine(date.fromisoformat(day), datetime.strptime("09:30", "%H:%M").time(), tzinfo=NY)
    bars = []
    for minute in range(151):
        ts = start + timedelta(minutes=minute)
        signal = (105 if trade else 100) if ts.strftime("%H:%M") == "10:22" else 100
        bid_high = 131.5 if activation_ambiguity and ts.strftime("%H:%M") == "10:24" else 100
        bid_low = 100 if activation_ambiguity and ts.strftime("%H:%M") == "10:24" else 98
        bars.append({"time": ts.astimezone(timezone.utc).isoformat(), "complete": True,
                     "mid": {"o": "100", "h": str(110 if minute == 0 else max(100, signal)),
                             "l": str(90 if minute == 0 else min(100, signal)), "c": str(signal)},
                     "bid": {"o": "99", "h": str(bid_high), "l": str(bid_low), "c": "99"},
                     "ask": {"o": "101", "h": "102", "l": "100", "c": "101"}})
    return bars


def sample():
    moving_2022 = day_bars("2022-09-23")
    # The earlier 11:15 exit benefits on this synthetic day but the noon
    # baseline does not: tests nonzero paired arithmetic, not just 0 control.
    moving_2022[105]["bid"].update({"o": "120", "h": "121", "l": "119", "c": "120"})
    moving_2022[105]["mid"].update({"o": "121", "h": "122", "l": "120", "c": "121"})
    moving_2022[105]["ask"].update({"o": "122", "h": "123", "l": "121", "c": "122"})
    data = {"2020-09-24": day_bars("2020-09-24"),
            "2021-09-24": day_bars("2021-09-24", trade=False),
            "2022-09-23": moving_2022,
            "2023-09-22": day_bars("2023-09-22"),
            "2024-09-23": day_bars("2024-09-23", trade=False),
            "2024-09-24": day_bars("2024-09-24", activation_ambiguity=True),
            "2020-09-25": []}  # quote outage, never a zero-P&L signal
    quality = {day: ("no_session_data" if day == "2020-09-25" else "complete") for day in data}
    baseline = {day: run_session(day, bars, StrategyParams()) if quality[day] == "complete"
                else {"day_ny": day, "status": "excluded", "reason": "quote_no_session_data"}
                for day, bars in data.items()}
    return data, quality, baseline


def test_protocol_frozen_before_results_and_prevents_numeric_tuning():
    rules, costs = validate_protocol(EXP, FOLDS)
    assert len(rules) == 9 and len(costs) == 2
    changed = deepcopy(EXP)
    changed["candidates"][1]["target_points"] = 41
    with pytest.raises(RollingProtocolError, match="numeric"):
        validate_protocol(changed, FOLDS)
    changed = deepcopy(FOLDS)
    changed["folds"][2]["evaluation_year"] = 2023
    with pytest.raises(RollingProtocolError, match="fold"):
        validate_protocol(EXP, changed)
    changed = deepcopy(EXP)
    changed["common"]["cost_cases"][1]["entry_slippage_points"] = .5
    with pytest.raises(RollingProtocolError, match="numeric"):
        validate_protocol(changed, FOLDS)
    changed = deepcopy(EXP)
    changed["validation"]["paired_block_bootstrap"]["seed"] += 1
    with pytest.raises(RollingProtocolError, match="bootstrap"):
        validate_protocol(changed, FOLDS)
    changed = deepcopy(EXP)
    changed["signal"]["entry_bar_ny"] = "10:21"
    with pytest.raises(RollingProtocolError, match="signal"):
        validate_protocol(changed, FOLDS)
    changed = deepcopy(EXP)
    changed["common"]["ambiguous_same_bar"] = "favorable_first"
    with pytest.raises(RollingProtocolError, match="execution"):
        validate_protocol(changed, FOLDS)


def test_identical_cost_case_sample_no_trade_and_any_case_ambiguity_excluded():
    data, quality, baseline = sample()
    out = run_rolling(data, quality, EXP, FOLDS, baseline)
    included = out["common_eligible_dates"]
    assert included == ["2020-09-24", "2021-09-24", "2022-09-23", "2023-09-22", "2024-09-23"]
    assert out["excluded_dates_with_reasons"]["2020-09-25"] == ["quote_no_session_data"]
    assert "one_minute_ordering_ambiguous" in out["excluded_dates_with_reasons"]["2024-09-24"]
    assert out["cases"]["bid_ask_only"]["daily_policy_paths"]["2024-09-24"]["protect_30_runner_75"]["ambiguous_same_bar"]
    assert not any(p.get("ambiguous_same_bar", False) for p in
                   out["cases"]["adverse_extra_1pt_per_fill"]["daily_policy_paths"]["2024-09-24"].values())
    assert out["coverage_by_year"]["2024"]["paired_clean_sessions"] == 1
    assert out["coverage_by_year"]["2024"]["no_trade_days"] == 1
    assert "2024-09-24" in out["posthoc_ambiguity_inclusive_dates"]
    assert "2020-09-25" not in out["posthoc_ambiguity_inclusive_dates"]
    assert out["cases"]["bid_ask_only"]["posthoc_ambiguity_inclusive_descriptive_by_year_in_fixed_policy_order"]["2024"][0]["eligible_sessions"] == 2
    for case in out["cost_case_order"]:
        folds = out["cases"][case]["folds"]
        assert folds["through_2021_check_2022"]["development_eligible_dates"] == ["2020-09-24", "2021-09-24"]
        assert folds["through_2021_check_2022"]["evaluation_eligible_dates"] == ["2022-09-23"]
        assert folds["through_2022_check_2023"]["evaluation_eligible_dates"] == ["2023-09-22"]
        assert folds["through_2023_check_2024"]["evaluation_eligible_dates"] == ["2024-09-23"]
        assert all(fold["evaluation_bootstrap_in_fixed_policy_order"][0]["status"] == "insufficient_history"
                   for fold in folds.values())
        assert all(fold["evaluation_in_fixed_policy_order"][0]["paired_total_net_usd_difference"] == 0
                   for fold in folds.values())  # current control is identical to itself
        early = next(row for row in folds["through_2021_check_2022"]["evaluation_in_fixed_policy_order"]
                     if row["id"] == "full_time_1115")
        assert early["paired_total_net_usd_difference"] == 1680
        assert early["paired_mean_net_usd_per_eligible_session"] == 1680
        assert early["paired_mean_points_per_initial_unit"] == 21
        assert early["paired_mean_net_points_equivalent_per_initial_unit"] == 21
        assert early["candidate_max_drawdown_usd"] == 0
    assert out["quoted_entry_spread_points_by_year"]["2020"]["median_points"] == 2


def test_gate_passing_evaluation_year_invokes_paired_week_bootstrap(monkeypatch):
    data, quality, baseline = sample()
    start = date(2022, 1, 3)  # 26 distinct complete Mon–Thu weeks, plus Sep sample day
    for w in range(26):
        for d in range(4):
            day = (start + timedelta(weeks=w, days=d)).isoformat()
            data[day] = day_bars(day)
            quality[day] = "complete"
            baseline[day] = run_session(day, data[day], StrategyParams())
    calls = []
    def fast_bootstrap(rows, *, iterations, seed, minimum_weeks, minimum_trades):
        calls.append((len(rows), iterations, seed, minimum_weeks, minimum_trades))
        return real_bootstrap(rows, iterations=10, seed=seed,
                              minimum_weeks=minimum_weeks, minimum_trades=minimum_trades)
    monkeypatch.setattr(research_rolling, "paired_week_bootstrap", fast_bootstrap)
    out = run_rolling(data, quality, EXP, FOLDS, baseline)
    assert any(n == 105 and iters == 2000 and weeks == 26 and trades == 100
               for n, iters, _, weeks, trades in calls)
    for case in out["cost_case_order"]:
        fold = out["cases"][case]["folds"]["through_2021_check_2022"]
        assert fold["evaluation_bootstrap_in_fixed_policy_order"][0]["status"] == "descriptive_bootstrap_only"
        assert fold["evaluation_bootstrap_in_fixed_policy_order"][0]["paired_mean_usd_per_session_p05_p50_p95"] == [0, 0, 0]


def test_private_notebook_freshness_refuses_changed_hash_and_duplicate_days(monkeypatch):
    fake_hashes = {"raw_quote_batch_digest": "a", "prior_baseline_sha256": "b",
                   "candidate_protocol_sha256": "c", "fold_protocol_sha256": "d",
                   "simulator_code_sha256": "e"}
    monkeypatch.setattr(runner, "current_provenance_digests", lambda: (fake_hashes, {"2020-09-24", "2021-09-24"}))
    report = {"status": "retrospective_diagnostics_only", "provenance_digests": dict(fake_hashes),
              "common_eligible_dates": ["2020-09-24"],
              "excluded_dates_with_reasons": {"2021-09-24": ["quote_no_session_data"]}}
    runner.verify_private_report_freshness(report)
    changed = deepcopy(report)
    changed["provenance_digests"]["simulator_code_sha256"] = "modified"
    with pytest.raises(ResearchDownloadError, match="stale"):
        runner.verify_private_report_freshness(changed)
    changed = deepcopy(report)
    changed["common_eligible_dates"].append("2020-09-24")
    with pytest.raises(ResearchDownloadError, match="stale"):
        runner.verify_private_report_freshness(changed)


def test_historical_notebook_template_has_no_cached_private_results():
    nb = nbformat.read(ROOT / "notebooks" / "07_historical_rolling_diagnostics.ipynb", as_version=4)
    assert any("untouched holdout" in cell.source.lower() for cell in nb.cells if cell.cell_type == "markdown")
    assert all(cell.execution_count is None and cell.outputs == [] for cell in nb.cells if cell.cell_type == "code")
    assert all(not cell.get("attachments") and not cell.metadata.get("widgets") for cell in nb.cells)
    assert not nb.metadata.get("widgets")


def test_refuse_prior_baseline_mismatch_and_hidden_date():
    data, quality, baseline = sample()
    baseline["2020-09-24"]["net_usd"] = 999999
    with pytest.raises(RollingProtocolError, match="differs"):
        run_rolling(data, quality, EXP, FOLDS, baseline)
    data, quality, baseline = sample()
    baseline["2020-09-25"] = {"day_ny": "2020-09-25", "status": "no_trade"}
    with pytest.raises(RollingProtocolError, match="quote exclusion"):
        run_rolling(data, quality, EXP, FOLDS, baseline)
    data, quality, baseline = sample()
    quality.pop("2020-09-25")
    with pytest.raises(RollingProtocolError, match="differ"):
        run_rolling(data, quality, EXP, FOLDS, baseline)
