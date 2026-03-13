#!/usr/bin/env python3
"""
5Min Trading Bot - Secure & Visual
"""

import os
import sys

# Load .env silently
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists('.env'):
        with open('.env') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value.strip().strip('"').strip("'")

def validate_environment():
    paper = os.getenv('PAPER_ENABLED', '').lower() == 'true'
    live = os.getenv('LIVE_ENABLED', '').lower() == 'true'
    
    if not paper and not live:
        print("❌ ERROR: Enable PAPER_ENABLED or LIVE_ENABLED in .env")
        sys.exit(1)
    
    if not os.getenv('TELEGRAM_TOKEN'):
        print("❌ ERROR: TELEGRAM_TOKEN not set")
        sys.exit(1)
    
    if live:
        missing = []
        if not os.getenv('POLYMARKET_PK'): missing.append('POLYMARKET_PK')
        if not os.getenv('POLYMARKET_API_KEY'): missing.append('POLYMARKET_API_KEY')
        if not os.getenv('POLYMARKET_SECRET'): missing.append('POLYMARKET_SECRET')
        
        if missing:
            print(f"❌ ERROR: Missing {len(missing)} Polymarket credentials")
            sys.exit(1)
    
    return paper, live

paper_enabled, live_enabled = validate_environment()

# ═══════════════════════════════════════════════════════════
# EMOJI LOGGING SETUP
# ═══════════════════════════════════════════════════════════

import logging
import json
import threading
import asyncio
import time
from datetime import datetime
from typing import Dict, Any

class EmojiFormatter(logging.Formatter):
    """Pretty emoji formatter"""
    EMOJIS = {
        'INFO': '✅',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '🔥',
        'DEBUG': '🔍',
        'MAIN': '🤖',
        'PAPER': '📘',
        'LIVE': '💰',
        'TELEGRAM': '📱',
        'MARKET': '📊',
        'SHIMMER': '✨',
        'POLYMARKET': '🎯'
    }
    
    def format(self, record):
        # Get emoji based on logger name or level
        name = record.name.split('.')[-1].upper()
        emoji = self.EMOJIS.get(name, self.EMOJIS.get(record.levelname, '•'))
        
        # Format time
        time_str = datetime.now().strftime('%H:%M:%S')
        
        # Clean message (no secrets)
        msg = record.getMessage()
        import re
        msg = re.sub(r'0x[a-fA-F0-9]{10,}', '***', msg)
        
        return f"{emoji} {time_str} │ {msg}"

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

for handler in logging.getLogger().handlers:
    handler.setFormatter(EmojiFormatter())

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

logger = logging.getLogger('MAIN')

# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════

try:
    from data.shimmer_client import ShimmerClient
    from data.polymarket_client import PolymarketClient
    from paper_trading.paper_executor import PaperExecutor
    from live_trading.live_executor import LiveExecutor
    from monitor.market_finder import MarketFinder
    from telegram_bot.bot import TelegramBotRunner
except ImportError as e:
    logger.error(f"Import failed: {e}")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
# BOT CLASS
# ═══════════════════════════════════════════════════════════

