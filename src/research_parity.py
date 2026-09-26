"""Read-only, conservative reconciliation of OANDA practice fills with the 25/75 baseline.

Pure functions: no network, order submission, notifications, or imports from the live bot.
OANDA transaction data and per-trade reports are private and must stay Git-ignored.
"""

from __future__ import annotations

from datetime import datetime, timedelta, time, timezone
import re
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def parse_time(value: str) -> datetime:
    # OANDA uses up to nine fractional-second digits; datetime supports six.
    normalized = re.sub(r"(\.\d{6})\d+(?=Z$|[+-]\d{2}:\d{2}$)", r"\1", value)
    result = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Expected timezone-aware timestamp")
    return result.astimezone(timezone.utc)


def extract_trades(fills: list[dict]) -> list[dict]:
    """Join broker ORDER_FILL tradeOpened/tradesClosed by ID; flag reductions.

    Only use the per-trade prices, not OANDA's deprecated top-level fill price.
    Ignore trades opened before this export window rather than inventing an entry.
    """
    trades: dict[str, dict] = {}
    for fill in sorted(fills, key=lambda f: (f["time"], int(f["id"]))):
        opened = fill.get("tradeOpened")
        if opened:
            tid = str(opened["tradeID"])
            trades[tid] = {
                "trade_id": tid,
                "instrument": fill.get("instrument"),
                "entry_time": fill["time"],
                "entry_price": opened.get("price"),
                "units": opened.get("units"),
                "closes": [],
            }
        reductions = list(fill.get("tradesClosed") or [])
        if fill.get("tradeReduced"):
            reductions.append(fill["tradeReduced"])
        for reduction in reductions:
            trade = trades.get(str(reduction["tradeID"]))
            if trade is not None:
                trade["closes"].append({
                    "time": fill["time"],
                    "price": reduction.get("price"),
                    "units": reduction.get("units"),
                    "realized_pl": reduction.get("realizedPL"),
                    "reason": fill.get("reason"),
                    "transaction_id": fill["id"],
                })
    return list(trades.values())


def broker_reason(reason: str | None, close_time: datetime) -> str | None:
    if reason == "STOP_LOSS_ORDER":
        return "sl"
    if reason == "TAKE_PROFIT_ORDER":
        return "tp"
    # A market close near the hard exit is a *candidate* time exit, not proof
    # that the bot rather than a human/external process initiated that order.
    t = close_time.astimezone(NY)
    noon = datetime.combine(t.date(), time(12), tzinfo=NY)
    if reason in ("MARKET_ORDER", "MARKET_ORDER_TRADE_CLOSE") and abs((t - noon).total_seconds()) <= 120:
        return "time_candidate"
    return None


def _first_safe_minute(ts: datetime) -> datetime:
    """Never use the price path before the broker fill within the entry minute."""
    minute = ts.replace(second=0, microsecond=0)
    return minute if minute == ts else minute + timedelta(minutes=1)


def simulate_baseline(trade: dict, candles: list[dict], stop: float = 25, target: float = 75) -> dict:
    """Return first executable bid/ask barrier after fill; no optimistic same-bar tie.

    OANDA candle timestamps are minute STARTs. For incomplete/missing paths,
    return unknown instead of pretending the noon close or stop was observed.
    """
    if not trade.get("entry_price") or not trade.get("units"):
        return {"reason": "unknown", "detail": "missing_broker_entry"}
    entry = float(trade["entry_price"])
    units = float(trade["units"])
    if units == 0 or stop <= 0 or target <= 0:
        return {"reason": "unknown", "detail": "invalid_entry_or_limits"}
    is_long = units > 0
    fill_time = parse_time(trade["entry_time"])
    start = _first_safe_minute(fill_time)
    local_fill = fill_time.astimezone(NY)
    noon = datetime.combine(local_fill.date(), time(12), tzinfo=NY).astimezone(timezone.utc)
    if fill_time >= noon:
        return {"reason": "unknown", "detail": "entry_at_or_after_noon"}
    # 12:00 candle covers 12:00–12:01, after the nominal hard-flat time.
    path = sorted((c for c in candles if start <= parse_time(c["time"]) < noon), key=lambda c: c["time"])
    if not path:
        return {"reason": "unknown", "detail": "missing_candles"}
    expected = start
    for c in path:
        ts = parse_time(c["time"])
        if ts != expected or not c.get("complete"):
            return {"reason": "unknown", "detail": "gap_or_incomplete_candle"}
        quote = c.get("bid" if is_long else "ask") or {}
        if not quote or "h" not in quote or "l" not in quote:
            return {"reason": "unknown", "detail": "missing_executable_quote"}
        hi, lo = float(quote["h"]), float(quote["l"])
        sl_hit = lo <= entry - stop if is_long else hi >= entry + stop
        tp_hit = hi >= entry + target if is_long else lo <= entry - target
        if sl_hit and tp_hit:
            return {"reason": "unknown", "detail": "ambiguous_same_bar", "first_bar": c["time"]}
        if sl_hit or tp_hit:
            return {"reason": "sl" if sl_hit else "tp", "first_bar": c["time"]}
        expected = ts + timedelta(minutes=1)
    if expected < noon:
        return {"reason": "unknown", "detail": "missing_candles_before_noon"}
    return {"reason": "time", "first_bar": noon.isoformat()}


