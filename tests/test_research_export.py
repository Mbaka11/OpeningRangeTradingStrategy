"""Offline-only tests. No real HTTP, orders, X posts or production job executions."""
from datetime import date, datetime, timezone
import json
import pytest

from scripts import export_oanda_research as exporter
from scripts.export_oanda_research import (
    PracticeReader, ResearchDownloadError, _safe_page, sanitize_fill, validate_dates,
)
from src.research_parity import extract_trades, parse_time, reconcile, simulate_baseline


def test_oanda_nanosecond_timestamp_parses_without_moving_second():
    ts = parse_time("2026-09-24T14:23:03.843001005Z")
    assert ts.isoformat() == "2026-09-24T14:23:03.843001+00:00"


def candle(minute, bid_hi=102.0, bid_lo=100.0, ask_hi=103.0, ask_lo=101.0, complete=True):
    return {"time": f"2026-09-24T{minute}:00Z", "complete": complete,
            "bid": {"h": str(bid_hi), "l": str(bid_lo)},
            "ask": {"h": str(ask_hi), "l": str(ask_lo)}}


def opened(units="80", price="100"):
    return {"trade_id": "abc", "instrument": "NAS100_USD",
            "entry_time": "2026-09-24T14:23:05Z", "entry_price": price,
            "units": units, "closes": []}


def test_long_uses_bid_and_ignores_partial_entry_bar():
    trade = opened()
    path = [candle("14:23", bid_hi=200), candle("14:24", bid_hi=175)]
    assert simulate_baseline(trade, path)["reason"] == "tp"
    # A mid/ask high reaching 175 is NOT sufficient for a long take profit.
    assert simulate_baseline(trade, [candle("14:24", bid_hi=170, ask_hi=190)])["reason"] == "unknown"


def test_short_uses_ask_and_same_bar_tie_is_not_declared_profit():
    trade = opened(units="-80")
    assert simulate_baseline(trade, [candle("14:24", bid_lo=0, ask_lo=27)])["reason"] == "unknown"
    assert simulate_baseline(trade, [candle("14:24", ask_hi=125, ask_lo=25)])["detail"] == "ambiguous_same_bar"
    assert simulate_baseline(trade, [candle("14:24", ask_hi=105, ask_lo=25)])["reason"] == "tp"


def test_gaps_and_missing_quotes_are_not_parity_matches():
    trade = opened()
    assert simulate_baseline(trade, [candle("14:25", bid_hi=175)])["detail"] == "gap_or_incomplete_candle"
    assert simulate_baseline(trade, [candle("14:24", complete=False)])["reason"] == "unknown"
    assert simulate_baseline(trade, [{"time": "2026-09-24T14:24:00Z", "complete": True}])["detail"] == "missing_executable_quote"


def test_noon_candle_cannot_create_late_take_profit():
    trade = opened()
    # 2026-09-24 12:00 NY is 16:00Z. No prior barrier touches.
    path = [candle(f"{hour:02d}:{minute:02d}") for hour in (14, 15)
            for minute in range(24 if hour == 14 else 0, 60)]
    path.append(candle("16:00", bid_hi=175))
    assert simulate_baseline(trade, path)["reason"] == "time"


def test_closed_broker_trade_is_joined_by_trade_id_and_compared():
    txs = [
        {"id": "2", "time": "2026-09-24T14:23:05Z", "instrument": "NAS100_USD", "reason": "MARKET_ORDER",
         "tradeOpened": {"tradeID": "abc", "units": "80", "price": "100"}},
        {"id": "3", "time": "2026-09-24T14:24:22Z", "instrument": "NAS100_USD", "reason": "TAKE_PROFIT_ORDER",
         "tradesClosed": [{"tradeID": "abc", "units": "80", "price": "175", "realizedPL": "6000"}]},
    ]
    trades = extract_trades(txs)
    assert len(trades) == 1
    rows = reconcile(trades, {"2026-09-24": [candle("14:24", bid_hi=175)]}, "NAS100_USD")
    assert rows[0]["status"] == "match"
    assert rows[0]["observed_points"] == 75
    assert rows[0]["price_delta_points"] == 0
    txs[-1]["reason"] = "STOP_LOSS_ORDER"
    assert reconcile(extract_trades(txs), {"2026-09-24": [candle("14:24", bid_hi=175)]}, "NAS100_USD")[0]["status"] == "mismatch"


def test_partial_close_and_early_market_exit_remain_unresolved():
    trade = opened()
    trade["closes"] = [{"time": "2026-09-24T14:24:30Z", "price": "105", "units": "40",
                        "realized_pl": "200", "reason": "MARKET_ORDER"}]
    assert reconcile([trade], {"2026-09-24": []}, "NAS100_USD")[0]["detail"] == "partial_or_missing_close"
    trade["closes"][0]["units"] = "80"
    assert reconcile([trade], {"2026-09-24": []}, "NAS100_USD")[0]["detail"] == "unclassified_broker_exit"
    trade["closes"][0].update({"time": "2026-09-24T14:23:30Z", "reason": "STOP_LOSS_ORDER"})
    row = reconcile([trade], {"2026-09-24": []}, "NAS100_USD")[0]
    assert row["detail"] == "exit_inside_entry_minute"
    assert row["realized_pl"] == "200"  # actual broker P&L is still retained


