"""Notifier for posting trade updates via Twitter/X API (v1.1 statuses/update).
Logs and skips if credentials are missing.
"""
import os
import requests
from requests_oauthlib import OAuth1
from dotenv import load_dotenv
from live.logging_utils import setup_logger

load_dotenv()
logger = setup_logger("notifier")

API_KEY = os.getenv("TWITTER_API_KEY", "")
API_SECRET = os.getenv("TWITTER_API_SECRET", "")
ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET", "")


def can_post_api() -> bool:
    ok = all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET])
    if not ok:
        logger.info("Notifier: Twitter API creds missing; set TWITTER_* env vars.")
    return ok


def notify_trade(message: str):
    if not can_post_api():
        logger.info(f"Notifier: would post (no creds): {message}")
        return {"status": "skipped", "reason": "no_credentials"}
    url = "https://api.twitter.com/1.1/statuses/update.json"
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
    try:
        resp = requests.post(url, auth=auth, data={"status": message}, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Notifier: API post failed ({resp.status_code}): {resp.text}")
            return {"status": "error", "code": resp.status_code, "body": resp.text}
        logger.info("Notifier: tweet posted via API")
        return {"status": "posted", "via": "api"}
    except Exception as e:
        logger.exception(f"Notifier: exception posting tweet: {e}")
        return {"status": "error", "reason": str(e)}
