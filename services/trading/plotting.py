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
                       or_high, or_low, sl, tp, mfe, mae,
                       exit_reason=None):
    """
    Generates a PNG image of the trade session.
    Returns: io.BytesIO object containing the image.
    """
    # Set a professional style
    try:
        plt.style.use('seaborn-v0_8-whitegrid')
    except OSError:
        pass  # Fallback if style not found

    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Professional Colors (Flat UI Palette)
    c_price = "#2C3E50"  # Dark Blue-Gray
    c_or    = "#95A5A6"  # Concrete Gray
    c_entry = "#2980B9"  # Belize Hole Blue
    c_sl    = "#C0392B"  # Pomegranate Red
    c_tp    = "#27AE60"  # Nephritis Green
    c_exit  = "#F39C12"  # Orange

    # Plot Price
    ax.plot(df.index, df["close"], label="Price", color=c_price, linewidth=1.5)
    
    # Plot OR Levels
    ax.axhline(or_high, color=c_or, linestyle="--", alpha=0.6, label="OR High", linewidth=1)
    ax.axhline(or_low, color=c_or, linestyle="--", alpha=0.6, label="OR Low", linewidth=1)
    ax.fill_between(df.index, or_low, or_high, color=c_or, alpha=0.15)

    # Plot Trade Markers
    if entry_price:
        ax.axhline(entry_price, color=c_entry, linestyle="-", alpha=0.8, label="Entry", linewidth=1)
        # Entry Marker
        # Find closest timestamp for entry
        entry_ts = pd.Timestamp.combine(trade_date, entry_time).tz_localize(df.index.tz)
        ax.scatter([entry_ts], [entry_price], color=c_entry, marker="^" if side == "long" else "v", s=120, zorder=5, edgecolors='white')

    # SL / TP Lines
    if sl:
        ax.axhline(sl, color=c_sl, linestyle=":", alpha=0.8, label="SL", linewidth=1.5)
    if tp:
        ax.axhline(tp, color=c_tp, linestyle=":", alpha=0.8, label="TP", linewidth=1.5)

    # Exit Marker
    exit_label = "Exit"
    if exit_reason:
        exit_label = f"Exit ({exit_reason.upper()})"
    if exit_price and exit_time:
        ax.scatter([exit_time], [exit_price], color=c_exit, marker="X", s=120, zorder=5, label=exit_label, edgecolors='white')

    # Formatting
    exit_tag = f" | Exit {exit_reason.upper()}" if exit_reason else ""
    ax.set_title(f"Trade {trade_date} | {side.upper()} | MFE +{mfe:.1f} / MAE -{mae:.1f}{exit_tag}", fontsize=12, fontweight='bold', color=c_price)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=df.index.tz))
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.legend(loc="best", frameon=True, framealpha=0.9)
    
    # Clean spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # Save to buffer
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)
    
    return buf


def create_or_chart(df, trade_date, or_high, or_low, top_cut, bot_cut):
    """
    Generates a PNG image of the Opening Range formation (09:30-10:00).
    """
    try:
        plt.style.use('seaborn-v0_8-whitegrid')
    except OSError:
        pass

    fig, ax = plt.subplots(figsize=(10, 6))
    
    c_price = "#2C3E50"
    c_or    = "#95A5A6"
    
    # Plot Price
    ax.plot(df.index, df["close"], label="Price", color=c_price, linewidth=1.5)
    
    # Plot OR Levels
    ax.axhline(or_high, color=c_or, linestyle="--", alpha=0.8, label="OR High")
    ax.axhline(or_low, color=c_or, linestyle="--", alpha=0.8, label="OR Low")
    ax.fill_between(df.index, or_low, or_high, color=c_or, alpha=0.15)
    
    # Plot Trigger Levels
    ax.axhline(top_cut, color="#2980B9", linestyle=":", alpha=0.8, label="Long Trigger", linewidth=1.5)
    ax.axhline(bot_cut, color="#F39C12", linestyle=":", alpha=0.8, label="Short Trigger", linewidth=1.5)

    # Formatting
    ax.set_title(f"Opening Range {trade_date} | {or_low:.2f} - {or_high:.2f}", fontsize=12, fontweight='bold', color=c_price)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=df.index.tz))
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.legend(loc="best", frameon=True, framealpha=0.9)
    
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # Save to buffer
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)
    
    return buf
