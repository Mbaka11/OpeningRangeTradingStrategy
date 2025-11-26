"""Notifier for posting trade updates via Twitter/X API v2 (tweepy Client).
Logs and skips if credentials are missing.
"""
import os
import tweepy
from dotenv import load_dotenv
from live.logging_utils import setup_logger

load_dotenv()
logger = setup_logger("notifier")

API_KEY = os.getenv("TWITTER_API_KEY", "")
API_SECRET = os.getenv("TWITTER_API_SECRET", "")
ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET", "")


def can_post() -> bool:
    ok = all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET])
    if not ok:
        logger.info("Notifier: Twitter API creds missing; set TWITTER_* env vars.")
    return ok


def notify_trade(message: str):
    if not can_post():
        logger.info(f"Notifier: would post (no creds): {message}")
        return {"status": "skipped", "reason": "no_credentials"}
    try:
        client = tweepy.Client(
            consumer_key=API_KEY,
            consumer_secret=API_SECRET,
            access_token=ACCESS_TOKEN,
            access_token_secret=ACCESS_SECRET,
        )
        resp = client.create_tweet(text=message)
        logger.info("Notifier: tweet posted via v2 client")
        return {"status": "posted", "via": "api", "id": getattr(resp, 'data', {})}
    except Exception as e:
        logger.warning(f"Notifier: tweet failed: {e}")
        return {"status": "error", "reason": str(e)}
