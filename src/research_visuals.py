"""Read-only charts for the PRIVATE offline exit-study report.

These are descriptive visualizations, not rule selection or broker execution.
Never save rendered figures or executed notebook outputs in Git.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


LABELS = {
    "baseline_25_75": "Current: -25 / +75",
    "full_40": "Entire trade: +40",
    "full_50": "Entire trade: +50",
    "half_30_runner_75": "Half +30; rest +75",
    "half_40_runner_75": "Half +40; rest +75",
    "protect_30_runner_75": "Move stop to entry at +30",
    "protect_40_runner_75": "Move stop to entry at +40",
    "trail_40_by_20_runner_75": "Trail 20 after +40",
    "full_time_1115": "Close by 11:15",
}


@dataclass(frozen=True)
class ExitView:
    case_id: str
    order: tuple[str, ...]
    eligible_dates: tuple[str, ...]
    coverage: pd.DataFrame
    net_difference: pd.DataFrame
    uncertainty: dict
    results: dict
    assumptions: dict


def _usd(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid finite hypothetical net USD value in private study report")
    return float(value)


def load_views(report: dict, protocol: dict) -> dict[str, ExitView]:
    """Check paired-date and protocol integrity before any chart uses private P&L."""
    if report.get("protocol_version") != protocol.get("protocol_version") or protocol.get("status") != "research_only":
        raise ValueError("Study and research-only protocol versions must match")
    order = tuple(row["id"] for row in protocol["candidates"])
    if len(order) != len(set(order)) or set(order) != set(LABELS) or order[0] != "baseline_25_75":
        raise ValueError("This notebook supports the predeclared nine-policy matrix only")
    if set(report["cost_cases"]) != {row["id"] for row in protocol["common"]["cost_cases"]}:
        raise ValueError("Study and protocol cost cases do not match")
    views = {}
    for case_id in (row["id"] for row in protocol["common"]["cost_cases"]):
        case = report["cost_cases"][case_id]
        if case["assumptions"] != next(row for row in protocol["common"]["cost_cases"] if row["id"] == case_id):
            raise ValueError("Study report cost assumptions have changed")
        descriptions = case["candidate_descriptions_in_predeclared_order"]
        if [x["id"] for x in descriptions] != list(order) or set(case["uncertainty"]) != set(order):
            raise ValueError("Missing or reordered policy descriptions or uncertainty gates")
        days = case["daily_policy_paths"]
        eligible = case["eligible_dates"]
        excluded = case["excluded_days"]
        if (len(eligible) != len(set(eligible)) or set(eligible) & set(excluded)
                or set(days) != (set(eligible) | set(excluded))
                or case["counts"]["paired_unambiguous_sessions"] != len(eligible)
                or case["counts"]["exported_sessions"] != len(days)):
            raise ValueError("Unmatched study days: do not compare different samples")
        coverage = []
        for day in sorted(days):
            date.fromisoformat(day)
            if set(days[day]) != set(order):
                raise ValueError("Policy missing from a session")
            reasons = excluded.get(day, [])
            if reasons:
                category = ("Multiple exclusions" if len(reasons) > 1 else {
                    "broker_exit_not_definitively_reconciled": "Broker exit uncertain",
                    "OHLC_ordering_ambiguous": "Minute-bar ordering uncertain",
                    "incomplete_or_ineligible_market_path": "Incomplete market data",
                }.get(reasons[0], "Other exclusion"))
            else:
                category = "Paired trade" if days[day][order[0]]["status"] == "trade" else "Paired no-trade"
            coverage.append({"date": day, "category": category})
        net_rows = []
        for day in eligible:  # same-day paired net differences; do not touch excluded P&L
            outcomes = days[day]
            status = outcomes[order[0]]["status"]
            if status not in ("trade", "no_trade") or any(outcomes[p]["status"] != status for p in order):
                raise ValueError("Eligible policy trade/no-trade statuses differ")
            base = _usd(outcomes[order[0]]["net_usd"]) if status == "trade" else 0.0
            row = {"date": day, "baseline_trade": status == "trade"}
            for p in order:
                pnl = _usd(outcomes[p]["net_usd"]) if status == "trade" else 0.0
                row[p] = pnl - base
            net_rows.append(row)
        frame = pd.DataFrame(net_rows, columns=["date", "baseline_trade", *order]).set_index("date")
        for desc in descriptions:
            if desc["paired_sessions"] != len(frame) or not math.isclose(
                _usd(desc["paired_difference_vs_baseline_usd"]), frame[desc["id"]].sum(), abs_tol=0.05
            ):
                raise ValueError("Study description disagrees with common-date paired results")
        gate = case["uncertainty"][order[0]]
        if (gate["eligible_sessions"] != len(eligible)
                or gate["baseline_trade_days"] != int(frame["baseline_trade"].sum())):
            raise ValueError("Uncertainty sample counts disagree with paired dates")
        views[case_id] = ExitView(case_id, order, tuple(eligible), pd.DataFrame(coverage),
                                  frame, case["uncertainty"], days, case["assumptions"])
    return views


COVERAGE_COLORS = {
    "Paired trade": "#167d78", "Paired no-trade": "#88cbb8",
    "Broker exit uncertain": "#d38319", "Minute-bar ordering uncertain": "#a43952",
    "Incomplete market data": "#666e7a", "Multiple exclusions": "#74469e", "Other exclusion": "#666e7a",
}


def plot_coverage(view: ExitView):
    """What was exported, what can be compared, and why dates were excluded."""
    fig, ax = plt.subplots(figsize=(12, 3.3), layout="constrained")
    for category, color in COVERAGE_COLORS.items():
        subset = view.coverage[view.coverage["category"] == category]
        if not subset.empty:
            ax.scatter(pd.to_datetime(subset["date"]), np.zeros(len(subset)), s=190,
                       marker="s", color=color, label=f"{category} ({len(subset)})")
    ax.set_ylim(-0.7, 0.7)
    ax.set_yticks([])
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.set_title(f"Which days are comparable?  {len(view.eligible_dates)} / {len(view.coverage)} paired days")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.48), ncol=3, fontsize=8, frameon=False)
    return fig


def plot_daily_differences(view: ExitView):
    """Same-day, same-cost paired differences; a visual audit, not a leaderboard."""
    if view.net_difference.empty:
        raise ValueError("No unambiguous paired days to display")
    vals = view.net_difference[list(view.order)].to_numpy(dtype=float).T
    scale = max(1.0, float(np.abs(vals).max()))
    fig, ax = plt.subplots(figsize=(max(11, len(view.eligible_dates) * 0.55), 5.8), layout="constrained")
    image = ax.imshow(vals, cmap="RdBu", vmin=-scale, vmax=scale, aspect="auto", interpolation="nearest")
    ax.set_yticks(range(len(view.order)), [LABELS[p] for p in view.order], fontsize=9)
    labels = [pd.Timestamp(day).strftime("%b %d") + ("\nno signal" if not trade else "")
              for day, trade in zip(view.eligible_dates, view.net_difference["baseline_trade"])]
    ax.set_xticks(range(len(labels)), labels, rotation=65, ha="right", fontsize=8)
    ax.set_title("Each square: hypothetical net difference vs. CURRENT rule on the SAME day\n"
                 f"{view.case_id} | blue = more, red = less, white = same | no-trade days retained", fontsize=10)
    fig.colorbar(image, ax=ax, shrink=0.75, label="Hypothetical net USD difference; NOT a broker account balance")
    return fig


def plot_cost_scenarios(views: dict[str, ExitView]):
    """Fixed-order totals; different eligible samples are labeled, never pooled."""
    if not views:
        raise ValueError("No study cost cases")
    fig, axes = plt.subplots(1, len(views), figsize=(max(10, 7 * len(views)), 6),
                             sharey=True, layout="constrained", squeeze=False)
    for ax, (name, view) in zip(axes[0], views.items()):
        total = view.net_difference[list(view.order)].sum(axis=0)
        ax.barh(range(len(view.order)), total, color=["#167d78" if x >= 0 else "#a43952" for x in total])
        ax.axvline(0, color="black", linewidth=0.9)
        ax.set_yticks(range(len(view.order)), [LABELS[p] for p in view.order])
        ax.invert_yaxis()
        ax.set_title(f"{name.replace('_', ' ')}\n{len(view.eligible_dates)} paired days (not an independent test)")
        ax.set_xlabel("Sum of paired hypothetical net USD differences vs. current rule")
    fig.suptitle("What changes if we assume extra slippage and per-fill costs?\n"
                 "Original policy order; NOT ranked, validated, or a projected profit", fontsize=11)
    return fig


def plot_one_day(view: ExitView, day: str | None = None):
    """One clean trade day to explain mechanics; this is not an observed fill."""
    trades = [d for d in view.eligible_dates if view.results[d][view.order[0]]["status"] == "trade"]
    if not trades:
        raise ValueError("No eligible trade days for the one-day illustration")
    day = day or trades[0]
    if day not in trades:
        raise ValueError("Choose a clean eligible TRADE date from the private report")
    outcomes = view.results[day]
    gross = [_usd(outcomes[p]["gross_points"]) for p in view.order]
    reasons = [outcomes[p]["exit_reason"] for p in view.order]
    fig, ax = plt.subplots(figsize=(11, 5.8), layout="constrained")
    ax.barh(range(len(view.order)), gross, color=["#167d78" if x >= 0 else "#a43952" for x in gross])
    ax.axvline(0, color="black", linewidth=0.9)
    ax.set_yticks(range(len(view.order)), [f"{LABELS[p]}  •  {reason}" for p, reason in zip(view.order, reasons)], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Hypothetical gross index points per initial unit (BEFORE costs)")
    ax.set_title(f"ONE example: {day} | what each exit model would have done\n"
                 "Partial rows include both closing legs; no claim of executable broker fills")
    return fig


def plot_evidence_gate(view: ExitView):
    """Do not visualize uncertainty intervals when sample-size gate is closed."""
    baseline = view.uncertainty[view.order[0]]
    fig, ax = plt.subplots(figsize=(10, 4.6), layout="constrained")
    if baseline["status"] == "insufficient_history":
        current = [baseline["distinct_weeks"], baseline["baseline_trade_days"]]
        needed = [baseline["minimum_distinct_weeks"], baseline["minimum_baseline_trade_days"]]
        ax.barh([0, 1], [min(1, a / b) for a, b in zip(current, needed)], color=["#d38319", "#a43952"])
        ax.set_yticks([0, 1], ["Independent calendar weeks", "Current-rule trade days"])
        ax.set_xlim(0, 1.1)
        for i, (a, b) in enumerate(zip(current, needed)):
            ax.text(min(1, a / b) + 0.02, i, f"{a} / {b}", va="center")
        ax.invert_yaxis()
        ax.set_xticks([])
        ax.set_title("Evidence gate CLOSED: no bootstrap probabilities or intervals\n"
                     "More data, audit work and future paper sessions are needed")
    elif baseline["status"] == "descriptive_bootstrap_only":
        for i, p in enumerate(view.order):
            lo, mid, hi = view.uncertainty[p]["paired_mean_usd_per_session_p05_p50_p95"]
            ax.plot([lo, hi], [i, i], color="#167d78", linewidth=2)
            ax.scatter([mid], [i], color="#134653", zorder=3)
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_yticks(range(len(view.order)), [LABELS[p] for p in view.order])
        ax.invert_yaxis()
        ax.set_xlabel("Paired net USD / session (bootstrap 5–95% range; not adjusted for selecting 9 rules)")
        ax.set_title("Descriptive week-block bootstrap only — NOT evidence of future profit")
    else:
        raise ValueError("Unknown uncertainty gate status")
    return fig
