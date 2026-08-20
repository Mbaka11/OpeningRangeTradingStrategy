"""Compact, readable daily X post formatting.

Normal cadence:
- Trade day: one signal post and one final recap.
- No-trade day: one final recap.

All formatters keep messages within X's 280-character text limit.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

MAX_POST_CHARS = 280


def _number(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.{decimals}f}"


def _signed_number(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):+,.2f}"


def _money(value: Optional[float], *, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    amount = float(value)
    if signed:
        sign = "+" if amount >= 0 else "-"
        return f"{sign}${abs(amount):,.2f}"
    return f"${amount:,.2f}"


def _account_value(snapshot: Optional[Mapping[str, Any]], key: str) -> Optional[float]:
    if not snapshot:
        return None
    value = snapshot.get(key)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _environment_label(environment: str) -> str:
    normalized = environment.strip().lower()
    if normalized == "replay":
        return "REPLAY"
    return "PAPER" if normalized in {"practice", "paper"} else "LIVE"


def _finish(lines: list[str]) -> str:
    message = "\n".join(lines)
    if len(message) > MAX_POST_CHARS:
        raise ValueError(f"Formatted X post is {len(message)} characters; maximum is {MAX_POST_CHARS}")
    return message


def format_signal_post(
    *,
    trade_date: Any,
    instrument: str,
    environment: str,
    or_start: str,
    exit_time: str,
    entry_time: str,
    or_low: float,
    or_high: float,
    long_cut: float,
    short_cut: float,
    side: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    position_size: float,
    point_value: float,
    account: Optional[Mapping[str, Any]],
) -> str:
    """Format the opening-range setup and accepted paper trade as post one."""
    label = _environment_label(environment)
    currency = (account or {}).get("currency") or "USD"
    balance = _account_value(account, "balance")
    nav = _account_value(account, "nav")
    lines = []
    if label == "REPLAY":
        lines.append("REPLAY ONLY - NO LIVE ORDER")
    lines.extend([
        f"{instrument} {label} | {trade_date}",
        f"Session {or_start}-{exit_time} ET | Entry {entry_time}",
        f"OR {_number(or_low)}-{_number(or_high)}",
        f"Long >= {_number(long_cut)} | Short <= {_number(short_cut)}",
        f"{side.upper()} @ {_number(entry)} | SL {_number(stop_loss)} | TP {_number(take_profit)}",
        f"Size {_number(position_size, 2)} x ${_number(point_value, 2)}/pt",
    ])
    if label == "REPLAY":
        lines.append("Balance unavailable in replay")
    else:
        lines.append(f"Balance {_number(balance)} {currency} | NAV {_number(nav)}")
    return _finish(lines)


def format_trade_recap_post(
    *,
    trade_date: Any,
    instrument: str,
    environment: str,
    side: str,
    entry: Optional[float],
    exit_price: Optional[float],
    exit_reason: Optional[str],
    pnl_points: Optional[float],
    pnl_usd: Optional[float],
    mfe: Optional[float],
    mae: Optional[float],
    start_account: Optional[Mapping[str, Any]],
    end_account: Optional[Mapping[str, Any]],
    signals: int,
    orders: int,
    skipped: int,
    errors: int,
) -> str:
    """Format the exit, performance, balances, and counters as post two."""
    label = _environment_label(environment)
    reason_labels = {"tp": "TP", "sl": "SL", "time": "12:00 EXIT"}
    reason = reason_labels.get((exit_reason or "").lower(), (exit_reason or "UNKNOWN").upper())

    balance_start = _account_value(start_account, "balance")
    balance_end = _account_value(end_account, "balance")
    nav_start = _account_value(start_account, "nav")
    nav_end = _account_value(end_account, "nav")
    currency = (end_account or start_account or {}).get("currency") or "USD"

    lines = []
    if label == "REPLAY":
        lines.append("REPLAY ONLY - NO LIVE ORDER")
    lines.extend([
        f"{instrument} {label} RECAP | {trade_date}",
        f"{side.upper()} {_number(entry)} -> {_number(exit_price)} | {reason}",
        f"PnL {_signed_number(pnl_points)} pt | {_money(pnl_usd, signed=True)}",
        f"MFE +{_number(mfe)} | MAE -{_number(mae)} pt",
    ])
    if label == "REPLAY":
        lines.append("Balance unavailable in replay")
        lines.append(f"Sim sig {signals} | Orders {orders} | Skip {skipped} | Err {errors}")
    else:
        lines.extend([
            f"Balance {_number(balance_start)} -> {_number(balance_end)} {currency}",
            f"NAV {_number(nav_start)} -> {_number(nav_end)}",
            f"Sig {signals} | Orders {orders} | Skip {skipped} | Err {errors}",
        ])
    return _finish(lines)


def format_no_trade_recap_post(
    *,
    trade_date: Any,
    instrument: str,
    environment: str,
    or_start: str,
    exit_time: str,
    entry_time: str,
    or_low: Optional[float],
    or_high: Optional[float],
    long_cut: Optional[float],
    short_cut: Optional[float],
    reason: str,
    start_account: Optional[Mapping[str, Any]],
    end_account: Optional[Mapping[str, Any]],
    signals: int,
    orders: int,
    skipped: int,
    errors: int,
) -> str:
    """Format the entire no-trade session as its single daily post."""
    label = _environment_label(environment)
    balance_start = _account_value(start_account, "balance")
    balance_end = _account_value(end_account, "balance")
    nav_start = _account_value(start_account, "nav")
    nav_end = _account_value(end_account, "nav")
    currency = (end_account or start_account or {}).get("currency") or "USD"
    reason_labels = {
        "none": "No trade: entry stayed in the middle zone",
        "missing_entry": "No trade: entry candle was unavailable",
        "missing_entry_bar": "No trade: entry candle was unavailable",
        "missing_exit_bar": "No trade: exit candle was unavailable",
        "or_incomplete": "No trade: opening-range data was incomplete",
        "or_zero_range": "No trade: opening range was zero",
        "past_hard_exit": "No trade: bot started after the hard exit",
        "past_hard_exit_closed_lingering": "No entry: late start; lingering trade closed",
        "order_rejected": "No trade: order was rejected by the broker",
        "orders_disabled": "Signal found: order placement was disabled",
    }
    if reason.startswith("order_rejected:"):
        rejection = reason.split(":", 1)[1].replace("_", " ")
        outcome = f"No trade: rejected ({rejection})"
    else:
        outcome = reason_labels.get(reason, f"No trade: {reason.replace('_', ' ')}")

    lines = []
    if label == "REPLAY":
        lines.append("REPLAY ONLY - NO LIVE ORDER")
    lines.extend([
        f"{instrument} {label} RECAP | {trade_date}",
        f"{or_start}-{exit_time} ET | Entry {entry_time}",
    ])
    if None not in (or_low, or_high, long_cut, short_cut):
        lines.extend([
            f"OR {_number(or_low)}-{_number(or_high)}",
            f"Long >= {_number(long_cut)} | Short <= {_number(short_cut)}",
        ])
    lines.append(outcome)
    if label == "REPLAY":
        lines.append("Balance unavailable in replay")
        lines.append(f"Sim sig {signals} | Orders {orders} | Skip {skipped} | Err {errors}")
    else:
        lines.extend([
            f"Balance {_number(balance_start)} -> {_number(balance_end)} {currency}",
            f"NAV {_number(nav_start)} -> {_number(nav_end)}",
            f"Sig {signals} | Orders {orders} | Skip {skipped} | Err {errors}",
        ])
    return _finish(lines)
