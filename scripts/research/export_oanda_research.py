"""Bounded READ-ONLY OANDA practice export and baseline parity audit.

Usage: python scripts/research/export_oanda_research.py --start 2026-09-23 --end 2026-09-24
No order APIs, X APIs or Cloud Run executions are called. Private outputs are
stored under ignored data/raw/oanda_research/. Never post these files online.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time as clock
from urllib.parse import urlparse

import requests
from dotenv import dotenv_values
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.research_parity import extract_trades, parse_time, reconcile

NY = ZoneInfo("America/New_York")
PRACTICE = "https://api-fxpractice.oanda.com/v3"
OUTPUT_ROOT = ROOT / "data" / "raw" / "oanda_research"
MAX_DAYS = 62
MAX_PAGES = 100


class ResearchDownloadError(Exception):
    """An error with no token, account ID, or raw HTTP response text."""


def credentials() -> tuple[str, str, str]:
    path = Path(os.getenv("DOTENV_PATH") or ROOT / ".env")
    values = dotenv_values(path) if path.is_file() else {}
    def value(name: str) -> str:
        return os.environ.get(name) or values.get(name) or ""
    if value("OANDA_ENV") != "practice":
        raise ResearchDownloadError("OANDA_ENV must explicitly equal practice; refusing export")
    account, token, instrument = value("OANDA_ACCOUNT_ID"), value("OANDA_API_TOKEN"), value("OANDA_INSTRUMENT")
    if not account or not re.fullmatch(r"[A-Za-z0-9-]+", account) or not token:
        raise ResearchDownloadError("Missing or invalid local practice account credentials")
    if not re.fullmatch(r"[A-Z0-9_]+", instrument or ""):
        raise ResearchDownloadError("Missing or invalid instrument")
    return account, token, instrument


def validate_dates(start: date, end: date, today: date) -> None:
    if end < start or start > today or end >= today:
        raise ResearchDownloadError("Use completed NY dates with start <= end < today")
    if (end - start).days + 1 > MAX_DAYS:
        raise ResearchDownloadError(f"Maximum export range is {MAX_DAYS} calendar days")


def _datetime_bounds(start: date, end: date) -> tuple[str, str]:
    from_dt = datetime.combine(start, time.min, tzinfo=NY).astimezone(timezone.utc)
    to_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=NY).astimezone(timezone.utc) - timedelta(microseconds=1)
    return from_dt.isoformat(), to_dt.isoformat()


def _session_bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, time(9, 0), tzinfo=NY).astimezone(timezone.utc)
    end = datetime.combine(day, time(12, 10), tzinfo=NY).astimezone(timezone.utc)
    return start.isoformat(), end.isoformat()


def _safe_page(page: str, account: str) -> str:
    parsed = urlparse(page)
    prefix = f"/v3/accounts/{account}/transactions/idrange"
    if parsed.scheme != "https" or parsed.netloc != "api-fxpractice.oanda.com" or parsed.path != prefix or not parsed.query or parsed.fragment:
        raise ResearchDownloadError("Unexpected OANDA transaction page URL; refusing authenticated request")
    return page


class PracticeReader:
    """Only GET requests to the fixed OANDA practice host, no redirect following."""

    def __init__(self, account: str, token: str, instrument: str):
        self.account = account
        self.instrument = instrument
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + token, "Accept": "application/json"})

    def get(self, url: str, params: dict | None = None) -> dict:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api-fxpractice.oanda.com" or not parsed.path.startswith("/v3/") or parsed.fragment:
            raise ResearchDownloadError("Refusing request to unexpected host or path")
        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=20, allow_redirects=False)
            except requests.RequestException:
                if attempt == 2:
                    raise ResearchDownloadError("OANDA read timed out or network failed (no output written)") from None
                clock.sleep(2 ** attempt)
                continue
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    raise ResearchDownloadError("OANDA returned invalid JSON") from None
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise ResearchDownloadError(f"OANDA read returned HTTP {response.status_code} (no credentials displayed)")
            clock.sleep(2 ** attempt)
        raise AssertionError("unreachable")

    def fills(self, start: date, end: date) -> list[dict]:
        from_dt, to_dt = _datetime_bounds(start, end)
        url = f"{PRACTICE}/accounts/{self.account}/transactions"
        index = self.get(url, {"from": from_dt, "to": to_dt, "pageSize": 1000})
        pages = index.get("pages")
        if not isinstance(pages, list) or len(pages) > MAX_PAGES:
            raise ResearchDownloadError("Missing or excessive OANDA transaction pages; export aborted")
        seen: set[str] = set()
        fills: dict[str, dict] = {}
        for page in pages:
            if not isinstance(page, str):
                raise ResearchDownloadError("Invalid OANDA page URL")
            url = _safe_page(page, self.account)
            if url in seen:
                raise ResearchDownloadError("Duplicate transaction page; export aborted")
            seen.add(url)
            payload = self.get(url)
            if not isinstance(payload.get("transactions"), list):
                raise ResearchDownloadError("Missing transaction list in OANDA page")
            for tx in payload["transactions"]:
                if tx.get("type") != "ORDER_FILL" or tx.get("instrument") != self.instrument:
                    continue
                # Date-index pages can include adjacent transactions; enforce exact NY interval.
                ts = parse_time(tx["time"]).astimezone(NY).date()
                if start <= ts <= end:
                    fills[str(tx["id"])] = sanitize_fill(tx)
        return sorted(fills.values(), key=lambda x: (x["time"], int(x["id"])))

    def candles(self, day: date) -> list[dict]:
        from_dt, to_dt = _session_bounds(day)
        payload = self.get(
            f"{PRACTICE}/instruments/{self.instrument}/candles",
            {"granularity": "M1", "price": "MBA", "smooth": "false", "from": from_dt, "to": to_dt},
        )
        if not isinstance(payload.get("candles"), list):
            raise ResearchDownloadError("Missing OANDA candle list")
        records = []
        for c in payload["candles"]:
            records.append({"time": c["time"], "complete": c.get("complete", False),
                            "mid": c.get("mid"), "bid": c.get("bid"), "ask": c.get("ask")})
        return records


def sanitize_fill(tx: dict) -> dict:
    """Only fields needed for parity; exclude account identity, tokens, raw response."""
    reduce_fields = ("tradeID", "units", "price", "realizedPL")
    def subset(obj, keys):
        return {k: obj[k] for k in keys if k in obj}
    clean = subset(tx, ("id", "time", "instrument", "reason"))
    if tx.get("tradeOpened"):
        clean["tradeOpened"] = subset(tx["tradeOpened"], ("tradeID", "units", "price"))
    if tx.get("tradesClosed"):
        clean["tradesClosed"] = [subset(t, reduce_fields) for t in tx["tradesClosed"]]
    if tx.get("tradeReduced"):
        clean["tradeReduced"] = subset(tx["tradeReduced"], reduce_fields)
    return clean


def _private_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".partial-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_output(path: Path) -> None:
    """Never write private broker records where git could stage them."""
    target = path.resolve()
    if not target.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ResearchDownloadError("Unsafe local output location")
    try:
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(target)], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    except OSError:
        raise ResearchDownloadError("Cannot verify private Git ignore rules") from None
    if ignored.returncode != 0:
        raise ResearchDownloadError("Private output is not Git-ignored; refusing to save")


def tally(candles_by_day: dict, fills: list[dict], trades: list[dict], rows: list[dict]) -> dict:
    return {"days": len(candles_by_day), "candles": sum(map(len, candles_by_day.values())),
            "fills": len(fills), "trades": len(trades),
            **{status: sum(r["status"] == status for r in rows)
               for status in ("match", "candidate_match", "mismatch", "unresolved")}}


def export(start: date, end: date, reader: PracticeReader) -> tuple[Path, dict]:
    validate_dates(start, end, datetime.now(NY).date())
    folder = OUTPUT_ROOT / f"{start.isoformat()}_{end.isoformat()}"
    if folder.exists():
        raise ResearchDownloadError("Private export folder already exists; refusing to overwrite")
    fills = reader.fills(start, end)
    candles_by_day = {}
    for n in range((end - start).days + 1):
        day = start + timedelta(days=n)
        if day.weekday() < 5:  # weekday does not imply trading holiday; empty candle arrays recorded
            candles_by_day[day.isoformat()] = reader.candles(day)
    trades = extract_trades(fills)
    rows = reconcile(trades, candles_by_day, reader.instrument)
    # No files are written until all authenticated GET requests succeed.
    _safe_output(folder / "fills.json")
    _private_json(folder / "fills.json", fills)
    _private_json(folder / "candles.json", candles_by_day)
    _private_json(folder / "parity.json", rows)
    return folder, tally(candles_by_day, fills, trades, rows)


def recheck(folder_name: str) -> tuple[Path, dict]:
    """Recompute the parity report offline from an existing private export."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}", folder_name):
        raise ResearchDownloadError("Use a generated YYYY-MM-DD_YYYY-MM-DD folder name")
    folder = OUTPUT_ROOT / folder_name
    _safe_output(folder / "parity.json")
    try:
        fills = json.loads((folder / "fills.json").read_text(encoding="utf-8"))
        candles = json.loads((folder / "candles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ResearchDownloadError("Private export is missing or invalid") from None
    instruments = {tx["instrument"] for tx in fills}
    if len(instruments) > 1:
        raise ResearchDownloadError("Export contains mixed instruments")
    trades = extract_trades(fills)
    rows = reconcile(trades, candles, next(iter(instruments), ""))
    _private_json(folder / "parity.json", rows)
    return folder, tally(candles, fills, trades, rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only, practice-only OANDA broker fill and candle audit")
    parser.add_argument("--start", type=date.fromisoformat, help="First completed NY date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="Last completed NY date (YYYY-MM-DD)")
    parser.add_argument("--recheck", help="Existing export folder name: recompute parity offline, no HTTP or token")
    args = parser.parse_args()
    if args.recheck and (args.start or args.end) or not args.recheck and not (args.start and args.end):
        parser.error("Provide --start AND --end, or --recheck (not both)")
    try:
        if args.recheck:
            folder, counts = recheck(args.recheck)
        else:
            validate_dates(args.start, args.end, datetime.now(NY).date())
            account, token, instrument = credentials()
            folder, counts = export(args.start, args.end, PracticeReader(account, token, instrument))
    except ResearchDownloadError as error:
        print(f"Export refused: {error}", file=sys.stderr)
        return 1
    print(f"Private research export: {folder.relative_to(ROOT)}")
    print("Audit counts (not profitability): " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print("Unresolved/mismatched cases require manual broker and quote-path review; do not change live rules from this report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
