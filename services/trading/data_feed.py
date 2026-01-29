"""Minimal OANDA M1 candle fetcher (polling) with UTC→NY conversion.
This keeps dependencies light; swap to streaming if desired.
"""
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd
import pytz

from services.trading.config import OANDA_API_BASE, OANDA_API_TOKEN, OANDA_INSTRUMENT, OANDA_TIMEZONE
from shared.logging_utils import setup_logger

NY = pytz.timezone(OANDA_TIMEZONE)
logger = setup_logger("data_feed")


def _headers():
    return {
        "Authorization": f"Bearer {OANDA_API_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_m1(count: int = 120, max_retries: int = 3, backoff_seconds: int = 5):
    """Fetch last `count` M1 candles with retries on transient errors."""
    url = f"{OANDA_API_BASE}/instruments/{OANDA_INSTRUMENT}/candles"
    params = {
        "granularity": "M1",
        "count": count,
        "price": "M",
        "smooth": "true",
    }
    last_exception = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("candles", [])
            records = []
            for c in data:
                # OANDA times can include nanosecond precision; let pandas handle it.
                ts = pd.to_datetime(c["time"], utc=True).to_pydatetime()
                mid = c.get("mid", {})
                records.append({
                    "time_utc": ts,
                    "time_ny": ts.astimezone(NY),
                    "open": float(mid.get("o", 0.0)),
                    "high": float(mid.get("h", 0.0)),
                    "low": float(mid.get("l", 0.0)),
                    "close": float(mid.get("c", 0.0)),
                    "complete": bool(c.get("complete", False)),
                })
            df = pd.DataFrame(records)
            df = df.sort_values("time_ny").reset_index(drop=True)
            logger.debug(f"Fetched {len(df)} M1 candles (latest NY {df['time_ny'].iloc[-1] if not df.empty else 'none'})")
            return df
        except requests.exceptions.RequestException as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {backoff_seconds}s...")
            time.sleep(backoff_seconds)
            backoff_seconds *= 2  # Exponential backoff
    
    logger.error(f"All {max_retries} attempts failed. Giving up.")
    raise last_exception


def latest_slice(df: pd.DataFrame, start_str: str, end_str: str) -> pd.DataFrame:
    """Return rows between start/end (NY local hh:mm)."""
    if df.empty:
        return df
    df = df.copy()
    df.index = pd.to_datetime(df["time_ny"])
    return df.between_time(start_str, end_str, inclusive="both")
