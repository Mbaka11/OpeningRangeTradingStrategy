"""Notifier for posting trade updates via Twitter/X API v2 (tweepy Client).
Logs and skips if credentials are missing.
"""
import os
import io
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


def notify_trade(message: str, image_buffer=None):
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
        
        media_ids = []
        if image_buffer:
            # Use v1.1 API for media upload
            auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
            api = tweepy.API(auth)
            try:
                media = api.media_upload(filename="chart.png", file=image_buffer)
                media_ids.append(media.media_id)
                logger.info("Notifier: Image uploaded successfully")
            except Exception as e:
                logger.warning(f"Notifier: Image upload failed (likely Free Tier limit): {e}")

        resp = client.create_tweet(text=message, media_ids=media_ids if media_ids else None)
        logger.info("Notifier: tweet posted via v2 client")
        return {"status": "posted", "via": "api", "id": getattr(resp, 'data', {})}
        try:
            resp = client.create_tweet(text=message, media_ids=media_ids if media_ids else None)
            logger.info("Notifier: tweet posted via v2 client")
            return {"status": "posted", "via": "api", "id": getattr(resp, 'data', {})}
        except Exception as e:
            # If media caused the 403 (common on Free Tier), retry text-only
            if media_ids and "403" in str(e):
                logger.warning(f"Notifier: Tweet with media failed (403). Retrying text-only...")
                resp = client.create_tweet(text=message)
                logger.info("Notifier: Text-only tweet posted successfully (fallback)")
                return {"status": "posted", "via": "api_fallback", "id": getattr(resp, 'data', {})}
            raise
    except Exception as e:
        logger.warning(f"Notifier: tweet failed: {e}")
        if "403" in str(e):
            logger.warning("Hint: 403 Forbidden often means missing Write permissions in Twitter Dev Portal or Free Tier limits.")
        return {"status": "error", "reason": str(e)}
