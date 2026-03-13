#!/usr/bin/env python3
"""
5Min Trading Bot - Main Entry Point
"""

import os
import sys
import time
import json
import logging
import threading
import asyncio
from datetime import datetime
from typing import Dict, Any

# ═══════════════════════════════════════════════════════════
# CLEAN LOGGING SETUP
# ═══════════════════════════════════════════════════════════

class CleanFormatter(logging.Formatter):
    """Ultra-clean formatter with emojis and minimal clutter"""
    
    def format(self, record):
        # Emoji mapping
        emojis = {
            'INFO': '✓',
            'WARNING': '⚠',
            'ERROR': '✗',
            'CRITICAL': '🔥',
            'DEBUG': '•'
        }
        
        # Simplify module names
        module = record.name.split('.')[-1].replace('_', ' ').title()
        
        # Format: "✓ Module | Message"
        emoji = emojis.get(record.levelname, '•')
        return f"{emoji} {module:12} | {record.getMessage()}"

# Setup clean handler
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(CleanFormatter())

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers = []  # Remove default handlers
root_logger.addHandler(handler)

# Silence noisy libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

logger = logging.getLogger('Main')

# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════

try:
    from paper_trading.paper_executor import PaperExecutor
    from paper_trading.paper_db import PaperDB
except ImportError as e:
    logger.error(f"Paper trading import failed: {e}")
    PaperExecutor = None
    PaperDB = None

try:
    from monitor.market_finder import MarketFinder
    from monitor.closure_checker import ClosureChecker
except ImportError as e:
    logger.error(f"Monitor import failed: {e}")
    MarketFinder = None
    ClosureChecker = None

try:
    from telegram_bot.bot import TelegramBotRunner
except ImportError as e:
    logger.error(f"Telegram import failed: {e}")
    TelegramBotRunner = None

try:
    from telegram_bot.dashboard import Dashboard
except ImportError:
    Dashboard = None

# Optional components
CLOBClient = None
DataStore = None

# ═══════════════════════════════════════════════════════════
# BOT CLASS
# ═══════════════════════════════════════════════════════════

