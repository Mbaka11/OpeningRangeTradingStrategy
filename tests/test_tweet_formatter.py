from datetime import date

from opening_range_bot.tweet_formatter import (
    MAX_POST_CHARS,
    format_no_trade_recap_post,
    format_signal_post,
    format_trade_recap_post,
)


SESSION = {
    "trade_date": date(2026, 8, 20),
    "instrument": "NAS100_USD",
    "or_start": "09:30",
    "exit_time": "12:00",
    "entry_time": "10:22",
    "or_low": 23120.40,
    "or_high": 23178.60,
    "long_cut": 23158.23,
    "short_cut": 23140.77,
}
START_ACCOUNT = {"balance": 100000.0, "nav": 100012.34, "currency": "USD"}
END_ACCOUNT = {"balance": 106000.0, "nav": 106000.0, "currency": "USD"}


def assert_valid_post(message: str) -> None:
    assert message
    assert len(message) <= MAX_POST_CHARS


def test_live_signal_post_contains_setup_trade_and_balance():
    message = format_signal_post(
        **SESSION,
        environment="practice",
        side="long",
        entry=23164.10,
        stop_loss=23139.10,
        take_profit=23239.10,
        position_size=1.0,
        point_value=80.0,
        account=START_ACCOUNT,
    )

    assert_valid_post(message)
    assert "NAS100_USD PAPER" in message
    assert "Session 09:30-12:00 ET | Entry 10:22" in message
    assert "OR 23,120.40-23,178.60" in message
    assert "Long >= 23,158.23 | Short <= 23,140.77" in message
    assert "LONG @ 23,164.10 | SL 23,139.10 | TP 23,239.10" in message
    assert "Size 1.00 x $80.00/pt" in message
    assert "Balance 100,000.00 USD | NAV 100,012.34" in message


def test_live_trade_recap_contains_result_balances_and_counters():
    message = format_trade_recap_post(
        trade_date=SESSION["trade_date"],
        instrument=SESSION["instrument"],
        environment="practice",
        side="long",
        entry=23164.10,
        exit_price=23239.10,
        exit_reason="tp",
        pnl_points=75.0,
        pnl_usd=6000.0,
        mfe=82.3,
        mae=11.4,
        start_account=START_ACCOUNT,
        end_account=END_ACCOUNT,
        signals=1,
        orders=1,
        skipped=0,
        errors=0,
    )

    assert_valid_post(message)
    assert "LONG 23,164.10 -> 23,239.10 | TP" in message
    assert "PnL +75.00 pt | +$6,000.00" in message
    assert "MFE +82.30 | MAE -11.40 pt" in message
    assert "Balance 100,000.00 -> 106,000.00 USD" in message
    assert "NAV 100,012.34 -> 106,000.00" in message
    assert "Sig 1 | Orders 1 | Skip 0 | Err 0" in message


def test_live_no_trade_post_is_single_complete_recap():
    message = format_no_trade_recap_post(
        **SESSION,
        environment="practice",
        reason="none",
        start_account=START_ACCOUNT,
        end_account=START_ACCOUNT,
        signals=0,
        orders=0,
        skipped=1,
        errors=0,
    )

    assert_valid_post(message)
    assert "No trade: entry stayed in the middle zone" in message
    assert "OR 23,120.40-23,178.60" in message
    assert "Balance 100,000.00 -> 100,000.00 USD" in message
    assert "NAV 100,012.34 -> 100,012.34" in message


def test_no_trade_post_handles_large_balances_within_limit():
    million_account = {"balance": 1_000_000.0, "nav": 1_000_123.45, "currency": "USD"}
    message = format_no_trade_recap_post(
        **SESSION,
        environment="practice",
        reason="none",
        start_account=million_account,
        end_account=million_account,
        signals=0,
        orders=0,
        skipped=1,
        errors=0,
    )

    assert_valid_post(message)
    assert "Balance 1,000,000.00 -> 1,000,000.00 USD" in message


def test_replay_trade_posts_are_warned_and_have_no_balance():
    signal = format_signal_post(
        **SESSION,
        environment="replay",
        side="short",
        entry=23135.0,
        stop_loss=23160.0,
        take_profit=23060.0,
        position_size=1.0,
        point_value=80.0,
        account=None,
    )
    recap = format_trade_recap_post(
        trade_date=SESSION["trade_date"],
        instrument=SESSION["instrument"],
        environment="replay",
        side="short",
        entry=23135.0,
        exit_price=23060.0,
        exit_reason="tp",
        pnl_points=75.0,
        pnl_usd=6000.0,
        mfe=80.0,
        mae=10.0,
        start_account=None,
        end_account=None,
        signals=1,
        orders=1,
        skipped=0,
        errors=0,
    )

    for message in (signal, recap):
        assert_valid_post(message)
        assert message.startswith("REPLAY ONLY - NO LIVE ORDER")
        assert "Balance unavailable in replay" in message
    assert "Sim sig 1 | Orders 1" in recap


def test_replay_trade_recap_handles_missing_exit_data():
    message = format_trade_recap_post(
        trade_date=SESSION["trade_date"],
        instrument=SESSION["instrument"],
        environment="replay",
        side="long",
        entry=23164.10,
        exit_price=None,
        exit_reason=None,
        pnl_points=None,
        pnl_usd=None,
        mfe=0.0,
        mae=0.0,
        start_account=None,
        end_account=None,
        signals=1,
        orders=1,
        skipped=0,
        errors=0,
    )

    assert_valid_post(message)
    assert "23,164.10 -> n/a | UNKNOWN" in message
    assert "PnL n/a pt | n/a" in message


def test_replay_no_trade_post_is_one_warned_recap():
    message = format_no_trade_recap_post(
        **SESSION,
        environment="replay",
        reason="none",
        start_account=None,
        end_account=None,
        signals=0,
        orders=0,
        skipped=1,
        errors=0,
    )

    assert_valid_post(message)
    assert message.startswith("REPLAY ONLY - NO LIVE ORDER")
    assert "No trade:" in message
    assert "Balance unavailable in replay" in message
    assert "Sim sig 0 | Orders 0 | Skip 1 | Err 0" in message
