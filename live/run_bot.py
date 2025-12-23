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
from live import notifier, plotting
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
    env_short = "Live" if "fxtrade" in broker_oanda.OANDA_API_BASE else "Practice"
    return (
        f"Session OR {OR_START}-{OR_END} NY, entry {ENTRY_T}, exit {EXIT_T}; "
        f"inst={broker_oanda.OANDA_INSTRUMENT} env={env_short}; "
        f"size={POSITION_SIZE} pt_val=${POINT_VAL:.2f}; "
        f"zones {TOP_PCT:.2f}/{BOT_PCT:.2f} SL={SL_PTS} TP={TP_PTS}; "
        f"orders={'ON' if PLACE_ORDERS else 'OFF'}"
    )


def compute_signal(win_df: pd.DataFrame, or_df: pd.DataFrame):
    # replicate or_core decision using latest dataframes
    or_high = or_df["high"].max(); or_low = or_df["low"].min()
    or_rng = or_high - or_low
    bottom_cut = or_low + BOT_PCT * or_rng
    top_cut    = or_high - TOP_PCT * or_rng
    
    e_rows = win_df.loc[win_df.index.time == ENTRY_T_T]
    if e_rows.empty:
        return None, "missing_entry"
    # Ensure parity with historical data: only trade on completed candles
    if "complete" in e_rows.columns and not e_rows.iloc[0]["complete"]:
        return None, "entry_incomplete"
    entry = float(e_rows.iloc[0]["close"])
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
    
    # Calculate MFE/MAE
    if exit_ts:
        trade_path = path.loc[:exit_ts]
    else:
        trade_path = path
    
    mfe, mae = 0.0, 0.0
    if not trade_path.empty:
        if side == "long":
            mfe = trade_path["high"].max() - entry
            mae = entry - trade_path["low"].min()
        else:
            mfe = entry - trade_path["low"].min()
            mae = trade_path["high"].max() - entry

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
        "mfe": mfe,
        "mae": mae,
    }


