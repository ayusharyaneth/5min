"""Configuration module - loads all environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# Wallet and API credentials
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_WALLET_ADDRESS = os.getenv("POLYMARKET_WALLET_ADDRESS", "")
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")

# Telegram settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_LOGS_CHANNEL_ID = os.getenv("TELEGRAM_LOGS_CHANNEL_ID", "")
TELEGRAM_TRADES_CHANNEL_ID = os.getenv("TELEGRAM_TRADES_CHANNEL_ID", "")
TELEGRAM_ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))

# Trading mode flags
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
PAPER_TRADING = os.getenv("PAPER_TRADING", "false").lower() == "true"

# Paper trading settings
PAPER_STARTING_BALANCE = float(os.getenv("PAPER_STARTING_BALANCE", "10000.0"))
PAPER_DB_PATH = os.getenv("PAPER_DB_PATH", "paper_trades.db")

# Risk management
DAILY_LOSS_LIMIT_USD = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100.0"))

# Strategy parameters
BASE_SIZE = float(os.getenv("BASE_SIZE", "24"))
COST_PER_PAIR_MAX = float(os.getenv("COST_PER_PAIR_MAX", "1.0"))
MAX_BUYS_PER_TICK = int(os.getenv("MAX_BUYS_PER_TICK", "2"))
COOLDOWN_SECS = int(os.getenv("COOLDOWN_SECS", "1"))
SIZE_REDUCE_AFTER_SECS = int(os.getenv("SIZE_REDUCE_AFTER_SECS", "240"))
SIZE_MIN_RATIO = float(os.getenv("SIZE_MIN_RATIO", "0.5"))
SIZE_MIN_SHARES = float(os.getenv("SIZE_MIN_SHARES", "6"))
TREND_WINDOW = int(os.getenv("TREND_WINDOW", "5"))

# Polling intervals
MARKET_POLL_INTERVAL = int(os.getenv("MARKET_POLL_INTERVAL", "15"))
CLOSURE_CHECK_INTERVAL = int(os.getenv("CLOSURE_CHECK_INTERVAL", "20"))

# Logging
LOG_FILE = os.getenv("LOG_FILE", "bot.log")

# CLOB API endpoints
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
