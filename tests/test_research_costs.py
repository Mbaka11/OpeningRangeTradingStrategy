"""Synthetic observed-cost accounting. No account/broker data or HTTP."""

from copy import deepcopy
from decimal import Decimal

import pytest

from src.research_costs import CostAuditError, audit_cost_snapshot, current_instrument_checks, number


def snapshot():
    return {"status": "practice_current_and_recent_cost_evidence", "environment": "practice", "instrument": "NAS100_USD",
            "account_currency": "USD", "collected_at_utc": "2020-09-26T16:00:00Z",
            "window": {"start_ny": "2020-09-24", "end_ny": "2020-09-24", "already_inspected": True},
            "instrument_specification": {"name": "NAS100_USD", "type": "CFD", "tradeUnitsPrecision": 0,
                                         "minimumTradeSize": "1", "maximumOrderUnits": "1000",
                                         "commission": {"commission": "2", "unitsTraded": "80", "minimumCommission": "1"}},
            "fills": [
                {"id": "100", "type": "ORDER_FILL", "instrument": "NAS100_USD", "time": "2020-09-24T14:23:03Z",
                 "reason": "MARKET_ORDER", "pl": "0", "commission": "2", "financing": "0", "guaranteedExecutionFee": "0", "halfSpreadCost": "1",
                 "tradeOpened": {"tradeID": "100", "units": "80", "price": "100", "halfSpreadCost": "1", "guaranteedExecutionFee": "0"}},
                {"id": "101", "type": "ORDER_FILL", "instrument": "NAS100_USD", "time": "2020-09-24T16:00:03Z",
                 "reason": "MARKET_ORDER_TRADE_CLOSE", "pl": "800", "commission": "2", "financing": "-3", "guaranteedExecutionFee": "0", "halfSpreadCost": "1",
                 "tradesClosed": [{"tradeID": "100", "units": "80", "price": "110", "realizedPL": "800", "financing": "-3",
                                    "halfSpreadCost": "1", "guaranteedExecutionFee": "0"}]}
            ], "daily_financing": [], "dividend_adjustments": [], "unattributed_daily_financing_count": 0}


def test_signed_financing_and_positive_commission_without_double_charging_spread_or_nested_costs():
    out = audit_cost_snapshot(snapshot())
    assert out["recent_price_units_pl_check_counts"] == {"match": 1}
    assert out["fee_field_coverage"]["commission"] == {"explicit_nonzero": 2}
    assert out["fee_field_coverage"]["financing"] == {"explicit_zero": 1, "explicit_nonzero": 1}
    a, b = out["fill_cost_checks_private"]
    assert Decimal(a["reported_fill_cash_components_usd_private"]) == -2
    assert Decimal(b["reported_fill_cash_components_usd_private"]) == 795  # 800-3-2; NOT 793 (double spread/financing)
    assert b["component_checks"]["closed_trade_financing"] == "match"
    assert not a["half_spread_subtracted_again"] and out["selection"] == "none"
    assert not out["historical_costs_verified"]


@pytest.mark.parametrize("field", ["commission", "financing", "guaranteedExecutionFee", "pl"])
def test_missing_or_null_cash_field_is_unknown_never_zero(field):
    data = snapshot()
    del data["fills"][0][field]
    data["fills"][1][field] = None
    # Remove matching nested fields too; missing components cannot be compared.
    if field == "pl":
        del data["fills"][1]["tradesClosed"][0]["realizedPL"]
    elif field != "commission":
        data["fills"][1]["tradesClosed"][0].pop(field, None)
    out = audit_cost_snapshot(data)
    assert out["fee_field_coverage"][field] == {"missing": 2}
    assert all(r["reported_fill_cash_components_usd_private"] is None for r in out["fill_cost_checks_private"])


def test_nonzero_guaranteed_fee_withholds_cash_sign_instead_of_guessing():
    data = snapshot()
    data["fills"][0]["guaranteedExecutionFee"] = "5"
    data["fills"][0]["tradeOpened"]["guaranteedExecutionFee"] = "5"
    out = audit_cost_snapshot(data)
    assert out["fill_cost_checks_private"][0]["cash_component_status"] == "withheld_nonzero_guaranteed_fee_sign_unconfirmed"


def test_short_partial_reductions_conserve_units_and_have_price_pl_evidence_not_fill_feasibility():
    data = snapshot()
    data["fills"][0]["tradeOpened"]["units"] = "-80"
    close = data["fills"][1]
    close["pl"] = "400"
    close["financing"] = "-1"
    leg = close.pop("tradesClosed")[0]
    leg.update({"units": "40", "price": "90", "realizedPL": "400", "financing": "-1"})
    close["tradeReduced"] = leg
    final = deepcopy(close)
    final.update({"id": "102", "time": "2020-09-24T16:01:03Z", "pl": "800", "financing": "-2"})
    final["tradesClosed"] = [final.pop("tradeReduced")]
    final["tradesClosed"][0].update({"price": "80", "realizedPL": "800", "financing": "-2"})
    data["fills"].append(final)
    out = audit_cost_snapshot(data)
    assert out["recent_price_units_pl_check_counts"] == {"match": 2}
    assert not out["current_instrument_checks"]["partial_close_or_stop_amendment_tested"]
    data["fills"][-1]["tradesClosed"][0]["units"] = "41"
    with pytest.raises(CostAuditError, match="units"):
        audit_cost_snapshot(data)


