"""The tracked notebook must remain blank; charts only consume paired private results."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nbformat
import pytest
import yaml

from src.research_visuals import (load_views, plot_coverage, plot_cost_scenarios,
                                  plot_daily_differences, plot_evidence_gate, plot_one_day)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = yaml.safe_load((ROOT / "research" / "experiments.yml").read_text(encoding="utf-8"))
ORDER = [p["id"] for p in PROTOCOL["candidates"]]


def synthetic_report():
    cases = {}
    for cost in PROTOCOL["common"]["cost_cases"]:
        paths = {}
        for day, status in (("2026-09-23", "trade"), ("2026-09-24", "trade"), ("2026-09-25", "no_trade")):
            paths[day] = {pid: ({"status": "trade", "net_usd": float(100 + 20 * i),
                                  "gross_points": float(-25 + 10 * i), "exit_reason": "tp"} if status == "trade"
                                else {"status": "no_trade"}) for i, pid in enumerate(ORDER)}
        cases[cost["id"]] = {
            "assumptions": cost,
            "daily_policy_paths": paths,
            "eligible_dates": ["2026-09-24", "2026-09-25"],
            "excluded_days": {"2026-09-23": ["OHLC_ordering_ambiguous"]},
            "counts": {"exported_sessions": 3, "paired_unambiguous_sessions": 2},
            "candidate_descriptions_in_predeclared_order": [
                {"id": pid, "paired_sessions": 2, "paired_difference_vs_baseline_usd": float(20 * i)}
                for i, pid in enumerate(ORDER)],
            "uncertainty": {pid: {"status": "insufficient_history", "eligible_sessions": 2,
                                  "baseline_trade_days": 1, "distinct_weeks": 1,
                                  "minimum_distinct_weeks": 26, "minimum_baseline_trade_days": 100}
                            for pid in ORDER},
        }
    return {"protocol_version": 2, "cost_cases": cases}


def test_paired_transform_retains_zero_no_trade_and_excludes_uncertain_day():
    views = load_views(synthetic_report(), PROTOCOL)
    assert set(views) == {"bid_ask_only", "adverse_extra_1pt_per_fill"}
    view = views["bid_ask_only"]
    assert len(view.coverage) == 3 and len(view.eligible_dates) == 2
    assert view.net_difference.index.tolist() == ["2026-09-24", "2026-09-25"]
    assert view.net_difference.loc["2026-09-24", "full_40"] == 20
    assert view.net_difference.loc["2026-09-25", "full_40"] == 0
    assert view.coverage.iloc[0]["category"] == "Minute-bar ordering uncertain"


def test_all_five_charts_render_on_synthetic_offline_data():
    views = load_views(synthetic_report(), PROTOCOL)
    view = views["adverse_extra_1pt_per_fill"]
    for fig in (plot_coverage(view), plot_daily_differences(view), plot_cost_scenarios(views),
                plot_one_day(view), plot_evidence_gate(view)):
        fig.canvas.draw()
        assert fig.axes and fig.get_size_inches().min() > 2
        plt.close(fig)
    with pytest.raises(ValueError, match="clean eligible TRADE"):
        plot_one_day(view, day="2026-09-23")


def test_report_mismatch_is_refused_not_misleadingly_charted():
    report = synthetic_report()
    report["cost_cases"]["bid_ask_only"]["candidate_descriptions_in_predeclared_order"][1][
        "paired_difference_vs_baseline_usd"] += 123
    with pytest.raises(ValueError, match="paired results"):
        load_views(report, PROTOCOL)
    report = synthetic_report()
    report["cost_cases"]["bid_ask_only"]["daily_policy_paths"]["2026-09-25"]["full_40"]["status"] = "trade"
    with pytest.raises(ValueError, match="statuses differ"):
        load_views(report, PROTOCOL)


def test_committed_notebook_never_contains_private_cached_outputs():
    notebook = nbformat.read(ROOT / "notebooks" / "06_exit_comparison.ipynb", as_version=4)
    assert any("what if?" in cell.source.lower() for cell in notebook.cells)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            assert cell.execution_count is None
            assert cell.outputs == []
    assert "fills.json" not in json.dumps(notebook)
