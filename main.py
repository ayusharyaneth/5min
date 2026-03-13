#!/usr/bin/env python3
"""
5Min Trading Bot - Main Entry Point
High-frequency trading bot for 5-minute prediction markets
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Import trading components
try:
    from paper_trading.paper_executor import PaperExecutor
    from paper_trading.paper_db import PaperDB
except ImportError as e:
    logger.error(f"Failed to import paper_trading modules: {e}")
    PaperExecutor = None
    PaperDB = None

try:
    from monitor.market_finder import MarketFinder
    from monitor.closure_checker import ClosureChecker
except ImportError as e:
    logger.error(f"Failed to import monitor modules: {e}")
    MarketFinder = None
    ClosureChecker = None

try:
    from telegram_bot.bot import TelegramBotRunner
except ImportError as e:
    logger.error(f"Failed to import telegram_bot: {e}")
    TelegramBotRunner = None

try:
    from telegram_bot.dashboard import Dashboard
except ImportError as e:
    logger.warning(f"Dashboard not available: {e}")
    Dashboard = None

try:
    from data.clob import CLOBClient  # Adjust import based on your actual CLOB module
except ImportError:
    try:
        from clob import CLOBClient
    except ImportError:
        logger.warning("CLOBClient not found, using None")
        CLOBClient = None

try:
    from data.store import DataStore  # Adjust import based on your actual store module
except ImportError:
    try:
        from store import DataStore
    except ImportError:
        logger.warning("DataStore not found, using None")
        DataStore = None


class TradingBot:
    def __init__(self, config_path: str = "config.json"):
        """Initialize the trading bot with configuration"""
        self.config = self._load_config(config_path)
        self.running = False
        self.threads = []
        
        # Component placeholders
        self.db = None
        self.store = None
        self.clob = None
        self.paper_exec = None
        self.market_finder = None
        self.closure_checker = None
        self.dashboard = None
        self.telegram_bot = None
        
        logger.info("TradingBot instance created")

    def _load_config(self, path: str) -> Dict:
        """Load configuration from JSON file"""
        default_config = {
            "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            "initial_balance": 10000.0,
            "check_interval": 60,
            "auto_trade": False,
            "default_trade_size": 1.0,
            "symbols": ["BTC-USD", "ETH-USD"],
            "notifications_enabled": True,
            "paper_trading": True,
            "db_path": "trades.db"
        }
        
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
                    logger.info(f"Configuration loaded from {path}")
            else:
                logger.warning(f"Config file {path} not found, using defaults")
                # Create default config file
                with open(path, 'w') as f:
                    json.dump(default_config, f, indent=2)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            
        return default_config

    def _init_database(self):
        """Initialize database connection"""
        try:
            if PaperDB:
                self.db = PaperDB(self.config.get('db_path', 'trades.db'))
                logger.info("Database initialized")
            else:
                self.db = None
                logger.warning("PaperDB not available")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            self.db = None

    def _init_clob_and_store(self):
        """Initialize CLOB and Data Store"""
        # Initialize Store
        try:
            if DataStore:
                self.store = DataStore(config=self.config)
                logger.info("DataStore initialized")
            else:
                self.store = None
        except Exception as e:
            logger.error(f"Failed to initialize store: {e}")
            self.store = None
        
        # Initialize CLOB
        try:
            if CLOBClient:
                self.clob = CLOBClient(config=self.config)
                logger.info("CLOB Client initialized")
            else:
                self.clob = None
        except Exception as e:
            logger.error(f"Failed to initialize CLOB: {e}")
            self.clob = None

    def _init_components(self):
        """Initialize all trading components with proper dependency injection"""
        logger.info("Initializing components...")
        
        # 1. Initialize DB first
        self._init_database()
        
        # 2. Initialize CLOB and Store (needed by other components)
        self._init_clob_and_store()
        
        # 3. Initialize Dashboard if available
        if Dashboard:
            try:
                self.dashboard = Dashboard(config=self.config)
                logger.info("Dashboard initialized")
            except Exception as e:
                logger.error(f"Failed to initialize dashboard: {e}")
                self.dashboard = None
        
        # 4. Initialize Paper Executor (core trading engine)
        if PaperExecutor:
            try:
                self.paper_exec = PaperExecutor(
                    initial_balance=self.config.get('initial_balance', 10000.0),
                    paper_clob=self.clob,  # Pass CLOB for price data
                    paper_store=self.store,  # Pass store for persistence
                    db=self.db,  # Pass database
                    config=self.config,
                    # notifier will be lazy-loaded to avoid circular imports
                )
                logger.info(f"PaperExecutor initialized with balance: ${self.config.get('initial_balance', 10000.0)}")
            except Exception as e:
                logger.error(f"Failed to initialize PaperExecutor: {e}")
                self.paper_exec = None
        else:
            logger.error("PaperExecutor not available")
            self.paper_exec = None
        
        # 5. Initialize Market Finder (depends on CLOB/Store)
        if MarketFinder:
            try:
                self.market_finder = MarketFinder(
                    clob=self.clob,  # For market data
                    store=self.store,  # For persistence
                    db=self.db,  # For recording opportunities
                    config=self.config,
                    paper_executor=self.paper_exec,  # For auto-trading
                    notifier=None  # Will lazy load
                )
                logger.info("MarketFinder initialized")
            except Exception as e:
                logger.error(f"Failed to initialize MarketFinder: {e}")
                self.market_finder = None
        else:
            logger.error("MarketFinder not available")
            self.market_finder = None
        
        # 6. Initialize Closure Checker (depends on CLOB/Store/DB)
        if ClosureChecker:
            try:
                self.closure_checker = ClosureChecker(
                    clob=self.clob,  # For market status
                    store=self.store,  # For settlement data
                    db=self.db,  # For recording settlements
                    config=self.config,
                    paper_executor=self.paper_exec,  # To update positions
                    notifier=None  # Will lazy load
                )
                logger.info("ClosureChecker initialized")
            except Exception as e:
                logger.error(f"Failed to initialize ClosureChecker: {e}")
                self.closure_checker = None
        else:
            logger.error("ClosureChecker not available")
            self.closure_checker = None
        
        # 7. Initialize Telegram Bot (pass ALL dependencies)
        if TelegramBotRunner:
            try:
                # Prepare bot config with chat_id
                bot_config = self.config.copy()
                if 'telegram_chat_id' in self.config:
                    bot_config['chat_id'] = self.config['telegram_chat_id']
                
                self.telegram_bot = TelegramBotRunner(
                    token=self.config.get('telegram_token', ''),
                    config=bot_config,
                    dashboard=self.dashboard,  # Dashboard integration
                    db=self.db,  # Database access
                    store=self.store,  # Store access
                    paper_executor=self.paper_exec,  # CRITICAL: Trading engine
                    market_finder=self.market_finder,  # CRITICAL: Market data
                    closure_checker=self.closure_checker  # CRITICAL: Monitor
                )
                
                # Inject telegram bot back into other components for notifications
                if self.paper_exec:
                    self.paper_exec._external_notifier = self.telegram_bot
                
                if self.market_finder:
                    self.market_finder._external_notifier = self.telegram_bot
                    
                if self.closure_checker:
                    self.closure_checker._external_notifier = self.telegram_bot
                
                logger.info("TelegramBotRunner initialized with all dependencies")
            except Exception as e:
                logger.error(f"Failed to initialize TelegramBotRunner: {e}")
                self.telegram_bot = None
        else:
            logger.error("TelegramBotRunner not available")
            self.telegram_bot = None
        
        logger.info("Components initialized successfully")

    def _market_discovery_loop(self):
        """Background thread: Continuously find trading opportunities"""
        logger.info("Market discovery thread started")
        
        if not self.market_finder:
            logger.error("MarketFinder not available, stopping discovery thread")
            return
        
        interval = self.config.get('discovery_interval', 15)  # Check every 15 seconds
        
        while self.running:
            try:
                # Find BTC 5m markets
                markets = self.market_finder.find_active_btc_5m_markets()
                
                if markets:
                    logger.info(f"Discovered {len(markets)} active BTC 5m markets")
                    # Analyze for opportunities
                    symbols = [m.get('symbol', m.get('market_id')) for m in markets if m]
                    if symbols:
                        opportunities = self.market_finder.find_opportunities(symbols)
                        if opportunities:
                            logger.info(f"Found {len(opportunities)} trading opportunities")
                else:
                    logger.debug("No active BTC 5m markets found")
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"Market discovery error: {e}")
                time.sleep(5)  # Short sleep on error

    def _closure_check_loop(self):
        """Background thread: Monitor for market closures and settle positions"""
        logger.info("Closure check thread started")
        
        if not self.closure_checker:
            logger.error("ClosureChecker not available, stopping closure thread")
            return
        
        # Run the async loop in this thread
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.closure_checker.run())
        except Exception as e:
            logger.error(f"Closure check loop error: {e}")
        finally:
            loop.close()

    def start(self):
        """Start the trading bot"""
        logger.info("Starting 5Min Trading Bot...")
        self.running = True
        
        # Initialize all components
        self._init_components()
        
        # Start Telegram Bot
        if self.telegram_bot:
            try:
                self.telegram_bot.start()
                # Give bot time to connect
                time.sleep(2)
            except Exception as e:
                logger.error(f"Failed to start Telegram bot: {e}")
        
        # Start Market Discovery Thread
        if self.market_finder:
            discovery_thread = threading.Thread(
                target=self._market_discovery_loop,
                name="MarketDiscovery",
                daemon=True
            )
            discovery_thread.start()
            self.threads.append(discovery_thread)
            logger.info("Market discovery thread started")
        
        # Start Closure Check Thread
        if self.closure_checker:
            closure_thread = threading.Thread(
                target=self._closure_check_loop,
                name="ClosureChecker",
                daemon=True
            )
            closure_thread.start()
            self.threads.append(closure_thread)
            logger.info("Closure check thread started")
        
        logger.info("All systems started. Entering main loop...")
        self._main_loop()

    def _main_loop(self):
        """Main trading loop"""
        logger.info("Starting main trading loop...")
        
        while self.running:
            try:
                # Main bot logic here
                # This could include:
                # - Periodic status checks
                # - Health monitoring
                # - Strategy execution
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                self.stop()
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(5)

    def stop(self):
        """Stop the trading bot gracefully"""
        logger.info("Stopping 5Min Trading Bot...")
        self.running = False
        
        # Stop Telegram bot
        if self.telegram_bot:
            try:
                self.telegram_bot.stop()
            except Exception as e:
                logger.error(f"Error stopping Telegram bot: {e}")
        
        # Stop closure checker
        if self.closure_checker:
            try:
                self.closure_checker.stop()
            except Exception as e:
                logger.error(f"Error stopping closure checker: {e}")
        
        # Wait for threads to finish
        for thread in self.threads:
            if thread.is_alive():
                logger.info(f"Waiting for {thread.name} to finish...")
                thread.join(timeout=5)
        
        logger.info("Bot stopped successfully")

    def run(self):
        """Entry point to run the bot"""
        try:
            self.start()
        except Exception as e:
            logger.critical(f"Fatal error in bot execution: {e}")
            raise


def main():
    """Main entry point"""
    # Check for required environment variables
    if not os.getenv("TELEGRAM_TOKEN") and not os.path.exists("config.json"):
        logger.warning("TELEGRAM_TOKEN not set and config.json not found")
        logger.info("Creating default config.json - please edit it with your credentials")
    
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
