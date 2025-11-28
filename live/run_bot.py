"""Skeleton live/paper runner.
- Polls OANDA M1 candles.
- Builds OR (09:30–10:00 NY), decides at 10:22 using or_core logic.
- One trade/day, SL/TP attached, hard flat at 12:00.
- Log-only by default (set PLACE_ORDERS=True to call OANDA).
"""
import time, os, sys, csv
from datetime import datetime, timedelta
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
PLACE_ORDERS = True  # toggle to True when ready
POSITION_SIZE = INSTRUMENTS.get("market", {}).get("position_size", 1.0)
POINT_VAL = INSTRUMENTS.get("market", {}).get("point_value_usd", 80.0)
REPLAY_FILE = os.getenv("REPLAY_FILE")  # if set, run once on this CSV instead of live polling
REPLAY_TWEETS = os.getenv("REPLAY_TWEETS", "false").lower() == "true"

OR_START = INSTRUMENTS.get("session", {}).get("or_window", {}).get("start", "09:30")
OR_END   = INSTRUMENTS.get("session", {}).get("or_window", {}).get("end_inclusive", "10:00")
ENTRY_T  = INSTRUMENTS.get("session", {}).get("entry_time", "10:22")
EXIT_T   = INSTRUMENTS.get("session", {}).get("hard_exit_time", "12:00")
TOP_PCT  = STRATEGY.get("parameters", {}).get("zones", {}).get("top_pct", 0.35)
BOT_PCT  = STRATEGY.get("parameters", {}).get("zones", {}).get("bottom_pct", 0.35)
SL_PTS   = STRATEGY.get("parameters", {}).get("risk", {}).get("stop_loss_points", 25)
TP_PTS   = STRATEGY.get("parameters", {}).get("risk", {}).get("take_profit_points", 75)

OR_START_T = pd.Timestamp(OR_START).time()
OR_END_T = pd.Timestamp(OR_END).time()
ENTRY_T_T = pd.Timestamp(ENTRY_T).time()
EXIT_T_T = pd.Timestamp(EXIT_T).time()


def now_ny():
    return datetime.now(tz=NY)


def format_session_overview() -> str:
    """Human-friendly summary of the configured session for logs/alerts."""
    return (
        f"Session OR {OR_START}-{OR_END} NY, entry {ENTRY_T}, exit {EXIT_T}; "
        f"instrument={broker_oanda.OANDA_INSTRUMENT} env={broker_oanda.OANDA_API_BASE}; "
        f"size={POSITION_SIZE} point_val=${POINT_VAL:.2f}; "
        f"zones top_pct={TOP_PCT:.2f} bottom_pct={BOT_PCT:.2f} SL={SL_PTS} TP={TP_PTS}; "
        f"orders={'ON' if PLACE_ORDERS else 'OFF'}"
    )


def compute_signal(win_df: pd.DataFrame, or_df: pd.DataFrame):
    # replicate or_core decision using latest dataframes
    or_high = or_df["high"].max(); or_low = or_df["low"].min()
    or_rng = or_high - or_low
    bottom_cut = or_low + BOT_PCT * or_rng
    top_cut    = or_high - TOP_PCT * or_rng
    e = win_df.loc[win_df.index.time == ENTRY_T_T, "close"]
    if e.empty:
        return None, "missing_entry"
    entry = float(e.iloc[0])
    if entry >= top_cut:
        return ("long", entry, entry - SL_PTS, entry + TP_PTS), "long"
    elif entry <= bottom_cut:
        return ("short", entry, entry + SL_PTS, entry - TP_PTS), "short"
    return None, "none"


def simulate_exit(win_df: pd.DataFrame, side: str, entry: float, sl: float, tp: float):
    """Walk bars after entry to find TP/SL/time exit (similar to execute_day)."""
    path = win_df.loc[win_df.index.time > ENTRY_T_T].copy()
    exit_ts = None
    exit_px = None
    exit_reason = None

    if side == "long":
        for ts, row in path.iterrows():
            hi, lo = float(row["high"]), float(row["low"])
            touched_tp = hi >= tp
            touched_sl = lo <= sl
            if touched_tp and touched_sl:
                exit_ts, exit_px, exit_reason = ts, sl, "sl"; break
            elif touched_sl:
                exit_ts, exit_px, exit_reason = ts, sl, "sl"; break
            elif touched_tp:
                exit_ts, exit_px, exit_reason = ts, tp, "tp"; break
    elif side == "short":
        for ts, row in path.iterrows():
            hi, lo = float(row["high"]), float(row["low"])
            touched_tp = lo <= tp
            touched_sl = hi >= sl
            if touched_tp and touched_sl:
                exit_ts, exit_px, exit_reason = ts, sl, "sl"; break
            elif touched_sl:
                exit_ts, exit_px, exit_reason = ts, sl, "sl"; break
            elif touched_tp:
                exit_ts, exit_px, exit_reason = ts, tp, "tp"; break

    if exit_ts is None:
        if not path.empty:
            exit_ts = path.index.max()
            exit_px = float(path.loc[exit_ts, "close"])
            exit_reason = "time"
    pnl_pts = None
    pnl_usd = None
    if exit_px is not None:
        pnl_pts = float(exit_px - entry) if side == "long" else float(entry - exit_px)
        pnl_usd = pnl_pts * POINT_VAL * POSITION_SIZE
    return {
        "exit_ts": exit_ts,
        "exit_px": exit_px,
        "exit_reason": exit_reason,
        "pnl_pts": pnl_pts,
        "pnl_usd": pnl_usd,
    }


