"""Thin OANDA order wrapper (practice/live toggle via config)."""
import requests
from live.config import OANDA_API_BASE, OANDA_API_TOKEN, OANDA_ACCOUNT_ID, OANDA_INSTRUMENT


def _headers():
    return {
        "Authorization": f"Bearer {OANDA_API_TOKEN}",
        "Content-Type": "application/json",
    }


def submit_market_with_sl_tp(units: int, sl_price: float, tp_price: float):
    """Place a market order with attached SL/TP. Units: positive=buy, negative=sell."""
    url = f"{OANDA_API_BASE}/accounts/{OANDA_ACCOUNT_ID}/orders"
    body = {
        "order": {
            "units": str(units),
            "instrument": OANDA_INSTRUMENT,
            "type": "MARKET",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": f"{sl_price}"},
            "takeProfitOnFill": {"price": f"{tp_price}"},
        }
    }
    resp = requests.post(url, headers=_headers(), json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def close_all_trades():
    url = f"{OANDA_API_BASE}/accounts/{OANDA_ACCOUNT_ID}/trades"
    trades = requests.get(url, headers=_headers(), timeout=10).json().get("trades", [])
    results = []
    for t in trades:
        tid = t.get("id")
        if not tid:
            continue
        c_url = f"{OANDA_API_BASE}/accounts/{OANDA_ACCOUNT_ID}/trades/{tid}/close"
        r = requests.put(c_url, headers=_headers(), timeout=10)
        r.raise_for_status()
        results.append(r.json())
    return results


def get_open_trades():
    url = f"{OANDA_API_BASE}/accounts/{OANDA_ACCOUNT_ID}/trades"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json().get("trades", [])
