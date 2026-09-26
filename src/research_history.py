"""Pure audit of OANDA practice historical M1/MBA quote sessions.

No broker/account access, orders, secrets or cloud connections. A missing minute
is NOT a no-trade day. A complete quote day is NOT a verified historical fill.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

from src.research_parity import parse_time

NY = ZoneInfo("America/New_York")
SESSION_START = time(9, 30)
SESSION_END = time(12, 0)
REQUEST_START = time(9, 0)
REQUEST_END = time(12, 10)


class HistoryAuditError(ValueError):
    """Malformed historical input, with no raw candle contents in the message."""


def _valid_quote(side: object) -> bool:
    if not isinstance(side, dict):
        return False
    try:
        values = {k: float(side[k]) for k in ("o", "h", "l", "c")}
    except (KeyError, ValueError, TypeError):
        return False
    if not all(math.isfinite(x) and x > 0 for x in values.values()):
        return False
    return values["l"] <= values["o"] <= values["h"] and values["l"] <= values["c"] <= values["h"]


def audit_day(day: date, candles: list[dict]) -> dict:
    """Count session coverage / quote issues; reject invalid times, never infer a fill.

    09:30–12:00 NY inclusive = 151 minute-start timestamps. The request
    includes 09:00–12:10 for provenance and post-session tolerance.
    """
    if not isinstance(candles, list) or len(candles) > 5000:
        raise HistoryAuditError("Missing or excessive historical candle response")
    raw_timestamps = []
    for candle in candles:
        if not isinstance(candle, dict) or not isinstance(candle.get("time"), str):
            raise HistoryAuditError("Historical candle missing a timestamp")
        try:
            raw_timestamps.append(parse_time(candle["time"]).astimezone(NY))
        except (ValueError, TypeError):
            raise HistoryAuditError("Invalid historical candle timestamp") from None
    expected_start = datetime.combine(day, SESSION_START, tzinfo=NY)
    expected = {expected_start + timedelta(minutes=m) for m in range(151)}
    seen = Counter(ts for ts in raw_timestamps if ts in expected)
    missing = len(expected - seen.keys())
    duplicate = sum(max(0, n - 1) for n in seen.values())
    incomplete = invalid_quote = 0
    for candle, ts in zip(candles, raw_timestamps):
        if ts in expected:
            incomplete += candle.get("complete") is not True
            valid = all(_valid_quote(candle.get(side)) for side in ("mid", "bid", "ask"))
            if valid:
                valid = all(float(candle["bid"][k]) <= float(candle["ask"][k])
                            for k in ("o", "c"))
            invalid_quote += not valid
    outside_request = sum(ts.date() != day or not REQUEST_START <= ts.time() < REQUEST_END
                          for ts in raw_timestamps)
    status = ("no_session_data" if not seen else "complete" if
              not (missing or duplicate or incomplete or invalid_quote or outside_request) else "incomplete")
    return {"day_ny": day.isoformat(), "status": status, "returned_bars": len(candles),
            "session_bars": sum(seen.values()), "missing_session_minutes": missing,
            "duplicate_session_minutes": duplicate, "incomplete_session_bars": int(incomplete),
            "invalid_bid_ask_mid_bars": int(invalid_quote), "bars_outside_requested_window": outside_request}


def audit_range(candles_by_day: dict[str, list[dict]]) -> dict:
    if not isinstance(candles_by_day, dict) or not candles_by_day:
        raise HistoryAuditError("No historical sessions supplied")
    sessions = {}
    for day, candles in sorted(candles_by_day.items()):
        try:
            parsed = date.fromisoformat(day)
        except (TypeError, ValueError):
            raise HistoryAuditError("Invalid historical NY date") from None
        if parsed.weekday() >= 5:
            raise HistoryAuditError("Unexpected weekend in historical weekday set")
        sessions[day] = audit_day(parsed, candles)
    counts = Counter(row["status"] for row in sessions.values())
    return {"sessions": sessions,
            "summary": {"requested_weekdays": len(sessions), "complete": counts["complete"],
                        "incomplete": counts["incomplete"], "no_session_data": counts["no_session_data"],
                        "returned_candles": sum(row["returned_bars"] for row in sessions.values())}}
