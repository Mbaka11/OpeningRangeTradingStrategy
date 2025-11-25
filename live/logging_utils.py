import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"

FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str = "bot", level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(FMT, DATEFMT))

    # Rotating file handler
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=5)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FMT, DATEFMT))

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.propagate = False
    return logger
