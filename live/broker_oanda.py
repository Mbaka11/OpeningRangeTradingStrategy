"""Thin OANDA order wrapper (practice/live toggle via config)."""
import requests
from live.config import OANDA_API_BASE, OANDA_API_TOKEN, OANDA_ACCOUNT_ID, OANDA_INSTRUMENT
from live.logging_utils import setup_logger

logger = setup_logger("broker")


def _headers():
    return {
        "Authorization": f"Bearer {OANDA_API_TOKEN}",
        "Content-Type": "application/json",
    }


def submit_market_with_sl_tp(units: int, sl_price: float = None, tp_price: float = None, sl_distance: float = None, tp_distance: float = None):
    """Place a market order with attached SL/TP. Supports fixed Price OR Distance."""
    url = f"{OANDA_API_BASE}/accounts/{OANDA_ACCOUNT_ID}/orders"
    
    order_body = {
        "units": str(units),
        "instrument": OANDA_INSTRUMENT,
        "type": "MARKET",
        "positionFill": "DEFAULT",
    }
    
    # Handle Stop Loss (Distance takes priority if both provided, or use logic as needed)
    if sl_distance is not None:
        order_body["stopLossOnFill"] = {"distance": f"{sl_distance:.2f}"}
    elif sl_price is not None:
        order_body["stopLossOnFill"] = {"price": f"{sl_price:.2f}"}
        
    # Handle Take Profit
    if tp_distance is not None:
        order_body["takeProfitOnFill"] = {"distance": f"{tp_distance:.2f}"}
    elif tp_price is not None:
        order_body["takeProfitOnFill"] = {"price": f"{tp_price:.2f}"}

    body = {"order": order_body}
    resp = requests.post(url, headers=_headers(), json=body, timeout=10)
    resp.raise_for_status()
    logger.info(f"Order sent units={units} sl_dist={sl_distance} tp_dist={tp_distance} (or px {sl_price}/{tp_price})")
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
    if results:
        logger.info(f"Closed trades: {len(results)}")
    return results


def get_open_trades():
    url = f"{OANDA_API_BASE}/accounts/{OANDA_ACCOUNT_ID}/trades"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    trades = resp.json().get("trades", [])
    logger.debug(f"Open trades: {len(trades)}")
    return trades


def get_account_summary():
    """Fetch account summary (balance, NAV, open trade count)."""
    url = f"{OANDA_API_BASE}/accounts/{OANDA_ACCOUNT_ID}/summary"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    acct = resp.json().get("account", {})
    # Safely cast to floats/ints; OANDA returns strings
    def _f(k, default=0.0):
        try:
            return float(acct.get(k, default))
        except Exception:
            return default

    def _i(k, default=0):
        try:
            return int(acct.get(k, default))
        except Exception:
            return default

    summary = {
        "balance": _f("balance"),
        "nav": _f("NAV"),
        "unrealized_pl": _f("unrealizedPL"),
        "margin_available": _f("marginAvailable"),
        "margin_used": _f("marginUsed"),
        "currency": acct.get("currency", ""),
        "open_trade_count": _i("openTradeCount"),
        "last_transaction_id": acct.get("lastTransactionID"),
    }
    logger.debug(f"Account summary: nav={summary['nav']} bal={summary['balance']} utpl={summary['unrealized_pl']}")
    return summary


def get_accounts():
    """Fetch list of all accounts authorized for this token."""
    url = f"{OANDA_API_BASE}/accounts"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()

def get_current_spread() -> float:
    """Fetch current spread (Ask - Bid) for the configured instrument."""
    url = f"{OANDA_API_BASE}/accounts/{OANDA_ACCOUNT_ID}/pricing"
    params = {"instruments": OANDA_INSTRUMENT}
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=5)
        resp.raise_for_status()
        prices = resp.json().get("prices", [])
        if prices:
            bid = float(prices[0]["bids"][0]["price"])
            ask = float(prices[0]["asks"][0]["price"])
            return ask - bid
    except Exception as e:
        logger.warning(f"Failed to fetch spread: {e}")
    return 0.0
