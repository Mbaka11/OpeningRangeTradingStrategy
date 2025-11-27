import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
import pytz

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"

LOG_TZ = pytz.timezone(os.getenv("OANDA_TIMEZONE", "America/New_York"))
FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S %Z"


class TZFormatter(logging.Formatter):
    """Formatter that stamps logs in a specific timezone (default NY)."""

    def __init__(self, fmt=None, datefmt=None, tz=None):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.tz = tz or LOG_TZ

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


def setup_logger(name: str = "bot", level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(TZFormatter(FMT, DATEFMT, tz=LOG_TZ))

    # Rotating file handler
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=5)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(TZFormatter(FMT, DATEFMT, tz=LOG_TZ))

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.propagate = False
    return logger
