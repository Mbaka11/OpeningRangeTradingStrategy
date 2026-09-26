"""Fixed matrix runner: paired days, preflight baseline gate, no network."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from scripts.research.export_oanda_research import ResearchDownloadError
from scripts.research.run_exit_study import run_study

NY = ZoneInfo("America/New_York")
MANIFEST = yaml.safe_load((Path(__file__).resolve().parents[1] / "research" / "experiments.yml").read_text(encoding="utf8"))


def full_day(day, *, signal_close):
    t = datetime.combine(date.fromisoformat(day), datetime.strptime("09:30", "%H:%M").time(), tzinfo=NY)
    candles = []
    for minute in range(151):
        now = t + timedelta(minutes=minute)
        hhmm = now.strftime("%H:%M")
        mid = signal_close if hhmm == "10:22" else 100
        candles.append({"time": now.astimezone(timezone.utc).isoformat(), "complete": True,
                        "mid": {"o": "100", "h": str(110 if minute == 0 else max(100, mid)),
                                "l": str(90 if minute == 0 else min(100, mid)), "c": str(mid)},
                        "bid": {"o": "99", "h": "100", "l": "98", "c": "99"},
                        "ask": {"o": "101", "h": "102", "l": "100", "c": "101"}})
    return candles


def test_paired_smoke_keeps_no_trade_days_and_withholds_mc():
    paths = {"2026-09-24": full_day("2026-09-24", signal_close=105),
             "2026-09-25": full_day("2026-09-25", signal_close=100)}
    baseline = {"summary": {"signal_comparison": {"match": 2}, "broker_pl_check": {"match": 1},
                            "broker_trades_on_exported_days": 1}}
    out = run_study(paths, [{"day_ny": "2026-09-24", "status": "match"}], baseline, MANIFEST)
    for case in out["cost_cases"].values():
        assert case["counts"]["paired_unambiguous_sessions"] == 2
        assert case["eligible_dates"] == ["2026-09-24", "2026-09-25"]
        assert case["daily_policy_paths"]["2026-09-25"]["baseline_25_75"]["status"] == "no_trade"
        assert all(x["paired_sessions"] == 2 for x in case["candidate_descriptions_in_predeclared_order"])
        assert all(x["status"] == "insufficient_history" for x in case["uncertainty"].values())
        assert all("prob_candidate_trails_baseline_in_resample" not in x for x in case["uncertainty"].values())
    rejected = run_study(paths, [{"day_ny": "2026-09-24", "status": "unresolved"}], baseline, MANIFEST)
    assert all(x["counts"]["paired_unambiguous_sessions"] == 1 for x in rejected["cost_cases"].values())
    assert all("broker_exit_not_definitively_reconciled" in x["excluded_days"]["2026-09-24"]
               for x in rejected["cost_cases"].values())


def test_study_refuses_unreconciled_baseline_or_mutated_protocol():
    paths = {"2026-09-24": full_day("2026-09-24", signal_close=105)}
    baseline = {"summary": {"signal_comparison": {"mismatch": 1}, "broker_pl_check": {"match": 1},
                            "broker_trades_on_exported_days": 1}}
    parity = [{"day_ny": "2026-09-24", "status": "match"}]
    with pytest.raises(ResearchDownloadError, match="Baseline"):
        run_study(paths, parity, baseline, MANIFEST)
    changed = {**MANIFEST, "protocol_version": 999}
    with pytest.raises(ResearchDownloadError, match="version"):
        run_study(paths, parity, baseline, changed)