def test_missing_partial_pl_cannot_hide_overclosed_units_on_a_known_trade():
    data = snapshot()
    partial = deepcopy(data["fills"][1])
    partial.update({"id": "101", "time": "2020-09-24T15:00:03Z", "pl": None})
    partial["tradeReduced"] = partial.pop("tradesClosed")[0]
    partial["tradeReduced"].update({"units": "40", "realizedPL": None})
    final = data["fills"][1]
    final["id"] = "102"  # closes the original 80 again -> 40+80 exceeds 80
    data["fills"].insert(1, partial)
    with pytest.raises(CostAuditError, match="units"):
        audit_cost_snapshot(data)
    final["tradesClosed"][0].update({"units": "40", "realizedPL": "400"})
    final["pl"] = "400"
    out = audit_cost_snapshot(data)
    assert out["recent_price_units_pl_check_counts"] == {"unresolved_missing_reported_pl": 1, "match": 1}


def test_signed_half_spread_diagnostics_and_missing_current_commission_are_not_guessed():
    data = snapshot()
    data["fills"][0]["halfSpreadCost"] = data["fills"][0]["tradeOpened"]["halfSpreadCost"] = "-1"
    del data["instrument_specification"]["commission"]
    del data["instrument_specification"]["tradeUnitsPrecision"]
    data["instrument_specification"]["maximumOrderUnits"] = "0"
    out = audit_cost_snapshot(data)
    assert out["current_instrument_checks"]["commission"]["status"] == "unknown_missing_fields"
    assert out["current_instrument_checks"]["size_checks"][0]["unit_precision_ok"] is None
    assert out["current_instrument_checks"]["size_checks"][0]["maximum_order_size_ok"] is None
    assert Decimal(out["fill_cost_checks_private"][0]["reported_fill_cash_components_usd_private"]) == -2


def test_current_size_and_nominal_commission_metadata_does_not_certify_historical_account_terms():
    out = current_instrument_checks(snapshot()["instrument_specification"])
    assert Decimal(out["commission"]["nominal_80_unit_fill_commission_home_currency"]) == 2
    assert Decimal(out["commission"]["nominal_40_unit_fill_commission_home_currency"]) == 1
    assert out["commission"]["historical_applicability"] == "unverified"
    assert all(r["unit_precision_ok"] and r["minimum_size_ok"] and r["maximum_order_size_ok"] for r in out["size_checks"])
    assert not any(r["order_tested"] for r in out["size_checks"])


def test_instrument_adjustments_are_separate_and_not_automatically_bot_attributed():
    data = snapshot()
    data["daily_financing"] = [{"id": "110", "type": "DAILY_FINANCING", "instrument": "NAS100_USD", "time": "2020-09-24T21:00:00Z",
                               "financing": "-8", "openTradeFinancings": [{"tradeID": "another", "financing": "-8"}]}]
    data["dividend_adjustments"] = [{"id": "111", "type": "DIVIDEND_ADJUSTMENT", "instrument": "NAS100_USD", "time": "2020-09-24T21:30:00Z",
                                    "dividendAdjustment": "2", "openTradeDividendAdjustments": [{"tradeID": "another", "dividendAdjustment": "2"}]}]
    out = audit_cost_snapshot(data)
    assert out["daily_financing_instrument_events"] == 1 and out["dividend_instrument_events"] == 1
    assert all(r["bot_attribution"] == "not_established" for r in out["instrument_adjustment_checks_private"])
    assert Decimal(out["fill_cost_checks_private"][1]["reported_fill_cash_components_usd_private"]) == 795


@pytest.mark.parametrize("mutation", ["currency", "duplicate", "negative_commission", "nonfinite", "nested_financing", "wrong_day"])
def test_invalid_or_inconsistent_evidence_fails_closed(mutation):
    data = snapshot()
    if mutation == "currency":
        data["account_currency"] = "EUR"
    elif mutation == "duplicate":
        data["fills"].append(deepcopy(data["fills"][0]))
    elif mutation == "negative_commission":
        data["fills"][0]["commission"] = "-2"
    elif mutation == "nonfinite":
        data["fills"][0]["commission"] = "NaN"
    elif mutation == "nested_financing":
        data["fills"][1]["tradesClosed"][0]["financing"] = "-9"
    elif mutation == "wrong_day":
        data["fills"][0]["time"] = "2020-09-25T14:23:03Z"
    with pytest.raises(CostAuditError):
        audit_cost_snapshot(data)


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", "not-money", {}])
def test_money_parser_refuses_nonfinite_or_unsupported_types(value):
    with pytest.raises(CostAuditError):
        number(value)
