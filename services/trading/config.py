"""
Configuration loader for the trading service.
Loads YAML configs and environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import yaml

# Load .env if present
load_dotenv()

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str):
    path = CONFIG_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_env(key: str, default=None):
    return os.getenv(key, default)


OANDA_ACCOUNT_ID = get_env("OANDA_ACCOUNT_ID", "")
OANDA_API_TOKEN  = get_env("OANDA_API_TOKEN", "")
OANDA_ENV        = get_env("OANDA_ENV", "practice")  # practice | live
OANDA_INSTRUMENT = get_env("OANDA_INSTRUMENT", "NAS100_USD")
OANDA_TIMEZONE   = get_env("OANDA_TIMEZONE", "America/New_York")

# Base URLs
if OANDA_ENV == "live":
    OANDA_API_BASE = "https://api-fxtrade.oanda.com/v3"
    OANDA_STREAM_BASE = "https://stream-fxtrade.oanda.com/v3"
else:
    OANDA_API_BASE = "https://api-fxpractice.oanda.com/v3"
    OANDA_STREAM_BASE = "https://stream-fxpractice.oanda.com/v3"

# Load strategy/instrument YAMLs (used for OR timings, SL/TP, etc.)
STRATEGY = load_yaml("strategy.yml")
INSTRUMENTS = load_yaml("instruments.yml")
