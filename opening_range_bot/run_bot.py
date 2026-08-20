"""Skeleton live and paper runner.
- Polls OANDA M1 candles.
- Builds OR (09:30–10:00 NY), decides at 10:22 using or_core logic.
- One trade/day, SL/TP attached, hard flat at 12:00.
- Log-only by default (set PLACE_ORDERS=True to call OANDA).
"""
import time, os, sys, csv, json
from datetime import datetime, timedelta
import pytz
import pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from opening_range_bot import data_feed, broker_oanda
from opening_range_bot import notifier, plotting, tweet_formatter
from opening_range_bot.config import INSTRUMENTS, STRATEGY, OANDA_ENV, OANDA_TIMEZONE
from opening_range_bot.logging_utils import setup_logger
from src import or_core
from opening_range_bot.trade_types import DailyLog, SessionSetup, SignalDecision, TradeResult
NY = pytz.timezone(OANDA_TIMEZONE)
logger = setup_logger("bot")
PLACE_ORDERS = True  # toggle to True when ready
POSITION_SIZE = INSTRUMENTS.get("market", {}).get("position_size", 1.0)
POINT_VAL = INSTRUMENTS.get("market", {}).get("point_value_usd", 80.0)
REPLAY_FILE = os.getenv("REPLAY_FILE")  # if set, run once on this CSV instead of live polling
REPLAY_TWEETS = os.getenv("REPLAY_TWEETS", "false").lower() == "true"
# Cloud Run Jobs run one market session and must terminate after its final recap.
# The default remains the existing always-on VM/container behavior.
RUN_SINGLE_SESSION = os.getenv("RUN_SINGLE_SESSION", "false").lower() == "true"

OR_START = INSTRUMENTS.get("session", {}).get("or_window", {}).get("start", "09:30")
OR_END   = INSTRUMENTS.get("session", {}).get("or_window", {}).get("end_inclusive", "10:00")
ENTRY_T  = INSTRUMENTS.get("session", {}).get("entry_time", "10:22")
EXIT_T   = INSTRUMENTS.get("session", {}).get("hard_exit_time", "12:00")
TOP_PCT  = STRATEGY.get("parameters", {}).get("zones", {}).get("top_pct", 0.35)
BOT_PCT  = STRATEGY.get("parameters", {}).get("zones", {}).get("bottom_pct", 0.35)
SL_PTS   = STRATEGY.get("parameters", {}).get("risk", {}).get("stop_loss_points", 25)
TP_PTS   = STRATEGY.get("parameters", {}).get("risk", {}).get("take_profit_points", 75)
OR_INCOMPLETE_TOLERANCE = 2  # How many missing candles to tolerate in OR window before skipping.

OR_START_T = pd.Timestamp(OR_START).time()
OR_END_T = pd.Timestamp(OR_END).time()
ENTRY_T_T = pd.Timestamp(ENTRY_T).time()
EXIT_T_T = pd.Timestamp(EXIT_T).time()


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        return super().default(obj)

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


