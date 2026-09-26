"""Pure, synthetic policy tests: no actual broker orders, cloud jobs or tweets."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import random
from zoneinfo import ZoneInfo

import pytest
import yaml

from src.research_backtest import StrategyParams, run_session
from src.research_exits import run_policy_session, validate_policy

NY = ZoneInfo("America/New_York")
DAY = "2026-09-24"
MANIFEST = yaml.safe_load((Path(__file__).resolve().parents[1] / "research" / "experiments.yml").read_text(encoding="utf8"))
POLICIES = {x["id"]: x for x in MANIFEST["candidates"]}


def bars(side="long"):
    start = datetime.combine(date.fromisoformat(DAY), datetime.strptime("09:30", "%H:%M").time(), tzinfo=NY)
    rows = []
    for i in range(151):
        ts = start + timedelta(minutes=i)
        hhmm = ts.strftime("%H:%M")
        mid_close = (105 if side == "long" else 95) if hhmm == "10:22" else 100
        rows.append({"time": ts.astimezone(timezone.utc).isoformat(), "complete": True,
                     "mid": {"o": "100", "h": str(110 if hhmm == "09:30" else max(100, mid_close)),
                             "l": str(90 if hhmm == "09:30" else min(100, mid_close)), "c": str(mid_close)},
                     "bid": {"o": "99", "h": "100", "l": "98", "c": "99"},
                     "ask": {"o": "101", "h": "102", "l": "100", "c": "101"}})
    return rows


def at(rows, hhmm):
    return next(x for x in rows if datetime.fromisoformat(x["time"]).astimezone(NY).strftime("%H:%M") == hhmm)


def policy(name):
    return POLICIES[name]


def test_matrix_is_frozen_and_all_nine_policies_validate():
    assert MANIFEST["status"] == "research_only" and MANIFEST["protocol_version"] == 2
    assert MANIFEST["validation"]["paired_block_bootstrap"]["minimum_distinct_weeks"] == 26
    assert MANIFEST["validation"]["paired_block_bootstrap"]["minimum_baseline_trade_days"] == 100
    assert len(POLICIES) == len(MANIFEST["candidates"]) == 9
    assert set(POLICIES) == {"baseline_25_75", "full_40", "full_50", "half_30_runner_75",
                             "half_40_runner_75", "protect_30_runner_75", "protect_40_runner_75",
                             "trail_40_by_20_runner_75", "full_time_1115"}
    for spec in POLICIES.values():
        validate_policy(spec, StrategyParams())
    with pytest.raises(ValueError):
        validate_policy({**policy("half_30_runner_75"), "remaining_stop_points_from_entry": 0}, StrategyParams())
    with pytest.raises(ValueError):
        validate_policy({**policy("protect_30_runner_75"), "activation_points": 90}, StrategyParams())


def test_control_reproduces_same_baseline_as_step2_for_long_short_no_trade():
    for side in ("long", "short"):
        rows = bars(side)
        if side == "long":
            at(rows, "10:24")["bid"]["h"] = "177"  # entry ask=101 -> +75
        else:
            at(rows, "10:24")["ask"]["l"] = "24"  # entry bid=99 -> +75 short
        a = run_session(DAY, rows, StrategyParams(commission_per_side_usd=3))
        b = run_policy_session(DAY, rows, StrategyParams(commission_per_side_usd=3), policy("baseline_25_75"))
        for key in ("status", "side", "entry_price", "exit_reason", "exit_price", "net_usd", "ambiguous_same_bar"):
            assert a[key] == b[key]
        assert b["net_usd"] == 5994 and len(b["legs"]) == 1
    rows = bars()
    at(rows, "10:22")["mid"]["c"] = "100"  # middle zone
    assert run_policy_session(DAY, rows, StrategyParams(), policy("half_30_runner_75"))["status"] == "no_trade"
    rows.pop(0)
    assert run_policy_session(DAY, rows, StrategyParams(), policy("protect_30_runner_75"))["status"] == "excluded"


def test_fixed_lower_target_changes_actual_exit():
    rows = bars()
    at(rows, "10:24")["bid"]["h"] = "143"
    at(rows, "10:25")["bid"]["l"] = "75"
    assert run_policy_session(DAY, rows, StrategyParams(), policy("baseline_25_75"))["exit_reason"] == "sl"
    result = run_policy_session(DAY, rows, StrategyParams(), policy("full_40"))
    assert result["exit_reason"] == "tp" and result["gross_points"] == 40


def test_half_at_30_then_remaining_stop_is_only_2_5_points_before_extra_fill_cost():
    rows = bars()
    at(rows, "10:24")["bid"]["h"] = "132"  # entry=101, first TP=131
    at(rows, "10:25")["bid"]["l"] = "75"   # original stop=76
    result = run_policy_session(DAY, rows, StrategyParams(commission_per_side_usd=2),
                                policy("half_30_runner_75"))
    assert result["gross_points"] == 2.5 and result["gross_usd"] == 200
    assert result["net_usd"] == 194  # opening + TWO closing order costs
    assert [(leg["units"], leg["reason"]) for leg in result["legs"]] == [(40, "tp_partial"), (40, "sl")]


def test_same_bar_stop_and_partial_target_assumes_full_stop_and_flags_ordering():
    rows = bars()
    bar = at(rows, "10:24")["bid"]
    bar.update({"h": "180", "l": "75"})
    res = run_policy_session(DAY, rows, StrategyParams(), policy("half_30_runner_75"))
    assert res["gross_points"] == -25 and res["ambiguous_same_bar"]
    assert len(res["legs"]) == 1 and res["legs"][0]["units"] == 80
    assert "stop_and_favorable_touch_same_bar" in res["ambiguity_reasons"]


def test_partial_runner_target_within_first_target_bar_is_deferred_and_flagged():
    rows = bars()
    at(rows, "10:24")["bid"].update({"h": "185", "l": "99"})
    at(rows, "10:25")["bid"]["l"] = "75"
    res = run_policy_session(DAY, rows, StrategyParams(), policy("half_30_runner_75"))
    assert res["gross_points"] == 2.5 and res["ambiguous_same_bar"]
    assert "runner_target_inside_first_partial_bar_deferred" in res["ambiguity_reasons"]


def test_protect_amendment_is_next_bar_not_an_intrabar_rescue():
    rows = bars()
    at(rows, "10:24")["bid"].update({"h": "132", "l": "100"})  # touches +30 then entry, unknown order
    at(rows, "10:25")["bid"].update({"o": "102", "l": "100"})
    res = run_policy_session(DAY, rows, StrategyParams(), policy("protect_30_runner_75"))
    assert res["gross_points"] == 0 and res["exit_reason"] == "sl" and res["amendments"] == 1
    assert res["ambiguous_same_bar"]  # theoretical intrabar update could have filled earlier
    at(rows, "10:25")["bid"]["o"] = "99"  # gap through protected stop at next-bar open
    slipped = run_policy_session(DAY, rows, StrategyParams(), policy("protect_30_runner_75"))
    assert slipped["gross_points"] == -2 and slipped["gap_through_stop"]
    at(rows, "10:24")["bid"]["l"] = "75"  # SL and activation same minute -> initial SL first
    stopped = run_policy_session(DAY, rows, StrategyParams(), policy("protect_30_runner_75"))
    assert stopped["gross_points"] == -25 and stopped["amendments"] == 0 and stopped["ambiguous_same_bar"]


def test_trailing_stop_is_based_on_completed_bar_and_never_loosens():
    rows = bars()
    at(rows, "10:24")["bid"].update({"h": "145", "l": "126"})  # peak=+44, trailing stop=125
    at(rows, "10:25")["bid"].update({"o": "127", "h": "127", "l": "124"})
    res = run_policy_session(DAY, rows, StrategyParams(), policy("trail_40_by_20_runner_75"))
    assert res["exit_price"] == 125 and res["gross_points"] == 24
    assert res["amendments"] == 1 and not res["ambiguous_same_bar"]
    # TP was working since entry: it remains a valid full exit on activation bar.
    at(rows, "10:24")["bid"].update({"h": "177", "l": "126"})
    assert run_policy_session(DAY, rows, StrategyParams(), policy("trail_40_by_20_runner_75"))["gross_points"] == 75


def test_short_partial_and_time_rule_have_correct_direction_and_exit_minute():
    rows = bars("short")
    at(rows, "10:24")["ask"]["l"] = "68"  # entry bid99, +30 at ask69
    at(rows, "10:25")["ask"]["h"] = "125"  # SL124
    short = run_policy_session(DAY, rows, StrategyParams(), policy("half_30_runner_75"))
    assert short["gross_points"] == 2.5 and [x["reason"] for x in short["legs"]] == ["tp_partial", "sl"]
    result = run_policy_session(DAY, bars(), StrategyParams(), policy("full_time_1115"))
    assert result["exit_minute"].endswith("11:15:00-04:00") and result["exit_reason"] == "time"


def test_random_paths_preserve_total_units_and_fee_accounting():
    rng = random.Random(11)
    for side in ("long", "short"):
        for _ in range(20):
            rows = bars(side)
            for minute in ("10:24", "10:25", "10:26", "10:27"):
                bar = at(rows, minute)
                bar["bid"]["h"] = str(max(99, rng.uniform(60, 200)))
                bar["bid"]["l"] = str(min(99, rng.uniform(60, 200)))
                bar["ask"]["h"] = str(max(101, rng.uniform(60, 200)))
                bar["ask"]["l"] = str(min(101, rng.uniform(60, 200)))
            params = StrategyParams(commission_per_side_usd=2)
            for spec in POLICIES.values():
                outcome = run_policy_session(DAY, rows, params, spec)
                assert outcome["status"] == "trade"
                assert sum(leg["units"] for leg in outcome["legs"]) == params.units
                assert 1 <= len(outcome["legs"]) <= 2
                assert outcome["net_usd"] == pytest.approx(
                    outcome["gross_usd"] - (1 + len(outcome["legs"])) * 2, abs=0.00001)


def test_gap_through_stop_applies_to_baseline_and_candidates_equally():
    rows = bars()
    at(rows, "10:24")["bid"].update({"o": "70", "l": "70"})  # gap beyond stop 76
    baseline = run_policy_session(DAY, rows, StrategyParams(), policy("baseline_25_75"))
    partial = run_policy_session(DAY, rows, StrategyParams(), policy("half_30_runner_75"))
    assert baseline["gross_points"] == partial["gross_points"] == -31
    assert baseline["gap_through_stop"] and partial["gap_through_stop"]
