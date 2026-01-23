# services/trading/or_core.py

from __future__ import annotations

"""
Core logic for the Opening Range (OR) strategy on NSXUSD.

What this module does, in plain language:
- Load 1-minute OHLCV data for NSXUSD from yearly CSV files in data/trading/historical/.
- Slice the regular session window (default 09:30–12:00 New York time).
- Compute the opening range (default 09:30–10:00), then check where the
  10:22 close sits inside that range.
- If 10:22 is near the top of the range: go long with predefined stop/target.
  If near the bottom: go short. Otherwise: stay flat.
- Simulate the intraday path to see whether the stop, the target, or the
  time-based exit (12:00) is hit first.

Everything is parameterized via config/trading/instruments.yml and config/trading/strategy.yml
so non-technical users can tweak times and risk numbers without editing code.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd
import numpy as np
import pytz
import yaml

# ----------------------------- Globals / Config -----------------------------

# Toggle small previews if you want (kept for parity with your notebooks)
PREVIEW: bool = False

# Determine ROOT based on execution context
if Path.cwd().name == "trading" and (Path.cwd().parent.name == "notebooks"):
    ROOT = Path.cwd().parent.parent  # notebooks/trading/ -> project root
elif Path.cwd().name == "notebooks":
    ROOT = Path.cwd().parent
else:
    ROOT = Path.cwd()

CONFIG_DIR = ROOT / "config" / "trading"
DATA_RAW_DIR = ROOT / "data" / "trading" / "historical"

def _load_yaml(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

try:
    INSTR = _load_yaml(CONFIG_DIR / "instruments.yml")
except Exception:
    INSTR = {}
try:
    STRATEGY = _load_yaml(CONFIG_DIR / "strategy.yml")
except Exception:
    STRATEGY = {}

session   = INSTR.get("session", {}) if isinstance(INSTR, dict) else {}
data_cfg  = INSTR.get("data",    {}) if isinstance(INSTR, dict) else {}
market    = INSTR.get("market",  {}) if isinstance(INSTR, dict) else {}

TZ_MARKET = session.get("timezone", "America/New_York")
ENTRY_T   = session.get("entry_time", "10:22")
EXIT_T    = session.get("hard_exit_time", "12:00")
OR_START  = session.get("or_window", {}).get("start", "09:30")
OR_END    = session.get("or_window", {}).get("end_inclusive", "10:00")  # inclusive

TOP_PCT   = (STRATEGY.get("parameters", {}) or {}).get("zones", {}).get("top_pct", 0.35)
BOT_PCT   = (STRATEGY.get("parameters", {}) or {}).get("zones", {}).get("bottom_pct", 0.35)
SL_PTS    = (STRATEGY.get("parameters", {}) or {}).get("risk", {}).get("stop_loss_points", 25)
TP_PTS    = (STRATEGY.get("parameters", {}) or {}).get("risk", {}).get("take_profit_points", 75)

POINT_VAL = market.get("point_value_usd", 80.0)
POS_SIZE  = market.get("position_size", 1.0)

DELIM         = data_cfg.get("delimiter", ";")
DATETIME_FMT  = data_cfg.get("datetime_format", "%Y%m%d %H%M%S")
SRC_TZ_NAME   = data_cfg.get("source_timezone")  # None ⇒ already NY local
NY            = pytz.timezone(TZ_MARKET)
SRC_TZ        = pytz.timezone(SRC_TZ_NAME) if SRC_TZ_NAME else None

def _discover_year_files() -> Dict[int, Path]:
    mapping: Dict[int, Path] = {}
    if DATA_RAW_DIR.exists():
        for p in sorted(DATA_RAW_DIR.glob("*.csv")):
            for token in ["2018","2019","2020","2021","2022","2023","2024","2025"]:
                if token in p.name:
                    mapping[int(token)] = p
                    break
    return mapping

YEAR_FILES: Dict[int, Path] = _discover_year_files()

# ----------------------------- Low-level helpers -----------------------------

def _parse_index(ts: pd.Series) -> pd.DatetimeIndex:
    idx = pd.to_datetime(ts, format=DATETIME_FMT, errors="coerce")
    if SRC_TZ is not None:
        idx = idx.dt.tz_localize(SRC_TZ, nonexistent="NaT", ambiguous="NaT").dt.tz_convert(NY)
    else:
        idx = idx.dt.tz_localize(NY, nonexistent="NaT", ambiguous="NaT")
    return pd.DatetimeIndex(idx)

@lru_cache(maxsize=8)
def _load_year_df(year: int) -> pd.DataFrame:
    """Load a single year of minute data, normalize types, and index by tz-aware timestamp."""
    fp = YEAR_FILES.get(year)
    if fp is None:
        raise FileNotFoundError(f"No CSV file for year {year} in {DATA_RAW_DIR}")
    raw = pd.read_csv(fp, sep=DELIM, header=None)
    if raw.shape[1] != 6:
        raise ValueError(f"{fp.name}: expected 6 columns, found {raw.shape[1]}.")
    raw.columns = ["datetime","open","high","low","close","volume"]
    for c in ["open","high","low","close","volume"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    idx = _parse_index(raw["datetime"])
    df = raw.drop(columns=["datetime"])
    df.index = idx
    return df[~df.index.isna()].sort_index()

def _expected_index_local(day: pd.Timestamp, start_str: str, end_str: str) -> pd.DatetimeIndex:
    start = NY.localize(pd.Timestamp.combine(day.date(), pd.Timestamp(start_str).time()))
    end   = NY.localize(pd.Timestamp.combine(day.date(), pd.Timestamp(end_str).time()))
    return pd.date_range(start=start, end=end, freq="T", tz=NY)

def _first_close_at(minute_df: pd.DataFrame, hhmm: str) -> Optional[float]:
    try:
        target_t = pd.Timestamp(hhmm).time()
        row = minute_df.loc[minute_df.index.time == target_t]
        return float(row["close"].iloc[0]) if not row.empty else None
    except Exception:
        return None

# ----------------------------- Public API (Notebook 3) -----------------------------

def load_day_window(date_str: str):
    """
    Convenience loader used by notebooks/backtests.

    Returns:
      win:      full trade window (default 09:30–12:00 local NY time)
      or_slice: opening range (default 09:30–10:00)
      qc:       quick checks (missing minutes, duplicates, OR highs/lows)
    """
    if isinstance(date_str, (pd.Timestamp,)):
        day = date_str.tz_localize(NY) if date_str.tzinfo is None else date_str.tz_convert(NY)
    else:
        day = pd.to_datetime(date_str).tz_localize(NY)
    y = int(day.year)
    if y not in YEAR_FILES:
        raise FileNotFoundError(f"No CSV file found for year {y} in {DATA_RAW_DIR}")
    df_year = _load_year_df(y)

    day_start = NY.localize(pd.Timestamp(day.date()))
    next_day  = day_start + pd.Timedelta(days=1)
    day_df = df_year.loc[(df_year.index >= day_start) & (df_year.index < next_day)].copy()

    tgt_or  = _expected_index_local(day_start, OR_START, OR_END)
    tgt_win = _expected_index_local(day_start, OR_START, EXIT_T)

    or_slice = day_df.loc[day_df.index.isin(tgt_or)].copy()
    win      = day_df.loc[day_df.index.isin(tgt_win)].copy()

    missing_or   = int(len(tgt_or)  - len(or_slice))
    missing_win  = int(len(tgt_win) - len(win))
    dupes        = int(or_slice.index.duplicated().sum() + win.index.duplicated().sum())

    has_1022 = any(win.index.time == pd.Timestamp(ENTRY_T).time())
    has_1200 = any(win.index.time == pd.Timestamp(EXIT_T).time())

    or_high = float(or_slice["high"].max()) if not or_slice.empty else None
    or_low  = float(or_slice["low"].min())  if not or_slice.empty else None
    or_rng  = (or_high - or_low) if (or_high is not None and or_low is not None) else None

    qc = {
        "file": YEAR_FILES[y].name,
        "missing_minutes": missing_or + missing_win,
        "duplicate_minutes": dupes,
        "has_entry_1022": bool(has_1022),
        "has_exit_1200": bool(has_1200),
        "or_high": or_high,
        "or_low": or_low,
        "or_range": or_rng,
    }

    if PREVIEW:
        print(f"[{date_str}] File: {qc['file']}")
        print("OR slice 09:30–10:00  (rows):", len(or_slice), " | expected:", len(tgt_or))
        print("Trade win 09:30–12:00 (rows):", len(win),      " | expected:", len(tgt_win))
        print("Has 10:22?", qc["has_entry_1022"], " | Has 12:00?", qc["has_exit_1200"],
              " | Missing:", qc["missing_minutes"], " | Duplicates:", qc["duplicate_minutes"])
        if not or_slice.empty:
            print(f"OR High: {qc['or_high']}  OR Low: {qc['or_low']}  OR Range: {qc['or_range']}")
        try:
            display(win.head(3)[["open","high","low","close"]])
            display(win.tail(3)[["open","high","low","close"]])
        except Exception:
            pass

    return win, or_slice, qc

@dataclass
class DaySignal:
    """Signal decision at 10:22 based on where that close sits inside the opening range."""
    date: str
    decision: str                 # "long" | "short" | "none" | "no_signal_missing_1022" | "invalid_or"
    entry_time: str
    entry_price: Optional[float]
    sl: Optional[float]
    tp: Optional[float]
    or_high: Optional[float]
    or_low: Optional[float]
    or_range: Optional[float]
    top_cutoff: Optional[float]
    bottom_cutoff: Optional[float]
    has_1022: bool
    has_1200: bool
    notes: str

def compute_signal_for_date(date_str: str, *, win=None, or_slice=None, qc=None) -> DaySignal:
    """
    Decide whether to go long, short, or stay out.

    Logic (matches the research notebook):
      - Build the opening range from 09:30–10:00.
      - Find the 10:22 close.
      - If 10:22 is in the top X% of the range: go long. If in bottom X%: short.
      - Otherwise: no trade. Missing/invalid data returns explicit failure states.
    """
    if (win is None) or (or_slice is None) or (qc is None):
        win, or_slice, qc = load_day_window(date_str)

    if or_slice.empty or qc.get("or_range") is None or qc.get("or_range") <= 0:
        return DaySignal(
            date=date_str, decision="invalid_or", entry_time=ENTRY_T,
            entry_price=None, sl=None, tp=None,
            or_high=qc.get("or_high"), or_low=qc.get("or_low"), or_range=qc.get("or_range"),
            top_cutoff=None, bottom_cutoff=None,
            has_1022=bool(qc.get("has_entry_1022")), has_1200=bool(qc.get("has_exit_1200")),
            notes="Invalid opening range (empty or zero range)."
        )

    or_high  = float(qc["or_high"])
    or_low   = float(qc["or_low"])
    or_range = float(qc["or_range"])

    bottom_cut = or_low  + BOT_PCT * or_range
    top_cut    = or_high - TOP_PCT * or_range

    e = _first_close_at(win, ENTRY_T)
    if e is None:
        return DaySignal(
            date=date_str, decision="no_signal_missing_1022", entry_time=ENTRY_T,
            entry_price=None, sl=None, tp=None,
            or_high=or_high, or_low=or_low, or_range=or_range,
            top_cutoff=top_cut, bottom_cutoff=bottom_cut,
            has_1022=False, has_1200=bool(qc.get("has_exit_1200")),
            notes="No 10:22 bar in trade window."
        )

    if e >= top_cut:
        decision = "long"
        sl = e - SL_PTS
        tp = e + TP_PTS
    elif e <= bottom_cut:
        decision = "short"
        sl = e + SL_PTS
        tp = e - TP_PTS
    else:
        decision = "none"
        sl = None
        tp = None

    return DaySignal(
        date=date_str, decision=decision, entry_time=ENTRY_T,
        entry_price=float(e), sl=float(sl) if sl is not None else None, tp=float(tp) if tp is not None else None,
        or_high=or_high, or_low=or_low, or_range=or_range,
        top_cutoff=float(top_cut), bottom_cutoff=float(bottom_cut),
        has_1022=True, has_1200=bool(qc.get("has_exit_1200")),
        notes="OK"
    )

@dataclass
class DayExecution:
    """Execution simulation for the chosen signal (stop/target/time exit)."""
    date: str
    decision: str                 # long | short | none | invalid_or | no_signal_missing_1022
    entry_time: str
    entry_price: Optional[float]
    sl: Optional[float]
    tp: Optional[float]
    exit_time: Optional[str]
    exit_price: Optional[float]
    exit_reason: Optional[str]       # "tp" | "sl" | "time" | "no_trade" | None
    pnl_pts: Optional[float]
    pnl_usd: Optional[float]
    notes: str

def execute_day(date_str: str) -> DayExecution:
    """
    Replay the day minute-by-minute after 10:22 and resolve the trade outcome.

    Tie-break is conservative: if a bar touches both stop and target, we assume
    the stop is hit first. This errs on the side of worse PnL.
    """
    win, or_slice, qc = load_day_window(date_str)
    sig = compute_signal_for_date(date_str, win=win, or_slice=or_slice, qc=qc)

    if sig.decision in ("invalid_or", "no_signal_missing_1022"):
        return DayExecution(
            date=date_str, decision=sig.decision, entry_time=sig.entry_time,
            entry_price=sig.entry_price, sl=None, tp=None,
            exit_time=None, exit_price=None, exit_reason=None,
            pnl_pts=None, pnl_usd=None, notes=sig.notes
        )

    if sig.decision == "none":
        return DayExecution(
            date=date_str, decision="none", entry_time=sig.entry_time,
            entry_price=sig.entry_price, sl=None, tp=None,
            exit_time=sig.entry_time, exit_price=sig.entry_price, exit_reason="no_trade",
            pnl_pts=0.0, pnl_usd=0.0, notes="Middle zone at 10:22; no position."
        )

    entry_t = pd.Timestamp(sig.entry_time).time()
    path = win.loc[win.index.time > entry_t].copy()  # 10:23 ... 12:00 inclusive

    has_1200 = any(path.index.time == pd.Timestamp(EXIT_T).time()) or bool(qc.get("has_exit_1200"))
    if not has_1200 and not path.empty:
        hard_exit_time = path.index.max()
    elif has_1200:
        hard_exit_time = path.index[path.index.time == pd.Timestamp(EXIT_T).time()][0]
    else:
        hard_exit_time = None

    E  = float(sig.entry_price)
    SL = float(sig.sl)
    TP = float(sig.tp)

    exit_ts = None
    exit_px = None
    exit_reason = None

    # Conservative tie-break
    if sig.decision == "long":
        for ts, row in path.iterrows():
            hi, lo = float(row["high"]), float(row["low"])
            touched_tp = hi >= TP
            touched_sl = lo <= SL
            if touched_tp and touched_sl:
                exit_ts, exit_px, exit_reason = ts, SL, "sl"; break
            elif touched_sl:
                exit_ts, exit_px, exit_reason = ts, SL, "sl"; break
            elif touched_tp:
                exit_ts, exit_px, exit_reason = ts, TP, "tp"; break
    elif sig.decision == "short":
        for ts, row in path.iterrows():
            hi, lo = float(row["high"]), float(row["low"])
            touched_tp = lo <= TP
            touched_sl = hi >= SL
            if touched_tp and touched_sl:
                exit_ts, exit_px, exit_reason = ts, SL, "sl"; break
            elif touched_sl:
                exit_ts, exit_px, exit_reason = ts, SL, "sl"; break
            elif touched_tp:
                exit_ts, exit_px, exit_reason = ts, TP, "tp"; break

    if exit_ts is None:
        if hard_exit_time is not None:
            exit_ts = hard_exit_time
            exit_px = float(path.loc[exit_ts, "close"])
            exit_reason = "time"
        else:
            return DayExecution(
                date=date_str, decision="none", entry_time=sig.entry_time,
                entry_price=sig.entry_price, sl=None, tp=None,
                exit_time=sig.entry_time, exit_price=sig.entry_price, exit_reason="no_trade",
                pnl_pts=0.0, pnl_usd=0.0, notes="No bars after entry — flat."
            )

    pnl_pts = float(exit_px - E) if sig.decision == "long" else float(E - exit_px)
    pnl_usd = pnl_pts * POINT_VAL * POS_SIZE

    return DayExecution(
        date=date_str, decision=sig.decision, entry_time=sig.entry_time,
        entry_price=E, sl=SL, tp=TP,
        exit_time=str(exit_ts.tz_convert(win.index.tz).time()) if hasattr(exit_ts, "tzinfo") else str(exit_ts),
        exit_price=float(exit_px), exit_reason=exit_reason,
        pnl_pts=float(pnl_pts), pnl_usd=float(pnl_usd),
        notes="Conservative tie-break; checks start after entry bar."
    )
