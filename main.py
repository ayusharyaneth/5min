#!/usr/bin/env python3
"""
5Min Trading Bot - Robust Version
"""

# ═══════════════════════════════════════════════════════════
# STEP 1: LOAD .ENV FILE (with detailed logging)
# ═══════════════════════════════════════════════════════════

import sys
import os

print("🔧 Loading environment...")

try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Loaded .env via python-dotenv")
except ImportError:
    print("⚠️  python-dotenv not installed, using manual loader")
    # Manual loader with better parsing
    if os.path.exists('.env'):
        with open('.env') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Remove quotes if present
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value
        print("✅ Loaded .env manually")
    else:
        print("❌ .env file not found!")
        sys.exit(1)

# Debug: Show what we loaded (hide sensitive values)
print(f"   PAPER_ENABLED: {os.getenv('PAPER_ENABLED', 'NOT SET')}")
print(f"   LIVE_ENABLED: {os.getenv('LIVE_ENABLED', 'NOT SET')}")
print(f"   TELEGRAM_TOKEN: {'✅ SET' if os.getenv('TELEGRAM_TOKEN') else '❌ MISSING'}")

# ═══════════════════════════════════════════════════════════
# STEP 2: VALIDATION (with clear error messages)
# ═══════════════════════════════════════════════════════════

def validate():
    paper = os.getenv('PAPER_ENABLED', '').lower() == 'true'
    live = os.getenv('LIVE_ENABLED', '').lower() == 'true'
    
    print(f"🔍 Paper mode: {paper}, Live mode: {live}")
    
    if not paper and not live:
        print("\n❌ ERROR: No trading mode enabled!")
        print("   Set PAPER_ENABLED=true or LIVE_ENABLED=true in .env")
        print(f"   Current PAPER_ENABLED='{os.getenv('PAPER_ENABLED')}'")
        print(f"   Current LIVE_ENABLED='{os.getenv('LIVE_ENABLED')}'")
        sys.exit(1)
    
    if not os.getenv('TELEGRAM_TOKEN'):
        print("\n❌ ERROR: TELEGRAM_TOKEN not set!")
        sys.exit(1)
    
    print("✅ Validation passed")
    return paper, live

paper_enabled, live_enabled = validate()

# ═══════════════════════════════════════════════════════════
# STEP 3: SETUP LOGGING
# ═══════════════════════════════════════════════════════════

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('MAIN')

# ═══════════════════════════════════════════════════════════
# STEP 4: IMPORTS (with error catching)
# ═══════════════════════════════════════════════════════════

print("📦 Loading modules...")

try:
    from data.shimmer_client import ShimmerClient
    print("   ✓ ShimmerClient")
except Exception as e:
    logger.error(f"   ✗ ShimmerClient: {e}")
    ShimmerClient = None

try:
    from data.polymarket_client import PolymarketClient
    print("   ✓ PolymarketClient")
except Exception as e:
    logger.error(f"   ✗ PolymarketClient: {e}")
    PolymarketClient = None

try:
    from paper_trading.paper_executor import PaperExecutor
    print("   ✓ PaperExecutor")
except Exception as e:
    logger.error(f"   ✗ PaperExecutor: {e}")
    PaperExecutor = None

try:
    from live_trading.live_executor import LiveExecutor
    print("   ✓ LiveExecutor")
except Exception as e:
    logger.error(f"   ✗ LiveExecutor: {e}")
    LiveExecutor = None

try:
    from monitor.market_finder import MarketFinder
    print("   ✓ MarketFinder")
except Exception as e:
    logger.error(f"   ✗ MarketFinder: {e}")
    MarketFinder = None

try:
    from telegram_bot.bot import TelegramBotRunner
    print("   ✓ TelegramBotRunner")
except Exception as e:
    logger.error(f"   ✗ TelegramBotRunner: {e}")
    TelegramBotRunner = None

print("✅ Modules loaded")

# ═══════════════════════════════════════════════════════════
# STEP 5: BOT CLASS (simplified and robust)
# ═══════════════════════════════════════════════════════════

import json
import threading
import asyncio
import time
from typing import Dict, Any