def reconcile(trades: list[dict], candles_by_day: dict[str, list[dict]], instrument: str) -> list[dict]:
    """Per-trade audit; matches require broker reason AND approximate hit time."""
    counts: dict[str, int] = {}
    for trade in trades:
        day = parse_time(trade["entry_time"]).astimezone(NY).date().isoformat()
        counts[day] = counts.get(day, 0) + 1
    results = []
    for trade in trades:
        day = parse_time(trade["entry_time"]).astimezone(NY).date().isoformat()
        row = {"day_ny": day, "trade_id": trade["trade_id"], "status": "unresolved"}
        results.append(row)
        if trade.get("instrument") != instrument:
            row["detail"] = "different_instrument"
            continue
        if counts[day] != 1:
            row["detail"] = "multiple_trades_same_day"
            continue
        if len(trade["closes"]) != 1 or not trade.get("units") or not trade.get("entry_price"):
            row["detail"] = "open_partial_or_missing_fill"
            continue
        close = trade["closes"][0]
        if not close.get("units") or not close.get("price") or abs(float(close["units"])) != abs(float(trade["units"])):
            row["detail"] = "partial_or_missing_close"
            continue
        observed = broker_reason(close["reason"], parse_time(close["time"]))
        row.update({"entry_price": trade["entry_price"], "close_price": close["price"],
                    "realized_pl": close["realized_pl"], "broker_reason": observed,
                    "broker_close_time": close["time"]})
        if parse_time(close["time"]) < _first_safe_minute(parse_time(trade["entry_time"])):
            row["detail"] = "exit_inside_entry_minute"
            continue
        if observed is None:
            row["detail"] = "unclassified_broker_exit"
            continue
        direction = 1 if float(trade["units"]) > 0 else -1
        row["observed_points"] = round(direction * (float(close["price"]) - float(trade["entry_price"])), 4)
        if observed in ("sl", "tp"):
            expected_points = -25 if observed == "sl" else 75
            row["expected_gross_points"] = expected_points
            row["price_delta_points"] = round(row["observed_points"] - expected_points, 4)
        simulation = simulate_baseline(trade, candles_by_day.get(day, []))
        row["simulated_reason"] = simulation["reason"]
        row["detail"] = simulation.get("detail", "")
        if simulation["reason"] == "unknown":
            continue
        first = parse_time(simulation["first_bar"])
        broker_close = parse_time(close["time"])
        # Market stops can slip and minute bars start before their true hit.
        # Large timing discrepancies require investigation, not a forced match.
        minutes_apart = abs((broker_close - first).total_seconds()) / 60
        row["minutes_apart"] = round(minutes_apart, 2)
        if simulation["reason"] == "time" and observed == "time_candidate" and minutes_apart <= 2:
            row["status"] = "candidate_match"  # cannot attribute a MARKET_ORDER to the bot
        elif simulation["reason"] == observed and minutes_apart <= 2:
            row["status"] = "match"
        elif minutes_apart > 2:
            row["status"] = "unresolved"
            row["detail"] = "broker_simulation_timing_disagreement"
        else:
            row["status"] = "mismatch"
            row["detail"] = "broker_simulation_reason_disagreement"
    return results