class TradingBot:
    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.running = False
        self.threads = []
        
        # Components
        self.db = None
        self.store = None
        self.clob = None
        self.paper_exec = None
        self.market_finder = None
        self.closure_checker = None
        self.dashboard = None
        self.telegram_bot = None
        
        # Track if we've logged the "no markets" warning already
        self._logged_no_markets = False

    def _load_config(self, path: str) -> Dict:
        """Load config with defaults"""
        defaults = {
            "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            "initial_balance": 10000.0,
            "check_interval": 60,
            "discovery_interval": 15,
            "auto_trade": False,
            "default_trade_size": 1.0,
            "db_path": "trades.db"
        }
        
        if os.path.exists(path):
            try:
                with open(path) as f:
                    defaults.update(json.load(f))
            except Exception as e:
                logger.warning(f"Config load failed: {e}")
        else:
            with open(path, 'w') as f:
                json.dump(defaults, f, indent=2)
            logger.info(f"Created default config: {path}")
        
        return defaults

    def _init_components(self):
        """Initialize all components with clean logging"""
        logger.info("Initializing components...")
        
        # Database
        if PaperDB:
            try:
                self.db = PaperDB(self.config['db_path'])
                logger.info("Database connected")
            except Exception as e:
                logger.error(f"Database failed: {e}")
        
        # Dashboard (optional)
        if Dashboard:
            try:
                self.dashboard = Dashboard()
                logger.info("Dashboard ready")
            except:
                pass  # Silent fail for optional component
        
        # Paper Executor
        if PaperExecutor:
            try:
                self.paper_exec = PaperExecutor(
                    initial_balance=self.config['initial_balance'],
                    paper_clob=None,  # Will use mock/mock later
                    paper_store=None,
                    db=self.db,
                    config=self.config
                )
                logger.info(f"Trading engine ready | Balance: ${self.config['initial_balance']:,.0f}")
            except Exception as e:
                logger.error(f"Trading engine failed: {e}")
        
        # Market Finder
        if MarketFinder:
            try:
                self.market_finder = MarketFinder(
                    clob=None,
                    store=None,
                    db=self.db,
                    config=self.config,
                    paper_executor=self.paper_exec
                )
                logger.info("Market finder ready")
            except Exception as e:
                logger.error(f"Market finder failed: {e}")
        
        # Closure Checker
        if ClosureChecker:
            try:
                self.closure_checker = ClosureChecker(
                    clob=None,
                    store=None,
                    db=self.db,
                    config=self.config,
                    paper_executor=self.paper_exec
                )
                logger.info("Monitor ready")
            except Exception as e:
                logger.error(f"Monitor failed: {e}")
        
        # Telegram Bot
        if TelegramBotRunner and self.config.get('telegram_token'):
            try:
                bot_config = self.config.copy()
                bot_config['chat_id'] = self.config.get('telegram_chat_id')
                
                self.telegram_bot = TelegramBotRunner(
                    token=self.config['telegram_token'],
                    config=bot_config,
                    dashboard=self.dashboard,
                    db=self.db,
                    store=self.store,
                    paper_executor=self.paper_exec,
                    market_finder=self.market_finder,
                    closure_checker=self.closure_checker
                )
                
                # Inject notifier back
                if self.paper_exec:
                    self.paper_exec._external_notifier = self.telegram_bot
                if self.market_finder:
                    self.market_finder._external_notifier = self.telegram_bot
                if self.closure_checker:
                    self.closure_checker._external_notifier = self.telegram_bot
                
                logger.info("Telegram bot ready")
            except Exception as e:
                logger.error(f"Telegram bot failed: {e}")
        
        # Summary
        active = sum([bool(self.db), bool(self.paper_exec), 
                     bool(self.market_finder), bool(self.closure_checker),
                     bool(self.telegram_bot)])
        logger.info(f"Systems online: {active}/5")

    def _market_discovery_loop(self):
        """Background market discovery"""
        logger.info("Market discovery started")
        interval = self.config.get('discovery_interval', 15)
        
        while self.running:
            try:
                if self.market_finder:
                    markets = self.market_finder.find_active_btc_5m_markets()
                    
                    if markets:
                        logger.info(f"Found {len(markets)} BTC markets")
                        symbols = [m.get('symbol') for m in markets if m]
                        if symbols:
                            opportunities = self.market_finder.find_opportunities(symbols)
                            if opportunities:
                                logger.info(f"Found {len(opportunities)} opportunities")
                    else:
                        # Only log this once to avoid spam
                        if not self._logged_no_markets:
                            logger.warning("No markets found (CLOB not connected)")
                            self._logged_no_markets = True
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"Discovery error: {e}")
                time.sleep(5)

    def _closure_check_loop(self):
        """Background closure monitoring"""
        logger.info("Monitor started")
        
        if not self.closure_checker:
            return
        
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.closure_checker.run())
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        finally:
            if loop:
                try:
                    loop.close()
                except:
                    pass

    def start(self):
        """Start bot"""
        logger.info("═" * 50)
        logger.info("5MIN TRADING BOT STARTING")
        logger.info("═" * 50)
        
        self.running = True
        self._init_components()
        
        # Start Telegram
        if self.telegram_bot:
            self.telegram_bot.start()
            time.sleep(2)
            logger.info("Bot active - Press Ctrl+C to stop")
        
        # Start threads
        if self.market_finder:
            t = threading.Thread(target=self._market_discovery_loop, name="Discovery", daemon=True)
            t.start()
            self.threads.append(t)
        
        if self.closure_checker:
            t = threading.Thread(target=self._closure_check_loop, name="Monitor", daemon=True)
            t.start()
            self.threads.append(t)
        
        self._main_loop()

    def _main_loop(self):
        """Main loop"""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n" + "═" * 50)
            logger.info("SHUTDOWN SIGNAL RECEIVED")
            self.stop()

    def stop(self):
        """Stop bot"""
        logger.info("Stopping...")
        self.running = False
        
        if self.telegram_bot:
            self.telegram_bot.stop()
        if self.closure_checker and hasattr(self.closure_checker, 'stop'):
            self.closure_checker.stop()
        
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=3)
        
        logger.info("Bot stopped")
        logger.info("═" * 50)

    def run(self):
        try:
            self.start()
        except Exception as e:
            logger.critical(f"Fatal error: {e}")
            raise


def main():
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
