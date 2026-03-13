#!/usr/bin/env python3
"""
5Min Trading Bot - Dual Mode
Shimmer (Simulation) | Polymarket (Live)
"""

import os
import sys
import time
import json
import logging
import threading
import asyncio
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════════════════════════
# MANDATORY ENVIRONMENT VARIABLE VALIDATION
# ═══════════════════════════════════════════════════════════

def validate_mandatory_env():
    """
    Check for mandatory environment variables.
    If any are missing, print error and force exit.
    """
    # Define mandatory variables
    MANDATORY_VARS = [
        'TELEGRAM_TOKEN',  # Essential for bot to function
    ]
    
    # Conditional mandatory based on mode
    trading_mode = os.getenv('TRADING_MODE', 'paper').lower()
    
    if trading_mode == 'live':
        # Additional requirements for live trading
        MANDATORY_VARS.extend([
            'POLYMARKET_PK',  # Private key required for live trading
            'POLYMARKET_API_KEY',  # API credentials
            'POLYMARKET_SECRET'
        ])
    
    # Check for missing variables
    missing = []
    for var in MANDATORY_VARS:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        # Print error banner
        print("\n" + "═" * 60)
        print("❌  ERROR: MANDATORY ENVIRONMENT VARIABLES MISSING")
        print("═" * 60)
        print("\nThe following required variables are not set:\n")
        
        for var in missing:
            if var == 'TELEGRAM_TOKEN':
                print(f"  • {var} - Your Telegram Bot Token (get from @BotFather)")
            elif var == 'POLYMARKET_PK':
                print(f"  • {var} - Your Polymarket Private Key (required for LIVE mode)")
            elif var == 'POLYMARKET_API_KEY':
                print(f"  • {var} - Polymarket API Key")
            elif var == 'POLYMARKET_SECRET':
                print(f"  • {var} - Polymarket API Secret")
            else:
                print(f"  • {var}")
        
        print("\n" + "─" * 60)
        print("Setup Instructions:")
        print("─" * 60)
        
        if 'TELEGRAM_TOKEN' in missing:
            print("\n1. Get Telegram Token:")
            print("   • Message @BotFather on Telegram")
            print("   • Create new bot with /newbot")
            print("   • Copy the token provided")
        
        if trading_mode == 'live' and any(x in missing for x in ['POLYMARKET_PK', 'POLYMARKET_API_KEY']):
            print("\n2. Polymarket Setup (for Live Trading):")
            print("   • Export your wallet private key")
            print("   • Get API credentials from Polymarket dashboard")
        
        print("\n3. Set Environment Variables:")
        print("   export TELEGRAM_TOKEN='your_token_here'")
        if trading_mode == 'live':
            print("   export POLYMARKET_PK='your_private_key'")
            print("   export TRADING_MODE='live'")
        else:
            print("   export TRADING_MODE='paper'")
        
        print("\n4. Or create .env file in bot directory with these variables")
        print("═" * 60)
        print("🛑 SHUTTING DOWN - Cannot start without required configuration")
        print("═" * 60 + "\n")
        
        # Force exit
        sys.exit(1)

# Run validation immediately on import
validate_mandatory_env()

# ═══════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════

class AlignFormatter(logging.Formatter):
    def format(self, record):
        icons = {'INFO': '✓', 'WARNING': '⚠', 'ERROR': '✗', 'CRITICAL': '🔥', 'DEBUG': '·'}
        icon = icons.get(record.levelname, '•')
        name = record.name.split('.')[-1].upper()[:10].ljust(10)
        return f"{icon}  {name} | {record.getMessage()}"

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(AlignFormatter())
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('telegram').setLevel(logging.ERROR)

logger = logging.getLogger('MAIN')

# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════

try:
    from data.shimmer_client import ShimmerClient
    from paper_trading.paper_executor import PaperExecutor
    from monitor.market_finder import MarketFinder
    from telegram_bot.bot import TelegramBotRunner
except ImportError as e:
    logger.error(f"Import error: {e}")

# ═══════════════════════════════════════════════════════════
# BOT CLASS
# ═══════════════════════════════════════════════════════════

