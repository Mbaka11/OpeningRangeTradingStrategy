# Shared Utilities

Cross-service utility modules used by all services.

## Modules

### `logging_utils.py`

TZ-aware rotating logger with New York timezone timestamps.

```python
from shared.logging_utils import setup_logger

logger = setup_logger("my_module", log_dir=Path("logs/myservice"))
logger.info("Message with NY timestamp")
```

Features:

- Rotating file handler (5 MB, 3 backups)
- Console handler
- America/New_York timezone
- Configurable log level via `LOG_LEVEL` env var

### `notifier.py`

Twitter/X posting for all services.

```python
from shared.notifier import notify_trade, post_tweet, can_post

# Check if posting is enabled
if can_post():
    post_tweet("Hello from OpeningRange!")

# Trading-specific helper
notify_trade("LONG", 21500.0, 21475.0, 21575.0, 21550.0, "Entry filled")
```

Features:

- Tweepy v2 API integration
- Optional image attachments
- Graceful degradation if credentials missing

## Environment Variables

| Variable                  | Used By         | Description                             |
| ------------------------- | --------------- | --------------------------------------- |
| `LOG_LEVEL`               | `logging_utils` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `TWITTER_CONSUMER_KEY`    | `notifier`      | Twitter API consumer key                |
| `TWITTER_CONSUMER_SECRET` | `notifier`      | Twitter API consumer secret             |
| `TWITTER_ACCESS_TOKEN`    | `notifier`      | Twitter access token                    |
| `TWITTER_ACCESS_SECRET`   | `notifier`      | Twitter access token secret             |
| `TWITTER_BEARER_TOKEN`    | `notifier`      | Twitter bearer token                    |