def main_loop():
    last_trade_date = None
    last_heartbeat_at = None
    summary = {"signals": 0, "orders": 0, "skipped": 0, "errors": 0, "last_signal": None}
    summary_path = Path(__file__).resolve().parent / "logs" / "summaries"
    summary_path.mkdir(parents=True, exist_ok=True)
    trade_log_path = summary_path / "trade_days.csv"
    summary_flushed_for = None
    or_announced_for = None
    session_announced_for = None
    start_account_snapshot = None
    or_expected_rows = len(pd.date_range(pd.Timestamp(OR_START), pd.Timestamp(OR_END), freq="min"))
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
            
            # Wait until the entry candle is fully closed (ENTRY_T + 1 minute)
            # e.g. if Entry is 10:22, we wait until 10:23:00 to ensure we have the final close.
            entry_wait_dt = NY.localize(datetime.combine(trade_date, ENTRY_T_T)) + timedelta(minutes=1)
            
            # Check for missing entry bar only after a buffer (e.g. 5 mins) to allow for latency/retries
            if ny_now > (entry_wait_dt + timedelta(minutes=5)) and not has_entry:
                if trade_date not in skipped_days:
                    skipped_days[trade_date] = "missing_entry_bar"
                    summary["skipped"] += 1
                    logger.warning(f"Skipping day (missing entry bar {ENTRY_T} after 5m wait)")
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
                
                # OR is valid; announce levels if not yet done
                if trade_date not in skipped_days and or_announced_for != trade_date:
                    or_rng = or_high - or_low
                    t_cut = or_high - TOP_PCT * or_rng
                    b_cut = or_low + BOT_PCT * or_rng
                    msg = (f"OR Levels {OR_START}-{OR_END}: {or_low:.2f}-{or_high:.2f} | "
                           f"Long > {t_cut:.2f} | Short < {b_cut:.2f}")
                    logger.info(msg)
                    
                    # Generate OR Chart
                    img_buf = None
                    try:
                        img_buf = plotting.create_or_chart(
                            slice_or, trade_date, or_high, or_low, t_cut, b_cut
                        )
                    except Exception:
                        logger.exception("Failed to generate OR chart")

                    try:
                        notifier.notify_trade(msg, image_buffer=img_buf)
                    except Exception:
                        logger.exception("Notifier error OR levels")
                    or_announced_for = trade_date

            if last_trade_date == trade_date:
                time.sleep(30); continue

            if ny_now < entry_wait_dt:
                time.sleep(10); continue

            # Safety: Don't enter trades if the session is already over (e.g. late start)
            if ny_now.time() >= EXIT_T_T:
                logger.warning(f"Current time {ny_now.strftime('%H:%M')} is past hard exit {EXIT_T}. Skipping trade entry.")
                last_trade_date = trade_date
                summary["skipped"] += 1
                handled_days.add(trade_date)
                time.sleep(60)
                continue

            # compute signal
            sig, reason = compute_signal(slice_win, slice_or)
            if sig is None:
                if reason == "entry_incomplete":
                    logger.info(f"Entry candle {ENTRY_T} present but not complete; waiting...")
                    time.sleep(10)
                    continue
                logger.info(f"No trade ({reason})")
                # Optional: Tweet that no trade was taken
                try:
                    notifier.notify_trade(f"No trade taken ({reason})")
                except Exception:
                    logger.exception("Notifier error no trade")
                last_trade_date = trade_date
                summary["skipped"] += 1
                handled_days.add(trade_date)
                time.sleep(60)
                continue

            side, entry, sl, tp = sig
            logger.info(f"Signal {side} @ {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")
            summary["signals"] += 1
            summary["last_signal"] = f"{trade_date} {side} {entry:.2f}"

            order_active = False
            if PLACE_ORDERS:
                # Scale units by POINT_VAL so OANDA PnL matches the $80/pt risk model
                qty = int(POSITION_SIZE * POINT_VAL)
                units = qty if side == "long" else -qty
                resp = broker_oanda.submit_market_with_sl_tp(units=units, sl_price=sl, tp_price=tp)
                
                # Check if order was immediately rejected (e.g. INSUFFICIENT_MARGIN)
                if "orderCancelTransaction" in resp:
                    cancel_reason = resp["orderCancelTransaction"].get("reason", "UNKNOWN")
                    if cancel_reason == "INSUFFICIENT_MARGIN":
                        acct = broker_oanda.get_account_summary()
                        margin_avail = acct.get("margin_available", 0)
                        ccy = acct.get("currency", "")
                        err_msg = (f"TRADE REJECTED: Insufficient Margin. "
                                   f"Req Units: {abs(units)} (~${abs(units)*entry:,.0f} value). "
                                   f"Margin Avail: {margin_avail:,.2f} {ccy}. "
                                   "Strategy requires more capital for this size.")
                        logger.error(err_msg)
                        notifier.notify_trade(f"CRITICAL: {err_msg}")
                    else:
                        logger.error(f"Order rejected: {cancel_reason}")
                else:
                    # Order accepted
                    order_active = True
                    logger.info(f"Order placed: {resp}")
                    summary["orders"] += 1
                    try:
                        notifier.notify_trade(f"Paper trade {side.upper()} @ {entry:.2f} SL {sl:.2f} TP {tp:.2f} ({trade_date})")
                    except Exception:
                        logger.exception("Notifier error while posting trade")
            else:
                logger.info("PLACE_ORDERS=False -> log-only mode")

            last_trade_date = trade_date

            # Monitor the trade until it's closed by SL/TP or until the hard exit time.
            if PLACE_ORDERS and order_active:
                logger.info("Monitoring open trade for SL/TP or 12:00 hard exit.")
                trade_closed_by_broker = False
                while now_ny().time() < EXIT_T_T:
                    time.sleep(30)  # Check every 30 seconds
                    try:
                        open_trades = broker_oanda.get_open_trades()
                        if not open_trades:
                            logger.info("Trade closed by broker (SL/TP hit).")
                            trade_closed_by_broker = True
                            break
                    except Exception:
                        logger.exception("Failed to check open trades during monitoring. Assuming trade is still open.")
                
                if not trade_closed_by_broker:
                    logger.info(f"Hard exit time {EXIT_T} reached. Closing any open trades.")
                    closed = broker_oanda.close_all_trades()
                    logger.info(f"Hard exit close_all: {closed}")
                    try:
                        count = len(closed)
                        notifier.notify_trade(f"Paper trade exit @ {EXIT_T} NY; forced flat. Closed {count} positions.")
                    except Exception:
                        logger.exception("Notifier error while posting exit")
                
                # Post-trade MFE/MAE analysis
                try:
                    # Fetch data covering the trade duration (Entry -> Now)
                    # Use a buffer (400 candles) to ensure we cover the start
                    df_post = data_feed.fetch_m1(count=400)
                    dt_entry = pd.Timestamp.combine(trade_date, ENTRY_T_T).tz_localize(NY)
                    dt_exit_actual = now_ny()
                    
                    # Filter for trade window (excluding entry bar itself to see subsequent price action)
                    mask = (df_post["time_ny"] > dt_entry) & (df_post["time_ny"] <= dt_exit_actual)
                    df_trade = df_post.loc[mask]
                    
                    if not df_trade.empty:
                        if side == "long":
                            mfe = df_trade["high"].max() - entry
                            mae = entry - df_trade["low"].min()
                        else:
                            mfe = entry - df_trade["low"].min()
                            mae = df_trade["high"].max() - entry
                        
                        stats_msg = f"Trade Stats: MFE +{mfe:.2f} pts | MAE -{mae:.2f} pts"
                        logger.info(stats_msg)
                        
                        # Generate Chart
                        try:
                            img_buf = plotting.create_trade_chart(
                                df_trade, trade_date, ENTRY_T_T, now_ny(), 
                                entry, float(df_trade.iloc[-1]["close"]), side, 
                                or_high, or_low, sl, tp, mfe, mae
                            )
                            notifier.notify_trade(stats_msg, image_buffer=img_buf)
                        except Exception:
                            logger.exception("Failed to generate/post chart")
                    else:
                        logger.warning("Trade duration too short or candle data delayed; skipping MFE/MAE stats.")
                except Exception:
                    logger.exception("Failed to calculate MFE/MAE")
            else: # If not placing orders, just wait until exit time as before
                while now_ny().time() < EXIT_T_T:
                    time.sleep(30)

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
        
        # Consolidated Report Builder
        report_lines = []
        img_buf = None
        or_chart_buf = None
        
        # Extract date for report/chart
        r_date = datetime.now().date()
        try:
             r_date = pd.to_datetime(Path(REPLAY_FILE).stem.replace("replay_", "")).date()
        except Exception:
             pass

        # 1. Session Info
        overview = format_session_overview()
        report_lines.append("--- SESSION LIVE ---")
        report_lines.append(f"{overview}")
        report_lines.append("Account: [BALANCE_START] [NAV_START] (Simulated)")

        # Parity check: Ensure OR has full data, just like main_loop
        or_expected_rows = len(pd.date_range(pd.Timestamp(OR_START), pd.Timestamp(OR_END), freq="min"))
        if len(slice_or) != or_expected_rows:
            logger.warning(f"Replay: OR incomplete (rows={len(slice_or)} expected={or_expected_rows}); skipping to match live logic")
            report_lines.append(f"\n[SKIPPED] OR incomplete ({len(slice_or)}/{or_expected_rows} rows)")
        else:
            # 2. OR Levels
            or_high, or_low = slice_or["high"].max(), slice_or["low"].min()
            or_rng = or_high - or_low
            t_cut = or_high - TOP_PCT * or_rng
            b_cut = or_low + BOT_PCT * or_rng
            
            # Generate OR Chart
            try:
                or_chart_buf = plotting.create_or_chart(
                    slice_or, r_date, or_high, or_low, t_cut, b_cut
                )
            except Exception:
                logger.exception("Failed to generate OR chart in replay")

            report_lines.append("\n--- OR LEVELS ---")
            report_lines.append(f"Range: {or_low:.2f}-{or_high:.2f}")
            report_lines.append(f"Long > {t_cut:.2f} | Short < {b_cut:.2f}")

            has_entry = any(slice_win.index.time == ENTRY_T_T)
            if not has_entry:
                logger.warning("Replay: missing entry bar; skipping")
                report_lines.append("\n[SKIPPED] Missing entry bar")
            else:
                sig, reason = compute_signal(slice_win, slice_or)
                if sig is None:
                    logger.info(f"Replay: no trade ({reason})")
                    report_lines.append(f"\n[NO TRADE] {reason}")
                else:
                    side, entry, sl, tp = sig
                    logger.info(f"Replay: Signal {side} @ {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")
                    report_lines.append(f"\n[SIGNAL] {side.upper()} @ {entry:.2f}")
                    report_lines.append(f"SL {sl:.2f} | TP {tp:.2f}")

                    # Simulate exit/PnL on the replay window
                    res = simulate_exit(slice_win, side, entry, sl, tp)
                    logger.info(f"Replay: Exit {res['exit_reason']} @ {res['exit_px']} | pnl_pts={res['pnl_pts']} pnl_usd={res['pnl_usd']} MFE={res['mfe']:.2f} MAE={res['mae']:.2f}")
                    
                    report_lines.append(f"\n[EXIT] {res['exit_reason']} @ {res['exit_px']:.2f}")
                    report_lines.append(f"PnL: ${res['pnl_usd']:.2f} ({res['pnl_pts']:.2f} pts)")
                    report_lines.append(f"Stats: MFE +{res['mfe']:.2f} | MAE -{res['mae']:.2f}")

                    # Generate Replay Chart
                    try:
                        img_buf = plotting.create_trade_chart(
                            slice_win, r_date, 
                            ENTRY_T_T, res['exit_ts'], 
                            entry, res['exit_px'], side, 
                            slice_or["high"].max(), slice_or["low"].min(), sl, tp, res['mfe'], res['mae']
                        )
                    except Exception:
                        logger.exception("Notifier error while generating replay chart")

        # 4. Recap
        report_lines.append("\n--- RECAP ---")
        # Determine if we had a trade for stats
        had_trade = 'res' in locals() and res is not None
        pnl_val = res['pnl_usd'] if had_trade else 0.0
        report_lines.append(f"Signals: {1 if had_trade else 0} | Orders: {1 if had_trade else 0}")
        report_lines.append(f"PnL: ${pnl_val:.2f} (Simulated)")
        report_lines.append("Account: [BALANCE_END] [NAV_END] (Simulated)")

        full_report = "\n".join(report_lines)
        
        try:
            logger.info("--- CONSOLIDATED REPLAY REPORT ---\n" + full_report)
        except UnicodeEncodeError:
            # Fallback for Windows consoles that cannot print emojis
            logger.info("--- CONSOLIDATED REPLAY REPORT ---\n" + full_report.encode("ascii", "replace").decode("ascii"))

        if REPLAY_TWEETS:
            # Construct Tweet (Shortened to <280 chars to avoid 403 errors)
            tweet_lines = []
            tweet_lines.append(f"REPLAY {r_date}")
            tweet_lines.append(f"OR: {slice_or['low'].min():.2f}-{slice_or['high'].max():.2f}")
            
            if 'sig' in locals() and sig:
                side, entry, sl, tp = sig
                tweet_lines.append(f"Sig: {side.upper()} @ {entry:.2f}")
                if 'res' in locals():
                    tweet_lines.append(f"Exit: {res['exit_reason']} @ {res['exit_px']:.2f}")
                    tweet_lines.append(f"PnL: ${res['pnl_usd']:.0f} (MFE {res['mfe']:.1f}/MAE {res['mae']:.1f})")
            else:
                tweet_lines.append("No Trade")
            
            tweet_lines.append(f"Simulated at {now_ny().strftime('%H:%M:%S')} NY")
            tweet_msg = "\n".join(tweet_lines)

            try:
                charts = []
                if or_chart_buf: charts.append(or_chart_buf)
                if img_buf: charts.append(img_buf)

                res = notifier.notify_trade(tweet_msg, images=charts)
                if res and res.get("status") == "posted":
                    logger.info("Replay tweet sent.")
                else:
                    logger.warning(f"Replay tweet failed: {res.get('reason') if res else 'unknown'}")
            except Exception:
                logger.exception("Notifier error while posting replay report")

        logger.info("Replay complete.")
    else:
        main_loop()