class TradingBot:
    def __init__(self):
        self.config = self._load_config()
        self.running = False
        self.threads = []
        
        # Systems
        self.paper_enabled = paper_enabled
        self.live_enabled = live_enabled
        
        self.shimmer = None
        self.paper_exec = None
        self.polymarket = None
        self.live_exec = None
        self.telegram = None

    def _load_config(self) -> Dict:
        """Load config with defaults"""
        config = {
            "telegram_token": os.getenv("TELEGRAM_TOKEN"),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            
            # Paper settings
            "shimmer_api_key": os.getenv("SHIMMER_API_KEY", ""),
            "shimmer_mock_mode": os.getenv("SHIMMER_MOCK_MODE", "true").lower() == "true",
            "paper_auto_trade": os.getenv("PAPER_AUTO_TRADE", "false").lower() == "true",
            "paper_trade_size": float(os.getenv("PAPER_TRADE_SIZE", "10")),
            "paper_initial_balance": 10000.0,
            
            # Live settings
            "polymarket_pk": os.getenv("POLYMARKET_PK", ""),
            "polymarket_api_key": os.getenv("POLYMARKET_API_KEY", ""),
            "polymarket_secret": os.getenv("POLYMARKET_SECRET", ""),
            "live_auto_trade": os.getenv("LIVE_AUTO_TRADE", "false").lower() == "true",
            "live_trade_size": float(os.getenv("LIVE_TRADE_SIZE", "5")),
            
            "check_interval": 60
        }
        
        # Load from config.json if exists (optional override)
        if os.path.exists("config.json"):
            try:
                with open("config.json") as f:
                    config.update(json.load(f))
            except:
                pass
                
        return config

    def init_systems(self):
        """Initialize all enabled systems"""
        logger.info("=" * 50)
        logger.info("INITIALIZING SYSTEMS")
        logger.info("=" * 50)
        
        # Initialize Paper System
        if self.paper_enabled and ShimmerClient and PaperExecutor:
            logger.info("[PAPER] Initializing...")
            try:
                self.shimmer = ShimmerClient({
                    'mock_mode': self.config['shimmer_mock_mode'],
                    'api_key': self.config['shimmer_api_key']
                })
                
                self.paper_exec = PaperExecutor(
                    initial_balance=self.config['paper_initial_balance'],
                    paper_clob=self.shimmer,
                    config=self.config
                )
                
                logger.info(f"[PAPER] ✅ Ready (Balance: ${self.config['paper_initial_balance']})")
            except Exception as e:
                logger.error(f"[PAPER] ❌ Failed: {e}")
                self.paper_enabled = False
        
        # Initialize Live System
        if self.live_enabled and PolymarketClient and LiveExecutor:
            logger.info("[LIVE] Initializing...")
            try:
                self.polymarket = PolymarketClient({
                    'private_key': self.config['polymarket_pk'],
                    'api_key': self.config['polymarket_api_key'],
                    'secret': self.config['polymarket_secret']
                })
                
                if self.polymarket.connected:
                    self.live_exec = LiveExecutor(
                        polymarket_client=self.polymarket,
                        config=self.config
                    )
                    logger.info("[LIVE] ✅ Ready")
                else:
                    logger.error("[LIVE] ❌ Connection failed")
                    self.live_enabled = False
            except Exception as e:
                logger.error(f"[LIVE] ❌ Failed: {e}")
                self.live_enabled = False
        
        # Initialize Telegram
        if TelegramBotRunner and self.config.get('telegram_token'):
            logger.info("[TELEGRAM] Initializing...")
            try:
                self.telegram = TelegramBotRunner(
                    token=self.config['telegram_token'],
                    config=self.config,
                    paper_executor=self.paper_exec,
                    live_executor=self.live_exec
                )
                
                # Link notifiers
                if self.paper_exec:
                    self.paper_exec._external_notifier = self.telegram
                if self.live_exec:
                    self.live_exec._external_notifier = self.telegram
                
                logger.info("[TELEGRAM] ✅ Ready")
            except Exception as e:
                logger.error(f"[TELEGRAM] ❌ Failed: {e}")

    def trading_loop(self):
        """Main trading logic"""
        logger.info("Trading loop started")
        
        while self.running:
            try:
                # Paper trading logic
                if self.paper_enabled and self.paper_exec:
                    logger.info("[PAPER] Scanning markets...")
                    # Add your market finding logic here
                
                # Live trading logic  
                if self.live_enabled and self.live_exec:
                    logger.info("[LIVE] Scanning markets...")
                    # Add your live trading logic here
                
                time.sleep(self.config['check_interval'])
                
            except Exception as e:
                logger.error(f"Loop error: {e}")
                time.sleep(5)

    def start(self):
        """Start the bot"""
        print("\n" + "=" * 50)
        print("5MIN TRADING BOT STARTING")
        if self.paper_enabled:
            print("📘 Paper: ENABLED")
        if self.live_enabled:
            print("💰 Live: ENABLED")
        print("=" * 50 + "\n")
        
        self.running = True
        self.init_systems()
        
        # Start Telegram
        if self.telegram:
            try:
                self.telegram.start()
                time.sleep(2)
            except Exception as e:
                logger.error(f"Telegram start failed: {e}")
        
        # Start trading thread
        logger.info("Starting trading thread...")
        t = threading.Thread(target=self.trading_loop, daemon=True)
        t.start()
        self.threads.append(t)
        
        # Keep main thread alive
        logger.info("Bot running (Ctrl+C to stop)")
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            self.stop()

    def stop(self):
        """Stop gracefully"""
        self.running = False
        if self.telegram:
            try:
                self.telegram.stop()
            except:
                pass
        
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=2)
        
        logger.info("Bot stopped")

# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

def main():
    print("🚀 Starting bot...")
    try:
        bot = TradingBot()
        bot.start()
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
