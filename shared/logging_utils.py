"""
Shared logging utilities with timezone-aware formatting.
Used by all services in the repository.
"""
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
import pytz

# Default log directory - can be overridden per service
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_TZ = pytz.timezone(os.getenv("LOG_TIMEZONE", os.getenv("OANDA_TIMEZONE", "America/New_York")))
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


def setup_logger(
    name: str = "app",
    level: int = logging.INFO,
    log_dir: Path = None,
    log_file: str = None,
) -> logging.Logger:
    """
    Set up a logger with console and rotating file handlers.
    
    Args:
        name: Logger name (appears in log messages)
        level: Logging level (default INFO)
        log_dir: Directory for log files (default: repo_root/logs/)
        log_file: Log filename (default: {name}.log)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    # Determine log directory and file
    if log_dir is None:
        log_dir = DEFAULT_LOG_DIR
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    if log_file is None:
        log_file = f"{name}.log"
    log_path = log_dir / log_file

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(TZFormatter(FMT, DATEFMT, tz=LOG_TZ))

    # Rotating file handler
    fh = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(TZFormatter(FMT, DATEFMT, tz=LOG_TZ))

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.propagate = False
    return logger