def test_market_trade_close_at_noon_is_candidate_not_verified_bot_action():
    trade = opened()
    trade["closes"] = [{"time": "2026-09-24T16:00:20Z", "price": "110", "units": "80",
                        "realized_pl": "800", "reason": "MARKET_ORDER_TRADE_CLOSE"}]
    path = [candle(f"{hour:02d}:{minute:02d}") for hour in (14, 15)
            for minute in range(24 if hour == 14 else 0, 60)]
    rows = reconcile([trade], {"2026-09-24": path}, "NAS100_USD")
    assert rows[0]["status"] == "candidate_match"
    assert rows[0]["broker_reason"] == "time_candidate"


def test_practice_host_allowlist_and_bounds():
    validate_dates(date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26))
    with pytest.raises(ResearchDownloadError):
        validate_dates(date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 26))
    with pytest.raises(ResearchDownloadError):
        validate_dates(date(2026, 1, 1), date(2026, 9, 25), date(2026, 9, 26))
    assert _safe_page("https://api-fxpractice.oanda.com/v3/accounts/a/transactions/idrange?from=1&to=3", "a")
    for url in ("https://api-fxtrade.oanda.com/v3/accounts/a/transactions/idrange?from=1&to=3",
                "https://evil.example/v3/accounts/a/transactions/idrange?from=1&to=3"):
        with pytest.raises(ResearchDownloadError):
            _safe_page(url, "a")


def test_read_refuses_redirect_without_forwarding_auth():
    reader = PracticeReader("test-account", "test-token", "NAS100_USD")
    calls = []
    def redirect(url, **kwargs):
        calls.append(kwargs)
        class Response:
            status_code = 302
        return Response()
    reader.session.get = redirect
    with pytest.raises(ResearchDownloadError, match="HTTP 302"):
        reader.get("https://api-fxpractice.oanda.com/v3/instruments/NAS100_USD/candles")
    assert len(calls) == 1 and calls[0]["allow_redirects"] is False
    with pytest.raises(ResearchDownloadError, match="unexpected host"):
        reader.get("https://bad.example/v3/instruments/NAS100_USD/candles")
    assert len(calls) == 1


def test_fill_sanitizer_excludes_account_identifiers_and_response_payloads():
    tx = {"id": "1", "accountID": "PRIVATE", "time": "2026-09-24T14:23:05Z",
          "instrument": "NAS100_USD", "type": "ORDER_FILL", "reason": "MARKET_ORDER",
          "secret": "NEVER_SAVE", "tradeOpened": {"tradeID": "abc", "price": "100", "units": "80", "secret": "NEVER_SAVE"}}
    clean = sanitize_fill(tx)
    assert "PRIVATE" not in str(clean) and "NEVER_SAVE" not in str(clean)
    assert clean["tradeOpened"]["price"] == "100"


def test_recheck_uses_private_files_without_credentials_or_http(tmp_path, monkeypatch):
    folder = tmp_path / "2026-09-24_2026-09-24"
    folder.mkdir()
    (folder / "fills.json").write_text("[]", encoding="utf-8")
    (folder / "candles.json").write_text('{"2026-09-24": []}', encoding="utf-8")
    monkeypatch.setattr(exporter, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(exporter, "_safe_output", lambda _: None)  # temp test dir is outside Git
    monkeypatch.setattr(exporter, "credentials", lambda: pytest.fail("recheck must not load token"))
    out, counts = exporter.recheck(folder.name)
    assert out == folder and counts["trades"] == 0
    assert json.loads((folder / "parity.json").read_text(encoding="utf-8")) == []
    with pytest.raises(ResearchDownloadError):
        exporter.recheck("../../keys")


def test_live_environment_refused_without_disclosing_token(tmp_path, monkeypatch):
    env = tmp_path / "secret.env"
    env.write_text("OANDA_ENV=live\nOANDA_ACCOUNT_ID=dummy\nOANDA_API_TOKEN=DO_NOT_PRINT\nOANDA_INSTRUMENT=NAS100_USD\n", encoding="utf-8")
    monkeypatch.setenv("DOTENV_PATH", str(env))
    for name in ("OANDA_ENV", "OANDA_ACCOUNT_ID", "OANDA_API_TOKEN", "OANDA_INSTRUMENT"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ResearchDownloadError, match="must explicitly equal practice") as error:
        exporter.credentials()
    assert "DO_NOT_PRINT" not in str(error.value)


def test_transaction_pagination_is_get_only_and_filters_instrument_and_date():
    reader = PracticeReader("test-account", "test-token", "NAS100_USD")
    base = "https://api-fxpractice.oanda.com/v3/accounts/test-account/transactions/idrange?from=1&to=4"
    calls = []
    def fake_get(url, params=None, **kwargs):
        calls.append((url, params, kwargs))
        class Response:
            status_code = 200
            def json(self):
                if url == base:
                    return {"transactions": [
                        {"type": "ORDER_FILL", "id": "2", "time": "2026-09-24T14:23:05Z",
                         "instrument": "NAS100_USD", "reason": "MARKET_ORDER"},
                        {"type": "ORDER_FILL", "id": "3", "time": "2026-09-24T14:23:05Z",
                         "instrument": "EUR_USD", "reason": "MARKET_ORDER"}]}
                return {"pages": [base]}
        return Response()
    reader.session.get = fake_get
    fills = reader.fills(date(2026, 9, 24), date(2026, 9, 24))
    assert len(fills) == 1 and fills[0]["id"] == "2"
    assert all(call[2]["allow_redirects"] is False for call in calls)
    assert all(call[0].startswith("https://api-fxpractice.oanda.com/v3/") for call in calls)
