"""Pure, POST-HOC audit of saved quote gaps, ambiguity flags and cost ledgers.

Not a new backtest, tick replay, execution bound, broker test or policy selector.
Never repairs quotes or changes the step-5 common sample. No network/secrets.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import math
from statistics import median

from src.research_backtest import NY, StrategyParams, _minute
from src.research_history import audit_day
from src.research_parity import parse_time
from src.research_rolling import validate_protocol

# Deferred amendments are deterministic under the frozen completed-bar model.
# Flags warn about substituting another implementation, not proven simultaneous
# fills of the stop which was actually working during the activation candle.
MECHANISMS = {
    "stop_and_target_same_bar": "working_stop_and_target_ordering",
    "stop_and_favorable_touch_same_bar": "working_stop_and_favorable_touch_ordering",
    "runner_target_inside_first_partial_bar_deferred": "partial_runner_installation_timing",
    "entry_stop_would_touch_activation_bar_before_amendment": "amendment_timing_sensitivity",
    "trail_would_touch_in_same_bar_before_amendment": "amendment_timing_sensitivity",
}


ALLOWED_MECHANISMS = {
    "fixed": {"stop_and_target_same_bar"},
    "time": {"stop_and_target_same_bar"},
    "partial": {"stop_and_favorable_touch_same_bar", "runner_target_inside_first_partial_bar_deferred"},
    "protect": {"stop_and_favorable_touch_same_bar", "entry_stop_would_touch_activation_bar_before_amendment"},
    "trailing": {"stop_and_favorable_touch_same_bar", "trail_would_touch_in_same_bar_before_amendment"},
}


class ExecutionAuditError(ValueError):
    """Sanitized, fail-closed diagnostic input error; no quotes/results in messages."""


def _finite(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExecutionAuditError("Non-finite or nonnumeric modeled ledger value")
    return float(value)


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionAuditError("Invalid modeled fill/unit/amendment count")
    return value


def validate_context(context: dict) -> None:
    if (context.get("protocol_version") != 1 or context.get("status") != "posthoc_execution_diagnostics_only"
            or context.get("selection") != "none" or context.get("change_primary_sample") is not False
            or context.get("change_exit_or_cost_rules") is not False or context.get("network_in_runner") is not False
            or context.get("calendar_basis") != "US_cash_equity_context_NOT_OANDA_CFD_quote_schedule"):
        raise ExecutionAuditError("Expected post-hoc diagnostics with unchanged sample/rules")
    for year in range(2020, 2025):
        ref = context["calendar_years"][str(year)]
        if ref["verification"] not in ("official_table_transcribed", "hypothesis_not_independently_transcribed"):
            raise ExecutionAuditError("Unknown calendar evidence level")
        source = context["sources"][ref["source"]]
        if (ref["verification"] == "official_table_transcribed"
                and source["evidence"] != "official_ICE_release_table_transcribed"):
            raise ExecutionAuditError("Unverified calendar cannot be labeled an official table")
        for day in ref["full_cash_equity_closures"]:
            d = date.fromisoformat(day)
            if d.year != year or d.weekday() >= 5:
                raise ExecutionAuditError("Calendar date outside reference weekday/year")
    for day, halt in context["cash_equity_halts"].items():
        start = datetime.fromisoformat(day + "T" + halt["start_ny"])
        end = datetime.fromisoformat(day + "T" + halt["end_ny"])
        if not start < end or halt["source"] not in context["sources"]:
            raise ExecutionAuditError("Invalid public cash-equity halt interval")


def _gap_context(day: str, candles: list[dict], context: dict) -> dict:
    d = date.fromisoformat(day)
    quality = audit_day(d, candles)
    first = _minute(d, "09:30")
    expected = [first + timedelta(minutes=i) for i in range(151)]
    seen = {parse_time(c["time"]).astimezone(NY) for c in candles}
    missing = [t for t in expected if t not in seen]
    ref = context["calendar_years"][str(d.year)]
    holiday = ref["full_cash_equity_closures"].get(day)
    classification = ("verified_cash_equity_holiday_context" if ref["verification"] == "official_table_transcribed"
                      else "unverified_cash_equity_holiday_hypothesis") if holiday else (
                          "no_cash_equity_holiday_in_reference" if ref["verification"] == "official_table_transcribed"
                          else "unverified_calendar_no_listed_holiday")
    halt = context["cash_equity_halts"].get(day)
    overlap = 0
    if halt:
        start = datetime.fromisoformat(day + "T" + halt["start_ny"]).replace(tzinfo=NY)
        end = datetime.fromisoformat(day + "T" + halt["end_ny"]).replace(tzinfo=NY)
        # A missing M1 candle covers [timestamp, timestamp+1m). Its interval
        # may overlap the documented CASH halt; this does NOT establish cause.
        overlap = sum(t < end and t + timedelta(minutes=1) > start for t in missing)
    return {"day_ny": day, "quality": quality, "missing_minute_starts_ny": [t.strftime("%H:%M") for t in missing],
            "missing_opening_range_minutes": sum(t <= _minute(d, "10:00") for t in missing),
            "missing_decision_minute": _minute(d, "10:22") in missing,
            "missing_entry_minute": _minute(d, "10:23") in missing,
            "missing_hard_flat_minute": _minute(d, "12:00") in missing,
            "cash_calendar_classification": classification, "cash_holiday": holiday,
            "calendar_source": ref["source"], "reference_cash_halt": halt,
            "missing_candle_intervals_overlapping_cash_halt": overlap,
            "oanda_gap_cause": "unverified", "kept_excluded": True}


def _ledger(row: dict, day: str, candles: list[dict], spec: dict, cost: dict, units: int) -> dict:
    if row.get("day_ny") != day or row.get("policy_id") != spec["id"]:
        raise ExecutionAuditError("Policy/day identity differs from saved modeled path")
    if row["status"] == "no_trade":
        if (row.get("legs") or row.get("amendments", 0) or row.get("ambiguous_same_bar", False)
                or row.get("ambiguity_reasons") or row.get("gap_through_stop", False)
                or any(row.get(k) is not None for k in ("side", "entry_price", "entry_minute", "exit_price", "exit_minute"))):
            raise ExecutionAuditError("No-trade day has modeled fills/amendments/ambiguity")
        if any(_finite(row.get(k, 0)) != 0 for k in ("gross_usd", "gross_points", "net_usd")):
            raise ExecutionAuditError("No-trade day is not a zero modeled ledger")
        return {"status": "no_trade"}
    if row["status"] != "trade" or row.get("side") not in ("long", "short"):
        raise ExecutionAuditError("Quote-complete path is not a trade/no-trade observation")
    direction = 1 if row["side"] == "long" else -1
    entry, legs = _finite(row["entry_price"]), row["legs"]
    entry_time = _minute(date.fromisoformat(day), "10:23")
    if parse_time(row["entry_minute"]) != entry_time:
        raise ExecutionAuditError("Saved modeled entry is not the frozen next-minute open")
    entry_bar = next(c for c in candles if parse_time(c["time"]) == entry_time)
    quote_entry = float(entry_bar["ask" if direction > 0 else "bid"]["o"])
    if not math.isclose(entry, quote_entry + direction * cost["entry_slippage_points"], abs_tol=1e-5):
        raise ExecutionAuditError("Modeled entry differs from executable-side open plus frozen penalty")
    if not isinstance(legs, list) or not 1 <= len(legs) <= (2 if spec["family"] == "partial" else 1):
        raise ExecutionAuditError("Unexpected modeled closing fill count")
    if any(_count(leg["units"]) == 0 for leg in legs) or sum(leg["units"] for leg in legs) != units:
        raise ExecutionAuditError("Modeled closing legs do not conserve initial units")
    if len(legs) == 2 and (legs[0]["reason"] != "tp_partial"
                         or legs[0]["units"] != int(units * spec["first_exit_fraction"])):
        raise ExecutionAuditError("Modeled partial leg differs from frozen unit split")
    hard_flat = _minute(date.fromisoformat(day), spec.get("exit_ny", "12:00"))
    times = [parse_time(leg["minute"]) for leg in legs]
    if (times != sorted(times) or any(not entry_time <= t <= hard_flat or t.second or t.microsecond for t in times)
            or len(times) == 2 and times[1] <= times[0]):
        raise ExecutionAuditError("Modeled closing legs outside causal session order/deferred runner")
    if any(leg["reason"] not in ("sl", "tp", "tp_partial", "time") for leg in legs):
        raise ExecutionAuditError("Unknown modeled close reason")
    if any((leg["reason"] == "time") != (t == hard_flat) for leg, t in zip(legs, times)):
        raise ExecutionAuditError("Modeled time close must be exactly at policy hard flat")
    gross = sum(direction * (_finite(leg["exit_price"]) - entry) * leg["units"] for leg in legs)
    commission = (1 + len(legs)) * cost["commission_per_side_usd"]
    weighted_exit = sum(leg["exit_price"] * leg["units"] for leg in legs) / units
    for field, expected in (("gross_usd", gross), ("gross_points", gross / units),
                            ("net_usd", gross - commission), ("exit_price", weighted_exit)):
        if not math.isclose(_finite(row[field]), expected, rel_tol=0, abs_tol=1e-4):
            raise ExecutionAuditError("Modeled units/weighted fill/fee ledger does not reconcile")
    if parse_time(row["exit_minute"]) != times[-1]:
        raise ExecutionAuditError("Modeled final exit differs from the last closing leg")
    amendments = _count(row.get("amendments", 0))
    if spec["family"] not in ("protect", "trailing") and amendments:
        raise ExecutionAuditError("Non-amending rule contains modeled stop amendments")
    reasons = row.get("ambiguity_reasons", [])
    if row.get("ambiguous_same_bar", False) and not reasons:
        if spec["family"] not in ("fixed", "time"):
            raise ExecutionAuditError("Dynamic ambiguity flag has no recognized mechanism")
        reasons = ["stop_and_target_same_bar"]
    if (not isinstance(row.get("ambiguous_same_bar", False), bool)
            or any(r not in ALLOWED_MECHANISMS[spec["family"]] for r in reasons)
            or bool(reasons) != bool(row.get("ambiguous_same_bar", False))):
        raise ExecutionAuditError("Unknown, wrong-family or inconsistent modeled ambiguity mechanism")
    return {"status": "trade", "mechanisms": sorted(set(reasons)), "amendments": amendments,
            "modeled_fill_count": 1 + len(legs), "modeled_commission_usd": commission,
            "unit_weighted_exit_penalty_usd": units * cost["exit_slippage_points"],
            # Entry penalty already shifts the fill AND all attached risk levels;
            # this amount is bookkeeping, not a ceteris-paribus P&L subtraction.
            "unit_weighted_entry_penalty_usd": units * cost["entry_slippage_points"],
            "modeled_tp_legs_with_adverse_penalty": sum(leg["reason"] in ("tp", "tp_partial")
                                                        for leg in legs) if cost["exit_slippage_points"] else 0}


def audit_execution(market: dict, quality: dict, study: dict,
                    experiments: dict, rolling: dict, context: dict) -> dict:
    """Audit authenticated saved paths, not optimize or reclassify them.

    Runner separately verifies raw batch/protocol/baseline/code fingerprints.
    Calendar comparison is cash-equity context only, never OANDA holiday proof.
    """
    rules, costs = validate_protocol(experiments, rolling)
    validate_context(context)
    dates = set(market)
    primary = study["common_eligible_dates"]
    excluded = study["excluded_dates_with_reasons"]
    complete = {d for d, flag in quality.items() if flag == "complete"}
    if (not dates or dates != set(quality) or study.get("status") != "retrospective_diagnostics_only"
            or study["candidate_order"] != [r["id"] for r in rules]
            or study["cost_case_order"] != [c["id"] for c in costs]
            or len(primary) != len(set(primary)) or set(primary) & set(excluded)
            or (set(primary) | set(excluded)) != dates
            or any(date.fromisoformat(d).year not in range(2020, 2025) or date.fromisoformat(d).weekday() >= 5 for d in dates)):
        raise ExecutionAuditError("Saved paired sample/report/date contract differs")
    quote_gaps, spreads = [], defaultdict(list)
    for day in sorted(dates):
        observed = audit_day(date.fromisoformat(day), market[day])
        if observed["status"] != quality[day]:
            raise ExecutionAuditError("Saved quote quality flag differs from current offline audit")
        if day not in complete:
            if excluded.get(day) != ["quote_" + quality[day]]:
                raise ExecutionAuditError("Quote exclusion differs from frozen study")
            quote_gaps.append(_gap_context(day, market[day], context))
        else:
            bar = next(c for c in market[day] if parse_time(c["time"]).astimezone(NY).strftime("%H:%M") == "10:23")
            spreads[str(date.fromisoformat(day).year)].append(float(bar["ask"]["o"]) - float(bar["bid"]["o"]))
    units = StrategyParams().units
    mechanism_days = {r: set() for r in MECHANISMS}
    category_days = {c: set() for c in set(MECHANISMS.values())}
    ambiguous_days, case_reports = set(), []
    structural_changes = {r["id"]: set() for r in rules}
    for cost in costs:
        case = study["cases"][cost["id"]]
        paths = case["daily_policy_paths"]
        if case["assumptions"] != cost or set(paths) != complete:
            raise ExecutionAuditError("Saved cost assumptions or quote-complete path dates differ")
        counters = {r["id"]: Counter() for r in rules}
        daily = {}
        for day in sorted(complete):
            if set(paths[day]) != {r["id"] for r in rules}:
                raise ExecutionAuditError("Missing or duplicate policy path on complete day")
            base = paths[day]["baseline_25_75"]
            for rule in rules:
                row = paths[day][rule["id"]]
                if (row["status"] != base["status"] or row.get("side") != base.get("side")
                        or row.get("entry_price") != base.get("entry_price") or row.get("entry_minute") != base.get("entry_minute")):
                    raise ExecutionAuditError("Candidate entry/direction/status differs from control")
                ledger = _ledger(row, day, market[day], rule, cost, units)
                daily.setdefault(day, {})[rule["id"]] = ledger
                counter = counters[rule["id"]]
                counter[ledger["status"] + "_days"] += 1
                if ledger["status"] == "trade":
                    for key in ("amendments", "modeled_fill_count", "modeled_tp_legs_with_adverse_penalty"):
                        counter[key] += ledger[key]
                    if ledger["mechanisms"]:
                        counter["ambiguous_policy_days"] += 1
                        ambiguous_days.add(day)
                    for reason in ledger["mechanisms"]:
                        mechanism_days[reason].add(day)
                        category_days[MECHANISMS[reason]].add(day)
                        counter[reason] += 1
                if cost != costs[0]:
                    earlier = study["cases"][costs[0]["id"]]["daily_policy_paths"][day][rule["id"]]
                    signature = lambda p: ([(leg["units"], leg["reason"], leg["minute"]) for leg in p.get("legs", [])],
                                           p.get("amendments", 0), p.get("ambiguous_same_bar", False), p.get("gap_through_stop", False))
                    if row["status"] != earlier["status"] or row.get("side") != earlier.get("side"):
                        raise ExecutionAuditError("Cost cases differ on signal/status")
                    if signature(row) != signature(earlier):
                        structural_changes[rule["id"]].add(day)
        case_reports.append({"id": cost["id"], "costs_are_observed": False,
                             "policy_counts_in_fixed_order": [{"id": r["id"], **dict(counters[r["id"]])} for r in rules],
                             "full_size_entry_price_stop_net_usd_model": -units * cost["exit_slippage_points"] - 2 * cost["commission_per_side_usd"],
                             "full_size_net_zero_trigger_offset_from_filled_entry_points_model": cost["exit_slippage_points"] + 2 * cost["commission_per_side_usd"] / units,
                             "daily_ledger_checks": daily})
    original_ambiguous = {d for d, reasons in excluded.items() if "one_minute_ordering_ambiguous" in reasons}
    if ambiguous_days != original_ambiguous or set(primary) != complete - ambiguous_days:
        raise ExecutionAuditError("Mechanism audit would alter the original clean paired sample")
    classifications = Counter(r["cash_calendar_classification"] for r in quote_gaps)
    return {"protocol_version": 1, "status": "posthoc_execution_diagnostics_only", "selection": "none",
            "execution_verified": False, "historical_costs_verified": False, "primary_sample_unchanged": True,
            "requested_weekdays": len(dates), "quote_complete_days": len(complete), "quote_excluded_days": len(quote_gaps),
            "original_clean_paired_days": len(primary), "original_any_policy_ambiguous_days": len(ambiguous_days),
            "mechanisms_in_fixed_order": [{"reason": reason, "category": MECHANISMS[reason],
                                            "unique_days_across_costs_and_policies": len(mechanism_days[reason]),
                                            "dates_private": sorted(mechanism_days[reason])} for reason in MECHANISMS],
            "category_unique_day_counts": {c: len(category_days[c]) for c in sorted(category_days)},
            "quote_gap_calendar_context_counts": dict(sorted(classifications.items())),
            "gap_days_with_missing_candle_intervals_overlapping_cash_halts": sum(r["missing_candle_intervals_overlapping_cash_halt"] > 0 for r in quote_gaps),
            "quote_gap_context_private": quote_gaps,
            "entry_open_quote_spreads_by_year": {y: {"quote_days": len(v), "median_points": round(median(v), 6)} for y, v in sorted(spreads.items())},
            "cost_cases_in_fixed_order": case_reports,
            "changed_modeled_exit_structure_or_minutes_under_existing_cost_stress": [
                {"id": r["id"], "days": len(structural_changes[r["id"]])} for r in rules],
            "limits": ["POST-HOC diagnostic, not revised primary sample, performance ranking or fill bound.",
                       "Mechanism date counts overlap; do not sum them as independent days.",
                       "Deferred amendments are deterministic only within the completed-bar model; actual latency/native trailing is unverified.",
                       "Cash equity holidays/halts do not prove OANDA CFD quote hours or why quotes are missing.",
                       "Entry penalty changes filled entry and anchored levels; stressed results are not merely a flat fee subtraction.",
                       "OANDA TP orders have equal-or-better-than-target semantics; adverse modeled TP penalties are only cost stress, NOT admissible resting-TP fill reconstructions.",
                       "Historical point/unit mapping, entity/account fees, partial order liquidity and broker executions remain unverified."]}
