"""Offline research baseline audit from the ignored OANDA practice export.

Usage: python scripts/audit_backtest_parity.py --folder 2026-08-20_2026-09-24
Never sends network requests or posts. This is NOT a strategy optimization.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_oanda_research import OUTPUT_ROOT, ResearchDownloadError, _private_json, _safe_output
from src.research_backtest import StrategyParams, run_session
from src.research_parity import NY, broker_reason, extract_trades, parse_time


def audit(candles_by_day: dict[str, list[dict]], fills: list[dict], params: StrategyParams) -> dict:
    """Signal-parity, research-only simulated outcomes and broker gross P&L checks."""
    trades_by_day: dict[str, list[dict]] = defaultdict(list)
    for trade in extract_trades(fills):
        day = parse_time(trade["entry_time"]).astimezone(NY).date().isoformat()
        trades_by_day[day].append(trade)
    sessions = []
    broker_checks = []
    for day, candles in sorted(candles_by_day.items()):
        simulation = run_session(day, candles, params)
        actual = trades_by_day.get(day, [])
        row = {"day_ny": day, "simulation": simulation, "observed_trade_count": len(actual),
               "signal_comparison": "unresolved"}
        sessions.append(row)
        if len(actual) > 1:
            row["signal_comparison"] = "multiple_broker_trades"
        elif simulation["status"] == "excluded":
            row["signal_comparison"] = "incomplete_market_path"
        elif not actual:
            row["signal_comparison"] = "match" if simulation["status"] == "no_trade" else "mismatch"
        else:
            trade = actual[0]
            observed_side = "long" if float(trade["units"]) > 0 else "short"
            row["observed_side"] = observed_side
            row["signal_comparison"] = "match" if simulation.get("side") == observed_side else "mismatch"
        for trade in actual:
            check = {"day_ny": day, "status": "unresolved"}
            broker_checks.append(check)
            if not trade.get("entry_price") or not trade.get("units") or len(trade["closes"]) != 1:
                check["detail"] = "missing_or_partial_entry_close"
                continue
            close = trade["closes"][0]
            if (not close.get("price") or not close.get("units") or close.get("realized_pl") is None
                    or abs(float(close["units"])) != abs(float(trade["units"]))):
                check["detail"] = "missing_or_partial_close"
                continue
            units = abs(float(trade["units"]))
            direction = 1 if float(trade["units"]) > 0 else -1
            price_points = direction * (float(close["price"]) - float(trade["entry_price"]))
            implied_pl = units * price_points
            broker_pl = float(close["realized_pl"])
            check.update({"status": "match" if abs(implied_pl - broker_pl) <= 0.01 else "mismatch",
                          "units": units, "broker_price_points": round(price_points, 5),
                          "price_implied_usd": round(implied_pl, 4),
                          "broker_realized_pl_usd": round(broker_pl, 4),
                          "usd_delta": round(broker_pl - implied_pl, 4),
                          "broker_reason": broker_reason(close["reason"], parse_time(close["time"]))})
            if len(actual) == 1 and simulation["status"] == "trade":
                check["simulated_exit_reason"] = simulation["exit_reason"]
                check["exit_reason_comparison"] = (
                    "inconclusive_same_bar" if simulation["ambiguous_same_bar"]
                    else "candidate_noon_match" if simulation["exit_reason"] == "time" and check["broker_reason"] == "time_candidate"
                    else "same_reason" if simulation["exit_reason"] == check["broker_reason"]
                    else "different_reason"
                )
    summary = {"sessions": len(sessions),
               "signal_comparison": dict(Counter(s["signal_comparison"] for s in sessions)),
               "simulated_trades": sum(s["simulation"]["status"] == "trade" for s in sessions),
               "simulated_ambiguous": sum(s["simulation"].get("ambiguous_same_bar", False) for s in sessions),
               "broker_trades_on_exported_days": len(broker_checks),
               "broker_pl_check": dict(Counter(b["status"] for b in broker_checks)),
               "exit_reason_comparison": dict(Counter(b.get("exit_reason_comparison", "not_comparable")
                                                   for b in broker_checks))}
    return {"params": vars(params), "summary": summary, "sessions": sessions,
            "broker_checks": broker_checks,
            "caveat": "Next-M1-open bid/ask research fills are hypothetical; do not confuse with actual broker fills."}


def compare_cloud_balances(entries: list[dict], report: dict) -> list[dict]:
    """Match SESSION_END account balance change to broker realized trade P&L.

    Excludes NAV/UTPL, account deposits, and instruments outside this export;
    differences are flagged, not silently assigned to the bot's trades.
    """
    if not isinstance(entries, list):
        raise ResearchDownloadError("Expected a JSON list of Cloud Logging entries")
    broker_by_day = defaultdict(float)
    invalid_days = set()
    for check in report["broker_checks"]:
        if check["status"] != "match":
            invalid_days.add(check["day_ny"])
        else:
            broker_by_day[check["day_ny"]] += check["broker_realized_pl_usd"]
    session_days = {s["day_ny"] for s in report["sessions"]}
    matched: dict[str, dict] = {}
    for entry in entries:
        msg = entry.get("textPayload", "") if isinstance(entry, dict) else ""
        m = re.search(r"SESSION_END date=(\d{4}-\d{2}-\d{2}).*?bal ([\d.]+)->([\d.]+) \(([+-][\d.]+)\)", msg)
        if not m or m.group(1) not in session_days:
            continue
        day, initial, final, logged = m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4))
        if abs((final - initial) - logged) > 0.01:
            raise ResearchDownloadError("Cloud balance line does not reconcile internally")
        if day in matched and abs(matched[day]["account_change_usd"] - logged) > 0.01:
            raise ResearchDownloadError("Conflicting SESSION_END entries for a single NY day")
        delta = logged - broker_by_day[day]
        matched[day] = {"day_ny": day, "status": ("unresolved" if day in invalid_days else
                      "match" if abs(delta) <= 0.01 else "mismatch"),
                      "account_change_usd": round(logged, 4),
                      "broker_realized_pl_usd": round(broker_by_day[day], 4),
                      "usd_delta": round(delta, 4)}
    if not matched:
        raise ResearchDownloadError("No matching SESSION_END entries in private log export")
    return [matched[day] for day in sorted(matched)]


def _read_private(folder_name: str) -> tuple[Path, dict, list]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}", folder_name):
        raise ResearchDownloadError("Expected a generated START_END folder name")
    folder = OUTPUT_ROOT / folder_name
    _safe_output(folder / "baseline.json")
    try:
        candles = json.loads((folder / "candles.json").read_text(encoding="utf-8"))
        fills = json.loads((folder / "fills.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ResearchDownloadError("Missing or invalid private export") from None
    if not isinstance(candles, dict) or not isinstance(fills, list):
        raise ResearchDownloadError("Unexpected private export format")
    return folder, candles, fills


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline explicit-parameter baseline and broker P&L audit")
    parser.add_argument("--folder", required=True, help="Previously exported START_END folder under data/raw/oanda_research")
    parser.add_argument("--session-logs", action="store_true", help="Also compare private session_end_logs.json from Cloud Logging")
    args = parser.parse_args()
    try:
        folder, candles, fills = _read_private(args.folder)
        report = audit(candles, fills, StrategyParams())
        if args.session_logs:
            _safe_output(folder / "session_end_logs.json")
            try:
                entries = json.loads((folder / "session_end_logs.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ResearchDownloadError("Missing or invalid private session_end_logs.json") from None
            report["account_balance_checks"] = compare_cloud_balances(entries, report)
            report["summary"]["account_balance_check"] = dict(Counter(r["status"] for r in report["account_balance_checks"]))
        _private_json(folder / "baseline.json", report)
    except ResearchDownloadError as error:
        parser.exit(1, f"Offline audit refused: {error}\n")
    print("Private baseline report:", (folder / "baseline.json").relative_to(OUTPUT_ROOT.parent.parent.parent))
    print("Summary (classification, not strategy improvement):", json.dumps(report["summary"], sort_keys=True))
    print("Historical 2020-2024 CSVs are absent; this sample cannot validate the old backtest ranking.")


if __name__ == "__main__":
    main()
