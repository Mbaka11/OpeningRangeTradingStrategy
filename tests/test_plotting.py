from datetime import date

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from opening_range_bot.plotting import create_or_chart, create_trade_chart


def sample_frame(start: str, periods: int = 31) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="min", tz="America/New_York")
    close = 23_140 + np.linspace(0, 35, periods) + np.sin(np.linspace(0, 8, periods)) * 6
    return pd.DataFrame(
        {
            "close": close,
            "high": close + 2.5,
            "low": close - 2.5,
        },
        index=index,
    )


def assert_dark_png(buffer) -> None:
    assert buffer.getvalue().startswith(b"\x89PNG\r\n\x1a\n")
    image = mpimg.imread(buffer, format="png")
    assert image.shape[0] >= 800
    assert image.shape[1] >= 1400
    assert float(image[0, 0, :3].mean()) < 0.15
    assert plt.get_fignums() == []


def test_opening_range_chart_is_dark_social_ready_png():
    frame = sample_frame("2026-08-20 09:30")
    buffer = create_or_chart(
        frame,
        date(2026, 8, 20),
        or_high=23_180.0,
        or_low=23_120.0,
        top_cut=23_159.0,
        bot_cut=23_141.0,
    )

    assert_dark_png(buffer)


def test_trade_chart_is_dark_social_ready_png():
    frame = sample_frame("2026-08-20 10:23", periods=60)
    buffer = create_trade_chart(
        frame,
        date(2026, 8, 20),
        pd.Timestamp("10:22").time(),
        frame.index[-1],
        entry_price=23_140.0,
        exit_price=23_175.0,
        side="long",
        or_high=23_160.0,
        or_low=23_110.0,
        sl=23_115.0,
        tp=23_215.0,
        mfe=41.2,
        mae=8.4,
        exit_reason="time",
    )

    assert_dark_png(buffer)
