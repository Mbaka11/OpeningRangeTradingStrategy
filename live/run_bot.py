"""Skeleton live/paper runner.
- Polls OANDA M1 candles.
- Builds OR (09:30–10:00 NY), decides at 10:22 using or_core logic.
- One trade/day, SL/TP attached, hard flat at 12:00.
- Log-only by default (set PLACE_ORDERS=True to call OANDA).
"""
import time
from datetime import datetime
import pytz
import pandas as pd
from pathlib import Path
from live import data_feed, broker_oanda
from live.config import INSTRUMENTS, STRATEGY, OANDA_TIMEZONE
from src import or_core

NY = pytz.timezone(OANDA_TIMEZONE)
PLACE_ORDERS = False  # toggle to True when ready
POSITION_SIZE = INSTRUMENTS.get("market", {}).get("position_size", 1.0)
POINT_VAL = INSTRUMENTS.get("market", {}).get("point_value_usd", 80.0)

OR_START = INSTRUMENTS.get("session", {}).get("or_window", {}).get("start", "09:30")
OR_END   = INSTRUMENTS.get("session", {}).get("or_window", {}).get("end_inclusive", "10:00")
ENTRY_T  = INSTRUMENTS.get("session", {}).get("entry_time", "10:22")
EXIT_T   = INSTRUMENTS.get("session", {}).get("hard_exit_time", "12:00")
TOP_PCT  = STRATEGY.get("parameters", {}).get("zones", {}).get("top_pct", 0.35)
BOT_PCT  = STRATEGY.get("parameters", {}).get("zones", {}).get("bottom_pct", 0.35)
SL_PTS   = STRATEGY.get("parameters", {}).get("risk", {}).get("stop_loss_points", 25)
TP_PTS   = STRATEGY.get("parameters", {}).get("risk", {}).get("take_profit_points", 75)


def now_ny():
    return datetime.now(tz=NY)


def log(msg):
    ts = now_ny().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts} NY] {msg}")


def compute_signal(win_df: pd.DataFrame, or_df: pd.DataFrame):
    # replicate or_core decision using latest dataframes
    or_high = or_df["high"].max(); or_low = or_df["low"].min()
    or_rng = or_high - or_low
    bottom_cut = or_low + BOT_PCT * or_rng
    top_cut    = or_high - TOP_PCT * or_rng
    e = win_df.loc[win_df.index.time == pd.Timestamp(ENTRY_T).time(), "close"]
    if e.empty:
        return None, "missing_entry"
    entry = float(e.iloc[0])
    if entry >= top_cut:
        return ("long", entry, entry - SL_PTS, entry + TP_PTS), "long"
    elif entry <= bottom_cut:
        return ("short", entry, entry + SL_PTS, entry - TP_PTS), "short"
    return None, "none"


def main_loop():
    last_trade_date = None
    while True:
        try:
            ny_now = now_ny()
            if ny_now.weekday() >= 5:  # skip weekends
                time.sleep(60); continue

            df = data_feed.fetch_m1(count=200)
            slice_win = data_feed.latest_slice(df, OR_START, EXIT_T)
            slice_or  = data_feed.latest_slice(df, OR_START, OR_END)

            # ensure indexes are time-aware for selection
            slice_win = slice_win.copy(); slice_or = slice_or.copy()
            slice_win.index = pd.to_datetime(slice_win["time_ny"])
            slice_or.index  = pd.to_datetime(slice_or["time_ny"])

            has_entry = any(slice_win.index.time == pd.Timestamp(ENTRY_T).time())
            has_exit  = any(slice_win.index.time == pd.Timestamp(EXIT_T).time())
            if not has_entry or not has_exit:
                log("Skipping (missing entry/exit bar)"); time.sleep(60); continue

            trade_date = ny_now.date()
            if last_trade_date == trade_date:
                time.sleep(30); continue

            if ny_now.time() < pd.Timestamp(ENTRY_T).time():
                time.sleep(30); continue

            # compute signal
            sig, reason = compute_signal(slice_win, slice_or)
            if sig is None:
                log(f"No trade ({reason})"); last_trade_date = trade_date; time.sleep(60); continue

            side, entry, sl, tp = sig
            log(f"Signal {side} @ {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")

            if PLACE_ORDERS:
                units = int(POSITION_SIZE) if side == "long" else -int(POSITION_SIZE)
                resp = broker_oanda.submit_market_with_sl_tp(units=units, sl_price=sl, tp_price=tp)
                log(f"Order placed: {resp}")
            else:
                log("PLACE_ORDERS=False -> log-only mode")

            last_trade_date = trade_date

            # monitor until 12:00 for flat (simplified: if PLACE_ORDERS False, just sleep)
            while now_ny().time() < pd.Timestamp(EXIT_T).time():
                time.sleep(30)
            if PLACE_ORDERS:
                closed = broker_oanda.close_all_trades()
                log(f"Hard exit close_all: {closed}")
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main_loop()
