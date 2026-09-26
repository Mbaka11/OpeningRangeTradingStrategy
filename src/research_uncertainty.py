"""Paired, calendar-week block resampling for OFFLINE uncertainty, not alpha proof.

Returns no probabilities on samples below the predeclared distinct-week/trade
threshold. No selection, no optimization, no live system access.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
import random
import statistics


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = fraction * (len(ordered) - 1)
    lower = int(index)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[min(lower + 1, len(ordered) - 1)] * weight


def _max_drawdown(pnl: list[float]) -> float:
    equity = peak = worst = 0.0
    for amount in pnl:
        equity += amount
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def paired_week_bootstrap(rows: list[dict], *, iterations: int = 2000, seed: int = 20260926,
                          minimum_weeks: int = 26, minimum_trades: int = 100) -> dict:
    """Each row: day_ny, baseline_usd, candidate_usd, baseline_trade bool.

    Both policies always use the SAME sampled calendar weeks; no-trade days
    remain in each block. Overlapping or absent dates fail instead of yielding
    a pseudo-confidence interval.
    """
    if iterations < 1 or minimum_weeks < 1 or minimum_trades < 1:
        raise ValueError("Invalid bootstrap controls")
    blocks: dict[tuple[int, int], list[dict]] = defaultdict(list)
    seen = set()
    for row in sorted(rows, key=lambda x: x["day_ny"]):
        day = date.fromisoformat(row["day_ny"])
        if day in seen:
            raise ValueError("Duplicate day in paired daily series")
        seen.add(day)
        if not all(isinstance(row[k], (int, float)) and math.isfinite(row[k])
                   for k in ("baseline_usd", "candidate_usd")):
            raise ValueError("Non-finite or non-numeric daily paired P&L")
        iso = day.isocalendar()
        blocks[(iso.year, iso.week)].append(row)
    weeks = len(blocks)
    trades = sum(bool(r["baseline_trade"]) for r in rows)
    if weeks < minimum_weeks or trades < minimum_trades:
        return {"status": "insufficient_history", "eligible_sessions": len(rows),
                "distinct_weeks": weeks, "baseline_trade_days": trades,
                "minimum_distinct_weeks": minimum_weeks,
                "minimum_baseline_trade_days": minimum_trades,
                "note": "No bootstrap probabilities: too few independent blocks/trades."}
    rng = random.Random(seed)
    week_rows = list(blocks.values())
    paired_means, baseline_dd, candidate_dd = [], [], []
    for _ in range(iterations):
        sample = [r for _ in range(weeks) for r in week_rows[rng.randrange(weeks)]]
        base = [float(r["baseline_usd"]) for r in sample]
        other = [float(r["candidate_usd"]) for r in sample]
        paired_means.append(statistics.mean(c - b for b, c in zip(base, other)))
        baseline_dd.append(_max_drawdown(base))
        candidate_dd.append(_max_drawdown(other))
    return {"status": "descriptive_bootstrap_only", "eligible_sessions": len(rows),
            "distinct_weeks": weeks, "baseline_trade_days": trades,
            "iterations": iterations, "seed": seed,
            "paired_mean_usd_per_session_p05_p50_p95": [round(_quantile(paired_means, p), 4) for p in (.05, .5, .95)],
            "prob_candidate_trails_baseline_in_resample": round(sum(x < 0 for x in paired_means) / iterations, 4),
            "baseline_max_drawdown_usd_p05_p50_p95": [round(_quantile(baseline_dd, p), 2) for p in (.05, .5, .95)],
            "candidate_max_drawdown_usd_p05_p50_p95": [round(_quantile(candidate_dd, p), 2) for p in (.05, .5, .95)],
            "note": "Not multiple-testing corrected, not a prediction or evidence of a tradable edge."}
