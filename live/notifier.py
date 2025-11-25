"""Notifier for posting trade updates via twikit (web client)."""
import os
from live.logging_utils import setup_logger

logger = setup_logger("notifier")

TW_USERNAME = os.getenv("TWIKIT_USERNAME", "")
TW_PASSWORD = os.getenv("TWIKIT_PASSWORD", "")
TW_EMAIL    = os.getenv("TWIKIT_EMAIL", "")
TW_SESSION  = os.getenv("TWIKIT_SESSION_PATH", "live/logs/twikit_session.json")


def can_post_twikit() -> bool:
    return bool(TW_USERNAME and TW_PASSWORD)


def notify_via_twikit(message: str):
    try:
        from twikit import Client
    except Exception as e:
        raise RuntimeError(f"twikit not available: {e}")

    client = Client("en-US")
    try:
        client.load_cookies(TW_SESSION)
        client.authorize()
    except Exception:
        client.login(auth_info_1=TW_USERNAME, auth_info_2=TW_EMAIL or None, password=TW_PASSWORD)
        try:
            client.save_cookies(TW_SESSION)
        except Exception:
            logger.warning("Twikit: could not save session cookies; will login next time")
    client.create_tweet(text=message)
    return {"status": "posted", "via": "twikit"}


def notify_trade(message: str):
    if can_post_twikit():
        try:
            res = notify_via_twikit(message)
            logger.info("Notifier: tweet posted via twikit")
            return res
        except Exception as e:
            logger.warning(f"Notifier twikit failed: {e}")
    logger.info(f"Notifier: credentials missing/failed; would post: {message}")
    return {"status": "skipped", "reason": "no_credentials"}
