"""Pure audit of CURRENT instrument metadata and RECENT observed fill-cost fields.

No requests, orders, account configuration, X posting or strategy promotion.
Absence is unknown, never zero. Spread and nested fee totals are not charged twice.
All inputs/results containing broker fills must remain private and Git-ignored.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

from src.research_parity import NY, parse_time

INSTRUMENT = "NAS100_USD"
FILL_COMPONENTS = ("pl", "financing", "commission", "guaranteedExecutionFee", "halfSpreadCost")
TRADE_COMPONENTS = ("realizedPL", "financing", "guaranteedExecutionFee", "halfSpreadCost")


class CostAuditError(ValueError):
    """Sanitized cost/identity failure; no broker field values in messages."""


def number(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise CostAuditError("Invalid numeric cost/size field")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise CostAuditError("Invalid numeric cost/size field") from None
    if not result.is_finite():
        raise CostAuditError("Non-finite cost/size field")
    return result


def _optional(row: dict, key: str) -> Decimal | None:
    # A present null is not explicit zero either.
    return number(row[key]) if key in row and row[key] is not None else None


def _text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _sum_check(top: dict, key: str, legs: list[dict]) -> str:
    total = _optional(top, key)
    values = [_optional(leg, key) for leg in legs]
    if total is None or not legs or any(v is None for v in values):
        return "unavailable_fields"
    return "match" if abs(total - sum(values, Decimal(0))) <= Decimal("0.00001") else "mismatch"


def current_instrument_checks(spec: dict) -> dict:
    if spec.get("name") != INSTRUMENT or spec.get("type") != "CFD":
        raise CostAuditError("Current account instrument is not expected NAS100 CFD")
    precision = spec.get("tradeUnitsPrecision")
    if precision is not None and (isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 8):
        raise CostAuditError("Invalid current trade unit precision")
    minimum, maximum = _optional(spec, "minimumTradeSize"), _optional(spec, "maximumOrderUnits")
    if minimum is not None and minimum <= 0 or maximum is not None and maximum < 0:
        raise CostAuditError("Invalid current size limit")
    size_checks = []
    for size in (Decimal(80), Decimal(40)):
        precision_ok = (size % (Decimal(10) ** -precision) == 0) if precision is not None else None
        # A zero/absent max is NOT silently interpreted as an unlimited order.
        maximum_ok = size <= maximum if maximum is not None and maximum > 0 else None
        minimum_ok = size >= minimum if minimum is not None else None
        size_checks.append({"model_units": str(size), "unit_precision_ok": precision_ok,
                            "minimum_size_ok": minimum_ok, "maximum_order_size_ok": maximum_ok,
                            "order_tested": False})
    commission = spec.get("commission")
    commission_check = {"status": "unknown_missing_fields", "historical_applicability": "unverified"}
    if isinstance(commission, dict):
        rate, basis, floor = (_optional(commission, k) for k in ("commission", "unitsTraded", "minimumCommission"))
        if all(x is not None for x in (rate, basis, floor)):
            if rate < 0 or basis <= 0 or floor < 0:
                raise CostAuditError("Invalid current instrument commission metadata")
            commission_check = {"status": "current_metadata_only", "historical_applicability": "unverified",
                                "nominal_80_unit_fill_commission_home_currency": str(max(rate * 80 / basis, floor)),
                                "nominal_40_unit_fill_commission_home_currency": str(max(rate * 40 / basis, floor))}
    return {"status": "current_snapshot_only", "size_checks": size_checks,
            "commission": commission_check, "legal_entity": "not_established_by_v20_snapshot",
            "2020_2024_contract_cost_hours_verified": False,
            "partial_close_or_stop_amendment_tested": False}


def audit_cost_snapshot(snapshot: dict) -> dict:
    """Field presence, arithmetic and recent price/unit parity, NOT a fitted fee model.

    Home-currency fill components use top-level pl/financing/commission exactly
    once. Nested trade fields only cross-check the totals. halfSpreadCost is a
    diagnostic already reflected by executable fill prices; do not subtract it.
    Nonzero guaranteed fees require separately confirmed cash-sign conventions;
    this audit withholds a full cash component calculation in that case.
    """
    if (snapshot.get("status") != "practice_current_and_recent_cost_evidence"
            or snapshot.get("environment") != "practice" or snapshot.get("instrument") != INSTRUMENT
            or snapshot.get("account_currency") != "USD" or snapshot["window"].get("already_inspected") is not True):
        raise CostAuditError("Expected USD practice current/recent evidence, not historical fee validation")
    collected = parse_time(snapshot["collected_at_utc"])
    start, end = (date.fromisoformat(snapshot["window"][k]) for k in ("start_ny", "end_ny"))
    if not start <= end < collected.astimezone(NY).date():
        raise CostAuditError("Expected completed recent evidence window")
    if (isinstance(snapshot["unattributed_daily_financing_count"], bool)
            or not isinstance(snapshot["unattributed_daily_financing_count"], int)
            or snapshot["unattributed_daily_financing_count"] < 0):
        raise CostAuditError("Invalid unattributed financing count")
    current = current_instrument_checks(snapshot["instrument_specification"])
    fills = snapshot["fills"]
    if not isinstance(fills, list) or not fills:
        raise CostAuditError("Missing recent fill evidence")
    ids = [str(row["id"]) for row in fills]
    if len(ids) != len(set(ids)):
        raise CostAuditError("Duplicate recent fill evidence")
    coverage = {k: Counter() for k in FILL_COMPONENTS}
    checks, trades, price_checks = [], {}, []
    for row in sorted(fills, key=lambda r: (parse_time(r["time"]), int(r["id"]))):
        if (row.get("type") != "ORDER_FILL" or row.get("instrument") != INSTRUMENT
                or not start <= parse_time(row["time"]).astimezone(NY).date() <= end):
            raise CostAuditError("Unexpected instrument/type/date in recent fill evidence")
        values = {k: _optional(row, k) for k in FILL_COMPONENTS}
        if values["commission"] is not None and values["commission"] < 0:
            raise CostAuditError("Commission must be a nonnegative debit magnitude")
        for key, value in values.items():
            coverage[key]["missing" if value is None else "explicit_zero" if value == 0 else "explicit_nonzero"] += 1
        opened = row.get("tradeOpened")
        closed = list(row.get("tradesClosed") or [])
        if row.get("tradeReduced"):
            closed.append(row["tradeReduced"])
        legs = ([opened] if opened else []) + closed
        if not legs:
            raise CostAuditError("Recent fill has no official trade-level fill prices")
        for leg in legs:
            if number(leg["price"]) <= 0 or number(leg["units"]) == 0:
                raise CostAuditError("Invalid official trade-level fill price/units")
            for key in TRADE_COMPONENTS:
                _optional(leg, key)
        cash_values = [values[k] for k in ("pl", "financing", "commission", "guaranteedExecutionFee")]
        if any(v is None for v in cash_values):
            cash_status, cash = "withheld_missing_components", None
        elif values["guaranteedExecutionFee"] != 0:
            cash_status, cash = "withheld_nonzero_guaranteed_fee_sign_unconfirmed", None
        else:
            cash_status = "reported_fill_components_only_not_account_balance_reconciliation"
            cash = values["pl"] + values["financing"] - values["commission"]
        sums = {"closed_trade_pl": _sum_check(row, "pl", [{"pl": l["realizedPL"]} if "realizedPL" in l else {} for l in closed]),
                "closed_trade_financing": _sum_check(row, "financing", closed),
                "all_trade_half_spread": _sum_check(row, "halfSpreadCost", legs),
                "all_trade_guaranteed_fees": _sum_check(row, "guaranteedExecutionFee", legs)}
        if any(v == "mismatch" for v in sums.values()):
            raise CostAuditError("Reported top-level and trade-level cost components disagree")
        checks.append({"transaction_id_private": row["id"], "component_checks": sums,
                       "cash_component_status": cash_status, "reported_fill_cash_components_usd_private": _text(cash),
                       "half_spread_subtracted_again": False})
        if opened:
            tid = str(opened["tradeID"])
            if tid in trades:
                raise CostAuditError("Duplicate opening trade identity")
            trades[tid] = {"entry": number(opened["price"]), "units": number(opened["units"]),
                           "opened_at": parse_time(row["time"]), "closed_units": Decimal(0)}
        for leg in closed:
            tid = str(leg["tradeID"])
            trade = trades.get(tid)
            reported_pl = _optional(leg, "realizedPL")
            if trade is None:
                price_checks.append({"status": "unresolved_opened_outside_window"})
                continue
            amount = abs(number(leg["units"]))
            trade["closed_units"] += amount
            if parse_time(row["time"]) < trade["opened_at"] or trade["closed_units"] > abs(trade["units"]):
                raise CostAuditError("Recent reduction chronology/units do not reconcile")
            if reported_pl is None:
                # Missing money evidence must not disable the independent
                # chronology/unit conservation check for a known trade.
                price_checks.append({"status": "unresolved_missing_reported_pl"})
                continue
            direction = Decimal(1) if trade["units"] > 0 else Decimal(-1)
            implied = direction * (number(leg["price"]) - trade["entry"]) * amount
            # Observed recent USD price/unit check, NOT an assertion of the
            # historical CFD multiplier or future executable partial fills.
            price_checks.append({"trade_id_private": tid, "status": "match" if abs(implied - reported_pl) <= Decimal("0.01") else "mismatch",
                                 "price_units_implied_usd_private": str(implied), "reported_realized_pl_usd_private": str(reported_pl)})
    financing = snapshot["daily_financing"]
    dividends = snapshot["dividend_adjustments"]
    adjustments = []
    for rows, field, kind in ((financing, "financing", "daily_financing"), (dividends, "dividendAdjustment", "dividend_adjustment")):
        for row in rows:
            expected_type = "DAILY_FINANCING" if kind == "daily_financing" else "DIVIDEND_ADJUSTMENT"
            if (row.get("instrument") != INSTRUMENT or row.get("type") != expected_type
                    or not start <= parse_time(row["time"]).astimezone(NY).date() <= end):
                raise CostAuditError("Foreign instrument/type/date adjustment in cost evidence")
            total = _optional(row, field)
            nested = row.get("openTradeFinancings" if kind == "daily_financing" else "openTradeDividendAdjustments")
            status = _sum_check(row, field, nested or [])
            if status == "mismatch":
                raise CostAuditError("Instrument adjustment differs from its trade components")
            adjustments.append({"kind": kind, "transaction_id_private": row["id"], "amount_home_currency_private": _text(total),
                                "trade_sum_status": status, "bot_attribution": "not_established"})
    return {"status": "current_and_recent_diagnostic_only", "selection": "none", "historical_costs_verified": False,
            "recent_fill_records": len(fills), "fee_field_coverage": {k: dict(v) for k, v in coverage.items()},
            "recent_price_units_pl_check_counts": dict(Counter(c["status"] for c in price_checks)),
            "fill_cash_component_status_counts": dict(Counter(c["cash_component_status"] for c in checks)),
            "current_instrument_checks": current, "daily_financing_instrument_events": len(financing),
            "dividend_instrument_events": len(dividends), "unattributed_account_financing_events": snapshot["unattributed_daily_financing_count"],
            "fill_cost_checks_private": checks, "recent_price_units_checks_private": price_checks,
            "instrument_adjustment_checks_private": adjustments,
            "limits": ["Already-inspected recent practice fills and current settings, not 2020-2024 contract/cost evidence or a new holdout.",
                       "Missing fee fields remain unknown; explicit zero is evidence only for that record.",
                       "Reported fill components are not a complete account balance/commission invoice reconciliation.",
                       "halfSpreadCost and nested cost fields are diagnostics/checks, not extra debits to subtract again.",
                       "Instrument adjustments may concern unrelated trades; no automatic bot attribution.",
                       "Current size/commission metadata does not certify partial order or stop replacement execution.",
                       "No exit parameters fitted, selected or promoted; no broker order or configuration change."]}
