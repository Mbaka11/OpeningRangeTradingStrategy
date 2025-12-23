"""
Plotting utilities for trade visualization.
Generates in-memory images for Twitter/logging.
"""
import io
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server/docker
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

def create_trade_chart(df, trade_date, entry_time, exit_time, 
                       entry_price, exit_price, side, 
                       or_high, or_low, sl, tp, mfe, mae):
    """
    Generates a PNG image of the trade session.
    Returns: io.BytesIO object containing the image.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Plot Price
    ax.plot(df.index, df["close"], label="Price", color="black", linewidth=1)
    
    # Plot OR Levels
    ax.axhline(or_high, color="gray", linestyle="--", alpha=0.5, label="OR High")
    ax.axhline(or_low, color="gray", linestyle="--", alpha=0.5, label="OR Low")
    ax.fill_between(df.index, or_low, or_high, color="gray", alpha=0.1)

    # Plot Trade Markers
    if entry_price:
        ax.axhline(entry_price, color="blue", linestyle=":", alpha=0.8, label="Entry")
        # Entry Marker
        # Find closest timestamp for entry
        entry_ts = pd.Timestamp.combine(trade_date, entry_time).tz_localize(df.index.tz)
        ax.scatter([entry_ts], [entry_price], color="blue", marker="^" if side=="long" else "v", s=100, zorder=5)

    # SL / TP Lines
    if sl: ax.axhline(sl, color="red", linestyle="--", alpha=0.6, label="SL")
    if tp: ax.axhline(tp, color="green", linestyle="--", alpha=0.6, label="TP")

    # Exit Marker
    if exit_price and exit_time:
        ax.scatter([exit_time], [exit_price], color="purple", marker="x", s=100, zorder=5, label="Exit")

    # Formatting
    ax.set_title(f"Trade {trade_date} | {side.upper()} | MFE +{mfe:.1f} / MAE -{mae:.1f}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=df.index.tz))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    
    # Save to buffer
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=100)
    buf.seek(0)
    plt.close(fig)
    
    return buf