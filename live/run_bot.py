"""Skeleton live/paper runner.
- Polls OANDA M1 candles.
- Builds OR (09:30–10:00 NY), decides at 10:22 using or_core logic.
- One trade/day, SL/TP attached, hard flat at 12:00.
- Log-only by default (set PLACE_ORDERS=True to call OANDA).
"""
import time, os, sys
from datetime import datetime
import pytz
import pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from live import data_feed, broker_oanda
from live import notifier
from live.config import INSTRUMENTS, STRATEGY, OANDA_TIMEZONE
from live.logging_utils import setup_logger
from src import or_core

NY = pytz.timezone(OANDA_TIMEZONE)
logger = setup_logger("bot")
PLACE_ORDERS = False  # toggle to True when ready
POSITION_SIZE = INSTRUMENTS.get("market", {}).get("position_size", 1.0)
POINT_VAL = INSTRUMENTS.get("market", {}).get("point_value_usd", 80.0)
REPLAY_FILE = os.getenv("REPLAY_FILE")  # if set, run once on this CSV instead of live polling

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
    last_heartbeat_min = None
    summary = {"signals": 0, "orders": 0, "skipped": 0, "errors": 0, "last_signal": None}
    summary_path = Path(__file__).resolve().parent / "logs" / "summaries"
    summary_path.mkdir(parents=True, exist_ok=True)
    summary_flushed_for = None

    # Pre-open status
    try:
        notifier.notify_trade(f"Bot ready (orders={'ON' if PLACE_ORDERS else 'OFF'}), watching OR {OR_START}-{OR_END} NY, entry {ENTRY_T}, exit {EXIT_T}.")
    except Exception:
        logger.exception("Notifier error while posting pre-open status")
    while True:
        try:
            ny_now = now_ny()
            if ny_now.weekday() >= 5:  # skip weekends
                time.sleep(60); continue

            # Heartbeat once per minute
            if last_heartbeat_min != ny_now.minute:
                logger.info("HEARTBEAT alive")
                last_heartbeat_min = ny_now.minute

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
                logger.warning("Skipping (missing entry/exit bar)")
                summary["skipped"] += 1
                time.sleep(60); continue

            trade_date = ny_now.date()
            if last_trade_date == trade_date:
                time.sleep(30); continue

            if ny_now.time() < pd.Timestamp(ENTRY_T).time():
                time.sleep(30); continue

            # compute signal
            sig, reason = compute_signal(slice_win, slice_or)
            if sig is None:
                logger.info(f"No trade ({reason})")
                last_trade_date = trade_date
                summary["skipped"] += 1
                time.sleep(60)
                continue

            side, entry, sl, tp = sig
            logger.info(f"Signal {side} @ {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")
            summary["signals"] += 1
            summary["last_signal"] = f"{trade_date} {side} {entry:.2f}"

            if PLACE_ORDERS:
                units = int(POSITION_SIZE) if side == "long" else -int(POSITION_SIZE)
                resp = broker_oanda.submit_market_with_sl_tp(units=units, sl_price=sl, tp_price=tp)
                logger.info(f"Order placed: {resp}")
                summary["orders"] += 1
                try:
                    notifier.notify_trade(f"Paper trade {side.upper()} @ {entry:.2f} SL {sl:.2f} TP {tp:.2f} ({trade_date})")
                except Exception:
                    logger.exception("Notifier error while posting trade")
            else:
                logger.info("PLACE_ORDERS=False -> log-only mode")

            last_trade_date = trade_date

            # monitor until 12:00 for flat (simplified: if PLACE_ORDERS False, just sleep)
            while now_ny().time() < pd.Timestamp(EXIT_T).time():
                time.sleep(30)
            if PLACE_ORDERS:
                closed = broker_oanda.close_all_trades()
                logger.info(f"Hard exit close_all: {closed}")
                try:
                    notifier.notify_trade(f"Paper trade exit @ {EXIT_T} NY; forced flat. Details: {closed}")
                except Exception:
                    logger.exception("Notifier error while posting exit")
        except Exception as e:
            logger.exception(f"Error: {e}")
            summary["errors"] += 1
            time.sleep(60)
        finally:
            # Flush summary after exit window (post 12:05 NY) once per trade_date
            ny_now = now_ny()
            after_exit = ny_now.time() >= pd.Timestamp(EXIT_T).time()
            if after_exit and last_trade_date and summary_flushed_for != last_trade_date:
                fname = summary_path / f"{last_trade_date}_summary.log"
                msg = (f"date={last_trade_date} signals={summary['signals']} orders={summary['orders']} "
                       f"skipped={summary['skipped']} errors={summary['errors']} last={summary['last_signal']}")
                with open(fname, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
                logger.info(f"Wrote daily summary: {msg}")
                try:
                    notifier.notify_trade(f"Daily recap {last_trade_date}: signals={summary['signals']} orders={summary['orders']} skipped={summary['skipped']} errors={summary['errors']}")
                except Exception:
                    logger.exception("Notifier error while posting recap")
                summary = {"signals": 0, "orders": 0, "skipped": 0, "errors": 0, "last_signal": None}
                summary_flushed_for = last_trade_date


if __name__ == "__main__":
    if REPLAY_FILE:
        logger.info(f"Replay mode from {REPLAY_FILE}")
        df = pd.read_csv(REPLAY_FILE)
        # Ensure time_ny is parsed and tz-aware
        if "time_ny" in df.columns:
            df["time_ny"] = pd.to_datetime(df["time_ny"]).dt.tz_convert(NY)
        elif "time" in df.columns:
            df["time_ny"] = pd.to_datetime(df["time"]).dt.tz_localize("UTC").dt.tz_convert(NY)
        df = df.sort_values("time_ny")
        df.index = pd.to_datetime(df["time_ny"])
        slice_win = data_feed.latest_slice(df, OR_START, EXIT_T)
        slice_or  = data_feed.latest_slice(df, OR_START, OR_END)
        has_entry = any(slice_win.index.time == pd.Timestamp(ENTRY_T).time())
        has_exit  = any(slice_win.index.time == pd.Timestamp(EXIT_T).time())
        if not has_entry or not has_exit:
            logger.warning("Replay: missing entry/exit bar; skipping")
        else:
            sig, reason = compute_signal(slice_win, slice_or)
            if sig is None:
                logger.info(f"Replay: no trade ({reason})")
            else:
                side, entry, sl, tp = sig
                logger.info(f"Replay: Signal {side} @ {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")
                try:
                    notifier.notify_trade(f"Replay {side.upper()} @ {entry:.2f} SL {sl:.2f} TP {tp:.2f} ({REPLAY_FILE})")
                except Exception:
                    logger.exception("Notifier error while posting replay signal")
        logger.info("Replay complete.")
    else:
        main_loop()