class TradingBot:
    def __init__(self):
        self.config = self._load_config()
        self.running = False
        self.threads = []
        self.start_time = time.time()
        
        self.paper_enabled = paper_enabled
        self.live_enabled = live_enabled
        
        self.shimmer = None
        self.paper_exec = None
        self.polymarket = None
        self.live_exec = None
        self.market_finder = None
        self.telegram = None

    def _load_config(self) -> Dict:
        return {
            "telegram_token": os.getenv("TELEGRAM_TOKEN"),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            "paper_enabled": paper_enabled,
            "live_enabled": live_enabled,
            "shimmer_api_key": os.getenv("SHIMMER_API_KEY", ""),
            "shimmer_mock_mode": os.getenv("SHIMMER_MOCK_MODE", "true").lower() == "true",
            "auto_trade": os.getenv("PAPER_AUTO_TRADE", "false").lower() == "true",
            "default_trade_size": float(os.getenv("PAPER_TRADE_SIZE", "10")),
            "initial_balance": 10000.0,
            "polymarket_pk": os.getenv("POLYMARKET_PK", ""),
            "polymarket_api_key": os.getenv("POLYMARKET_API_KEY", ""),
            "polymarket_secret": os.getenv("POLYMARKET_SECRET", ""),
            "live_auto_trade": os.getenv("LIVE_AUTO_TRADE", "false").lower() == "true",
            "live_trade_size": float(os.getenv("LIVE_TRADE_SIZE", "5")),
            "check_interval": 60
        }

    def _mask_wallet(self, address: str) -> str:
        if len(address) < 10:
            return "***"
        return f"{address[:6]}...{address[-4:]}"

    def _get_uptime(self) -> str:
        """Get uptime in readable format"""
        uptime = time.time() - self.start_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        return f"{hours}h {minutes}m"

    def _init_systems(self):
        """Initialize with emoji logs"""
        logger.info("══════════════════════════════════════════")
        logger.info("🚀 INITIALIZING TRADING SYSTEMS")
        logger.info("══════════════════════════════════════════")
        
        # Paper System
        if self.paper_enabled:
            logger.info("📘 Initializing Paper Trading (Shimmer)...")
            try:
                self.shimmer = ShimmerClient({
                    'mock_mode': self.config['shimmer_mock_mode'],
                    'api_key': self.config['shimmer_api_key']
                })
                
                self.paper_exec = PaperExecutor(
                    initial_balance=self.config['initial_balance'],
                    paper_clob=self.shimmer,
                    config=self.config
                )
                
                self.market_finder = MarketFinder(
                    clob=self.shimmer,
                    config=self.config,
                    paper_executor=self.paper_exec
                )
                
                mode = "🎭 MOCK" if self.shimmer.mock_mode else "🔗 API"
                logger.info(f"📘 Paper Ready │ Mode: {mode} │ Balance: ${self.config['initial_balance']:,.0f}")
                
            except Exception as e:
                logger.error(f"📘 Paper Failed: {str(e)}")
                self.paper_enabled = False
        
        # Live System
        if self.live_enabled:
            logger.info("💰 Initializing Live Trading (Polymarket)...")
            logger.warning("💰 ⚠️  REAL MONEY MODE ACTIVATED")
            
            try:
                self.polymarket = PolymarketClient({
                    'private_key': self.config['polymarket_pk'],
                    'api_key': self.config['polymarket_api_key'],
                    'secret': self.config['polymarket_secret']
                })
                
                if not self.polymarket.connected:
                    raise Exception("Connection failed")
                
                self.live_exec = LiveExecutor(
                    polymarket_client=self.polymarket,
                    config=self.config
                )
                
                wallet = self._mask_wallet(self.polymarket.wallet_address or "Unknown")
                balance = self.polymarket.get_balance()
                
                logger.info(f"💰 Live Connected │ Wallet: {wallet}")
                logger.info(f"💰 Balance: {balance.get('usdc', 0)} USDC")
                
            except Exception as e:
                error_msg = str(e)
                if '0x' in error_msg:
                    error_msg = "Auth failed"
                logger.error(f"💰 Live Failed: {error_msg}")
                self.live_enabled = False
        
        # Telegram
        if TelegramBotRunner and self.config.get('telegram_token'):
            logger.info("📱 Starting Telegram Bot...")
            try:
                safe_config = {k: v for k, v in self.config.items() 
                             if not any(x in k for x in ['key', 'secret', 'pk', 'token'])}
                
                self.telegram = TelegramBotRunner(
                    token=self.config['telegram_token'],
                    config=safe_config,
                    paper_executor=self.paper_exec,
                    live_executor=self.live_exec,
                    market_finder=self.market_finder,
                    paper_enabled=self.paper_enabled,
                    live_enabled=self.live_enabled,
                    get_uptime=self._get_uptime  # Pass uptime function
                )
                
                if self.paper_exec:
                    self.paper_exec._external_notifier = self.telegram
                if self.live_exec:
                    self.live_exec._external_notifier = self.telegram
                
                logger.info("📱 Telegram Ready")
            except Exception as e:
                logger.error(f"📱 Telegram Failed")
        
        # Summary
        logger.info("══════════════════════════════════════════")
        active = []
        if self.paper_enabled: active.append("📘 Paper")
        if self.live_enabled: active.append("💰 Live")
        logger.info(f"🎯 Active Systems: {' + '.join(active) if active else '❌ None'}")
        logger.info("══════════════════════════════════════════")

    def _paper_loop(self):
        """Paper trading loop with emojis"""
        logger.info("📘 Paper trading loop started")
        interval = self.config.get('check_interval', 60)
        
        while self.running and self.paper_enabled:
            try:
                if self.market_finder:
                    markets = self.market_finder.find_active_btc_5m_markets()
                    
                    if markets:
                        logger.info(f"📊 Found {len(markets)} markets")
                        
                        for market in markets[:2]:
                            symbol = market.get('symbol')
                            opportunities = self.market_finder.find_opportunities([symbol])
                            
                            if opportunities and self.config.get('auto_trade'):
                                for opp in opportunities:
                                    conf = opp.get('confidence', 0)
                                    sig = opp['signal']
                                    logger.info(f"🎯 Signal: {symbol} {sig} ({conf:.0%})")
                                    
                                    result = self.paper_exec.execute_trade(
                                        symbol=symbol,
                                        side=sig,
                                        size=self.config.get('default_trade_size', 10)
                                    )
                                    if result.get('success'):
                                        logger.info(f"✅ Trade executed: {symbol} {sig}")
                                    else:
                                        logger.error(f"❌ Trade failed")
                    else:
                        logger.debug("🔍 No markets found")
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"❌ Paper Error: {str(e)[:50]}")
                time.sleep(5)

    def _live_loop(self):
        """Live trading loop with emojis"""
        logger.info("💰 Live trading loop started (REAL MONEY)")
        interval = self.config.get('check_interval', 60)
        
        while self.running and self.live_enabled:
            try:
                if self.live_exec:
                    logger.info("💰 Scanning Polymarket...")
                    # Live trading logic here
                    pass
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"❌ Live Error")
                time.sleep(5)

    def start(self):
        """Start with pretty banner"""
        print("\n" + "╔" + "═" * 48 + "╗")
        print("║" + " " * 12 + "🤖 5MIN TRADING BOT" + " " * 17 + "║")
        if self.paper_enabled:
            print("║" + " " * 12 + "📘 Paper: ENABLED" + " " * 19 + "║")
        if self.live_enabled:
            print("║" + " " * 12 + "💰 Live:  ENABLED" + " " * 19 + "║")
        print("╚" + "═" * 48 + "╝\n")
        
        self.running = True
        self._init_systems()
        
        if self.telegram:
            self.telegram.start()
            time.sleep(2)
        
        if self.paper_enabled:
            t = threading.Thread(target=self._paper_loop, name="Paper", daemon=True)
            t.start()
            self.threads.append(t)
        
        if self.live_enabled:
            t = threading.Thread(target=self._live_loop, name="Live", daemon=True)
            t.start()
            self.threads.append(t)
        
        logger.info("🚀 Bot running (Ctrl+C to stop)")
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            logger.info("🛑 Shutdown signal received...")
            self.stop()

    def stop(self):
        logger.info("🛑 Stopping systems...")
        self.running = False
        
        if self.telegram:
            self.telegram.stop()
        
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=3)
        
        logger.info("👋 Bot stopped")
        logger.info("══════════════════════════════════════════")

    def run(self):
        try:
            self.start()
        except Exception as e:
            logger.critical(f"💥 Fatal error")
            raise

def main():
    bot = TradingBot()
    bot.run()

if __name__ == "__main__":
    main()
