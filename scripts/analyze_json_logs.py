"""
Analyzes daily JSON logs to produce Quant metrics and tweets a summary.
Run this weekly or monthly to track performance.
"""
import sys
import json
import io
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg") # Non-interactive backend
import matplotlib.pyplot as plt

# Add repo root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared import notifier
from shared.logging_utils import setup_logger

logger = setup_logger("analyzer")
JSON_DIR = ROOT / "services" / "trading" / "logs" / "summaries" / "daily_json"

def load_all_logs():
    data = []
    if not JSON_DIR.exists():
        logger.warning(f"No JSON directory found at {JSON_DIR}")
        return pd.DataFrame()

    # Iterate over all JSON files
    for f in sorted(JSON_DIR.glob("*.json")):
        try:
            with open(f, "r") as jf:
                entry = json.load(jf)
                
                # Basic Session Info
                row = {
                    "date": entry.get("session_setup", {}).get("date"),
                    "instrument": entry.get("session_setup", {}).get("instrument"),
                }
                
                # Pre-trade checks (Spread/ATR)
                checks = entry.get("pre_trade_checks", {})
                if checks:
                    row["spread"] = checks.get("spread", 0.0)
                    row["atr"] = checks.get("volatility_atr_14", 0.0)

                # Signal info
                sig = entry.get("signal_decision", {})
                if sig:
                    row["signal"] = sig.get("signal_type")
                    row["entry_price"] = sig.get("entry_price")
                else:
                    row["signal"] = "none"

                # Trade Result info
                res = entry.get("trade_result", {})
                if res:
                    row["pnl_usd"] = res.get("pnl_usd", 0.0)
                    row["pnl_pts"] = res.get("pnl_points", 0.0)
                    row["mfe"] = res.get("mfe_points", 0.0)
                    row["mae"] = res.get("mae_points", 0.0)
                    row["exit_reason"] = res.get("exit_reason", "n/a")
                else:
                    row["pnl_usd"] = 0.0
                    row["mfe"] = 0.0
                    row["mae"] = 0.0
                
                data.append(row)
        except Exception as e:
            logger.error(f"Error loading {f.name}: {e}")
            
    df = pd.DataFrame(data)
    if not df.empty and "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        
    return df

def create_performance_charts(df):
    """Generates in-memory PNG buffers for PnL and MFE/MAE."""
    charts = []
    
    # 1. Cumulative PnL Chart
    if not df.empty and "pnl_usd" in df.columns:
        try:
            plt.style.use('seaborn-v0_8-whitegrid')
        except OSError:
            pass # Fallback
            
        fig, ax = plt.subplots(figsize=(10, 5))
        df["cum_pnl"] = df["pnl_usd"].cumsum()
        
        # Plot line
        ax.plot(df["date"], df["cum_pnl"], marker='o', linestyle='-', color='#2980B9', linewidth=2, label="Net PnL")
        ax.fill_between(df["date"], df["cum_pnl"], 0, alpha=0.1, color='#2980B9')
        ax.axhline(0, color='black', linewidth=1, linestyle='--')
        
        ax.set_title("Cumulative PnL ($)", fontsize=12, fontweight='bold')
        ax.tick_params(axis='x', rotation=45)
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        charts.append(buf)
        plt.close(fig)

    # 2. MFE vs MAE Scatter (Trade Quality)
    trades = df[df["signal"] != "none"]
    if not trades.empty:
        fig, ax = plt.subplots(figsize=(6, 6))
        
        # Color points: Green for Win, Red for Loss
        colors = ['#27AE60' if p > 0 else '#C0392B' for p in trades["pnl_usd"]]
        
        ax.scatter(trades["mae"], trades["mfe"], c=colors, alpha=0.7, s=100, edgecolors='white')
        
        # 1:1 Line (Ideal is MFE > MAE, so points should be above this line)
        max_val = max(trades["mfe"].max(), trades["mae"].max()) if not trades.empty else 10
        if max_val == 0: max_val = 10
        
        ax.plot([0, max_val], [0, max_val], linestyle='--', color='gray', alpha=0.5, label="1:1 Ratio")
        
        ax.set_xlabel("MAE (Adverse Excursion)", fontweight='bold')
        ax.set_ylabel("MFE (Favorable Excursion)", fontweight='bold')
        ax.set_title("Trade Efficiency: MFE vs MAE", fontsize=12, fontweight='bold')
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        charts.append(buf)
        plt.close(fig)

    return charts

def main():
    logger.info("Starting analysis...")
    df = load_all_logs()
    
    if df.empty:
        logger.info("No data found to analyze.")
        return

    # Filter for actual trades
    trades = df[df["signal"] != "none"].copy()
    total_days = len(df)
    total_trades = len(trades)
    
    if total_trades == 0:
        logger.info("No trades executed yet.")
        return

    # Metrics Calculation
    wins = trades[trades["pnl_usd"] > 0]
    win_rate = len(wins) / total_trades * 100
    total_pnl = trades["pnl_usd"].sum()
    
    avg_win = wins["pnl_usd"].mean() if not wins.empty else 0.0
    losses = trades[trades["pnl_usd"] <= 0]
    avg_loss = losses["pnl_usd"].mean() if not losses.empty else 0.0
    
    # Expectancy formula: (Win% * AvgWin) + (Loss% * AvgLoss)
    expectancy = (win_rate/100.0 * avg_win) + ((1.0 - win_rate/100.0) * avg_loss)
    
    # Construct Tweet Message
    # Keeping it concise for Twitter limits
    msg = (
        f"📊 Performance Update\n\n"
        f"Trades: {total_trades} (over {total_days} sessions)\n"
        f"Net PnL: ${total_pnl:,.2f}\n"
        f"Win Rate: {win_rate:.1f}%\n"
        f"Expectancy: ${expectancy:.2f}/trade\n"
        f"Avg Win: ${avg_win:.0f} | Avg Loss: ${avg_loss:.0f}\n\n"
        f"#AlgoTrading #Quant"
    )
    
    logger.info(f"Analysis Result:\n{msg}")
    
    # Generate Charts
    charts = create_performance_charts(df)
    
    # Tweet
    logger.info("Attempting to tweet analysis...")
    try:
        # notify_trade handles the API calls and potential errors
        res = notifier.notify_trade(msg, images=charts)
        if res:
            logger.info(f"Tweet result: {res.get('status')}")
    except Exception as e:
        logger.error(f"Failed to tweet analysis: {e}")

if __name__ == "__main__":
    main()