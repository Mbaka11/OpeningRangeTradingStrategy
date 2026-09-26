"""Resumable OANDA PRACTICE 2020–2024 M1 quote backfill, research only.

Dry-run by default. Explicit --fetch --year YYYY --max-requests N makes at
most N GETs in that invocation, each via atomic <=5-day private batches.
Existing checksum-verified days are never refetched. No orders, Cloud or X.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research import export_oanda_history as history
from scripts.research.export_oanda_research import ResearchDownloadError, _private_json, _safe_output, credentials

FOLDER_PATTERN = re.compile(r"20(?:2[0-4])-\d{2}-\d{2}_20(?:2[0-4])-\d{2}-\d{2}\Z")
MAX_YEAR_REQUESTS = 262


def weekdays(year: int) -> list[date]:
    if year not in range(2020, 2025):
        raise ResearchDownloadError("Only historical NY years 2020-2024 are authorized")
    first, last = date(year, 1, 1), date(year, 12, 31)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)
            if (first + timedelta(days=i)).weekday() < 5]


def audited_batches() -> dict[date, tuple[str, str]]:
    """Audit every existing batch hash and provenance BEFORE making any HTTP."""
    covered: dict[date, tuple[str, str]] = {}
    root = history.HISTORY_ROOT
    if not root.exists():
        return covered
    for folder in sorted(root.iterdir()):
        if folder.name.startswith(".partial-history-"):
            raise ResearchDownloadError("Stale incomplete history directory; manual review required")
        if not folder.is_dir():
            continue
        if folder.is_symlink() or not FOLDER_PATTERN.fullmatch(folder.name):
            raise ResearchDownloadError("Unknown history directory or symlink; refusing silent omission")
        history.audit_existing(folder.name)  # checks SHA-256 and stored quality, no network
        try:
            provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
            if (provenance.get("source_endpoint") !=
                    "https://api-fxpractice.oanda.com/v3/instruments/NAS100_USD/candles"
                    or provenance["request"]["price"] != "MBA"
                    or provenance["request"]["granularity"] != "M1"
                    or provenance["request"]["smooth"] is not False
                    or provenance["request"]["session_window_ny"] != "09:00-12:10"
                    or provenance["request"]["maximum_attempts_per_day"] != 1):
                raise ResearchDownloadError("Historical batch source/settings differ; do not merge feeds")
            sessions = provenance["quality"]["sessions"]
            start, end = (date.fromisoformat(s) for s in provenance["ny_date_range"])
            if (len(sessions) != provenance["request"]["authenticated_GETs"]
                    or list(sessions) != [d.isoformat() for d in history.request_days(start, end, len(sessions))]):
                raise ResearchDownloadError("Historical batch dates differ from bounded request")
            for day_str, quality in sessions.items():
                day = date.fromisoformat(day_str)
                if day.year not in range(2020, 2025) or day in covered:
                    raise ResearchDownloadError("Historical weekday duplicated or outside authorized years")
                covered[day] = (folder.name, quality["status"])
        except (KeyError, ValueError, TypeError):
            raise ResearchDownloadError("Historical batch provenance is invalid") from None
    return covered


def batches_for_days(selected: list[date]) -> list[list[date]]:
    """At most five *consecutive weekdays* per batch; do not bridge saved days."""
    groups: list[list[date]] = []
    for day in selected:
        if groups and len(groups[-1]) < 5 and day == next_weekday(groups[-1][-1]):
            groups[-1].append(day)
        else:
            groups.append([day])
    for group in groups:
        if history.request_days(group[0], group[-1], len(group)) != group:
            raise ResearchDownloadError("Historical batch would refetch an existing weekday")
    return groups


def next_weekday(day: date) -> date:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def build_index(covered: dict[date, tuple[str, str]]) -> dict:
    yearly = {}
    for year in range(2020, 2025):
        expected = set(weekdays(year))
        observed = {day for day in expected if day in covered}
        yearly[str(year)] = {"weekdays_expected_including_holidays": len(expected),
                             "weekdays_downloaded": len(observed),
                             "not_downloaded": len(expected - observed),
                             "complete": sum(covered[d][1] == "complete" for d in observed),
                             "incomplete": sum(covered[d][1] == "incomplete" for d in observed),
                             "no_session_data": sum(covered[d][1] == "no_session_data" for d in observed)}
    return {"dataset": "OANDA NAS100_USD PRACTICE MBA M1, not original NSXUSD CSV",
            "updated_utc": datetime.now(timezone.utc).isoformat(), "years": yearly,
            "batches": sorted({folder for folder, _ in covered.values()}),
            "warning": "Quote coverage only; holidays/no-session and ambiguous fills are not no-trade days or validated alpha."}


def save_index(covered: dict[date, tuple[str, str]]) -> dict:
    target = history.HISTORY_ROOT / "index.json"
    _safe_output(target)
    index = build_index(covered)
    _private_json(target, index)
    return index


def backfill(year: int, budget: int, reader) -> tuple[int, dict]:
    """Explicitly bounded collection; safe to resume after a stopped prior run."""
    if not 1 <= budget <= MAX_YEAR_REQUESTS:
        raise ResearchDownloadError("Annual GET budget must be 1..262")
    covered = audited_batches()
    pending = [day for day in weekdays(year) if day not in covered]
    groups = batches_for_days(pending[:budget])
    attempted = 0
    try:
        for group in groups:
            if attempted:
                time.sleep(0.55)  # also throttle connections between atomic batches
            folder, counts = history.fetch(group[0], group[-1], len(group), reader)
            for day in group:
                # Every weekday is explicitly present, even when there were no quotes.
                covered[day] = (folder.name, "pending_audit")
            attempted += len(group)
            print(f"Saved {folder.name}: {len(group)} practice GETs, "
                  f"complete={counts['complete']}, incomplete={counts['incomplete']}, "
                  f"no_session_data={counts['no_session_data']}; year GETs={attempted}/{budget}", flush=True)
    finally:
        # Re-audit all persisted batches even on interruption/failure; no false
        # 'pending_audit' entries are allowed into the final private index.
        index = save_index(audited_batches())
    return attempted, index


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run by default; resumable practice-only annual M1 quote backfill")
    parser.add_argument("--year", type=int, required=True, choices=range(2020, 2025))
    parser.add_argument("--max-requests", type=int, default=5, help="Hard GET count this run (1..262), default 5")
    parser.add_argument("--fetch", action="store_true", help="Explicit permission for read-only practice GETs")
    args = parser.parse_args()
    try:
        if not 1 <= args.max_requests <= MAX_YEAR_REQUESTS:
            raise ResearchDownloadError("Hard GET budget must be 1..262")
        covered = audited_batches()
        pending = [day for day in weekdays(args.year) if day not in covered]
        will_fetch = min(len(pending), args.max_requests)
        if not args.fetch:
            print(f"DRY RUN: {args.year} has {len(pending)} weekdays not downloaded; "
                  f"this invocation would perform at most {will_fetch} practice GETs; ZERO HTTP now")
            print("Missing original NSXUSD CSVs remain a separate historical provenance blocker.")
            return 0
        if not pending:
            print(f"{args.year}: all weekdays already checksum-audited; zero GETs")
            return 0
        _, token, instrument = credentials()
        if instrument != "NAS100_USD":
            raise ResearchDownloadError("Practice instrument must be NAS100_USD; no HTTP attempted")
        reader = history.HistoryReader(token)
        attempted, index = backfill(args.year, args.max_requests, reader)
        info = index["years"][str(args.year)]
        print(f"{args.year} saved GETs this run={attempted}; covered={info['weekdays_downloaded']}/"
              f"{info['weekdays_expected_including_holidays']}, incomplete={info['incomplete']}, "
              f"no_session_data={info['no_session_data']}; index is private, not a strategy result")
        return 0
    except ResearchDownloadError as error:
        print(f"Historical backfill stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
