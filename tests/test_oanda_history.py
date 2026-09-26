"""Read-only bounded OANDA historical quotes; synthetic dates/prices, never an account."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import pytest

from scripts.research import export_oanda_history as history
from scripts.research.export_oanda_research import OUTPUT_ROOT, ResearchDownloadError
from src.research_history import HistoryAuditError, audit_day, audit_range

NY = ZoneInfo("America/New_York")
DAY = date(2020, 9, 24)


def sample(day=DAY):
    start = datetime.combine(day, datetime.strptime("09:30", "%H:%M").time(), tzinfo=NY)
    records = []
    for n in range(151):
        ts = (start + timedelta(minutes=n)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".000000000Z"
        records.append({"time": ts, "complete": True,
                        "bid": {"o": "99", "h": "100", "l": "98", "c": "99"},
                        "mid": {"o": "100", "h": "101", "l": "99", "c": "100"},
                        "ask": {"o": "101", "h": "102", "l": "100", "c": "101"}})
    return records


def test_audit_m1_three_sided_coverage_and_dst():
    assert audit_day(DAY, sample())["status"] == "complete"
    assert audit_day(date(2020, 1, 15), sample(date(2020, 1, 15)))["status"] == "complete"
    assert audit_day(date(2024, 3, 8), sample(date(2024, 3, 8)))["status"] == "complete"
    assert audit_day(date(2024, 3, 11), sample(date(2024, 3, 11)))["status"] == "complete"
    assert audit_day(DAY, [])["status"] == "no_session_data"  # unknown holiday ≠ no trade
    result = audit_range({DAY.isoformat(): sample()})
    assert result["summary"]["complete"] == 1 and result["summary"]["returned_candles"] == 151


def test_audit_flags_gaps_duplicates_invalid_quotes_and_incomplete_bars():
    rows = sample()
    rows.pop(52)  # the completed 10:22 signal candle
    rows += [rows[0].copy()]  # duplicate 09:30
    rows[1]["complete"] = False
    rows[2]["bid"]["o"] = "200"  # impossible > high, input is separate per test
    result = audit_day(DAY, rows)
    assert result["status"] == "incomplete"
    assert (result["missing_session_minutes"], result["duplicate_session_minutes"],
            result["incomplete_session_bars"], result["invalid_bid_ask_mid_bars"]) == (1, 1, 1, 1)
    with pytest.raises(HistoryAuditError, match="timestamp"):
        audit_day(DAY, [{"time": "secret://not-a-date"}])
    with pytest.raises(HistoryAuditError, match="weekend"):
        audit_range({"2020-09-26": []})


def test_range_hard_budget_and_year_bounds_before_authentication():
    assert len(history.request_days(date(2020, 9, 21), date(2020, 9, 25), 5)) == 5
    for start, end, budget in ((date(2020, 9, 21), date(2020, 10, 9), 10),
                               (date(2019, 1, 1), date(2019, 1, 1), 1),
                               (date(2025, 1, 1), date(2025, 1, 1), 1),
                               (date(2020, 9, 21), date(2020, 9, 25), 4),
                               (date(2020, 9, 21), date(2020, 9, 21), 11)):
        with pytest.raises(ResearchDownloadError):
            history.request_days(start, end, budget)


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response, self.calls, self.headers = response, [], {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_reader_calls_only_practice_candles_once_never_follows_redirect():
    reader = history.HistoryReader("fake-token-never-print")
    session = FakeSession(Response(payload={"instrument": "NAS100_USD", "granularity": "M1", "candles": sample()}))
    reader.session = session
    assert len(reader.candles(DAY)) == 151
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "https://api-fxpractice.oanda.com/v3/instruments/NAS100_USD/candles"
    assert kwargs["allow_redirects"] is False and kwargs["timeout"] == 20
    assert kwargs["params"]["price"] == "MBA" and kwargs["params"]["smooth"] == "false"
    assert kwargs["params"]["granularity"] == "M1"
    reader.session = FakeSession(Response(status=301))
    with pytest.raises(ResearchDownloadError, match="HTTP 301"):
        reader.candles(DAY)
    assert len(reader.session.calls) == 1  # no retry even on failure
    reader.session = FakeSession(Response(payload={"instrument": "EUR_USD", "granularity": "M1", "candles": []}))
    with pytest.raises(ResearchDownloadError, match="mismatch"):
        reader.candles(DAY)


def test_cli_dry_run_never_loads_credentials_or_makes_requests(monkeypatch, capsys):
    monkeypatch.setattr(history, "credentials", lambda: pytest.fail("Dry run must not load a token"))
    monkeypatch.setattr(history, "HistoryReader", lambda _: pytest.fail("Dry run must not use HTTP"))
    monkeypatch.setattr("sys.argv", ["export_oanda_history.py", "--start", "2021-09-13",
                                      "--end", "2021-09-17", "--max-requests", "5"])
    assert history.main() == 0
    assert "zero HTTP" in capsys.readouterr().out


def test_private_batch_is_atomic_hash_verified_and_never_overwritten(monkeypatch):
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUTPUT_ROOT, prefix=".pytest-history-") as directory:
        monkeypatch.setattr(history, "HISTORY_ROOT", Path(directory))
        class FakeReader:
            calls = 0
            def candles(self, day):
                self.calls += 1
                return sample(day)
        reader = FakeReader()
        folder, summary = history.fetch(DAY, DAY, 1, reader)
        assert summary["complete"] == reader.calls == 1
        assert list(sorted(p.name for p in folder.iterdir())) == ["candles.json", "provenance.json"]
        saved = (folder / "provenance.json").read_text(encoding="utf-8")
        assert "Authorization" not in saved and "accountID" not in saved and "/accounts/" not in saved
        assert history.audit_existing(folder.name)[1] == summary
        with pytest.raises(ResearchDownloadError, match="already exists"):
            history.fetch(DAY, DAY, 1, reader)
        assert reader.calls == 1
        (folder / "candles.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ResearchDownloadError, match="checksum"):
            history.audit_existing(folder.name)


def test_failed_second_get_leaves_no_partial_private_batch(monkeypatch):
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUTPUT_ROOT, prefix=".pytest-history-") as directory:
        monkeypatch.setattr(history, "HISTORY_ROOT", Path(directory))
        monkeypatch.setattr(history.time, "sleep", lambda _: None)
        class FailsOnSecondDay:
            calls = 0
            def candles(self, day):
                self.calls += 1
                if self.calls == 2:
                    raise ResearchDownloadError("Synthetic GET failure")
                return sample(day)
        reader = FailsOnSecondDay()
        with pytest.raises(ResearchDownloadError, match="Synthetic GET failure"):
            history.fetch(DAY, DAY + timedelta(days=1), 2, reader)
        assert reader.calls == 2 and not list(Path(directory).iterdir())
