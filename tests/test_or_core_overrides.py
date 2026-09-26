"""Old mid-price CSV research API must apply overrides, not merely label sweeps."""

from pathlib import Path
import json

import pandas as pd
import pytest

from src import or_core

DAY = "2026-09-24"


def historical_day():
    index = pd.DatetimeIndex([pd.Timestamp(f"{DAY} {t}", tz="America/New_York")
                              for t in ("09:30", "10:00", "10:22", "10:23", "10:24", "12:00")])
    win = pd.DataFrame({"high": [110, 110, 105, 105, 150, 103],
                        "low": [90, 90, 100, 99, 89, 100],
                        "close": [100, 100, 105, 100, 100, 102]}, index=index)
    opening_range = win.loc[win.index.time <= pd.Timestamp("10:00").time()]
    qc = {"or_high": 110, "or_low": 90, "or_range": 20,
          "has_entry_1022": True, "has_exit_1200": True}
    return win, opening_range, qc


def test_historical_execute_day_applies_sl_tp_zone_and_entry_without_mutating_globals(monkeypatch):
    win, opening_range, qc = historical_day()
    monkeypatch.setattr(or_core, "load_day_window", lambda day, *, entry_time=None: (win, opening_range, qc))
    previous = (or_core.ENTRY_T, or_core.TOP_PCT, or_core.BOT_PCT, or_core.SL_PTS, or_core.TP_PTS)
    baseline = or_core.execute_day(DAY)
    assert baseline.decision == "long" and baseline.exit_reason == "time"
    take40 = or_core.execute_day(DAY, tp_pts=40)
    stop15 = or_core.execute_day(DAY, sl_pts=15)
    strict_zone = or_core.execute_day(DAY, top_pct=.1)
    delayed = or_core.execute_day(DAY, entry_time="10:23")
    assert take40.exit_reason == "tp" and take40.tp == 145 and take40.pnl_pts == 40
    assert stop15.exit_reason == "sl" and stop15.sl == 90 and stop15.pnl_pts == -15
    assert strict_zone.decision == "none" and strict_zone.pnl_usd == 0
    assert delayed.decision == "none" and delayed.entry_time == "10:23"
    assert (or_core.ENTRY_T, or_core.TOP_PCT, or_core.BOT_PCT, or_core.SL_PTS, or_core.TP_PTS) == previous
    assert or_core.execute_day(DAY).exit_reason == baseline.exit_reason


def test_historical_short_zone_and_risk_override(monkeypatch):
    win, opening_range, qc = historical_day()
    win.loc[win.index.time == pd.Timestamp("10:22").time(), "close"] = 95
    monkeypatch.setattr(or_core, "load_day_window", lambda day, *, entry_time=None: (win, opening_range, qc))
    short = or_core.execute_day(DAY, sl_pts=15, tp_pts=30)
    assert short.decision == "short" and short.sl == 110 and short.tp == 65
    assert or_core.execute_day(DAY, bot_pct=.1).decision == "none"
    with pytest.raises(ValueError, match="Invalid entry"):
        or_core.execute_day(DAY, entry_time="10:00")  # within inclusive OR window


def test_notebook4_no_global_entry_mutation_and_explicit_override_call():
    notebook = json.loads((Path(__file__).resolve().parents[1] / "notebooks" / "04_parameter_robustness.ipynb").read_text(encoding="utf-8"))
    code = "\n".join("".join(c.get("source", [])) for c in notebook["cells"] if c["cell_type"] == "code")
    assert all(not c.get("outputs") for c in notebook["cells"] if c["cell_type"] == "code")
    assert "or_core.ENTRY_T =" not in code
    assert "temporary_strategy_overrides(" not in code
    assert "sl_pts=sl_pts, tp_pts=tp_pts" in code
    assert "10:00" not in next(line for line in code.splitlines() if line.startswith("ENTRY_GRID"))
