"""Dark, social-ready charts for opening-range paper-trading updates."""
from __future__ import annotations

import io
from datetime import time
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend for server/docker.
import matplotlib.dates as mdates
import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import pandas as pd

# High-contrast dark palette sized for social-media images.
BG = "#070A0F"
PANEL = "#0D131D"
GRID = "#233044"
TEXT = "#F4F7FB"
MUTED = "#91A0B5"
PRICE = "#65D7FF"
PRICE_RAW = "#9DE8FF"
OR_COLOR = "#60738E"
ENTRY = "#44C7FF"
LONG = "#38D996"
SHORT = "#FFB454"
STOP = "#FF5D73"
EXIT = "#F8E16C"


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a sorted plotting frame with numeric OHLC values."""
    if df is None or df.empty:
        raise ValueError("Cannot create a chart from an empty dataframe")

    frame = df.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        if "time_ny" not in frame:
            raise ValueError("Chart data requires a DatetimeIndex or time_ny column")
        frame.index = pd.to_datetime(frame["time_ny"])
    frame = frame.sort_index()

    if "close" not in frame:
        raise ValueError("Chart data requires a close column")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["high"] = pd.to_numeric(frame.get("high", frame["close"]), errors="coerce")
    frame["low"] = pd.to_numeric(frame.get("low", frame["close"]), errors="coerce")
    frame = frame.dropna(subset=["close", "high", "low"])
    if frame.empty:
        raise ValueError("Chart data contains no valid OHLC rows")
    return frame


def _canvas():
    fig, ax = plt.subplots(figsize=(12, 6.75), facecolor=BG)
    fig.subplots_adjust(left=0.08, right=0.96, top=0.86, bottom=0.14)
    ax.set_facecolor(PANEL)
    return fig, ax


def _style_axes(ax, timezone) -> None:
    ax.grid(True, color=GRID, alpha=0.48, linewidth=0.75, linestyle="--")
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_ylabel("Price", color=MUTED, fontsize=10, labelpad=10)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=timezone))
    ax.margins(x=0.02, y=0.10)
    for spine in ax.spines.values():
        spine.set_color(GRID)
        spine.set_linewidth(0.8)


def _plot_price(ax, frame: pd.DataFrame) -> None:
    """Show exact minute values plus a subtle 3-bar EMA for visual flow."""
    trend = frame["close"].ewm(span=3, adjust=False).mean()
    ax.fill_between(
        frame.index,
        frame["low"].to_numpy(),
        frame["high"].to_numpy(),
        color=PRICE,
        alpha=0.055,
        linewidth=0,
        label="1m high-low",
    )
    ax.plot(
        frame.index,
        frame["close"],
        color=PRICE_RAW,
        alpha=0.72,
        linewidth=1.35,
        marker="o",
        markersize=1.8,
        markeredgewidth=0,
        label="1m close (exact)",
    )
    trend_line, = ax.plot(
        frame.index,
        trend,
        color=PRICE,
        linewidth=1.95,
        solid_capstyle="round",
        solid_joinstyle="round",
        label="3-bar EMA (visual)",
        zorder=4,
    )
    trend_line.set_path_effects([
        path_effects.Stroke(linewidth=4.6, foreground="#1A8BB3", alpha=0.16),
        path_effects.Normal(),
    ])


def _level(ax, y: float, label: str, color: str, *, linestyle: str = "--", width: float = 1.25) -> None:
    ax.axhline(y, color=color, linestyle=linestyle, linewidth=width, alpha=0.92, label=label)
    ax.annotate(
        f" {label}  {y:,.2f} ",
        xy=(1, y),
        xycoords=("axes fraction", "data"),
        xytext=(-8, 0),
        textcoords="offset points",
        ha="right",
        va="center",
        color=TEXT,
        fontsize=8,
        fontweight="bold",
        bbox={"boxstyle": "round,pad=0.28", "facecolor": color, "edgecolor": "none", "alpha": 0.88},
        zorder=8,
    )


def _legend(ax, *, columns: int = 3) -> None:
    handles, labels = ax.get_legend_handles_labels()
    unique = {}
    for handle, label in zip(handles, labels):
        if label and label not in unique:
            unique[label] = handle
    legend = ax.legend(
        unique.values(),
        unique.keys(),
        loc="upper center",
        bbox_to_anchor=(0.5, -0.11),
        ncol=columns,
        frameon=False,
        fontsize=8.5,
        labelcolor=MUTED,
        handlelength=2.4,
    )
    if legend:
        for text in legend.get_texts():
            text.set_color(MUTED)


def _timestamp_for_session(trade_date, session_time: time, timezone) -> pd.Timestamp:
    session_date = pd.Timestamp(trade_date).date()
    timestamp = pd.Timestamp.combine(session_date, session_time)
    if timezone is not None:
        timestamp = timestamp.tz_localize(timezone)
    return timestamp


def _coerce_timestamp(value, timezone) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timezone is not None and timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone)
    elif timezone is not None and timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(timezone)
    return timestamp


def _save(fig) -> io.BytesIO:
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=140,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.18,
    )
    buffer.seek(0)
    plt.close(fig)
    return buffer


def create_trade_chart(
    df,
    trade_date,
    entry_time,
    exit_time,
    entry_price,
    exit_price,
    side,
    or_high,
    or_low,
    sl,
    tp,
    mfe,
    mae,
    exit_reason=None,
):
    """Create a dark trade-result chart and return it as an in-memory PNG."""
    frame = _frame(df)
    timezone = frame.index.tz
    fig, ax = _canvas()

    _plot_price(ax, frame)
    ax.fill_between(frame.index, or_low, or_high, color=OR_COLOR, alpha=0.09, linewidth=0)
    _level(ax, or_high, "OR HIGH", OR_COLOR, linestyle="--", width=1.0)
    _level(ax, or_low, "OR LOW", OR_COLOR, linestyle="--", width=1.0)

    if entry_price is not None:
        reward_low, reward_high = sorted((entry_price, tp))
        risk_low, risk_high = sorted((entry_price, sl))
        ax.fill_between(frame.index, reward_low, reward_high, color=LONG, alpha=0.055, linewidth=0)
        ax.fill_between(frame.index, risk_low, risk_high, color=STOP, alpha=0.05, linewidth=0)
        _level(ax, entry_price, "ENTRY", ENTRY, linestyle="-", width=1.5)

        entry_ts = _timestamp_for_session(trade_date, entry_time, timezone)
        marker = "^" if str(side).lower() == "long" else "v"
        ax.scatter(
            [entry_ts],
            [entry_price],
            color=ENTRY,
            marker=marker,
            s=150,
            zorder=9,
            edgecolors=TEXT,
            linewidths=1.2,
        )
        ax.annotate(
            f" {str(side).upper()} ENTRY ",
            (entry_ts, entry_price),
            xytext=(10, 18 if marker == "^" else -24),
            textcoords="offset points",
            color=TEXT,
            fontsize=8.5,
            fontweight="bold",
            bbox={"boxstyle": "round,pad=0.28", "facecolor": ENTRY, "edgecolor": "none", "alpha": 0.9},
        )

    if sl is not None:
        _level(ax, sl, "STOP", STOP, linestyle=":", width=1.7)
    if tp is not None:
        _level(ax, tp, "TARGET", LONG, linestyle=":", width=1.7)

    exit_ts = _coerce_timestamp(exit_time, timezone)
    if exit_price is not None and exit_ts is not None:
        reason = (exit_reason or "exit").upper()
        ax.scatter(
            [exit_ts],
            [exit_price],
            color=EXIT,
            marker="X",
            s=165,
            zorder=10,
            edgecolors=BG,
            linewidths=1.1,
            label=f"Exit ({reason})",
        )
        ax.annotate(
            f" {reason}  {exit_price:,.2f} ",
            (exit_ts, exit_price),
            xytext=(-10, 18),
            textcoords="offset points",
            ha="right",
            color=BG,
            fontsize=8.5,
            fontweight="bold",
            bbox={"boxstyle": "round,pad=0.3", "facecolor": EXIT, "edgecolor": "none", "alpha": 0.95},
        )

    reason_title = (exit_reason or "open").upper()
    ax.set_title(
        f"{str(side).upper()} TRADE  /  {trade_date}",
        loc="left",
        color=TEXT,
        fontsize=17,
        fontweight="bold",
        pad=22,
    )
    ax.text(
        0,
        1.025,
        f"Result: {reason_title}   •   MFE +{float(mfe or 0):.2f} pt   •   MAE -{float(mae or 0):.2f} pt",
        transform=ax.transAxes,
        color=EXIT if reason_title == "TP" else MUTED,
        fontsize=10,
        va="bottom",
    )

    _style_axes(ax, timezone)
    _legend(ax, columns=4)
    return _save(fig)


def create_or_chart(df, trade_date, or_high, or_low, top_cut, bot_cut):
    """Create a dark opening-range chart with visually distinct signal zones."""
    frame = _frame(df)
    timezone = frame.index.tz
    fig, ax = _canvas()

    # Zone fills explain the decision model at a glance.
    ax.fill_between(frame.index, top_cut, or_high, color=LONG, alpha=0.09, linewidth=0)
    ax.fill_between(frame.index, bot_cut, top_cut, color=OR_COLOR, alpha=0.055, linewidth=0)
    ax.fill_between(frame.index, or_low, bot_cut, color=SHORT, alpha=0.09, linewidth=0)
    _plot_price(ax, frame)

    _level(ax, or_high, "OR HIGH", OR_COLOR, linestyle="--", width=1.15)
    _level(ax, top_cut, "LONG", LONG, linestyle=":", width=1.65)
    _level(ax, bot_cut, "SHORT", SHORT, linestyle=":", width=1.65)
    _level(ax, or_low, "OR LOW", OR_COLOR, linestyle="--", width=1.15)

    range_size = float(or_high) - float(or_low)
    ax.set_title(
        f"OPENING RANGE  /  {trade_date}",
        loc="left",
        color=TEXT,
        fontsize=17,
        fontweight="bold",
        pad=22,
    )
    ax.text(
        0,
        1.025,
        f"Range {or_low:,.2f} - {or_high:,.2f}   •   Width {range_size:,.2f} pt   •   Long / Neutral / Short zones",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=10,
        va="bottom",
    )

    _style_axes(ax, timezone)
    _legend(ax, columns=4)
    return _save(fig)
