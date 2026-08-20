"""Generate reproducible documentation examples for the X posting flows."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opening_range_bot.plotting import create_or_chart, create_trade_chart
from opening_range_bot.tweet_formatter import (
    format_no_trade_recap_post,
    format_signal_post,
    format_trade_recap_post,
)

ASSETS = ROOT / "docs" / "assets"
EXAMPLE_DATE = date(2026, 8, 20)
INSTRUMENT = "NAS100_USD"
ENTRY = 23_164.10
STOP = 23_139.10
TARGET = 23_239.10
START_ACCOUNT = {"balance": 100_000.0, "nav": 100_012.34, "currency": "USD"}
END_ACCOUNT = {"balance": 106_000.0, "nav": 106_000.0, "currency": "USD"}


def _frame(index: pd.DatetimeIndex, close: np.ndarray) -> pd.DataFrame:
    wave = np.sin(np.linspace(0, 7, len(index)))
    return pd.DataFrame(
        {
            "close": close,
            "high": close + 2.3 + np.maximum(wave, 0) * 1.1,
            "low": close - 2.3 + np.minimum(wave, 0) * 1.1,
        },
        index=index,
    )


def _save(buffer, filename: str) -> None:
    (ASSETS / filename).write_bytes(buffer.getvalue())


def generate() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    or_index = pd.date_range("2026-08-20 09:30", "2026-08-20 10:00", freq="min", tz="America/New_York")
    or_close = np.linspace(23_132, 23_163, len(or_index)) + np.sin(np.linspace(0, 9, len(or_index))) * 11
    trade_or = _frame(or_index, or_close)
    trade_or_low = float(trade_or["low"].min())
    trade_or_high = float(trade_or["high"].max())
    trade_or_range = trade_or_high - trade_or_low
    trade_long_cut = trade_or_high - 0.35 * trade_or_range
    trade_short_cut = trade_or_low + 0.35 * trade_or_range
    _save(
        create_or_chart(
            trade_or,
            EXAMPLE_DATE,
            trade_or_high,
            trade_or_low,
            trade_long_cut,
            trade_short_cut,
        ),
        "trade-day-opening-range.png",
    )

    trade_index = pd.date_range("2026-08-20 10:23", "2026-08-20 11:21", freq="min", tz="America/New_York")
    progress = np.linspace(0, 1, len(trade_index))
    trade_close = ENTRY + 71 * progress + np.sin(np.linspace(0, 13, len(trade_index))) * 4.2 * (1 - progress * 0.45)
    trade_close = np.minimum(trade_close, TARGET - 3.0)
    trade_close[-1] = TARGET - 1.2
    trade_path = _frame(trade_index, trade_close)
    trade_path.iloc[-1, trade_path.columns.get_loc("high")] = TARGET
    exit_time = trade_path.index[-1]
    mfe = float(trade_path["high"].max() - ENTRY)
    mae = float(ENTRY - trade_path["low"].min())
    _save(
        create_trade_chart(
            trade_path,
            EXAMPLE_DATE,
            pd.Timestamp("10:22").time(),
            exit_time,
            ENTRY,
            TARGET,
            "long",
            trade_or_high,
            trade_or_low,
            STOP,
            TARGET,
            mfe,
            mae,
            exit_reason="tp",
        ),
        "trade-day-result.png",
    )

    no_trade_index = pd.date_range("2026-08-20 09:30", "2026-08-20 10:00", freq="min", tz="America/New_York")
    no_trade_close = 23_148 + np.sin(np.linspace(0, 11, len(no_trade_index))) * 9 + np.cos(np.linspace(0, 5, len(no_trade_index))) * 3
    no_trade_or = _frame(no_trade_index, no_trade_close)
    no_trade_low = float(no_trade_or["low"].min())
    no_trade_high = float(no_trade_or["high"].max())
    no_trade_range = no_trade_high - no_trade_low
    no_trade_long_cut = no_trade_high - 0.35 * no_trade_range
    no_trade_short_cut = no_trade_low + 0.35 * no_trade_range
    _save(
        create_or_chart(
            no_trade_or,
            EXAMPLE_DATE,
            no_trade_high,
            no_trade_low,
            no_trade_long_cut,
            no_trade_short_cut,
        ),
        "no-trade-opening-range.png",
    )

    session = {
        "trade_date": EXAMPLE_DATE,
        "instrument": INSTRUMENT,
        "or_start": "09:30",
        "exit_time": "12:00",
        "entry_time": "10:22",
        "or_low": trade_or_low,
        "or_high": trade_or_high,
        "long_cut": trade_long_cut,
        "short_cut": trade_short_cut,
    }
    signal_post = format_signal_post(
        **session,
        environment="practice",
        side="long",
        entry=ENTRY,
        stop_loss=STOP,
        take_profit=TARGET,
        position_size=1.0,
        point_value=80.0,
        account=START_ACCOUNT,
    )
    recap_post = format_trade_recap_post(
        trade_date=EXAMPLE_DATE,
        instrument=INSTRUMENT,
        environment="practice",
        side="long",
        entry=ENTRY,
        exit_price=TARGET,
        exit_reason="tp",
        pnl_points=75.0,
        pnl_usd=6_000.0,
        mfe=mfe,
        mae=mae,
        start_account=START_ACCOUNT,
        end_account=END_ACCOUNT,
        signals=1,
        orders=1,
        skipped=0,
        errors=0,
    )
    no_trade_session = {
        **session,
        "or_low": no_trade_low,
        "or_high": no_trade_high,
        "long_cut": no_trade_long_cut,
        "short_cut": no_trade_short_cut,
    }
    no_trade_post = format_no_trade_recap_post(
        **no_trade_session,
        environment="practice",
        reason="none",
        start_account=START_ACCOUNT,
        end_account=START_ACCOUNT,
        signals=0,
        orders=0,
        skipped=1,
        errors=0,
    )

    markdown = f"""# X post flow examples

These illustrative examples are generated by `scripts/generate_example_assets.py` using the same formatters and chart functions as the bot.

## Use case 1: trade day — two posts

### Post 1: opening range and accepted paper trade

```text
{signal_post}
```

Attached chart:

![Dark opening-range chart for a trade day](trade-day-opening-range.png)

### Post 2: exit and final recap

```text
{recap_post}
```

Attached chart:

![Dark trade-result chart](trade-day-result.png)

## Use case 2: no-trade day — one post

```text
{no_trade_post}
```

Attached chart:

![Dark opening-range chart for a no-trade day](no-trade-opening-range.png)
"""
    (ASSETS / "tweet-flow-examples.md").write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    generate()
    print(f"Generated X post examples in {ASSETS}")
