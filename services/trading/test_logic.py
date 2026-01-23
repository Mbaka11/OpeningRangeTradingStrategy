"""
Tests for strategy logic parity between Live and Replay.
Run with: pytest services/trading/test_logic.py
"""
import sys
from pathlib import Path
import pandas as pd
import pytest
from datetime import date
import pytz

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from services.trading.run_bot import compute_signal, check_or_completeness

# Mock configuration constants for the test
ENTRY_TIME_STR = "10:22"
ENTRY_TIME = pd.Timestamp(ENTRY_TIME_STR).time()
OR_START = "09:30"
OR_END = "10:00"
OR_INCOMPLETE_TOLERANCE = 2
NY = pytz.timezone("America/New_York")


@pytest.fixture
def mock_or_data():
    def _creator(missing_rows=0):
        trade_date = date(2025, 12, 22)
        expected_ts = pd.date_range(start=f"{trade_date} {OR_START}", end=f"{trade_date} {OR_END}", freq="min", tz=NY)
        
        # Create a full OR dataframe
        df = pd.DataFrame({
            "time_ny": expected_ts,
            "high": 100,
            "low": 90
        })
        df.index = df["time_ny"]
        
        # If we need to simulate missing rows, drop them
        if missing_rows > 0:
            df = df.drop(df.index[:missing_rows])
            
        return df, len(expected_ts), trade_date
    return _creator


def create_mock_data(entry_price, complete=True):
    """Creates a 1-row DataFrame representing the entry candle."""
    df = pd.DataFrame([{
        "time_ny": pd.Timestamp(f"2025-12-22 {ENTRY_TIME_STR}:00").tz_localize("America/New_York"),
        "open": entry_price, "high": entry_price+10, "low": entry_price-10, "close": entry_price,
        "complete": complete
    }])
    df.index = df["time_ny"]
    return df


def create_mock_or(high, low):
    """Creates a dummy OR dataframe to establish levels."""
    return pd.DataFrame({"high": [high], "low": [low]})


def test_live_scenario_incomplete_candle():
    """
    Live Bot Scenario: The candle exists but is still forming (complete=False).
    The bot should NOT trade, but return 'entry_incomplete' to trigger a wait.
    """
    # OR: 100-200. Short < 135. Price is 120 (Short signal), BUT candle is incomplete.
    win_df = create_mock_data(entry_price=120, complete=False)
    or_df = create_mock_or(high=200, low=100)
    
    signal, reason = compute_signal(win_df, or_df)
    
    assert signal is None
    assert reason == "entry_incomplete"
    print("\n[PASS] Live Scenario: Incomplete candle correctly triggers wait.")


def test_replay_scenario_complete_candle():
    """
    Replay Scenario: The candle is loaded from CSV and is complete.
    The bot SHOULD generate a signal immediately.
    """
    # OR: 100-200. Short < 135. Price is 120.
    win_df = create_mock_data(entry_price=120, complete=True)
    or_df = create_mock_or(high=200, low=100)
    
    signal, reason = compute_signal(win_df, or_df)
    
    assert signal is not None
    side, entry, sl, tp = signal
    assert side == "short"
    assert reason == "short"
    print("[PASS] Replay Scenario: Complete candle correctly triggers signal.")


def test_or_completeness_full(mock_or_data):
    """Test OR completeness check when data is full."""
    slice_or, or_expected_rows, trade_date = mock_or_data(missing_rows=0)
    log_msg, tweet_msg, should_skip = check_or_completeness(
        slice_or, or_expected_rows, trade_date, OR_START, OR_END, OR_INCOMPLETE_TOLERANCE, NY
    )
    assert not should_skip
    assert log_msg is None
    assert tweet_msg is None


def test_or_completeness_within_tolerance(mock_or_data):
    """Test OR completeness check when missing rows are within tolerance."""
    slice_or, or_expected_rows, trade_date = mock_or_data(missing_rows=1)
    log_msg, tweet_msg, should_skip = check_or_completeness(
        slice_or, or_expected_rows, trade_date, OR_START, OR_END, OR_INCOMPLETE_TOLERANCE, NY
    )
    assert not should_skip
    assert log_msg is not None  # Should log a warning
    assert tweet_msg is None  # But no tweet


def test_or_completeness_exceeds_tolerance(mock_or_data):
    """Test OR completeness check when missing rows exceed tolerance."""
    slice_or, or_expected_rows, trade_date = mock_or_data(missing_rows=5)
    log_msg, tweet_msg, should_skip = check_or_completeness(
        slice_or, or_expected_rows, trade_date, OR_START, OR_END, OR_INCOMPLETE_TOLERANCE, NY
    )
    assert should_skip
    assert log_msg is not None
    assert tweet_msg is not None
