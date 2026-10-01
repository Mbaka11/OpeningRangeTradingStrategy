"""Budgeted practice cost reader: fake GETs only, never credentials or broker orders."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile

import pytest
import requests

from scripts.research import export_oanda_cost_evidence as cli
from scripts.research.export_oanda_research import OUTPUT_ROOT, ResearchDownloadError, sanitize_fill
from src.research_costs import audit_cost_snapshot

DAY = date(2020, 9, 24)
ACCOUNT = "fake-account"
PAGE = f"https://api-fxpractice.oanda.com/v3/accounts/{ACCOUNT}/transactions/idrange?from=100&to=199"


def instrument():
    return {"name": "NAS100_USD", "type": "CFD", "tradeUnitsPrecision": 0,
            "minimumTradeSize": "1", "maximumOrderUnits": "1000", "accountID": "NEVER_SAVE_ACCOUNT",
            "commission": {"commission": "0", "unitsTraded": "1000", "minimumCommission": "0", "secret": "NEVER_SAVE"}}


def fills():
    return [
        {"id": "100", "type": "ORDER_FILL", "instrument": "NAS100_USD", "time": "2020-09-24T14:23:03Z", "reason": "MARKET_ORDER",
         "pl": "0", "financing": "0", "commission": "0", "guaranteedExecutionFee": "0", "halfSpreadCost": "1",
         "accountID": "NEVER_SAVE_ACCOUNT", "accountBalance": "NEVER_SAVE_BALANCE", "userID": "NEVER_SAVE_USER",
         "tradeOpened": {"tradeID": "100", "price": "100", "units": "80", "halfSpreadCost": "1", "guaranteedExecutionFee": "0", "clientExtensions": {"id": "NEVER_SAVE"}}},
        {"id": "101", "type": "ORDER_FILL", "instrument": "NAS100_USD", "time": "2020-09-24T16:00:03Z", "reason": "MARKET_ORDER_TRADE_CLOSE",
         "pl": "800", "financing": "0", "commission": "0", "guaranteedExecutionFee": "0", "halfSpreadCost": "1",
         "tradesClosed": [{"tradeID": "100", "price": "110", "units": "80", "realizedPL": "800", "financing": "0",
                            "guaranteedExecutionFee": "0", "halfSpreadCost": "1"}]}
    ]


class Response:
    def __init__(self, data=None, status=200, invalid=False):
        self.status_code, self.data, self.invalid = status, data, invalid
    def json(self):
        if self.invalid:
            raise ValueError("NEVER_PRINT_RESPONSE")
        return deepcopy(self.data)


class Session:
    def __init__(self):
        self.calls, self.status, self.pages, self.closed = [], 200, [PAGE], False
        self.transactions = fills()
        self.currency = "USD"
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.status != 200:
            return Response(status=self.status)
        if url.endswith("/summary"):
            return Response({"account": {"currency": self.currency, "id": "NEVER_SAVE_ACCOUNT", "balance": "NEVER_SAVE_BALANCE", "alias": "NEVER_SAVE_ALIAS"}})
        if url.endswith("/instruments"):
            return Response({"instruments": [instrument()]})
        if url.endswith("/transactions"):
            return Response({"pages": self.pages})
        return Response({"transactions": self.transactions})
    def post(self, *a, **k):
        pytest.fail("No POST allowed")
    def put(self, *a, **k):
        pytest.fail("No PUT allowed")
    def close(self):
        self.closed = True


def reader():
    obj = cli.CostReader(ACCOUNT, "fake-token-never-print")
    obj.session = Session()
    return obj


def test_bearer_and_direct_routing_cannot_be_overridden_by_ambient_netrc_or_proxies(monkeypatch):
    monkeypatch.setattr("requests.sessions.get_netrc_auth", lambda *a: pytest.fail("No ambient .netrc access"))
    monkeypatch.setenv("HTTPS_PROXY", "https://untrusted-proxy.invalid")
    obj = cli.CostReader(ACCOUNT, "synthetic-bearer")
    try:
        prepared = obj.session.prepare_request(requests.Request("GET", obj.base + "/summary"))
        assert prepared.headers["Authorization"] == "Bearer synthetic-bearer"
        settings = obj.session.merge_environment_settings(prepared.url, {}, None, True, None)
        assert not settings["proxies"] and settings["verify"] is True
        assert obj.session.trust_env is False
        assert obj.session.get_adapter("https://").max_retries.total == 0
    finally:
        obj.session.close()


def test_reader_uses_four_allowed_gets_and_sanitizes_account_and_balance_fields():
    obj = reader()
    snapshot = obj.snapshot(DAY, DAY)
    assert obj.requests_used == 4
    assert "NEVER_SAVE" not in json.dumps(snapshot)
    assert not any(k in json.dumps(snapshot) for k in ("accountBalance", "userID", "clientExtensions"))
    assert all(c[1]["allow_redirects"] is False for c in obj.session.calls)
    assert all(c[0].startswith("https://api-fxpractice.oanda.com/v3/accounts/fake-account/") for c in obj.session.calls)
    assert obj.session.calls[1][1]["params"] == {"instruments": "NAS100_USD"}
    assert "type" not in obj.session.calls[2][1]["params"]  # retain newer dividends not in old Filter enum
    cli.compare_prior(snapshot["fills"], [sanitize_fill(r) for r in fills()])
    assert audit_cost_snapshot(snapshot)["recent_fill_records"] == 2


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500, 503])
def test_http_failure_or_redirect_never_retries_or_discloses_payload(status):
    obj = reader()
    obj.session.status = status
    with pytest.raises(ResearchDownloadError) as e:
        obj.snapshot(DAY, DAY)
    assert obj.requests_used == len(obj.session.calls) == 1
    assert "fake-token" not in str(e.value) and "NEVER_SAVE" not in str(e.value)


def test_timeout_counts_one_attempt_and_does_not_retry():
    obj = reader()
    def fails(*a, **k):
        raise requests.Timeout("NEVER_PRINT_URL_OR_TOKEN")
    obj.session.get = fails
    with pytest.raises(ResearchDownloadError) as e:
        obj.snapshot(DAY, DAY)
    assert obj.requests_used == 1 and "NEVER_PRINT" not in str(e.value)


def test_eight_request_ceiling_counts_gets_and_blocks_ninth_before_http():
    obj = reader()
    for _ in range(8):
        obj.get(obj.base + "/summary")
    with pytest.raises(ResearchDownloadError, match="budget"):
        obj.get(obj.base + "/summary")
    assert obj.requests_used == len(obj.session.calls) == 8


@pytest.mark.parametrize("url", [
    "https://api-fxtrade.oanda.com/v3/accounts/fake-account/summary",
    "https://evil.example/v3/accounts/fake-account/summary",
    "https://api-fxpractice.oanda.com/v3/accounts/other-account/summary",
    "https://api-fxpractice.oanda.com/v3/accounts/fake-account/orders",
    "https://api-fxpractice.oanda.com/v3/accounts/fake-account/trades/1/close",
    PAGE + "&redirect=evil", PAGE.replace("from=100", "from=abc"), PAGE + "&from=1",
    PAGE.replace("idrange?", "idrange;unexpected?"),
])
def test_host_path_query_allowlist_blocks_before_any_request(url):
    obj = reader()
    with pytest.raises(ResearchDownloadError):
        obj.get(url)
    assert obj.requests_used == 0 and obj.session.calls == []


@pytest.mark.parametrize("pages", [[PAGE] * 2, [PAGE.replace("100", str(n)) for n in range(6)]])
def test_excess_or_duplicate_pages_stops_before_page_download(pages):
    obj = reader()
    obj.session.pages = pages
    with pytest.raises(ResearchDownloadError):
        obj.snapshot(DAY, DAY)
    assert obj.requests_used == len(obj.session.calls) == 3


def test_non_usd_currency_stops_after_summary_without_assuming_dollar_point_mapping():
    obj = reader()
    obj.session.currency = "EUR"
    with pytest.raises(ResearchDownloadError, match="USD"):
        obj.snapshot(DAY, DAY)
    assert obj.requests_used == 1


def test_filters_foreign_fills_and_allocates_only_instrument_adjustments():
    obj = reader()
    obj.session.transactions.extend([
        {"id": "102", "type": "ORDER_FILL", "instrument": "EUR_USD", "time": "2020-09-24T14:23:03Z", "accountID": "NEVER_SAVE"},
        {"id": "103", "type": "DAILY_FINANCING", "time": "2020-09-24T21:00:00Z", "financing": "-900",
         "positionFinancings": [{"instrument": "EUR_USD", "financing": "-892"},
                                {"instrument": "NAS100_USD", "financing": "-8", "openTradeFinancings": [{"tradeID": "another", "financing": "-8"}]}]},
        {"id": "104", "type": "DIVIDEND_ADJUSTMENT", "instrument": "NAS100_USD", "time": "2020-09-24T21:00:00Z", "dividendAdjustment": "2",
         "openTradeDividendAdjustments": [{"tradeID": "another", "dividendAdjustment": "2"}]},
        {"id": "105", "type": "DAILY_FINANCING", "time": "2020-09-24T21:00:00Z", "financing": "-10"},
        {"id": "106", "type": "TRANSFER_FUNDS", "time": "2020-09-24T21:00:00Z", "amount": "NEVER_SAVE"},
        {"id": "107", "type": "ORDER_FILL", "instrument": "NAS100_USD", "time": "2020-09-23T23:00:00Z", "tradeOpened": {"secret": "NEVER_SAVE"}},
    ])
    snapshot = obj.snapshot(DAY, DAY)
    assert len(snapshot["fills"]) == 2
    assert snapshot["daily_financing"][0]["financing"] == "-8"
    assert len(snapshot["dividend_adjustments"]) == 1
    assert snapshot["unattributed_daily_financing_count"] == 1
    assert "-900" not in json.dumps(snapshot) and "EUR_USD" not in json.dumps(snapshot)
    assert "NEVER_SAVE" not in json.dumps(snapshot)
    out = audit_cost_snapshot(snapshot)
    assert out["instrument_adjustment_checks_private"][0]["bot_attribution"] == "not_established"


def test_exact_old_fill_comparison_refuses_new_or_changed_trade_fields():
    original = [sanitize_fill(r) for r in fills()]
    current = [cli.sanitize_cost_fill(r) for r in fills()]
    cli.compare_prior(current, original)
    current[0]["tradeOpened"]["units"] = "40"
    with pytest.raises(ResearchDownloadError, match="differ"):
        cli.compare_prior(current, original)


def test_bundle_is_atomic_ignored_hash_verified_and_offline_recomputed(monkeypatch):
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUTPUT_ROOT, prefix=".pytest-costs-") as tmp:
        root = Path(tmp)
        old = root / "2020-09-24_2020-09-24"
        old.mkdir()
        (old / "fills.json").write_text(json.dumps([sanitize_fill(r) for r in fills()]), encoding="utf8")
        monkeypatch.setattr(cli, "OUTPUT_ROOT", root)
        monkeypatch.setattr(cli, "COST_ROOT", root / "cost_evidence")
        _, _, prior, digest = cli.read_prior(old.name)
        obj = reader()
        snapshot = obj.snapshot(DAY, DAY)
        cli.compare_prior(snapshot["fills"], prior)
        report = audit_cost_snapshot(snapshot)
        folder = cli.save_bundle(snapshot, report, digest, old.name, 4)
        assert sorted(p.name for p in folder.iterdir()) == ["cost_audit.json", "provenance.json", "snapshot.json"]
        monkeypatch.setattr(cli, "credentials", lambda: pytest.fail("Offline audit cannot load credentials"))
        monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("Offline audit cannot use HTTP"))
        assert cli.audit_bundle(folder.name) == (folder, report)
        raw = (folder / "snapshot.json").read_text(encoding="utf8")
        assert "NEVER_SAVE" not in raw and "accountBalance" not in raw
        (folder / "snapshot.json").write_text("{}", encoding="utf8")
        with pytest.raises(ResearchDownloadError, match="checksum"):
            cli.audit_bundle(folder.name)


def test_cli_dry_run_does_not_load_credentials_http_or_write(monkeypatch, capsys):
    monkeypatch.setattr(cli, "read_prior", lambda _: (DAY, DAY, fills(), "synthetic"))
    monkeypatch.setattr(cli, "credentials", lambda: pytest.fail("Dry run cannot load credentials"))
    monkeypatch.setattr(cli, "CostReader", lambda *a: pytest.fail("Dry run cannot use HTTP"))
    monkeypatch.setattr(cli, "save_bundle", lambda *a: pytest.fail("Dry run cannot write"))
    monkeypatch.setattr("sys.argv", ["cost_evidence.py", "--folder", "2020-09-24_2020-09-24"])
    assert cli.main() == 0
    assert "zero HTTP" in capsys.readouterr().out


def test_failed_fetch_never_writes_bundle_or_discloses_credentials(monkeypatch, capsys):
    monkeypatch.setattr(cli, "read_prior", lambda _: (DAY, DAY, [sanitize_fill(r) for r in fills()], "synthetic"))
    monkeypatch.setattr(cli, "credentials", lambda: (ACCOUNT, "NEVER_PRINT_TOKEN", "NAS100_USD"))
    obj = reader()
    obj.session.status = 403
    monkeypatch.setattr(cli, "CostReader", lambda *a: obj)
    monkeypatch.setattr(cli, "save_bundle", lambda *a: pytest.fail("Failed fetch cannot write"))
    monkeypatch.setattr("sys.argv", ["cost_evidence.py", "--folder", "2020-09-24_2020-09-24", "--fetch"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 1 and obj.session.closed and obj.requests_used == 1
    err = capsys.readouterr().err
    assert "NEVER_PRINT_TOKEN" not in err and "fake-account" not in err
