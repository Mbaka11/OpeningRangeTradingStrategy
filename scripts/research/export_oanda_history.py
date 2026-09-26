"""Bounded, read-only OANDA PRACTICE historical M1/MBA quote importer.

Dry-run by default: no credentials, HTTP, orders or X posts. --fetch explicitly
permits at most ten historical weekday GETs; no automatic retries or bulk mode.
This is NAS100_USD practice-feed history, NOT the missing NSXUSD vendor CSVs.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.export_oanda_research import (
    OUTPUT_ROOT, PRACTICE, ResearchDownloadError, _private_json, _safe_output,
    _session_bounds, credentials,
)
from src.research_history import HistoryAuditError, audit_range

HISTORY_ROOT = OUTPUT_ROOT / "history"
MIN_DAY, MAX_DAY = date(2020, 1, 1), date(2024, 12, 31)
MAX_SPAN_DAYS, MAX_REQUESTS = 14, 10


def request_days(start: date, end: date, budget: int) -> list[date]:
    if not MIN_DAY <= start <= end <= MAX_DAY:
        raise ResearchDownloadError("Historical fetch supports only completed 2020-2024 NY dates")
    if (end - start).days + 1 > MAX_SPAN_DAYS or not 1 <= budget <= MAX_REQUESTS:
        raise ResearchDownloadError("At most 14 calendar days and 10 GET requests per run")
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5]
    if not days or len(days) > budget:
        raise ResearchDownloadError("No weekdays or weekday GET count exceeds --max-requests; no HTTP attempted")
    return days


class HistoryReader:
    """Only one GET to a fixed practice-candles path per requested weekday."""

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + token, "Accept": "application/json"})

    def candles(self, day: date) -> list[dict]:
        start, end = _session_bounds(day)  # 09:00–12:10 NY, DST-aware; ~190 M1 bars
        try:
            response = self.session.get(
                f"{PRACTICE}/instruments/NAS100_USD/candles",
                params={"granularity": "M1", "price": "MBA", "smooth": "false", "from": start, "to": end},
                timeout=20, allow_redirects=False,
            )
        except requests.RequestException:
            raise ResearchDownloadError("Historical practice candle GET failed; no private output written") from None
        if response.status_code != 200:
            raise ResearchDownloadError(f"Historical practice candle GET returned HTTP {response.status_code}; no private output written")
        try:
            payload = response.json()
        except ValueError:
            raise ResearchDownloadError("Historical practice candle response is not JSON") from None
        if (not isinstance(payload, dict) or payload.get("instrument") != "NAS100_USD"
                or payload.get("granularity") != "M1" or not isinstance(payload.get("candles"), list)):
            raise ResearchDownloadError("Historical candle response instrument/granularity/schema mismatch")
        if len(payload["candles"]) > 5000 or any(not isinstance(c, dict) for c in payload["candles"]):
            raise ResearchDownloadError("Unexpected historical candle count or schema")
        # Do not save account IDs, response headers, token, or other payload fields.
        return [{"time": c.get("time"), "complete": c.get("complete"),
                 "mid": c.get("mid"), "bid": c.get("bid"), "ask": c.get("ask")}
                for c in payload["candles"]]


def fetch(start: date, end: date, budget: int, reader: HistoryReader) -> tuple[Path, dict]:
    days = request_days(start, end, budget)
    folder = HISTORY_ROOT / f"{start.isoformat()}_{end.isoformat()}"
    _safe_output(folder / "candles.json")
    if folder.exists():
        raise ResearchDownloadError("Private history range already exists; refusing overwrite or duplicate GETs")
    data = {}
    for i, day in enumerate(days):
        if i:
            time.sleep(0.55)  # well below OANDA's two NEW connections/second limit
        data[day.isoformat()] = reader.candles(day)
    audit = audit_range(data)  # reject malformed timestamps; flag quote gaps/invalid OHLC before saving
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=HISTORY_ROOT, prefix=".partial-history-") as temp:
        scratch = Path(temp)
        candles_path = scratch / "candles.json"
        _private_json(candles_path, data)
        checksum = hashlib.sha256(candles_path.read_bytes()).hexdigest()
        provenance = {
            "dataset": "OANDA NAS100_USD PRACTICE M1 mid/bid/ask; NOT original NSXUSD historical CSV",
            "source_endpoint": f"{PRACTICE}/instruments/NAS100_USD/candles",
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "ny_date_range": [start.isoformat(), end.isoformat()],
            "request": {"granularity": "M1", "price": "MBA", "smooth": False,
                        "session_window_ny": "09:00-12:10", "authenticated_GETs": len(days),
                        "maximum_attempts_per_day": 1},
            "candles_sha256": checksum,
            "quality": audit,
        }
        _private_json(scratch / "provenance.json", provenance)
        if folder.exists():
            raise ResearchDownloadError("History folder appeared during download; refusing overwrite")
        os.replace(scratch, folder)
    return folder, audit["summary"]


def audit_existing(folder_name: str) -> tuple[Path, dict]:
    if not re.fullmatch(r"20(?:2[0-4])-\d{2}-\d{2}_20(?:2[0-4])-\d{2}-\d{2}", folder_name):
        raise ResearchDownloadError("Expected a historical YYYY-MM-DD_YYYY-MM-DD folder name")
    folder = HISTORY_ROOT / folder_name
    _safe_output(folder / "candles.json")
    try:
        raw = (folder / "candles.json").read_bytes()
        provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
        candles = json.loads(raw)
    except (OSError, ValueError):
        raise ResearchDownloadError("Private history/provenance missing or invalid") from None
    if (hashlib.sha256(raw).hexdigest() != provenance.get("candles_sha256")
            or provenance.get("ny_date_range") != folder_name.split("_")):
        raise ResearchDownloadError("Private history checksum/date mismatch; do not trust this batch")
    audit = audit_range(candles)
    if audit != provenance.get("quality"):
        raise ResearchDownloadError("Private history quality audit mismatch")
    return folder, audit["summary"]


def main() -> int:
    parser = argparse.ArgumentParser(description="OFFLINE default; explicitly --fetch for <=10 practice-only historical candle GETs")
    parser.add_argument("--start", type=date.fromisoformat, help="NY date in 2020-2024")
    parser.add_argument("--end", type=date.fromisoformat, help="NY date, <=14 calendar days after start")
    parser.add_argument("--max-requests", type=int, default=5, help="Hard GET budget, default 5, max 10; NO automatic retries")
    parser.add_argument("--fetch", action="store_true", help="Explicitly allow bounded practice-only GET requests")
    parser.add_argument("--audit", help="Check an existing ignored history batch OFFLINE; no token/network")
    args = parser.parse_args()
    if args.audit and (args.start or args.end or args.fetch) or not args.audit and not (args.start and args.end):
        parser.error("Specify --audit OR --start and --end (add --fetch only for explicit read-only GETs)")
    try:
        if args.audit:
            folder, summary = audit_existing(args.audit)
            print("Private offline historical quote audit:", folder.relative_to(ROOT), summary)
            return 0
        days = request_days(args.start, args.end, args.max_requests)
        folder = HISTORY_ROOT / f"{args.start.isoformat()}_{args.end.isoformat()}"
        _safe_output(folder / "candles.json")
        if folder.exists():
            raise ResearchDownloadError("Private history range already exists; no overwrite")
        if not args.fetch:
            print("DRY RUN: no credentials used, zero HTTP;", len(days), "weekday GETs required, budget", args.max_requests)
            print("Use --fetch only for a consciously bounded practice-history read; no original NSXUSD CSVs created.")
            return 0
        _, token, instrument = credentials()  # OANDA_ENV must explicitly be practice
        if instrument != "NAS100_USD":
            raise ResearchDownloadError("Practice instrument must be NAS100_USD; refusing other symbols")
        folder, summary = fetch(args.start, args.end, args.max_requests, HistoryReader(token))
        print("Private PRACTICE history:", folder.relative_to(ROOT))
        print("Quote-quality counts (NOT backtest/trading performance):", summary)
        print("Original NSXUSD CSVs are still missing; do not use this sample to select an exit rule.")
        return 0
    except (ResearchDownloadError, HistoryAuditError) as error:
        print(f"Historical import refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
