"""Pure OFFLINE rolling-origin diagnostics on OANDA M1 practice quotes.

Fixed nine-rule matrix, identical eligible days across all candidates and cost
cases. Previously viewed years are retrospective diagnostics, NOT a holdout.
No OANDA requests, orders, X posts, cloud calls or rule promotion.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
import math
from statistics import mean, median
from zoneinfo import ZoneInfo

from src.research_backtest import StrategyParams
from src.research_parity import parse_time
from src.research_exits import run_policy_session, validate_policy
from src.research_uncertainty import paired_week_bootstrap

NY = ZoneInfo("America/New_York")

EXPECTED_FOLDS = (
    ("through_2021_check_2022", (2020, 2021), 2022),
    ("through_2022_check_2023", (2020, 2021, 2022), 2023),
    ("through_2023_check_2024", (2020, 2021, 2022, 2023), 2024),
)
EXPECTED_POLICIES = (
    "baseline_25_75", "full_40", "full_50", "half_30_runner_75",
    "half_40_runner_75", "protect_30_runner_75", "protect_40_runner_75",
    "trail_40_by_20_runner_75", "full_time_1115",
)
EXPECTED_COST_CASES = ("bid_ask_only", "adverse_extra_1pt_per_fill")
# Freeze numeric thresholds/size as well as IDs before looking at outcomes.
EXPECTED_RULE_DEFINITIONS = (
    {"id": "baseline_25_75", "family": "fixed", "target_points": 75},
    {"id": "full_40", "family": "fixed", "target_points": 40},
    {"id": "full_50", "family": "fixed", "target_points": 50},
    {"id": "half_30_runner_75", "family": "partial", "first_target_points": 30,
     "first_exit_fraction": .5, "remaining_target_points": 75, "remaining_stop_points_from_entry": -25},
    {"id": "half_40_runner_75", "family": "partial", "first_target_points": 40,
     "first_exit_fraction": .5, "remaining_target_points": 75, "remaining_stop_points_from_entry": -25},
    {"id": "protect_30_runner_75", "family": "protect", "activation_points": 30,
     "new_stop_points_from_entry": 0, "target_points": 75},
    {"id": "protect_40_runner_75", "family": "protect", "activation_points": 40,
     "new_stop_points_from_entry": 0, "target_points": 75},
    {"id": "trail_40_by_20_runner_75", "family": "trailing", "activation_points": 40,
     "trailing_distance_points": 20, "target_points": 75},
    {"id": "full_time_1115", "family": "time", "exit_ny": "11:15", "target_points": 75},
)
EXPECTED_COST_DEFINITIONS = (
    {"id": "bid_ask_only", "entry_slippage_points": 0,
     "exit_slippage_points": 0, "commission_per_side_usd": 0},
    {"id": "adverse_extra_1pt_per_fill", "entry_slippage_points": 1,
     "exit_slippage_points": 1, "commission_per_side_usd": 2},
)


class RollingProtocolError(ValueError):
    """Sanitized protocol/sample failure; do not include raw quote values."""


def validate_protocol(experiments: dict, rolling: dict) -> tuple[list[dict], list[dict]]:
    if (experiments.get("protocol_version") != 2 or experiments.get("status") != "research_only"
            or rolling.get("protocol_version") != 1 or rolling.get("status") != "retrospective_diagnostics_only"
            or rolling.get("source") != "oanda_practice_NAS100_USD_M1_MBA_2020_2024"
            or rolling.get("candidate_protocol_version") != 2
            or rolling.get("candidate_manifest") != "research/experiments.yml"
            or rolling.get("selection") != "none" or rolling.get("no_automatic_promotion") is not True):
        raise RollingProtocolError("Expected frozen retrospective research-only protocols")
    folds = tuple((f["id"], tuple(f["development_years"]), f["evaluation_year"]) for f in rolling["folds"])
    if folds != EXPECTED_FOLDS:
        raise RollingProtocolError("Rolling-origin fold boundaries changed")
    rules = experiments["candidates"]
    costs = experiments["common"]["cost_cases"]
    if (tuple(r["id"] for r in rules) != EXPECTED_POLICIES or
            tuple(c["id"] for c in costs) != EXPECTED_COST_CASES or
            tuple(rules) != EXPECTED_RULE_DEFINITIONS or tuple(costs) != EXPECTED_COST_DEFINITIONS):
        raise RollingProtocolError("Historical numeric candidate or cost matrix changed")
    if (experiments["signal"] != {
            "opening_range_ny": "09:30-10:00", "entry_bar_ny": "10:22",
            "first_action": "after_entry_bar_complete", "hard_flat_ny": "12:00"}
            or experiments["common"]["initial_stop_points"] != 25
            or experiments["common"]["initial_units_fraction"] != 1
            or experiments["common"]["one_signal_per_day"] is not True
            or experiments["common"]["ambiguous_same_bar"] != "adverse_first"
            or experiments["common"]["evaluation_unit"] != "eligible_session_including_no_trade"
            or experiments["common"]["price_series"] != "executable_bid_ask"
            or experiments["common"]["account_for_additional_partial_fill_costs"] is not True
            or experiments["validation"]["baseline_parity_required"] is not True
            or experiments["validation"]["selection"] != "chronological_rolling_origin_then_prospective_paper"):
        raise RollingProtocolError("Historical signal, execution or research-only selection contract changed")
    if rolling["common_sample"] != {
        "include_no_trade_days_as_zero": True,
        "exclude_incomplete_and_no_quote_weekdays": True,
        "exclude_if_any_candidate_in_any_cost_case_is_ambiguous": True,
        "require_same_entry_and_side_for_all_candidates_per_cost_case": True,
        "require_same_eligible_dates_across_both_cost_cases": True,
    }:
        raise RollingProtocolError("Historical paired sample policy changed")
    if (rolling["metrics"]["primary"] != "paired_mean_net_usd_per_eligible_session"
            or rolling["uncertainty"] != "use_experiments_yml_week_bootstrap_only_if_26_weeks_and_100_baseline_trades"
            or rolling["future_untouched_confirmation"] != "new_prospective_practice_sessions_only"
            or rolling["metrics"]["no_annualized_sharpe"] is not True
            or rolling["metrics"]["descriptive"] != [
                "paired_total_net_usd_difference", "paired_mean_points_per_initial_unit",
                "candidate_max_drawdown_usd", "worst_week_usd", "worst_5pct_daily_mean_usd",
                "trade_days", "no_trade_days", "additional_closing_fills", "stop_amendments"]):
        raise RollingProtocolError("Historical metric or prospective gate changed")
    for rule in rules:
        validate_policy(rule, StrategyParams())
    for cost in costs:
        if any(not isinstance(cost[k], (int, float)) or isinstance(cost[k], bool)
               or not math.isfinite(cost[k]) or cost[k] < 0
               for k in ("entry_slippage_points", "exit_slippage_points", "commission_per_side_usd")):
            raise RollingProtocolError("Historical modeled cost is invalid")
    gate = experiments["validation"]["paired_block_bootstrap"]
    if (gate["minimum_distinct_weeks"] != 26 or gate["minimum_baseline_trade_days"] != 100
            or gate["minimum_block"] != "calendar_week" or gate["repetitions"] != 2000
            or gate["seed"] != 20260926 or experiments["validation"]["report_quantiles"] != [.05, .50, .95]):
        raise RollingProtocolError("Historical bootstrap gate, seed or quantiles changed")
    return rules, costs


def _pnl(result: dict) -> float:
    if result["status"] == "no_trade":
        return 0.0
    if result["status"] != "trade" or not isinstance(result.get("net_usd"), (float, int)):
        raise RollingProtocolError("Invalid hypothetical trade/no-trade outcome")
    pnl = float(result["net_usd"])
    if not math.isfinite(pnl):
        raise RollingProtocolError("Non-finite hypothetical P&L")
    return pnl


def _max_drawdown(daily: list[float]) -> float:
    equity = peak = worst = 0.0
    for pnl in daily:
        equity += pnl
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def descriptive_metrics(days: list[str], paths: dict, candidate: str, units: int) -> dict:
    """Candidate vs baseline on identical dates, not a significance test."""
    if not days:
        return {"status": "no_eligible_days", "eligible_sessions": 0}
    base, other, weeks = [], [], defaultdict(float)
    trades = extra_fills = amendments = 0
    for day in days:
        b, c = paths[day]["baseline_25_75"], paths[day][candidate]
        if b["status"] != c["status"] or b["status"] not in ("trade", "no_trade"):
            raise RollingProtocolError("Paired policy statuses differ on eligible day")
        trades += b["status"] == "trade"
        extra_fills += max(0, len(c.get("legs", [])) - 1)
        amendments += c.get("amendments", 0)
        b_value, c_value = _pnl(b), _pnl(c)
        base.append(b_value)
        other.append(c_value)
        iso = date.fromisoformat(day).isocalendar()
        weeks[(iso.year, iso.week)] += c_value
    diffs = [c - b for b, c in zip(base, other)]
    count = max(1, math.ceil(len(other) * 0.05))
    paired_mean = round(mean(diffs), 4)
    points_equiv = round(mean(diffs) / units, 6)
    worst_week = round(min(weeks.values()), 4)
    worst_tail = round(mean(sorted(other)[:count]), 4)
    return {"status": "descriptive_only", "eligible_sessions": len(days), "baseline_trade_days": trades,
            "trade_days": trades, "no_trade_days": len(days) - trades,
            "paired_total_net_usd_difference": round(sum(diffs), 4),
            "paired_mean_net_usd_per_eligible_session": paired_mean,
            "paired_mean_net_usd_per_session": paired_mean,  # compatibility with existing private local notebook copy
            "paired_mean_points_per_initial_unit": points_equiv,  # net USD / model units; not executable index-point fills
            "paired_mean_net_points_equivalent_per_initial_unit": points_equiv,
            "candidate_max_drawdown_usd": round(_max_drawdown(other), 4),
            "baseline_max_drawdown_usd": round(_max_drawdown(base), 4),
            "worst_week_usd": worst_week, "candidate_worst_week_usd": worst_week,
            "worst_5pct_daily_mean_usd": worst_tail, "candidate_worst_5pct_daily_mean_usd": worst_tail,
            "additional_closing_fills": extra_fills, "stop_amendments": amendments}


def run_rolling(market: dict[str, list[dict]], quality: dict[str, str],
                experiments: dict, rolling: dict, baseline_check: dict | None = None) -> dict:
    """One predeclared historical matrix; no ranking/selection; stored report PRIVATE."""
    rules, costs = validate_protocol(experiments, rolling)
    if set(market) != set(quality) or not market:
        raise RollingProtocolError("Quote days and quality flags differ")
    if baseline_check is not None and set(baseline_check) != set(market):
        raise RollingProtocolError("Historical baseline does not cover every quote day")
    cost_params = {c["id"]: replace(StrategyParams(), **{
        k: c[k] for k in ("entry_slippage_points", "exit_slippage_points", "commission_per_side_usd")})
        for c in costs}
    all_results = {c["id"]: {} for c in costs}
    excluded: dict[str, list[str]] = {}
    eligible = []
    spreads_by_year: dict[int, list[float]] = defaultdict(list)
    for day in sorted(market):
        if date.fromisoformat(day).year not in range(2020, 2025):
            raise RollingProtocolError("Historical date outside frozen 2020–2024 period")
        if quality[day] != "complete":
            if quality[day] not in ("incomplete", "no_session_data"):
                raise RollingProtocolError("Unknown historical quote-quality flag")
            expected_reason = "quote_" + quality[day]
            if baseline_check is not None and (baseline_check[day].get("status") != "excluded" or
                                               baseline_check[day].get("reason") != expected_reason):
                raise RollingProtocolError("Historical quote exclusion differs from audited baseline")
            excluded[day] = [expected_reason]
            continue
        # Quote spreads are feed observations, NOT measured commission or
        # a guarantee of executable partial fills. Never print raw prices.
        entry_bars = [c for c in market[day] if parse_time(c["time"]).astimezone(NY).strftime("%H:%M") == "10:23"]
        if len(entry_bars) != 1:
            raise RollingProtocolError("Complete quote day lacks one 10:23 NY entry minute")
        spread = float(entry_bars[0]["ask"]["o"]) - float(entry_bars[0]["bid"]["o"])
        if not math.isfinite(spread) or spread < 0:
            raise RollingProtocolError("Invalid historical quoted entry spread")
        spreads_by_year[date.fromisoformat(day).year].append(spread)
        reasons = []
        for cost in costs:
            case = cost["id"]
            per_policy = {p["id"]: run_policy_session(day, market[day], cost_params[case], p) for p in rules}
            all_results[case][day] = per_policy
            base = per_policy["baseline_25_75"]
            if any(result["status"] != base["status"] for result in per_policy.values()):
                raise RollingProtocolError("Historical signal/trade status differs between candidates")
            if base["status"] == "trade" and any(result.get("side") != base["side"] or
                                                    result.get("entry_price") != base["entry_price"] or
                                                    result.get("entry_minute") != base["entry_minute"]
                                                    for result in per_policy.values()):
                raise RollingProtocolError("Historical candidate entry or direction differs")
            if any(result["status"] == "excluded" for result in per_policy.values()):
                reasons.append("simulator_excluded")
            if any(result.get("ambiguous_same_bar", False) for result in per_policy.values()):
                reasons.append("one_minute_ordering_ambiguous")
            if case == "bid_ask_only" and baseline_check is not None:
                prior = baseline_check[day]
                for field in ("status", "side", "entry_price", "exit_price", "exit_reason", "net_usd"):
                    if base.get(field) != prior.get(field):
                        raise RollingProtocolError("Historical zero-extra baseline differs from audited run")
        if reasons:
            excluded[day] = sorted(set(reasons))
        else:
            eligible.append(day)
    # In the common sample a no-trade signal is always a ZERO observation, not
    # dropped. Both cost cases share the same eligible dates and rule order.
    # Post-hoc sensitivity added after observing exclusion COUNTS (not P&L):
    # include modelled ambiguous paths under adverse-first/deferred-amendment
    # rules. This is NOT a best/worst fill bound or a second primary sample.
    modelled_inclusive = [d for d in sorted(market) if quality[d] == "complete" and
                         "simulator_excluded" not in excluded.get(d, [])]
    for day in eligible:
        statuses = {all_results[c["id"]][day]["baseline_25_75"]["status"] for c in costs}
        if len(statuses) != 1 or statuses.pop() not in ("trade", "no_trade"):
            raise RollingProtocolError("Cost cases differ on historical signal day")
    by_year = {}
    for year in range(2020, 2025):
        included = [d for d in eligible if date.fromisoformat(d).year == year]
        trade_count = sum(all_results[costs[0]["id"]][d]["baseline_25_75"]["status"] == "trade" for d in included)
        year_dates = [d for d in market if date.fromisoformat(d).year == year]
        by_year[str(year)] = {"requested_weekdays": len(year_dates), "paired_clean_sessions": len(included),
                              "baseline_trade_days": trade_count, "no_trade_days": len(included) - trade_count,
                              "excluded_quote_days": sum(any(r.startswith("quote_") for r in excluded.get(d, [])) for d in year_dates),
                              "excluded_ordering_or_simulator_days": sum(d in excluded and quality[d] == "complete" for d in year_dates)}
    gate = experiments["validation"]["paired_block_bootstrap"]
    case_reports = {}
    for cost in costs:
        case = cost["id"]
        paths = all_results[case]
        yearly = {str(year): {p["id"]: descriptive_metrics(
            [d for d in eligible if date.fromisoformat(d).year == year], paths, p["id"], cost_params[case].units)
            for p in rules} for year in range(2020, 2025)}
        folds = {}
        for fold_id, development, evaluation in EXPECTED_FOLDS:
            dev = [d for d in eligible if date.fromisoformat(d).year in development]
            val = [d for d in eligible if date.fromisoformat(d).year == evaluation]
            if not dev or not val or max(dev) >= min(val):
                raise RollingProtocolError("Chronological fold has no data or leaked future days")
            folds[fold_id] = {"development_years": list(development), "evaluation_year": evaluation,
                              "development_eligible_dates": dev, "evaluation_eligible_dates": val,
                              "development_in_fixed_policy_order": [
                                  {"id": p["id"], **descriptive_metrics(dev, paths, p["id"], cost_params[case].units)}
                                  for p in rules],
                              "evaluation_in_fixed_policy_order": [
                                  {"id": p["id"], **descriptive_metrics(val, paths, p["id"], cost_params[case].units)}
                                  for p in rules],
                              "evaluation_bootstrap_in_fixed_policy_order": [
                                  {"id": p["id"], **paired_week_bootstrap(
                                      [{"day_ny": d,
                                        "baseline_usd": _pnl(paths[d]["baseline_25_75"]),
                                        "candidate_usd": _pnl(paths[d][p["id"]]),
                                        "baseline_trade": paths[d]["baseline_25_75"]["status"] == "trade"}
                                       for d in val], iterations=gate["repetitions"], seed=gate["seed"],
                                      minimum_weeks=gate["minimum_distinct_weeks"],
                                      minimum_trades=gate["minimum_baseline_trade_days"])}
                                  for p in rules]}
        sensitivity = {str(year): [
            {"id": p["id"], **descriptive_metrics(
                [d for d in modelled_inclusive if date.fromisoformat(d).year == year],
                paths, p["id"], cost_params[case].units)} for p in rules]
            for year in range(2020, 2025)}
        case_reports[case] = {"assumptions": cost, "by_year_in_fixed_policy_order": yearly,
                              "folds": folds,
                              "posthoc_ambiguity_inclusive_descriptive_by_year_in_fixed_policy_order": sensitivity,
                              "daily_policy_paths": paths}
    spread_summary = {}
    for year in range(2020, 2025):
        values = sorted(spreads_by_year[year])
        spread_summary[str(year)] = ({"quote_days": len(values), "min_points": round(values[0], 6),
                                      "median_points": round(median(values), 6),
                                      "p95_points": round(values[max(0, math.ceil(.95 * len(values)) - 1)], 6),
                                      "max_points": round(values[-1], 6)} if values else {"quote_days": 0})
    return {"protocol_version": rolling["protocol_version"], "status": "retrospective_diagnostics_only",
            "warning": "NOT independent validation or actual broker fills. No candidate selected or promoted.",
            "candidate_order": list(EXPECTED_POLICIES), "cost_case_order": list(EXPECTED_COST_CASES),
            "common_eligible_dates": eligible, "excluded_dates_with_reasons": excluded,
            "posthoc_ambiguity_inclusive_dates": modelled_inclusive,
            "posthoc_sensitivity_warning": "Added after seeing exclusion counts only; modelled OHLC paths are not fill bounds, inference, or selection.",
            "coverage_by_year": by_year, "quoted_entry_spread_points_by_year": spread_summary,
            "exclusion_reason_counts": dict(Counter(reason for reasons in excluded.values() for reason in reasons)),
            "cases": case_reports}