def main_loop():
    last_trade_date = None
    last_heartbeat_at = None
    summary = {"signals": 0, "orders": 0, "skipped": 0, "errors": 0, "last_signal": None}
    summary_path = Path(__file__).resolve().parent / "logs" / "summaries"
    summary_path.mkdir(parents=True, exist_ok=True)
    trade_log_path = summary_path / "trade_days.csv"
    summary_flushed_for = None
    session_announced_for = None
    start_account_snapshot = None
    or_expected_rows = len(pd.date_range(pd.Timestamp(OR_START), pd.Timestamp(OR_END), freq="T"))
    skipped_days = {}
    session_started_for = None
    handled_days = set()

    # Pre-open status
    try:
        overview = format_session_overview()
        logger.info(f"STARTUP {overview}")
        notifier.notify_trade(f"Bot ready: {overview}")
    except Exception:
        logger.exception("Notifier error while posting pre-open status")
    while True:
        try:
            fetch_latency_ms = None
            ny_now = now_ny()
            if ny_now.weekday() >= 5:  # skip weekends
                time.sleep(60); continue

            in_session_window = OR_START_T <= ny_now.time() <= EXIT_T_T
            if in_session_window and session_announced_for != ny_now.date():
                logger.info(f"SESSION_START {format_session_overview()}")
                session_announced_for = ny_now.date()
                try:
                    # If the bot restarted mid-session, ensure we are flat
                    open_trades = broker_oanda.get_open_trades()
                    if open_trades:
                        logger.warning(f"Found {len(open_trades)} open trades at session start; closing them.")
                        broker_oanda.close_all_trades()
                    start_account_snapshot = broker_oanda.get_account_summary()
                    session_started_for = ny_now.date()
                    logger.info(
                        "SESSION_ACCOUNT_START "
                        f"balance={start_account_snapshot['balance']:.2f} "
                        f"nav={start_account_snapshot['nav']:.2f} "
                        f"utpl={start_account_snapshot['unrealized_pl']:.2f} "
                        f"open_trades={start_account_snapshot['open_trade_count']} "
                        f"ccy={start_account_snapshot['currency']}"
                    )
                    notifier.notify_trade(f"Session live: {format_session_overview()}")
                except Exception:
                    logger.exception("Could not fetch account summary at session start")

            fetch_started = datetime.utcnow()
            df = data_feed.fetch_m1(count=400)
            fetch_latency_ms = int((datetime.utcnow() - fetch_started).total_seconds() * 1000)
            slice_win = data_feed.latest_slice(df, OR_START, EXIT_T)
            slice_or  = data_feed.latest_slice(df, OR_START, OR_END)

            # ensure indexes are time-aware for selection
            slice_win = slice_win.copy(); slice_or = slice_or.copy()
            slice_win.index = pd.to_datetime(slice_win["time_ny"])
            slice_or.index  = pd.to_datetime(slice_or["time_ny"])

            trade_date = ny_now.date()
            if trade_date in skipped_days or trade_date in handled_days:
                # Already decided to skip/handle this trade day; keep heartbeats only.
                time.sleep(60); continue

            # Heartbeat cadence: 10m during session window, hourly otherwise
            hb_interval = timedelta(minutes=10) if in_session_window else timedelta(hours=1)
            if (not last_heartbeat_at) or (ny_now - last_heartbeat_at >= hb_interval):
                hb_open_trades = []
                try:
                    hb_open_trades = broker_oanda.get_open_trades()
                except Exception:
                    logger.exception("Heartbeat: failed to fetch open trades")
                last_ts = slice_win.index.max() if not slice_win.empty else None
                last_px = float(slice_win.loc[last_ts, "close"]) if last_ts is not None else None
                logger.info(
                    f"HEARTBEAT alive latency_ms={fetch_latency_ms} "
                    f"last_bar={last_ts} last_px={last_px} open_trades={len(hb_open_trades)}"
                )
                last_heartbeat_at = ny_now

            has_entry = any(slice_win.index.time == ENTRY_T_T)
            has_exit  = any(slice_win.index.time == EXIT_T_T)
            if ny_now.time() >= ENTRY_T_T and not has_entry:
                if trade_date not in skipped_days:
                    skipped_days[trade_date] = "missing_entry_bar"
                    summary["skipped"] += 1
                    logger.warning(f"Skipping day (missing entry bar {ENTRY_T})")
                    handled_days.add(trade_date)
                    last_trade_date = trade_date
                time.sleep(60); continue
            if ny_now.time() >= EXIT_T_T and not has_exit:
                if trade_date not in skipped_days:
                    skipped_days[trade_date] = "missing_exit_bar"
                    summary["skipped"] += 1
                    logger.warning(f"Skipping day (missing exit bar {EXIT_T})")
                    handled_days.add(trade_date)
                    last_trade_date = trade_date
                time.sleep(60); continue

            # OR completeness / zero-range guard
            if ny_now.time() >= OR_END_T:
                if len(slice_or) != or_expected_rows:
                    if trade_date not in skipped_days:
                        skipped_days[trade_date] = "or_incomplete"
                        summary["skipped"] += 1
                        logger.warning(f"Skipping day (OR incomplete rows={len(slice_or)} expected={or_expected_rows})")
                        handled_days.add(trade_date)
                        last_trade_date = trade_date
                    time.sleep(60); continue
                or_high, or_low = slice_or["high"].max(), slice_or["low"].min()
                if or_high == or_low:
                    if trade_date not in skipped_days:
                        skipped_days[trade_date] = "or_zero_range"
                        summary["skipped"] += 1
                        logger.warning("Skipping day (OR range zero)")
                        handled_days.add(trade_date)
                        last_trade_date = trade_date
                    time.sleep(60); continue

            if last_trade_date == trade_date:
                time.sleep(30); continue

            if ny_now.time() < ENTRY_T_T:
                time.sleep(30); continue

            # compute signal
            sig, reason = compute_signal(slice_win, slice_or)
            if sig is None:
                logger.info(f"No trade ({reason})")
                last_trade_date = trade_date
                summary["skipped"] += 1
                handled_days.add(trade_date)
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
            while now_ny().time() < EXIT_T_T:
                time.sleep(30)
            if PLACE_ORDERS:
                closed = broker_oanda.close_all_trades()
                logger.info(f"Hard exit close_all: {closed}")
                try:
                    notifier.notify_trade(f"Paper trade exit @ {EXIT_T} NY; forced flat. Details: {closed}")
                except Exception:
                    logger.exception("Notifier error while posting exit")
        except Exception as e:
            logger.exception(f"Error: {e} (last fetch latency_ms={fetch_latency_ms})")
            summary["errors"] += 1
            time.sleep(60)
        finally:
            # Flush summary after exit window (post 12:05 NY) once per trade_date
            ny_now = now_ny()
            after_exit = ny_now.time() >= EXIT_T_T
            if after_exit and last_trade_date and summary_flushed_for != last_trade_date and session_started_for == last_trade_date:
                fname = summary_path / f"{last_trade_date}_summary.log"
                end_snapshot = None
                try:
                    end_snapshot = broker_oanda.get_account_summary()
                    pnl_nav = None
                    pnl_bal = None
                    if start_account_snapshot:
                        pnl_nav = end_snapshot["nav"] - start_account_snapshot.get("nav", 0.0)
                        pnl_bal = end_snapshot["balance"] - start_account_snapshot.get("balance", 0.0)
                    pnl_nav_disp = f"{pnl_nav:+.2f}" if pnl_nav is not None else "n/a"
                    pnl_bal_disp = f"{pnl_bal:+.2f}" if pnl_bal is not None else "n/a"
                    logger.info(
                        "SESSION_ACCOUNT_END "
                        f"balance={end_snapshot['balance']:.2f} "
                        f"nav={end_snapshot['nav']:.2f} "
                        f"utpl={end_snapshot['unrealized_pl']:.2f} "
                        f"open_trades={end_snapshot['open_trade_count']} "
                        f"ccy={end_snapshot['currency']} "
                        f"pnl_nav={pnl_nav_disp} "
                        f"pnl_bal={pnl_bal_disp}"
                    )
                except Exception:
                    logger.exception("Could not fetch account summary at session end")
                pnl_nav_str = ""
                if end_snapshot and start_account_snapshot:
                    pnl_nav = end_snapshot["nav"] - start_account_snapshot.get("nav", 0.0)
                    pnl_bal = end_snapshot["balance"] - start_account_snapshot.get("balance", 0.0)
                    pnl_nav_str = f" nav {start_account_snapshot.get('nav', 0.0):.2f}->{end_snapshot['nav']:.2f} ({pnl_nav:+.2f})"
                    pnl_nav_str += f" bal {start_account_snapshot.get('balance', 0.0):.2f}->{end_snapshot['balance']:.2f} ({pnl_bal:+.2f})"
                msg = (f"date={last_trade_date} signals={summary['signals']} orders={summary['orders']} "
                       f"skipped={summary['skipped']} errors={summary['errors']} last={summary['last_signal']}{pnl_nav_str}")
                logger.info(f"SESSION_END {msg}")
                # Persist daily summary CSV for quick review
                headers = [
                    "date", "signals", "orders", "skipped", "errors", "last_signal",
                    "balance_start", "nav_start", "balance_end", "nav_end",
                    "pnl_balance", "pnl_nav", "open_trades_end", "currency",
                ]
                row = {
                    "date": last_trade_date,
                    "signals": summary["signals"],
                    "orders": summary["orders"],
                    "skipped": summary["skipped"],
                    "errors": summary["errors"],
                    "last_signal": summary["last_signal"],
                    "balance_start": start_account_snapshot.get("balance") if start_account_snapshot else None,
                    "nav_start": start_account_snapshot.get("nav") if start_account_snapshot else None,
                    "balance_end": end_snapshot.get("balance") if end_snapshot else None,
                    "nav_end": end_snapshot.get("nav") if end_snapshot else None,
                    "pnl_balance": pnl_bal if start_account_snapshot and end_snapshot else None,
                    "pnl_nav": pnl_nav if start_account_snapshot and end_snapshot else None,
                    "open_trades_end": end_snapshot.get("open_trade_count") if end_snapshot else None,
                    "currency": end_snapshot.get("currency") if end_snapshot else None,
                }
                write_header = not trade_log_path.exists()
                with open(trade_log_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=headers)
                    if write_header:
                        writer.writeheader()
                    writer.writerow(row)
                with open(fname, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
                logger.info(f"Wrote daily summary: {msg}")
                try:
                    notifier.notify_trade(
                        f"Recap {last_trade_date}: "
                        f"signals {summary['signals']}, orders {summary['orders']}, skipped {summary['skipped']}, errors {summary['errors']} |"
                        f"{pnl_nav_str}"
                    )
                except Exception:
                    logger.exception("Notifier error while posting recap")
                summary = {"signals": 0, "orders": 0, "skipped": 0, "errors": 0, "last_signal": None}
                summary_flushed_for = last_trade_date
                start_account_snapshot = None
                session_started_for = None


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
        has_entry = any(slice_win.index.time == ENTRY_T_T)
        has_exit  = any(slice_win.index.time == EXIT_T_T)
        if not has_entry or not has_exit:
            logger.warning("Replay: missing entry/exit bar; skipping")
            if REPLAY_TWEETS:
                try:
                    notifier.notify_trade(f"[REPLAY] Skipped {REPLAY_FILE}: missing entry/exit bar")
                except Exception:
                    logger.exception("Notifier error while posting replay skip")
        else:
            sig, reason = compute_signal(slice_win, slice_or)
            if sig is None:
                logger.info(f"Replay: no trade ({reason})")
                if REPLAY_TWEETS:
                    try:
                        notifier.notify_trade(f"[REPLAY] No trade ({reason}) from {REPLAY_FILE}")
                    except Exception:
                        logger.exception("Notifier error while posting replay no-trade")
            else:
                side, entry, sl, tp = sig
                logger.info(f"Replay: Signal {side} @ {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")
                # Simulate exit/PnL on the replay window
                res = simulate_exit(slice_win, side, entry, sl, tp)
                logger.info(f"Replay: Exit {res['exit_reason']} @ {res['exit_px']} | pnl_pts={res['pnl_pts']} pnl_usd={res['pnl_usd']}")
                if REPLAY_TWEETS:
                    try:
                        replay_date = pd.to_datetime(REPLAY_FILE).date() if REPLAY_FILE else None
                        msg = (f"[REPLAY {replay_date}] {side.upper()} @ {entry:.2f} SL {sl:.2f} TP {tp:.2f} "
                               f"-> exit {res['exit_reason']} @ {res['exit_px']} "
                               f"pnl {res['pnl_pts']} pts / ${res['pnl_usd']}")
                        notifier.notify_trade(msg)
                    except Exception:
                        logger.exception("Notifier error while posting replay signal")
        logger.info("Replay complete.")
    else:
        main_loop()
