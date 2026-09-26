"""Full-year collection remains practice-GET-only, strictly bounded, resumable."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import pytest

from scripts.research import backfill_oanda_history as bulk
from scripts.research import export_oanda_history as history
from scripts.research.audit_oanda_history_baseline import build_baseline
from scripts.research.export_oanda_research import OUTPUT_ROOT, ResearchDownloadError
from src.research_backtest import StrategyParams

NY = ZoneInfo("America/New_York")


def sample(day):
    start = datetime.combine(day, datetime.strptime("09:30", "%H:%M").time(), tzinfo=NY)
    records = []
    for n in range(151):
        ts = (start + timedelta(minutes=n)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".000000000Z"
        records.append({"time": ts, "complete": True,
                        "mid": {"o": "100", "h": "100", "l": "100", "c": "100"},
                        "bid": {"o": "99", "h": "99", "l": "99", "c": "99"},
                        "ask": {"o": "101", "h": "101", "l": "101", "c": "101"}})
    return records


class FakeReader:
    def __init__(self):
        self.calls = []
    def candles(self, day):
        self.calls.append(day)
        return sample(day)


def test_group_only_consecutive_weekdays_and_never_cross_existing_pilot():
    assert bulk.next_weekday(date(2020, 1, 3)) == date(2020, 1, 6)  # Fri -> Mon
    assert bulk.batches_for_days([date(2020, 1, 1), date(2020, 1, 3), date(2020, 1, 6)]) == [
        [date(2020, 1, 1)], [date(2020, 1, 3), date(2020, 1, 6)]]
    assert history.request_days(date(2020, 1, 3), date(2020, 1, 6), 2) == [date(2020, 1, 3), date(2020, 1, 6)]


def test_restart_skips_pilot_and_respects_total_request_budget(monkeypatch):
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUTPUT_ROOT, prefix=".pytest-backfill-") as directory:
        monkeypatch.setattr(history, "HISTORY_ROOT", Path(directory))
        monkeypatch.setattr(bulk.time, "sleep", lambda _: None)
        pilot = FakeReader()
        history.fetch(date(2020, 1, 2), date(2020, 1, 2), 1, pilot)
        reader = FakeReader()
        attempted, index = bulk.backfill(2020, 3, reader)
        assert attempted == 3 and reader.calls == [date(2020, 1, 1), date(2020, 1, 3), date(2020, 1, 6)]
        assert index["years"]["2020"]["weekdays_downloaded"] == 4
        assert index["years"]["2020"]["not_downloaded"] == len(bulk.weekdays(2020)) - 4
        assert (Path(directory) / "index.json").is_file()
        reader2 = FakeReader()
        attempted, updated = bulk.backfill(2020, 2, reader2)
        assert attempted == 2 and reader2.calls == [date(2020, 1, 7), date(2020, 1, 8)]
        assert updated["years"]["2020"]["weekdays_downloaded"] == 6
        assert len(set(pilot.calls + reader.calls + reader2.calls)) == 6


def test_audited_batches_rejects_duplicate_day_across_folders(monkeypatch):
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUTPUT_ROOT, prefix=".pytest-backfill-") as directory:
        monkeypatch.setattr(history, "HISTORY_ROOT", Path(directory))
        history.fetch(date(2020, 1, 2), date(2020, 1, 2), 1, FakeReader())
        history.fetch(date(2020, 1, 1), date(2020, 1, 2), 2, FakeReader())
        with pytest.raises(ResearchDownloadError, match="duplicated"):
            bulk.audited_batches()


def test_offline_historical_baseline_preserves_missing_days_as_exclusions():
    trade_day, flat_day, absent = date(2020, 1, 15), date(2020, 1, 16), date(2020, 1, 17)
    trade, flat = sample(trade_day), sample(flat_day)
    for bars in (trade, flat):
        bars[0]["mid"].update({"h": "110", "l": "90"})
    trade[52]["mid"].update({"h": "105", "c": "105"})  # completed 10:22 top-zone signal
    days = {trade_day.isoformat(): trade, flat_day.isoformat(): flat, absent.isoformat(): []}
    quality = {trade_day.isoformat(): "complete", flat_day.isoformat(): "complete",
               absent.isoformat(): "no_session_data"}
    report = build_baseline(days, quality, StrategyParams())
    assert (report["by_year"]["2020"]["trade"], report["by_year"]["2020"]["no_trade"],
            report["by_year"]["2020"]["excluded"]) == (1, 1, 1)
    assert report["daily_hypothetical"][absent.isoformat()]["reason"] == "quote_no_session_data"
    with pytest.raises(ResearchDownloadError, match="dates differ"):
        build_baseline(days, {flat_day.isoformat(): "complete"}, StrategyParams())


def test_year_dry_run_does_not_load_token_or_make_http(monkeypatch, capsys):
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUTPUT_ROOT, prefix=".pytest-backfill-") as directory:
        monkeypatch.setattr(history, "HISTORY_ROOT", Path(directory))
        monkeypatch.setattr(bulk, "credentials", lambda: pytest.fail("dry-run cannot read token"))
        monkeypatch.setattr(bulk.history, "HistoryReader", lambda _: pytest.fail("dry-run cannot call API"))
        monkeypatch.setattr("sys.argv", ["backfill_oanda_history.py", "--year", "2020", "--max-requests", "262"])
        assert bulk.main() == 0
        assert "ZERO HTTP" in capsys.readouterr().out
    with pytest.raises(ResearchDownloadError):
        bulk.weekdays(2019)
