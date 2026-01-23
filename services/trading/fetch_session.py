"""Fetch a specific session window (NY time) of M1 candles and save to CSV.
Usage:
  python -m services.trading.fetch_session 2025-01-02
saves to data/trading/replay/replay_2025-01-02.csv
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pytz
import pandas as pd
import requests

# Ensure repo root on path
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trading.config import OANDA_API_BASE, OANDA_API_TOKEN, OANDA_INSTRUMENT, OANDA_TIMEZONE

NY = pytz.timezone(OANDA_TIMEZONE)


def headers():
    return {
        "Authorization": f"Bearer {OANDA_API_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_range(from_dt, to_dt):
    url = f"{OANDA_API_BASE}/instruments/{OANDA_INSTRUMENT}/candles"
    params = {
        "granularity": "M1",
        "price": "M",
        "smooth": "true",
        "from": from_dt.isoformat(),
        "to": to_dt.isoformat(),
    }
    resp = requests.get(url, headers=headers(), params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("candles", [])
    records = []
    for c in data:
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
    if not records:
        # Return empty DF with expected columns so callers don't KeyError on sort
        return pd.DataFrame(columns=["time_utc", "time_ny", "open", "high", "low", "close", "complete"])
    return pd.DataFrame(records).sort_values("time_ny").reset_index(drop=True)


def main(date_str):
    # fetch from 09:00 to 13:00 NY to cover OR and exit window
    day = NY.localize(datetime.strptime(date_str, "%Y-%m-%d"))
    start = day.replace(hour=9, minute=0, second=0, microsecond=0).astimezone(pytz.UTC)
    end = day.replace(hour=13, minute=0, second=0, microsecond=0).astimezone(pytz.UTC)

    # OANDA returns 400 if 'to' is in the future. Clamp to now.
    now_utc = datetime.now(pytz.UTC)
    if start > now_utc:
        print(f"Session start {start} is in the future. Cannot fetch.")
        return
    if end > now_utc:
        # Buffer by 30s to avoid 'future' error due to clock skew, and strip micros
        safe_end = (now_utc - timedelta(seconds=30)).replace(microsecond=0)
        print(f"Session in progress. Clamping end time to {safe_end}.")
        end = safe_end

    df = fetch_range(start, end)
    if df.empty:
        print(f"No data returned for {date_str} between {start} and {end}. Check instrument/token/time window.")
        return
    out = ROOT / "data" / "trading" / "replay" / f"replay_{date_str}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Saved {len(df)} rows to {out}")
    print(df.head())
    print(df.tail())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m services.trading.fetch_session YYYY-MM-DD")
        sys.exit(1)
    main(sys.argv[1])
