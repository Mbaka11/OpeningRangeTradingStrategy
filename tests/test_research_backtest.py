"""Synthetic, offline-only parity/parameter-effect tests; no broker or X access."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pandas as pd

from opening_range_bot.run_bot import compute_signal
from scripts.research.audit_backtest_parity import audit, compare_cloud_balances
from scripts.research.export_oanda_research import ResearchDownloadError
from src.research_backtest import StrategyParams, run_session

NY = ZoneInfo("America/New_York")
DAY = "2026-09-24"


def day_bars(day=DAY, entry_close=105, or_high=110, or_low=90):
    """Complete NY 09:30–12:00 candles in OANDA MBA schema."""
    cursor = datetime.combine(date.fromisoformat(day), datetime.strptime("09:30", "%H:%M").time(), tzinfo=NY)
    result = []
    for _ in range(151):
        mid_high = or_high if cursor.strftime("%H:%M") == "09:30" else 100
        mid_low = or_low if cursor.strftime("%H:%M") == "09:30" else 100
        if cursor.strftime("%H:%M") == "10:22":
            mid_high = max(100, entry_close)
            mid_low = min(100, entry_close)
        result.append({
            "time": cursor.astimezone(timezone.utc).isoformat(), "complete": True,
            "mid": {"o": "100", "h": str(mid_high), "l": str(mid_low),
                    "c": str(entry_close if cursor.strftime("%H:%M") == "10:22" else 100)},
            "bid": {"o": "99", "h": "100", "l": "98", "c": "99"},
            "ask": {"o": "101", "h": "102", "l": "100", "c": "101"},
        })
        cursor += timedelta(minutes=1)
    return result


def at(bars, hhmm):
    return next(c for c in bars if datetime.fromisoformat(c["time"]).astimezone(NY).strftime("%H:%M") == hhmm)


def test_research_signal_matches_current_live_signal_on_same_completed_mid_candles():
    bars = day_bars()
    timestamps = [pd.Timestamp(x["time"]).tz_convert(NY) for x in bars]
    frame = pd.DataFrame({"time_ny": timestamps, "high": [float(x["mid"]["h"]) for x in bars],
                          "low": [float(x["mid"]["l"]) for x in bars],
                          "close": [float(x["mid"]["c"]) for x in bars],
                          "complete": [x["complete"] for x in bars]}, index=timestamps)
    opening = frame.between_time("09:30", "10:00", inclusive="both")
    old, reason = compute_signal(frame, opening)
    new = run_session(DAY, bars, StrategyParams())
    assert reason == new["side"] == old[0] == "long"
    assert new["signal"]["signal_price"] == old[1] == 105
    assert old[2:] == (80, 180)  # live levels from signal; offline fill may differ


def test_next_bar_bid_ask_entry_and_noon_open():
    res = run_session(DAY, day_bars(), StrategyParams())
    assert res["side"] == "long" and res["entry_price"] == 101
    assert res["sl_price"] == 76 and res["tp_price"] == 176
    assert res["exit_reason"] == "time"
    assert res["exit_price"] == 99
    assert res["gross_points"] == -2 and res["net_usd"] == -160


def test_target_parameter_changes_exit_not_just_label():
    bars = day_bars()
    at(bars, "10:25")["bid"]["h"] = "145"
    at(bars, "10:26")["bid"]["l"] = "75"
    base = run_session(DAY, bars, StrategyParams())
    early = run_session(DAY, bars, replace(StrategyParams(), take_profit_points=40))
    assert base["exit_reason"] == "sl" and base["gross_points"] == -25
    assert early["exit_reason"] == "tp" and early["gross_points"] == 40
    assert early["exit_minute"] != base["exit_minute"]


def test_stop_parameter_changes_actual_exit():
    bars = day_bars()
    at(bars, "10:24")["bid"]["l"] = "90"
    at(bars, "10:25")["bid"]["h"] = "177"
    base = run_session(DAY, bars, StrategyParams())
    tight = run_session(DAY, bars, replace(StrategyParams(), stop_loss_points=10))
    assert base["exit_reason"] == "tp" and base["gross_points"] == 75
    assert tight["exit_reason"] == "sl" and tight["gross_points"] == -10


def test_zone_and_entry_time_parameters_change_signal():
    bars = day_bars()
    assert run_session(DAY, bars, StrategyParams())["status"] == "trade"
    strict = run_session(DAY, bars, replace(StrategyParams(), top_pct=.10))
    later = run_session(DAY, bars, replace(StrategyParams(), entry_time="10:23"))
    assert strict["status"] == "no_trade"
    assert later["status"] == "no_trade"
    assert strict["signal"]["top_cut"] == 108
    short = day_bars(entry_close=95)
    assert run_session(DAY, short, StrategyParams())["side"] == "short"
    assert run_session(DAY, short, replace(StrategyParams(), bottom_pct=.10))["status"] == "no_trade"


def test_short_barriers_are_ask_only_and_ties_are_adverse():
    bars = day_bars(entry_close=95)
    at(bars, "10:24")["bid"]["l"] = "10"  # impossible TP: short closes at ask
    assert run_session(DAY, bars, StrategyParams())["exit_reason"] == "time"
    at(bars, "10:24")["ask"]["l"] = "24"  # entry bid=99, TP=24
    assert run_session(DAY, bars, StrategyParams())["exit_reason"] == "tp"
    at(bars, "10:24")["ask"]["h"] = "124" # entry bid=99, SL=124
    tied = run_session(DAY, bars, StrategyParams())
    assert tied["exit_reason"] == "sl" and tied["ambiguous_same_bar"] is True


def test_slippage_size_fees_and_time_exit_parameter():
    bars = day_bars()
    base = run_session(DAY, bars, StrategyParams())
    changed = run_session(DAY, bars, replace(StrategyParams(), units=40, entry_slippage_points=1,
                                             exit_slippage_points=1, commission_per_side_usd=3,
                                             exit_time="11:15"))
    assert base["exit_minute"].endswith("12:00:00-04:00")
    assert changed["exit_minute"].endswith("11:15:00-04:00")
    assert changed["entry_price"] == 102 and changed["exit_price"] == 98
    assert changed["gross_points"] == -4 and changed["gross_usd"] == -160
    assert changed["net_usd"] == -166


def test_missing_duplicate_and_incomplete_day_are_excluded_not_zero_pnl():
    bars = day_bars()
    for missing in (bars[:5] + bars[6:], bars + [bars[0]], bars[:30] + bars[31:]):
        res = run_session(DAY, missing, StrategyParams())
        assert res["status"] == "excluded" and "net_usd" not in res
    bars = day_bars()
    at(bars, "11:40")["complete"] = False
    assert run_session(DAY, bars, StrategyParams())["status"] == "excluded"
    bars = day_bars()
    del at(bars, "10:23")["ask"]["o"]
    assert run_session(DAY, bars, StrategyParams())["reason"] == "missing_bid_ask_or_mid_ohlc"


def test_broker_point_value_and_account_balance_reconciliation():
    bars = day_bars()
    at(bars, "10:24")["bid"]["h"] = "177"
    fills = [
        {"id": "2", "time": "2026-09-24T14:23:05Z", "instrument": "NAS100_USD",
         "reason": "MARKET_ORDER", "tradeOpened": {"tradeID": "abc", "price": "101", "units": "80"}},
        {"id": "3", "time": "2026-09-24T14:24:15Z", "instrument": "NAS100_USD",
         "reason": "TAKE_PROFIT_ORDER", "tradesClosed": [{"tradeID": "abc", "price": "176",
                                                 "units": "80", "realizedPL": "6000"}]},
    ]
    report = audit({DAY: bars, "2026-09-25": day_bars(day="2026-09-25", entry_close=100)}, fills, StrategyParams())
    assert report["summary"]["signal_comparison"] == {"match": 2}
    assert report["summary"]["broker_pl_check"] == {"match": 1}
    assert report["summary"]["exit_reason_comparison"] == {"same_reason": 1}
    entries = [
        {"textPayload": "SESSION_END date=2026-09-24 signals=1 orders=1 nav 100->6100 bal 100->6100 (+6000.00)"},
        {"textPayload": "SESSION_END date=2026-09-25 signals=0 orders=0 nav 6100->6100 bal 6100->6100 (+0.00)"},
    ]
    results = compare_cloud_balances(entries, report)
    assert [r["status"] for r in results] == ["match", "match"]
    entries[0]["textPayload"] = entries[0]["textPayload"].replace("6100 (+6000.00)", "6101 (+6001.00)")
    assert compare_cloud_balances(entries, report)[0]["status"] == "mismatch"
    with pytest.raises(ResearchDownloadError, match="No matching"):
        compare_cloud_balances([], report)


def test_ny_timezone_handles_dst_and_parameter_validation():
    result = run_session("2026-03-09", day_bars(day="2026-03-09"), StrategyParams())
    assert result["entry_minute"].endswith("10:23:00-04:00")
    with pytest.raises(ValueError, match="Overlapping"):
        StrategyParams(top_pct=.6, bottom_pct=.5)
    with pytest.raises(ValueError, match="hard exit"):
        StrategyParams(exit_time="12:30")
    with pytest.raises(ValueError, match="positive"):
        StrategyParams(take_profit_points=0)