class TradingBot:
    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.running = False
        self.threads = []
        
        self.trading_mode = self.config.get('trading_mode', 'paper')
        
        self.shimmer = None
        self.paper_exec = None
        self.market_finder = None
        self.telegram = None
        
    def _load_config(self, path: str) -> Dict:
        defaults = {
            "trading_mode": os.getenv('TRADING_MODE', 'paper'),
            "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            "shimmer_api_key": os.getenv("SHIMMER_KEY", ""),
            "shimmer_url": "https://api.shimmer.network",
            "mock_mode": True,
            "initial_balance": 10000.0,
            "max_trade_size": 100.0,
            "auto_trade": False,
            "default_trade_size": 1.0,
            "check_interval": 60,
            "discovery_interval": 15,
            "db_path": "trades.db"
        }
        
        if os.path.exists(path):
            try:
                with open(path) as f:
                    loaded = json.load(f)
                    defaults.update(loaded)
            except Exception as e:
                logger.warning(f"Config error: {e}")
        else:
            with open(path, 'w') as f:
                json.dump(defaults, f, indent=2)
            logger.info(f"Created default config: {path}")
        
        return defaults

    def _init_components(self):
        """Initialize based on trading mode"""
        logger.info(f"{'='*40}")
        logger.info(f"MODE: {self.trading_mode.upper()} TRADING")
        logger.info(f"{'='*40}")
        
        # Initialize components
        if ShimmerClient:
            self.shimmer = ShimmerClient(self.config)
            logger.info("Shimmer connected")
        
        if PaperExecutor:
            self.paper_exec = PaperExecutor(
                initial_balance=self.config['initial_balance'],
                paper_clob=self.shimmer,
                config=self.config
            )
            logger.info(f"Trading ready | Balance ${self.config['initial_balance']:,.0f}")
        
        if MarketFinder:
            self.market_finder = MarketFinder(
                clob=self.shimmer,
                config=self.config,
                paper_executor=self.paper_exec
            )
            logger.info("Market finder ready")
        
        if TelegramBotRunner and self.config.get('telegram_token'):
            self.telegram = TelegramBotRunner(
                token=self.config['telegram_token'],
                config=self.config,
                paper_executor=self.paper_exec,
                market_finder=self.market_finder
            )
            
            if self.paper_exec:
                self.paper_exec._external_notifier = self.telegram
            if self.market_finder:
                self.market_finder._external_notifier = self.telegram
            
            logger.info("Telegram ready")
        
        count = sum([bool(self.shimmer), bool(self.paper_exec), 
                    bool(self.market_finder), bool(self.telegram)])
        logger.info(f"Systems online: {count}/4")

    def _market_discovery_loop(self):
        """Market discovery"""
        logger.info("Discovery started")
        interval = self.config.get('discovery_interval', 15)
        warned = False
        
        while self.running:
            try:
                if self.market_finder:
                    markets = self.market_finder.find_active_btc_5m_markets()
                    
                    if markets:
                        logger.info(f"Found {len(markets)} markets")
                        if self.config.get('auto_trade'):
                            for m in markets[:3]:
                                opportunities = self.market_finder.find_opportunities([m['symbol']])
                                if opportunities:
                                    logger.info(f"Opportunities: {len(opportunities)}")
                    else:
                        if not warned:
                            logger.warning("No markets (CLOB not connected)")
                            warned = True
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"Discovery error: {e}")
                time.sleep(5)

    def start(self):
        """Start bot"""
        print()
        logger.info("══════════════════════════════════════")
        logger.info("     5MIN TRADING BOT STARTING")
        logger.info("══════════════════════════════════════")
        
        self.running = True
        self._init_components()
        
        if self.telegram:
            self.telegram.start()
            time.sleep(2)
            logger.info("Use Ctrl+C to stop")
            print()
        
        if self.market_finder:
            t = threading.Thread(target=self._market_discovery_loop, name="Discovery", daemon=True)
            t.start()
            self.threads.append(t)
        
        self._main_loop()

    def _main_loop(self):
        """Main loop"""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            logger.info("══════════════════════════════════════")
            logger.info("     SHUTDOWN SIGNAL RECEIVED")
            self.stop()

    def stop(self):
        """Stop bot"""
        logger.info("Stopping...")
        self.running = False
        
        if self.telegram:
            self.telegram.stop()
        
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=2)
        
        logger.info("Bot stopped")
        logger.info("══════════════════════════════════════")

    def run(self):
        """Entry point"""
        try:
            self.start()
        except Exception as e:
            logger.critical(f"Fatal error: {e}")
            raise

# ═══════════════════════════════════════════════════════════
# MAIN ENTRY
# ═══════════════════════════════════════════════════════════

def main():
    """Main entry point"""
    bot = TradingBot()
    bot.run()

if __name__ == "__main__":
    main()
