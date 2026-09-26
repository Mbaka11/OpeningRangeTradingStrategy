"""OFFLINE five-year OANDA PRACTICE quote-coverage + 25/75 baseline smoke.

This reproduces a NEW NAS100_USD/MBA simulator run, NOT the missing NSXUSD
vendor CSV backtest, not broker fill parity, and not a strategy winner. It
never makes network, OANDA order, Cloud Run or X posting calls. Output PRIVATE.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research import export_oanda_history as history
from scripts.research.backfill_oanda_history import audited_batches, build_index
from scripts.research.export_oanda_research import ResearchDownloadError, _private_json, _safe_output
from src.research_backtest import StrategyParams, run_session

OUTPUT = history.HISTORY_ROOT / "historical_baseline.json"


def build_baseline(candles_by_day: dict, quality_by_day: dict, params: StrategyParams) -> dict:
    """Missing/incomplete quote sessions are EXCLUDED, never fabricated flats."""
    if set(candles_by_day) != set(quality_by_day) or not candles_by_day:
        raise ResearchDownloadError("Historical quality and candle dates differ")
    results = {}
    for day in sorted(quality_by_day):
        quality = quality_by_day[day]
        if quality not in ("complete", "incomplete", "no_session_data"):
            raise ResearchDownloadError("Unknown historical quote-quality status")
        results[day] = (run_session(day, candles_by_day[day], params) if quality == "complete" else
                        {"day_ny": day, "status": "excluded", "reason": "quote_" + quality})
    years = {}
    for year in range(2020, 2025):
        rows = [r for day, r in results.items() if day.startswith(str(year))]
        status = Counter(r["status"] for r in rows)
        years[str(year)] = {"quote_days": len(rows), "trade": status["trade"], "no_trade": status["no_trade"],
                            "excluded": status["excluded"],
                            "ambiguous_trades": sum(r.get("ambiguous_same_bar", False) for r in rows),
                            "stop_gap_trades": sum(r.get("gap_through_stop", False) for r in rows)}
    return {"source": "historical OANDA PRACTICE NAS100_USD M1 MBA; NOT original NSXUSD vendor CSV",
            "method": "next-minute executable bid/ask open; fixed -25/+75; zero extra costs; hypothetical ONLY",
            "parameters": asdict(params), "by_year": years, "daily_hypothetical": results,
            "caveat": "Historical broker fills unavailable; old NSXUSD notebook baseline not reproduced; no policy selected."}


def run_from_private_history() -> dict:
    covered = audited_batches()  # rechecks every stored SHA-256 and provenance before any arithmetic
    index = build_index(covered)
    if any(row["not_downloaded"] for row in index["years"].values()):
        raise ResearchDownloadError("Historical weekday backfill incomplete; baseline audit refused")
    if not covered:
        raise ResearchDownloadError("No private historical quotes found")
    candles, quality = {}, {}
    for folder_name in index["batches"]:
        folder, _ = history.audit_existing(folder_name)
        try:
            batch = json.loads((folder / "candles.json").read_text(encoding="utf-8"))
            report = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ResearchDownloadError("Historical private batch missing or invalid") from None
        for day, bars in batch.items():
            if day in candles:
                raise ResearchDownloadError("Overlapping historical quote day; no result written")
            candles[day] = bars
            quality[day] = report["quality"]["sessions"][day]["status"]
    report = build_baseline(candles, quality, StrategyParams())
    if sum(r["quote_days"] for r in report["by_year"].values()) != len(covered):
        raise ResearchDownloadError("Historical baseline did not cover every requested weekday")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline hypothetical -25/+75 baseline over saved private practice quotes")
    parser.add_argument("--replace-private", action="store_true", help="Explicitly replace prior ignored baseline only")
    args = parser.parse_args()
    try:
        _safe_output(OUTPUT)
        if OUTPUT.exists() and not args.replace_private:
            raise ResearchDownloadError("Existing private baseline; use --replace-private only after review")
        report = run_from_private_history()
        _private_json(OUTPUT, report)
    except ResearchDownloadError as error:
        print(f"Offline history baseline refused: {error}", file=sys.stderr)
        return 1
    print("Private OFFLINE hypothetical baseline:", OUTPUT.relative_to(ROOT))
    for year, values in report["by_year"].items():
        print(year, "quote days", values["quote_days"], "trade", values["trade"],
              "no_trade", values["no_trade"], "excluded", values["excluded"],
              "ambiguous trades", values["ambiguous_trades"])
    print("NO original NSXUSD CSV reproduction, verified historical fills, cost estimate, or strategy selection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