def check_or_completeness(slice_or, or_expected_rows, trade_date, or_start, or_end, tolerance, ny_timezone):
    """
    Checks if the opening range data is complete within a tolerance.
    
    Returns:
        A tuple (log_msg, tweet_msg, should_skip)
    """
    missing_rows = or_expected_rows - len(slice_or)
    if missing_rows > 0:
        expected_ts = pd.date_range(start=f"{trade_date} {or_start}", end=f"{trade_date} {or_end}", freq="min", tz=ny_timezone)
        missing_ts = sorted(list(set(expected_ts) - set(slice_or.index)))
        missing_ts_str = ", ".join([ts.strftime('%H:%M') for ts in missing_ts])

        if missing_rows > tolerance:
            # Returns a message indicating that the day should be skipped
            log_msg = (f"Skipping day (OR incomplete rows={len(slice_or)} expected={or_expected_rows}). "
                       f"Missing: {missing_ts_str}")
            tweet_msg = f"WARNING: Skipping day (OR incomplete, missing {len(missing_ts)} candle(s) e.g. {missing_ts_str})"
            if len(tweet_msg) > 280:
                tweet_msg = tweet_msg[:277] + "..."
            return log_msg, tweet_msg, True  # Skip = True
        else:
            # Returns a warning but indicates not to skip
            log_msg = (f"OR incomplete but within tolerance (missing {missing_rows} rows: {missing_ts_str}). "
                       f"Proceeding with {len(slice_or)} candles.")
            return log_msg, None, False  # Skip = False
    return None, None, False  # No missing rows, don't skip

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculates the Average True Range (ATR) for the given DataFrame."""
    if len(df) < period + 1:
        return 0.0
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def main_loop():
    last_trade_date = None
    last_heartbeat_at = None
    summary = {"signals": 0, "orders": 0, "skipped": 0, "errors": 0, "last_signal": None}
    summary_path = ROOT / "logs" / "summaries"
    summary_path.mkdir(parents=True, exist_ok=True)
    trade_log_path = summary_path / "trade_days.csv"
    summary_flushed_for = None
    or_announced_for = None
    session_announced_for = None
    daily_details: Optional[DailyLog] = {}
    start_account_snapshot = None
    or_expected_rows = len(pd.date_range(pd.Timestamp(OR_START), pd.Timestamp(OR_END), freq="min"))
    skipped_days = {}
    session_started_for = None
    handled_days = set()
    or_chart_buf = None
    trade_chart_buf = None
    daily_outcome_reason = None

    # RECOVERY: Attempt to load existing daily_details if restarting mid-day
    try:
        today_str = str(now_ny().date())
        json_rec_path = summary_path / "daily_json" / f"{today_str}.json"
        if json_rec_path.exists():
            with open(json_rec_path, "r") as f:
                daily_details = json.load(f)
            logger.info(f"Recovered daily_details for {today_str} from disk.")
    except Exception as e:
        logger.warning(f"Could not recover existing JSON log: {e}")

    # Log startup details. Normal X cadence starts with the consolidated
    # signal post, avoiding a separate paid startup post.
    overview = format_session_overview()
    logger.info(f"STARTUP {overview}")
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
                # Mark the session before external account calls so a transient
                # account-summary failure cannot suppress the final recap.
                session_started_for = ny_now.date()
                try:
                    # If the bot restarted mid-session, ensure we are flat
                    open_trades = broker_oanda.get_open_trades()
                    if open_trades:
                        logger.warning(f"Found {len(open_trades)} open trades at session start; closing them.")
                        broker_oanda.close_all_trades()
                    start_account_snapshot = broker_oanda.get_account_summary()
                    logger.info(
                        "SESSION_ACCOUNT_START "
                        f"balance={start_account_snapshot['balance']:.2f} "
                        f"nav={start_account_snapshot['nav']:.2f} "
                        f"utpl={start_account_snapshot['unrealized_pl']:.2f} "
                        f"open_trades={start_account_snapshot['open_trade_count']} "
                        f"ccy={start_account_snapshot['currency']}"
                    )
                    # Session details are included in the consolidated signal
                    # or no-trade recap instead of a separate X post.
                except Exception:
                    logger.exception("Could not fetch account summary at session start")

            fetch_started = datetime.utcnow()
            df = data_feed.fetch_m1(count=600)
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
            
            if last_trade_date == trade_date:
                time.sleep(30); continue

            # Safety: Don't enter trades if the session is already over (e.g. late start)
            if ny_now.time() >= EXIT_T_T:
                # Safety: Ensure any lingering trades are closed if we wake up past exit time.
                # Report the closure in the single final recap instead of a
                # separate paid warning post.
                closed_lingering_trade = False
                try:
                    if broker_oanda.get_open_trades():
                        logger.warning("Found open trades past hard exit time. Closing all.")
                        broker_oanda.close_all_trades()
                        closed_lingering_trade = True
                except Exception:
                    logger.exception("Failed to check/close trades in safety block")

                msg = f"Current time {ny_now.strftime('%H:%M')} is past hard exit {EXIT_T}. Skipping trade entry."
                logger.warning(msg)
                daily_outcome_reason = (
                    "past_hard_exit_closed_lingering"
                    if closed_lingering_trade
                    else "past_hard_exit"
                )
                session_started_for = trade_date
                last_trade_date = trade_date
                summary["skipped"] += 1
                handled_days.add(trade_date)
                time.sleep(60)
                continue

            # Check for missing entry bar only after a buffer (e.g. 5 mins) to allow for latency/retries
            if ny_now > (entry_wait_dt + timedelta(minutes=5)) and not has_entry:
                if trade_date not in skipped_days:
                    skipped_days[trade_date] = "missing_entry_bar"
                    summary["skipped"] += 1
                    msg = f"Skipping day (missing entry bar {ENTRY_T} after 5m wait)"
                    logger.warning(msg)
                    daily_outcome_reason = "missing_entry_bar"
                    handled_days.add(trade_date)
                    last_trade_date = trade_date
                time.sleep(60); continue

            if ny_now.time() >= EXIT_T_T and not has_exit:
                if trade_date not in skipped_days:
                    skipped_days[trade_date] = "missing_exit_bar"
                    summary["skipped"] += 1
                    msg = f"Skipping day (missing exit bar {EXIT_T})"
                    logger.warning(msg)
                    daily_outcome_reason = "missing_exit_bar"
                    handled_days.add(trade_date)
                    last_trade_date = trade_date
                time.sleep(60); continue

            # OR completeness / zero-range guard
            if ny_now.time() >= OR_END_T:
                if trade_date not in skipped_days:
                    # Retry loop for fetching OR data
                    or_slice_is_complete = False
                    for i in range(3):  # 3 attempts
                        # On attempt > 1, re-fetch data. Otherwise, use data from main loop fetch.
                        if i > 0:
                            df = data_feed.fetch_m1(count=600)
                            slice_win = data_feed.latest_slice(df, OR_START, EXIT_T)
                            slice_or  = data_feed.latest_slice(df, OR_START, OR_END)
                            slice_win.index = pd.to_datetime(slice_win["time_ny"])
                            slice_or.index  = pd.to_datetime(slice_or["time_ny"])

                        if len(slice_or) == or_expected_rows:
                            or_slice_is_complete = True
                            if i > 0: # Log only if it wasn't complete on the first try
                                logger.info(f"OR data is complete on attempt {i+1}.")
                            break
                        else:
                            if i < 2: # Don't log retry message on the last attempt
                                logger.warning(
                                    f"OR data incomplete on attempt {i+1} "
                                    f"({len(slice_or)}/{or_expected_rows} rows). Retrying in 15s."
                                )
                                time.sleep(15)

                    log_msg, tweet_msg, should_skip = check_or_completeness(
                        slice_or, or_expected_rows, trade_date, OR_START, OR_END, 
                        OR_INCOMPLETE_TOLERANCE, NY
                    )
                    
                    if should_skip:
                        skipped_days[trade_date] = "or_incomplete"
                        summary["skipped"] += 1
                        logger.warning(log_msg)
                        daily_outcome_reason = "or_incomplete"
                        handled_days.add(trade_date)
                        last_trade_date = trade_date
                        time.sleep(60)
                        continue
                    elif log_msg:
                        # Log if it was incomplete but within tolerance
                        logger.warning(log_msg)
                
                or_high, or_low = slice_or["high"].max(), slice_or["low"].min()
                if or_high == or_low:
                    if trade_date not in skipped_days:
                        skipped_days[trade_date] = "or_zero_range"
                        summary["skipped"] += 1
                        msg = "Skipping day (OR range zero)"
                        logger.warning(msg)
                        daily_outcome_reason = "or_zero_range"
                        handled_days.add(trade_date)
                        last_trade_date = trade_date
                    time.sleep(60); continue
                
                # OR is valid; archive levels and prepare the chart for the
                # consolidated signal/no-trade post.
                if trade_date not in skipped_days and or_announced_for != trade_date:
                    or_rng = or_high - or_low
                    t_cut = or_high - TOP_PCT * or_rng
                    b_cut = or_low + BOT_PCT * or_rng
                    msg = (f"OR Levels {OR_START}-{OR_END}: {or_low:.2f}-{or_high:.2f} | "
                           f"Long > {t_cut:.2f} | Short < {b_cut:.2f}")
                    
                    # ARCHIVE: Save Session & OR Setup
                    daily_details["session_setup"] = {
                        "date": str(trade_date),
                        "instrument": broker_oanda.OANDA_INSTRUMENT,
                        "strategy_params": {
                            "entry_time": ENTRY_T,
                            "exit_time": EXIT_T,
                            "top_pct": TOP_PCT,
                            "bot_pct": BOT_PCT,
                            "sl_points": SL_PTS,
                            "tp_points": TP_PTS
                        },
                        "or_high": or_high, "or_low": or_low, "or_range": or_rng,
                        "or_completeness": f"{len(slice_or)}/{or_expected_rows}",
                        "or_candles": slice_or.to_dict(orient="records")
                    }
                    logger.info(msg)
                    
                    # Generate the OR chart now, but attach it later so OR
                    # levels do not consume a separate paid X post.
                    or_chart_buf = None
                    try:
                        or_chart_buf = plotting.create_or_chart(
                            slice_or, trade_date, or_high, or_low, t_cut, b_cut
                        )
                    except Exception:
                        logger.exception("Failed to generate OR chart")

                    or_announced_for = trade_date

            if ny_now < entry_wait_dt:
                time.sleep(10); continue

            # PRE-TRADE CHECKS: Log Volatility & Spread before decision
            if "pre_trade_checks" not in daily_details:
                current_spread = 0.0
                if PLACE_ORDERS: # Only fetch live spread if we are actually trading/connected
                    current_spread = broker_oanda.get_current_spread()
                
                current_atr = calculate_atr(df, period=14)
                daily_details["pre_trade_checks"] = {
                    "spread": current_spread,
                    "volatility_atr_14": current_atr,
                    "timestamp": str(ny_now)
                }

            # compute signal
            sig, reason = compute_signal(slice_win, slice_or)
            if sig is None:
                if reason == "entry_incomplete":
                    logger.info(f"Entry candle {ENTRY_T} present but not complete; waiting...")
                    time.sleep(10)
                    continue
                logger.info(f"No trade ({reason})")
                daily_outcome_reason = reason
                setup = daily_details.get("session_setup", {})
                or_rng_log = setup.get("or_range", 0.0)
                entry_rows = slice_win.loc[slice_win.index.time == ENTRY_T_T]
                entry_price = float(entry_rows.iloc[0]["close"]) if not entry_rows.empty else None
                daily_details["signal_decision"] = {
                    "signal_type": "none",
                    "signal_reason": reason,
                    "entry_price": entry_price,
                    "entry_bounds": {
                        "top_cut": setup.get("or_high", 0.0) - TOP_PCT * or_rng_log,
                        "bottom_cut": setup.get("or_low", 0.0) + BOT_PCT * or_rng_log,
                    },
                    "timestamp": str(ny_now),
                }
                # The single no-trade post is sent with final balances after
                # the session closes.
                last_trade_date = trade_date
                summary["skipped"] += 1
                handled_days.add(trade_date)
                time.sleep(60)
                continue

            side, entry, sl, tp = sig
            logger.info(f"Signal {side} @ {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")
            summary["signals"] += 1
            # ARCHIVE: Save Signal context
            # Recalculate bounds for logging as they are local to OR block
            or_rng_log = daily_details["session_setup"]["or_range"]
            daily_details["signal_decision"] = {
                "signal_type": side,
                "signal_reason": "strategy_signal",
                "entry_price": entry,
                "entry_bounds": {"top_cut": daily_details["session_setup"]["or_high"] - TOP_PCT * or_rng_log, "bottom_cut": daily_details["session_setup"]["or_low"] + BOT_PCT * or_rng_log},
                "timestamp": str(ny_now)
            }
            summary["last_signal"] = f"{trade_date} {side} {entry:.2f}"

            order_active = False
            if PLACE_ORDERS:
                # Scale units by POINT_VAL so OANDA PnL matches the $80/pt risk model
                qty = int(POSITION_SIZE * POINT_VAL)
                units = qty if side == "long" else -qty
                
                # Use DISTANCE to ensure fixed risk ($2000) regardless of slippage
                resp = broker_oanda.submit_market_with_sl_tp(
                    units=units, sl_distance=SL_PTS, tp_distance=TP_PTS
                )
                
                # Check if order was immediately rejected (e.g. INSUFFICIENT_MARGIN)
                if "orderCancelTransaction" in resp:
                    cancel_reason = resp["orderCancelTransaction"].get("reason", "UNKNOWN")
                    daily_outcome_reason = f"order_rejected:{cancel_reason.lower()}"
                    daily_details["signal_decision"]["signal_reason"] = f"order_rejected:{cancel_reason}"
                    summary["skipped"] += 1
                    if cancel_reason == "INSUFFICIENT_MARGIN":
                        acct = broker_oanda.get_account_summary()
                        margin_avail = acct.get("margin_available", 0)
                        ccy = acct.get("currency", "")
                        err_msg = (f"TRADE REJECTED: Insufficient Margin. "
                                   f"Req Units: {abs(units)} (~${abs(units)*entry:,.0f} value). "
                                   f"Margin Avail: {margin_avail:,.2f} {ccy}. "
                                   "Strategy requires more capital for this size.")
                        logger.error(err_msg)
                    else:
                        logger.error(f"Order rejected: {cancel_reason}")
                else:
                    # Order accepted
                    order_active = True
                    logger.info(f"Order placed: {resp}")
                    
                    # Log actual risk based on fill price vs fixed SL
                    try:
                        fill_tx = resp.get("orderFillTransaction", {})
                        fill_px = float(fill_tx.get("price", 0.0))
                        if fill_px > 0:
                            # RE-ALIGN STRATEGY VARIABLES TO FILL
                            # This ensures "Fixed 25 points" is respected in charts/stats/logs
                            entry = fill_px
                            if side == "long":
                                sl = entry - SL_PTS
                                tp = entry + TP_PTS
                            else:
                                sl = entry + SL_PTS
                                tp = entry - TP_PTS
                            
                            risk_usd = SL_PTS * abs(units)
                            logger.info(f"Risk Monitor: Fill {fill_px:.2f} | Risk Fixed at {SL_PTS} pts (${risk_usd:.2f})")
                            logger.info(f"Aligned Strategy Levels to Fill: Entry {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")
                    except Exception:
                        logger.warning("Could not parse fill details; stats may use signal price.")

                    summary["orders"] += 1
                    daily_details["signal_decision"]["entry_price"] = entry

                    # Post 1/2: session, OR, accepted trade, risk, and account
                    # values in one message with the OR chart.
                    try:
                        account_for_post = start_account_snapshot
                        if account_for_post is None:
                            account_for_post = broker_oanda.get_account_summary()
                            start_account_snapshot = account_for_post
                        setup = daily_details["session_setup"]
                        bounds = daily_details["signal_decision"]["entry_bounds"]
                        signal_message = tweet_formatter.format_signal_post(
                            trade_date=trade_date,
                            instrument=broker_oanda.OANDA_INSTRUMENT,
                            environment=OANDA_ENV,
                            or_start=OR_START,
                            exit_time=EXIT_T,
                            entry_time=ENTRY_T,
                            or_low=setup["or_low"],
                            or_high=setup["or_high"],
                            long_cut=bounds["top_cut"],
                            short_cut=bounds["bottom_cut"],
                            side=side,
                            entry=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            position_size=POSITION_SIZE,
                            point_value=POINT_VAL,
                            account=account_for_post,
                        )
                        notifier.notify_trade(signal_message, image_buffer=or_chart_buf)
                    except Exception:
                        logger.exception("Notifier error while posting consolidated signal")
            else:
                logger.info("PLACE_ORDERS=False -> log-only mode")
                daily_outcome_reason = "orders_disabled"
                summary["skipped"] += 1

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
                
                exit_reason = None
                exit_px = None
                exit_ts = None
                exit_details = ""
                if not trade_closed_by_broker:
                    logger.info(f"Hard exit time {EXIT_T} reached. Closing any open trades.")
                    closed = broker_oanda.close_all_trades()
                    logger.info(f"Hard exit close_all: {closed}")
                    count = len(closed)
                    exit_details = f"Hard Exit @ {EXIT_T} NY. Closed {count} positions.\n"
                    exit_reason = "time"
                else:
                    logger.info("Trade closed by broker; classifying exit using price path.")
                
                # Post-trade MFE/MAE analysis. The chart is retained for the
                # final consolidated recap instead of posted separately.
                stats_msg = ""
                trade_chart_buf = None
                mfe = 0.0
                mae = 0.0
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
                        df_plot = df_trade.copy()
                        df_plot.index = pd.to_datetime(df_plot["time_ny"])

                        sim_res = simulate_exit(df_plot, side, entry, sl, tp)
                        exit_reason = exit_reason or sim_res.get("exit_reason")
                        exit_px = sim_res.get("exit_px")
                        exit_ts = sim_res.get("exit_ts")
                        mfe = sim_res.get("mfe", 0.0)
                        mae = sim_res.get("mae", 0.0)

                        if exit_px is None:
                            exit_px = float(df_plot.iloc[-1]["close"])
                        if exit_ts is None:
                            exit_ts = df_plot.index.max()
                        
                        stats_msg = f"Stats: MFE +{mfe:.2f} pts | MAE -{mae:.2f} pts"
                        reason_for_log = exit_reason.upper() if exit_reason else "UNKNOWN"
                        logger.info(f"Trade Stats ({reason_for_log}): MFE +{mfe:.2f} pts | MAE -{mae:.2f} pts | exit_px {exit_px:.2f}")
                        
                        # ARCHIVE: Save Trade Result & Path
                        daily_details["trade_result"] = {
                            "side": side,
                            "entry_price": entry,
                            "exit_price": exit_px,
                            "exit_timestamp": exit_ts,
                            "pnl_points": sim_res.get("pnl_pts"),
                            "pnl_usd": sim_res.get("pnl_usd"),
                            "exit_reason": exit_reason or "unknown",
                            "mfe_points": mfe, "mae_points": mae,
                            "trade_path_candles": df_trade.to_dict(orient="records")
                        }
                        
                        # Generate Chart
                        try:
                            trade_chart_buf = plotting.create_trade_chart(
                                df_plot, trade_date, ENTRY_T_T, exit_ts, 
                                entry, exit_px, side, 
                                or_high, or_low, sl, tp, mfe, mae, exit_reason=exit_reason
                            )
                        except Exception:
                            logger.exception("Failed to generate chart")
                    else:
                        logger.warning("Trade duration too short or candle data delayed; skipping MFE/MAE stats.")
                except Exception:
                    logger.exception("Failed to calculate MFE/MAE")

                if "trade_result" not in daily_details:
                    daily_details["trade_result"] = {
                        "side": side,
                        "entry_price": entry,
                        "exit_price": exit_px,
                        "exit_timestamp": exit_ts,
                        "pnl_points": None,
                        "pnl_usd": None,
                        "exit_reason": exit_reason or "unknown",
                        "mfe_points": mfe,
                        "mae_points": mae,
                        "trade_path_candles": [],
                    }
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
                pnl_nav = None
                pnl_bal = None
                try:
                    end_snapshot = broker_oanda.get_account_summary()
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
                
                # Save Rich JSON Log
                if daily_details:
                    json_dir = summary_path / "daily_json"
                    json_dir.mkdir(parents=True, exist_ok=True)
                    json_path = json_dir / f"{last_trade_date}.json"
                    
                    # Update PnL in trade_result if available from session summary
                    if "trade_result" in daily_details and pnl_bal is not None:
                         daily_details["trade_result"]["pnl_usd"] = pnl_bal
                         # Estimate points from USD PnL
                         if POINT_VAL > 0 and POSITION_SIZE > 0:
                             daily_details["trade_result"]["pnl_points"] = pnl_bal / (POINT_VAL * POSITION_SIZE)

                    with open(json_path, "w") as f:
                        json.dump(daily_details, f, cls=DateTimeEncoder, indent=2)

                with open(fname, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
                logger.info(f"Wrote daily summary: {msg}")

                # Final daily post: this is post 2/2 on a trade day, or the
                # only post on a no-trade day. Operational CRITICAL alerts are
                # intentionally still sent immediately outside this cadence.
                try:
                    trade_result = daily_details.get("trade_result")
                    signal_decision = daily_details.get("signal_decision", {})
                    if summary["orders"] > 0 and trade_result:
                        recap_message = tweet_formatter.format_trade_recap_post(
                            trade_date=last_trade_date,
                            instrument=broker_oanda.OANDA_INSTRUMENT,
                            environment=OANDA_ENV,
                            side=trade_result.get("side") or signal_decision.get("signal_type", "unknown"),
                            entry=trade_result.get("entry_price") or signal_decision.get("entry_price"),
                            exit_price=trade_result.get("exit_price"),
                            exit_reason=trade_result.get("exit_reason"),
                            pnl_points=trade_result.get("pnl_points"),
                            pnl_usd=trade_result.get("pnl_usd"),
                            mfe=trade_result.get("mfe_points"),
                            mae=trade_result.get("mae_points"),
                            start_account=start_account_snapshot,
                            end_account=end_snapshot,
                            signals=summary["signals"],
                            orders=summary["orders"],
                            skipped=summary["skipped"],
                            errors=summary["errors"],
                        )
                        notifier.notify_trade(recap_message, image_buffer=trade_chart_buf)
                    else:
                        setup = daily_details.get("session_setup", {})
                        bounds = signal_decision.get("entry_bounds", {})
                        no_trade_reason = (
                            daily_outcome_reason
                            or signal_decision.get("signal_reason")
                            or skipped_days.get(last_trade_date)
                            or "none"
                        )
                        recap_message = tweet_formatter.format_no_trade_recap_post(
                            trade_date=last_trade_date,
                            instrument=broker_oanda.OANDA_INSTRUMENT,
                            environment=OANDA_ENV,
                            or_start=OR_START,
                            exit_time=EXIT_T,
                            entry_time=ENTRY_T,
                            or_low=setup.get("or_low"),
                            or_high=setup.get("or_high"),
                            long_cut=bounds.get("top_cut"),
                            short_cut=bounds.get("bottom_cut"),
                            reason=no_trade_reason,
                            start_account=start_account_snapshot,
                            end_account=end_snapshot,
                            signals=summary["signals"],
                            orders=summary["orders"],
                            skipped=summary["skipped"],
                            errors=summary["errors"],
                        )
                        notifier.notify_trade(recap_message, image_buffer=or_chart_buf)
                except Exception:
                    logger.exception("Notifier error while posting consolidated recap")

                summary = {"signals": 0, "orders": 0, "skipped": 0, "errors": 0, "last_signal": None}
                daily_details = {}
                summary_flushed_for = last_trade_date
                start_account_snapshot = None
                session_started_for = None
                or_chart_buf = None
                trade_chart_buf = None
                daily_outcome_reason = None

                if RUN_SINGLE_SESSION:
                    logger.info("RUN_SINGLE_SESSION=true; completed final recap and exiting.")
                    return


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
        sig = None
        replay_result = None
        replay_reason = None
        or_high = or_low = t_cut = b_cut = None
        
        # Extract date for report/chart
        r_date = datetime.now().date()
        try:
             r_date = pd.to_datetime(Path(REPLAY_FILE).stem.replace("replay_", "")).date()
        except Exception:
             pass

        # 1. Session Info
        overview = format_session_overview()
        report_lines.append("--- REPLAY SESSION - NO LIVE ORDER ---")
        report_lines.append(f"{overview}")
        report_lines.append("Account balance/NAV: unavailable in replay")

        # Parity check: Ensure OR has full data, just like main_loop
        or_expected_rows = len(pd.date_range(pd.Timestamp(OR_START), pd.Timestamp(OR_END), freq="min"))
        if len(slice_or) != or_expected_rows:
            replay_reason = "or_incomplete"
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
                replay_reason = "missing_entry"
                logger.warning("Replay: missing entry bar; skipping")
                report_lines.append("\n[SKIPPED] Missing entry bar")
            else:
                sig, reason = compute_signal(slice_win, slice_or)
                replay_reason = reason
                if sig is None:
                    logger.info(f"Replay: no trade ({reason})")
                    report_lines.append(f"\n[NO TRADE] {reason}")
                else:
                    side, entry, sl, tp = sig
                    logger.info(f"Replay: Signal {side} @ {entry:.2f} | SL {sl:.2f} | TP {tp:.2f}")
                    report_lines.append(f"\n[SIGNAL] {side.upper()} @ {entry:.2f}")
                    report_lines.append(f"SL {sl:.2f} | TP {tp:.2f}")

                    # Simulate exit/PnL on the replay window
                    replay_result = simulate_exit(slice_win, side, entry, sl, tp)
                    logger.info(f"Replay: Exit {replay_result['exit_reason']} @ {replay_result['exit_px']} | pnl_pts={replay_result['pnl_pts']} pnl_usd={replay_result['pnl_usd']} MFE={replay_result['mfe']:.2f} MAE={replay_result['mae']:.2f}")

                    replay_exit = replay_result.get("exit_px")
                    replay_pnl_usd = replay_result.get("pnl_usd")
                    replay_pnl_pts = replay_result.get("pnl_pts")
                    exit_display = f"{replay_exit:.2f}" if replay_exit is not None else "n/a"
                    pnl_usd_display = f"${replay_pnl_usd:.2f}" if replay_pnl_usd is not None else "n/a"
                    pnl_pts_display = f"{replay_pnl_pts:.2f}" if replay_pnl_pts is not None else "n/a"
                    report_lines.append(f"\n[EXIT] {replay_result['exit_reason']} @ {exit_display}")
                    report_lines.append(f"PnL: {pnl_usd_display} ({pnl_pts_display} pts)")
                    report_lines.append(f"Stats: MFE +{replay_result['mfe']:.2f} | MAE -{replay_result['mae']:.2f}")

                    # Generate Replay Chart
                    try:
                        img_buf = plotting.create_trade_chart(
                            slice_win, r_date,
                            ENTRY_T_T, replay_result['exit_ts'],
                            entry, replay_result['exit_px'], side,
                            slice_or["high"].max(), slice_or["low"].min(), sl, tp, replay_result['mfe'], replay_result['mae'], exit_reason=replay_result['exit_reason']
                        )
                    except Exception:
                        logger.exception("Notifier error while generating replay chart")

        # 4. Recap
        report_lines.append("\n--- RECAP ---")
        # Determine if we had a trade for stats
        had_trade = replay_result is not None
        pnl_val = replay_result.get("pnl_usd") if had_trade else 0.0
        pnl_display = f"${pnl_val:.2f}" if pnl_val is not None else "n/a"
        report_lines.append(f"Signals: {1 if had_trade else 0} | Orders: {1 if had_trade else 0}")
        report_lines.append(f"PnL: {pnl_display} (Simulated)")
        report_lines.append("Account balance/NAV: unavailable in replay")

        full_report = "\n".join(report_lines)
        
        try:
            logger.info("--- CONSOLIDATED REPLAY REPORT ---\n" + full_report)
        except UnicodeEncodeError:
            # Fallback for Windows consoles that cannot print emojis
            logger.info("--- CONSOLIDATED REPLAY REPORT ---\n" + full_report.encode("ascii", "replace").decode("ascii"))

        if REPLAY_TWEETS:
            try:
                if sig and replay_result:
                    side, entry, sl, tp = sig
                    signal_message = tweet_formatter.format_signal_post(
                        trade_date=r_date,
                        instrument=broker_oanda.OANDA_INSTRUMENT,
                        environment="replay",
                        or_start=OR_START,
                        exit_time=EXIT_T,
                        entry_time=ENTRY_T,
                        or_low=or_low,
                        or_high=or_high,
                        long_cut=t_cut,
                        short_cut=b_cut,
                        side=side,
                        entry=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        position_size=POSITION_SIZE,
                        point_value=POINT_VAL,
                        account=None,
                    )
                    first_result = notifier.notify_trade(signal_message, image_buffer=or_chart_buf)
                    if not first_result or first_result.get("status") != "posted":
                        logger.warning(f"Replay signal post failed: {first_result.get('reason') if first_result else 'unknown'}")

                    recap_message = tweet_formatter.format_trade_recap_post(
                        trade_date=r_date,
                        instrument=broker_oanda.OANDA_INSTRUMENT,
                        environment="replay",
                        side=side,
                        entry=entry,
                        exit_price=replay_result.get("exit_px"),
                        exit_reason=replay_result.get("exit_reason"),
                        pnl_points=replay_result.get("pnl_pts"),
                        pnl_usd=replay_result.get("pnl_usd"),
                        mfe=replay_result.get("mfe"),
                        mae=replay_result.get("mae"),
                        start_account=None,
                        end_account=None,
                        signals=1,
                        orders=1,
                        skipped=0,
                        errors=0,
                    )
                    second_result = notifier.notify_trade(recap_message, image_buffer=img_buf)
                    if not second_result or second_result.get("status") != "posted":
                        logger.warning(f"Replay recap post failed: {second_result.get('reason') if second_result else 'unknown'}")
                else:
                    no_trade_message = tweet_formatter.format_no_trade_recap_post(
                        trade_date=r_date,
                        instrument=broker_oanda.OANDA_INSTRUMENT,
                        environment="replay",
                        or_start=OR_START,
                        exit_time=EXIT_T,
                        entry_time=ENTRY_T,
                        or_low=or_low,
                        or_high=or_high,
                        long_cut=t_cut,
                        short_cut=b_cut,
                        reason=replay_reason or "none",
                        start_account=None,
                        end_account=None,
                        signals=0,
                        orders=0,
                        skipped=1,
                        errors=0,
                    )
                    replay_post_result = notifier.notify_trade(no_trade_message, image_buffer=or_chart_buf)
                    if not replay_post_result or replay_post_result.get("status") != "posted":
                        logger.warning(f"Replay no-trade post failed: {replay_post_result.get('reason') if replay_post_result else 'unknown'}")
            except Exception:
                logger.exception("Notifier error while posting replay report")

        logger.info("Replay complete.")
    else:
        main_loop()
