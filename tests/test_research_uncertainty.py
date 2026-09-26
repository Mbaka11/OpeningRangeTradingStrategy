"""No Monte Carlo probabilities from the short observed trading history."""

from datetime import date, timedelta

import pytest

from src.research_uncertainty import paired_week_bootstrap


def days(weeks: int):
    start = date(2025, 1, 6)  # Monday
    return [{"day_ny": (start + timedelta(weeks=w, days=d)).isoformat(),
             "baseline_usd": -20.0 if d != 4 else 0.0,
             "candidate_usd": -10.0 if d != 4 else 0.0, "baseline_trade": d != 4}
            for w in range(weeks) for d in range(5)]


def test_short_sample_returns_explicit_gate_not_probabilities():
    result = paired_week_bootstrap(days(6))
    assert result["status"] == "insufficient_history"
    assert result["distinct_weeks"] == 6 and result["baseline_trade_days"] == 24
    assert "prob_candidate_trails_baseline_in_resample" not in result
    assert "paired_mean_usd_per_session_p05_p50_p95" not in result


def test_week_blocks_are_paired_and_seed_reproducible_when_gate_passes():
    sample = days(26)  # 26 weeks, 104 trade days, one no-trade per week
    a = paired_week_bootstrap(sample, iterations=60, seed=17)
    b = paired_week_bootstrap(sample, iterations=60, seed=17)
    assert a == b and a["status"] == "descriptive_bootstrap_only"
    assert a["paired_mean_usd_per_session_p05_p50_p95"] == [8, 8, 8]
    assert a["prob_candidate_trails_baseline_in_resample"] == 0
    assert a["candidate_max_drawdown_usd_p05_p50_p95"][-1] < a["baseline_max_drawdown_usd_p05_p50_p95"][-1]


def test_duplicate_days_are_rejected():
    sample = days(2)
    with pytest.raises(ValueError, match="Duplicate"):
        paired_week_bootstrap(sample + [sample[0]])
