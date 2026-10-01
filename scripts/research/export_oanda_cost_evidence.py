"""Budgeted GET-only current/recent PRACTICE cost evidence; dry-run by default.

Requires a saved, previously inspected fill export. At most eight requests, no
retries/redirects/candles/orders/Cloud/X. Exact old fill identity must match.
Current metadata is NOT historical 2020-2024 instrument or fee validation.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.export_oanda_research import (
    OUTPUT_ROOT, PRACTICE, ResearchDownloadError, _datetime_bounds, _private_json,
    _safe_output, credentials, sanitize_fill, validate_dates,
)
from src.research_costs import CostAuditError, FILL_COMPONENTS, INSTRUMENT, audit_cost_snapshot, number
from src.research_parity import NY, parse_time

MAX_REQUESTS = 8
TYPES = ("ORDER_FILL", "DAILY_FINANCING", "DIVIDEND_ADJUSTMENT")
COST_ROOT = OUTPUT_ROOT / "cost_evidence"
LEG_FIELDS = ("tradeID", "units", "price", "realizedPL", "financing", "guaranteedExecutionFee", "halfSpreadCost")
INSTRUMENT_FIELDS = (
    "name", "type", "displayPrecision", "pipLocation", "tradeUnitsPrecision", "minimumTradeSize",
    "maximumOrderUnits", "maximumPositionSize", "marginRate", "minimumTrailingStopDistance",
    "maximumTrailingStopDistance", "guaranteedStopLossOrderMode", "minimumGuaranteedStopLossDistance",
    "guaranteedStopLossOrderExecutionPremium",
)


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _code_digest() -> str:
    paths = ("src/research_costs.py", "scripts/research/export_oanda_cost_evidence.py",
             "src/research_parity.py", "scripts/research/export_oanda_research.py")
    return _hash("\n".join(f"{p}:{_hash((ROOT / p).read_bytes())}" for p in paths).encode("utf-8"))


def _scalar_subset(obj: dict, fields: tuple[str, ...]) -> dict:
    if not isinstance(obj, dict):
        raise CostAuditError("Malformed selected evidence object")
    clean = {}
    for key in fields:
        if key in obj:
            value = obj[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
                raise CostAuditError("Malformed selected scalar evidence field")
            clean[key] = value
    return clean


def sanitize_instrument(obj: dict) -> dict:
    clean = _scalar_subset(obj, INSTRUMENT_FIELDS)
    if "commission" in obj:
        clean["commission"] = (_scalar_subset(obj["commission"], ("commission", "unitsTraded", "minimumCommission"))
                               if obj["commission"] is not None else None)
    if "financing" in obj and obj["financing"] is not None:
        clean["financing"] = _scalar_subset(obj["financing"], ("longRate", "shortRate"))
        if "financingDaysOfWeek" in obj["financing"]:
            days = obj["financing"]["financingDaysOfWeek"]
            if not isinstance(days, list) or len(days) > 7:
                raise CostAuditError("Malformed current financing schedule")
            clean["financing"]["financingDaysOfWeek"] = [_scalar_subset(d, ("dayOfWeek", "daysCharged")) for d in days]
    return clean


def sanitize_cost_fill(row: dict) -> dict:
    clean = _scalar_subset(row, ("id", "time", "type", "instrument", "reason", *FILL_COMPONENTS))
    if row.get("tradeOpened"):
        clean["tradeOpened"] = _scalar_subset(row["tradeOpened"], LEG_FIELDS)
    if row.get("tradeReduced"):
        clean["tradeReduced"] = _scalar_subset(row["tradeReduced"], LEG_FIELDS)
    if "tradesClosed" in row:
        if not isinstance(row["tradesClosed"], list):
            raise CostAuditError("Malformed closed-trade list")
        clean["tradesClosed"] = [_scalar_subset(leg, LEG_FIELDS) for leg in row["tradesClosed"]]
    return clean


def _adjustment(row: dict) -> tuple[list[dict], bool]:
    """Select instrument-only adjustments; never save account financing totals."""
    identity = _scalar_subset(row, ("id", "time", "type"))
    if row["type"] == "DIVIDEND_ADJUSTMENT":
        if row.get("instrument") != INSTRUMENT:
            return [], False
        clean = {**identity, **_scalar_subset(row, ("instrument", "dividendAdjustment"))}
        if "openTradeDividendAdjustments" in row:
            clean["openTradeDividendAdjustments"] = [
                _scalar_subset(r, ("tradeID", "dividendAdjustment")) for r in row["openTradeDividendAdjustments"]]
        return [clean], False
    positions = row.get("positionFinancings")
    if not isinstance(positions, list):
        return [], True  # no allocation evidence, NOT proof of zero financing
    selected = []
    for position in positions:
        if position.get("instrument") == INSTRUMENT:
            clean = {**identity, **_scalar_subset(position, ("instrument", "financing", "accountFinancingMode"))}
            if "openTradeFinancings" in position:
                clean["openTradeFinancings"] = [_scalar_subset(r, ("tradeID", "financing"))
                                                for r in position["openTradeFinancings"]]
            selected.append(clean)
    if len(selected) > 1:
        raise CostAuditError("Duplicate target instrument financing allocation")
    # Explicit nonzero account financing with no target allocation remains
    # unattributed; do not assign another instrument's charges to NAS100.
    unattributed = not selected and (row.get("financing") is None or number(row["financing"]) != 0)
    return selected, unattributed


def _safe_page(url: str, account: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != "https" or parsed.netloc != "api-fxpractice.oanda.com"
            or parsed.path != f"/v3/accounts/{account}/transactions/idrange" or parsed.params or parsed.fragment
            or set(query) - {"from", "to", "type"}
            or any(len(query.get(k, [])) != 1 or not re.fullmatch(r"[0-9]+", query[k][0]) for k in ("from", "to"))
            or int(query["from"][0]) > int(query["to"][0])
            or any(t not in TYPES for value in query.get("type", []) for t in value.split(","))):
        raise ResearchDownloadError("Unexpected transaction page; authenticated GET refused")
    return url


class CostReader:
    """Only explicitly allowed GET paths on the practice host; one attempt each."""

    def __init__(self, account: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9-]+", account) or not token:
            raise ResearchDownloadError("Invalid practice credentials")
        self.account = account
        self.base = f"{PRACTICE}/accounts/{account}"
        self.requests_used = 0
        self.session = requests.Session()
        # Do not route account credentials through ambient proxies or let
        # .netrc replace the explicitly supplied Bearer authentication.
        self.session.trust_env = False
        self.session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
        self.session.headers.update({"Authorization": "Bearer " + token, "Accept": "application/json",
                                     "Accept-Datetime-Format": "RFC3339"})

    def get(self, url: str, params: dict | None = None) -> dict:
        if url not in {self.base + suffix for suffix in ("/summary", "/instruments", "/transactions")}:
            _safe_page(url, self.account)
        if self.requests_used >= MAX_REQUESTS:
            raise ResearchDownloadError("Eight-request hard budget exhausted")
        self.requests_used += 1  # failed attempts also count; no retry/fallback
        try:
            response = self.session.get(url, params=params, timeout=20, allow_redirects=False)
        except requests.RequestException:
            raise ResearchDownloadError("Practice GET failed; no retry or output") from None
        if response.status_code != 200:
            raise ResearchDownloadError("Practice GET declined; no retry or raw response displayed")
        try:
            payload = response.json()
        except ValueError:
            raise ResearchDownloadError("Invalid practice JSON; no output") from None
        if not isinstance(payload, dict):
            raise ResearchDownloadError("Malformed practice response; no output")
        return payload

    def snapshot(self, start: date, end: date) -> dict:
        account = self.get(self.base + "/summary").get("account", {})
        if account.get("currency") != "USD":
            raise ResearchDownloadError("Expected USD practice account; stopping before further reads")
        response = self.get(self.base + "/instruments", {"instruments": INSTRUMENT})
        instruments = response.get("instruments")
        if not isinstance(instruments, list) or len(instruments) != 1:
            raise ResearchDownloadError("Expected exactly the requested current instrument")
        instrument = sanitize_instrument(instruments[0])
        if instrument.get("name") != INSTRUMENT or instrument.get("type") != "CFD":
            raise ResearchDownloadError("Current instrument mismatch; stopping")
        from_dt, to_dt = _datetime_bounds(start, end)
        # The documented TransactionFilter enum does not list every newer
        # TransactionType (e.g. dividends). Use the same bounded date index as
        # the old export; retain ONLY target fills/adjustments in memory below.
        index = self.get(self.base + "/transactions", {"from": from_dt, "to": to_dt, "pageSize": 1000})
        pages = index.get("pages")
        if not isinstance(pages, list) or len(pages) > MAX_REQUESTS - self.requests_used:
            raise ResearchDownloadError("Transaction pages exceed remaining hard budget; no page reads")
        urls = [_safe_page(page, self.account) for page in pages]
        if len(set(urls)) != len(urls):
            raise ResearchDownloadError("Duplicate transaction pages; no page reads")
        fills, financing, dividends, seen = [], [], [], set()
        unallocated = 0
        for url in urls:
            transactions = self.get(url).get("transactions")
            if not isinstance(transactions, list) or len(transactions) > 1000:
                raise ResearchDownloadError("Missing/excessive transaction page records")
            for tx in transactions:
                if tx.get("type") not in TYPES:
                    continue
                d = parse_time(tx["time"]).astimezone(NY).date()
                if not start <= d <= end:
                    continue
                tid = str(tx["id"])
                if not re.fullmatch(r"[0-9]+", tid) or tid in seen:
                    raise ResearchDownloadError("Invalid/duplicate transaction identity")
                seen.add(tid)
                if tx["type"] == "ORDER_FILL":
                    if tx.get("instrument") == INSTRUMENT:
                        fills.append(sanitize_cost_fill(tx))
                else:
                    selected, unattributed = _adjustment(tx)
                    unallocated += unattributed
                    (financing if tx["type"] == "DAILY_FINANCING" else dividends).extend(selected)
        return {"status": "practice_current_and_recent_cost_evidence", "environment": "practice", "instrument": INSTRUMENT,
                "account_currency": "USD", "collected_at_utc": datetime.now(timezone.utc).isoformat(),
                "window": {"start_ny": start.isoformat(), "end_ny": end.isoformat(), "already_inspected": True},
                "instrument_specification": instrument, "fills": sorted(fills, key=lambda r: (r["time"], int(r["id"]))),
                "daily_financing": financing, "dividend_adjustments": dividends,
                "unattributed_daily_financing_count": unallocated}


def read_prior(folder_name: str) -> tuple[date, date, list[dict], str]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}", folder_name):
        raise ResearchDownloadError("Expected an existing inspected START_END fill-export folder")
    start, end = map(date.fromisoformat, folder_name.split("_"))
    validate_dates(start, end, datetime.now(NY).date())
    path = OUTPUT_ROOT / folder_name / "fills.json"
    _safe_output(path)
    try:
        raw = path.read_bytes()
        prior = json.loads(raw)
    except (OSError, ValueError):
        raise ResearchDownloadError("Missing/invalid prior inspected fill export") from None
    if not isinstance(prior, list) or not prior or any(r.get("instrument") != INSTRUMENT for r in prior):
        raise ResearchDownloadError("Expected prior inspected NAS100 fill records")
    ids = [str(r["id"]) for r in prior]
    if len(ids) != len(set(ids)):
        raise ResearchDownloadError("Duplicate prior inspected fill identities")
    return start, end, prior, _hash(raw)


def compare_prior(current: list[dict], prior: list[dict]) -> None:
    # Original exporter omitted all new costs; compare exactly the original
    # IDs/times/reasons/prices/units/realizedPL, not newly retained fee fields.
    old = {str(r["id"]): r for r in prior}
    new = {str(r["id"]): sanitize_fill(r) for r in current}
    if len(new) != len(current) or new != old:
        raise ResearchDownloadError("Re-exported fills differ from the already-inspected evidence; no output")


def save_bundle(snapshot: dict, report: dict, prior_sha: str, folder_name: str, count: int) -> Path:
    name = folder_name + "_snapshot_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = COST_ROOT / name
    _safe_output(output / "snapshot.json")
    COST_ROOT.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ResearchDownloadError("Private evidence bundle exists; refusing overwrite")
    temporary = Path(tempfile.mkdtemp(dir=COST_ROOT, prefix=".partial-"))
    try:
        _private_json(temporary / "snapshot.json", snapshot)
        _private_json(temporary / "cost_audit.json", report)
        provenance = {"version": 1, "source": "OANDA_PRACTICE_GET_ONLY_CURRENT_AND_PREVIOUSLY_INSPECTED_RECENT_WINDOW",
                      "request_budget": MAX_REQUESTS, "requests_used": count, "automatic_retries": 0,
                      "prior_fill_export_sha256": prior_sha, "snapshot_sha256": _hash((temporary / "snapshot.json").read_bytes()),
                      "audit_sha256": _hash((temporary / "cost_audit.json").read_bytes()),
                      "source_code_sha256": _code_digest(), "historical_2020_2024_applicability": "unverified"}
        _private_json(temporary / "provenance.json", provenance)
        os.rename(temporary, output)  # unique destination, never replace existing evidence
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)  # only this run's own temporary private folder
    return output


def audit_bundle(name: str) -> tuple[Path, dict]:
    """Zero HTTP/credentials/writes; check saved SHA-256s and recomputed audit."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_snapshot_\d{8}T\d{12}Z", name):
        raise ResearchDownloadError("Expected a generated private cost bundle name")
    folder = COST_ROOT / name
    _safe_output(folder / "snapshot.json")
    try:
        snapshot_raw = (folder / "snapshot.json").read_bytes()
        audit_raw = (folder / "cost_audit.json").read_bytes()
        provenance = json.loads((folder / "provenance.json").read_bytes())
        snapshot, saved = json.loads(snapshot_raw), json.loads(audit_raw)
    except (OSError, ValueError):
        raise ResearchDownloadError("Missing or invalid private cost bundle") from None
    count = provenance.get("requests_used")
    if (provenance.get("version") != 1 or provenance.get("request_budget") != MAX_REQUESTS
            or provenance.get("automatic_retries") != 0 or isinstance(count, bool)
            or not isinstance(count, int) or not 1 <= count <= MAX_REQUESTS
            or provenance.get("snapshot_sha256") != _hash(snapshot_raw)
            or provenance.get("audit_sha256") != _hash(audit_raw)
            or provenance.get("source_code_sha256") != _code_digest()):
        raise ResearchDownloadError("Private cost checksum/source contract changed; review offline")
    _, _, prior, prior_sha = read_prior(name.split("_snapshot_")[0])
    if provenance.get("prior_fill_export_sha256") != prior_sha:
        raise ResearchDownloadError("Prior fill export checksum changed")
    compare_prior(snapshot["fills"], prior)
    if audit_cost_snapshot(snapshot) != saved:
        raise ResearchDownloadError("Saved private cost audit differs from offline recomputation")
    return folder, saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Current/recent practice cost evidence; no orders, max 8 GETs")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--folder", help="Saved previously inspected START_END fill export")
    mode.add_argument("--audit", help="Generated cost bundle name; verify offline with zero credentials/HTTP/writes")
    parser.add_argument("--fetch", action="store_true", help="Only after explicit authorization: <=8 practice GETs, no retries")
    args = parser.parse_args()
    if args.audit and args.fetch:
        parser.error("--audit is offline; cannot combine it with --fetch")
    reader = None
    try:
        if args.audit:
            folder, report = audit_bundle(args.audit)
            print("Private cost bundle verified offline:", folder.relative_to(ROOT))
            print("Zero credentials, zero HTTP, zero writes; current/recent evidence only.")
            print("Fill records:", report["recent_fill_records"], "; historical costs verified: false")
            return 0
        start, end, prior, prior_sha = read_prior(args.folder)
        if not args.fetch:
            print("Dry run: zero credentials, zero HTTP, zero writes. Current/recent evidence only.")
            print("Existing inspected window:", args.folder, "; prior fill count:", len(prior), "; maximum practice GETs:", MAX_REQUESTS)
            return 0
        account, token, instrument = credentials()
        if instrument != INSTRUMENT:
            raise ResearchDownloadError("Expected configured practice NAS100 instrument")
        reader = CostReader(account, token)
        snapshot = reader.snapshot(start, end)
        compare_prior(snapshot["fills"], prior)
        report = audit_cost_snapshot(snapshot)
        folder = save_bundle(snapshot, report, prior_sha, args.folder, reader.requests_used)
    except (ResearchDownloadError, CostAuditError, ValueError, KeyError, TypeError, AttributeError, OSError):
        parser.exit(1, "Practice cost evidence refused; no retries. Check configuration/source/identity privately.\n")
    finally:
        if reader is not None:
            reader.session.close()
    print("Private current/recent cost evidence:", folder.relative_to(ROOT))
    print("Practice GETs used:", reader.requests_used, "of", MAX_REQUESTS, "; retries: 0")
    print("Re-exported fill identities matched:", len(prior))
    print("Fee field coverage (counts only):", report["fee_field_coverage"])
    print("Recent price/unit P&L check statuses:", report["recent_price_units_pl_check_counts"])
    print("Current metadata/recent fees are NOT 2020-2024 terms or prospective evidence. No new exit rule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
