#!/usr/bin/env python3
"""
5Min Trading Bot - Secure Version
API Keys are NEVER logged
"""

# ═══════════════════════════════════════════════════════════
# STEP 1: LOAD .ENV (Silent)
# ═══════════════════════════════════════════════════════════

import os
import sys

# Load .env without printing values
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

# ═══════════════════════════════════════════════════════════
# STEP 2: VALIDATION (No values printed)
# ═══════════════════════════════════════════════════════════

def validate_environment():
    paper = os.getenv('PAPER_ENABLED', '').lower() == 'true'
    live = os.getenv('LIVE_ENABLED', '').lower() == 'true'
    
    if not paper and not live:
        print("❌ ERROR: Enable PAPER_ENABLED or LIVE_ENABLED in .env")
        sys.exit(1)
    
    if not os.getenv('TELEGRAM_TOKEN'):
        print("❌ ERROR: TELEGRAM_TOKEN not set")
        sys.exit(1)
    
    # Check Live requirements without printing keys
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
# STEP 3: MINIMAL LOGGING (No secrets)
# ═══════════════════════════════════════════════════════════

import logging
import json
import threading
import asyncio
import time
from typing import Dict, Any

class SecureFormatter(logging.Formatter):
    """Formatter that masks secrets automatically"""
    def format(self, record):
        icons = {'INFO': '•', 'WARNING': '!', 'ERROR': '✗', 'CRITICAL': '🔥', 'DEBUG': '·'}
        icon = icons.get(record.levelname, '•')
        name = record.name.split('.')[-1].upper()[:8].ljust(8)
        msg = record.getMessage()
        
        # Auto-redact common secret patterns
        import re
        # Mask 0x... private keys
        msg = re.sub(r'0x[a-fA-F0-9]{10,}', '0x***HIDDEN***', msg)
        # Mask API tokens with :
        msg = re.sub(r':[a-zA-Z0-9_-]{20,}', ':***', msg)
        
        return f"{icon} {name} | {msg}"

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
for handler in logging.getLogger().handlers:
    handler.setFormatter(SecureFormatter())

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
# BOT CLASS (Secure)
# ═══════════════════════════════════════════════════════════

class TradingBot:
    def __init__(self):
        self.config = self._load_config()
        self.running = False
        self.threads = []
        
        self.paper_enabled = paper_enabled
        self.live_enabled = live_enabled
        
        self.shimmer = None
        self.paper_exec = None
        self.polymarket = None
        self.live_exec = None
        self.market_finder = None
        self.telegram = None

    def _load_config(self) -> Dict:
        # NEVER log this dictionary directly as it contains secrets
        return {
            "telegram_token": os.getenv("TELEGRAM_TOKEN"),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            
            "paper_enabled": paper_enabled,
            "live_enabled": live_enabled,
            
            # Paper
            "shimmer_api_key": os.getenv("SHIMMER_API_KEY", ""),
            "shimmer_mock_mode": os.getenv("SHIMMER_MOCK_MODE", "true").lower() == "true",
            "auto_trade": os.getenv("PAPER_AUTO_TRADE", "false").lower() == "true",
            "default_trade_size": float(os.getenv("PAPER_TRADE_SIZE", "10")),
            "initial_balance": 10000.0,
            
            # Live (Sensitive - never log these)
            "polymarket_pk": os.getenv("POLYMARKET_PK", ""),
            "polymarket_api_key": os.getenv("POLYMARKET_API_KEY", ""),
            "polymarket_secret": os.getenv("POLYMARKET_SECRET", ""),
            "live_auto_trade": os.getenv("LIVE_AUTO_TRADE", "false").lower() == "true",
            "live_trade_size": float(os.getenv("LIVE_TRADE_SIZE", "5")),
            
            "check_interval": 60
        }

    def _mask_wallet(self, address: str) -> str:
        """Show only first 4 and last 4 chars of wallet"""
        if len(address) < 10:
            return "***"
        return f"{address[:4]}...{address[-4:]}"

    def _init_systems(self):
        """Initialize without logging secrets"""
        logger.info("=" * 50)
        logger.info("INITIALIZING")
        logger.info("=" * 50)
        
        # ═══════════════════════════════════════════════════════
        # PAPER SYSTEM
        # ═══════════════════════════════════════════════════════
        if self.paper_enabled:
            logger.info("[PAPER] Starting simulation...")
            try:
                self.shimmer = ShimmerClient({
                    'mock_mode': self.config['shimmer_mock_mode'],
                    'api_key': self.config['shimmer_api_key']  # Not logged
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
                
                mode = "MOCK" if self.shimmer.mock_mode else "API"
                logger.info(f"[PAPER] Ready | Mode: {mode} | Balance: ${self.config['initial_balance']:,.0f}")
                
            except Exception as e:
                logger.error(f"[PAPER] Failed: {str(e)}")  # Error without stack trace containing keys
                self.paper_enabled = False
        
        # ═══════════════════════════════════════════════════════
        # LIVE SYSTEM (Critical: No keys logged)
        # ═══════════════════════════════════════════════════════
        if self.live_enabled:
            logger.info("[LIVE] Connecting... (REAL MONEY)")
            
            try:
                # Initialize WITHOUT logging the config dict
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
                
                # Log ONLY the masked wallet address, never the key
                wallet = self.polymarket.wallet_address or "Unknown"
                masked_wallet = self._mask_wallet(wallet)
                
                balance = self.polymarket.get_balance()
                usdc = balance.get('usdc', 0)
                
                logger.info(f"[LIVE] Connected | Wallet: {masked_wallet}")
                logger.info(f"[LIVE] Balance: {usdc} USDC")
                
            except Exception as e:
                # Log error but ensure it doesn't contain the key
                error_msg = str(e)
                if '0x' in error_msg and len(error_msg) > 20:
                    error_msg = "Authentication failed"  # Sanitize
                logger.error(f"[LIVE] Failed: {error_msg}")
                self.live_enabled = False
        
        # ═══════════════════════════════════════════════════════
        # TELEGRAM (Token is passed but never logged)
        # ═══════════════════════════════════════════════════════
        if TelegramBotRunner and self.config.get('telegram_token'):
            logger.info("[TELEGRAM] Starting...")
            try:
                self.telegram = TelegramBotRunner(
                    token=self.config['telegram_token'],  # Passed safely, not logged
                    config={k: v for k, v in self.config.items() if 'key' not in k and 'secret' not in k and 'pk' not in k},  # Strip secrets
                    paper_executor=self.paper_exec,
                    live_executor=self.live_exec,
                    market_finder=self.market_finder,
                    paper_enabled=self.paper_enabled,
                    live_enabled=self.live_enabled
                )
                
                if self.paper_exec:
                    self.paper_exec._external_notifier = self.telegram
                if self.live_exec:
                    self.live_exec._external_notifier = self.telegram
                
                logger.info("[TELEGRAM] Ready")
            except Exception as e:
                logger.error(f"[TELEGRAM] Failed")
        
        # Summary (no values, just status)
        active = []
        if self.paper_enabled: active.append("Paper")
        if self.live_enabled: active.append("Live")
        logger.info("=" * 50)
        logger.info(f"Systems: {' + '.join(active) if active else 'None'}")
        logger.info("=" * 50)

    def _paper_loop(self):
        """Paper trading loop"""
        logger.info("[PAPER] Trading started")
        interval = self.config.get('check_interval', 60)
        
        while self.running and self.paper_enabled:
            try:
                if self.market_finder:
                    markets = self.market_finder.find_active_btc_5m_markets()
                    
                    if markets:
                        logger.info(f"[PAPER] Markets: {len(markets)}")
                        
                        for market in markets[:2]:
                            symbol = market.get('symbol')
                            opportunities = self.market_finder.find_opportunities([symbol])
                            
                            if opportunities and self.config.get('auto_trade'):
                                for opp in opportunities:
                                    conf = opp.get('confidence', 0)
                                    logger.info(f"[PAPER] Signal: {symbol} {opp['signal']} ({conf:.0%})")
                                    
                                    result = self.paper_exec.execute_trade(
                                        symbol=symbol,
                                        side=opp['signal'],
                                        size=self.config.get('default_trade_size', 10)
                                    )
                                    if result.get('success'):
                                        logger.info("[PAPER] Executed")
                    else:
                        logger.debug("[PAPER] No markets")
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"[PAPER] Error")
                time.sleep(5)

    def _live_loop(self):
        """Live trading loop"""
        logger.info("[LIVE] Trading started - REAL MONEY ACTIVE")
        interval = self.config.get('check_interval', 60)
        
        while self.running and self.live_enabled:
            try:
                # Critical: Only high confidence for live
                if self.live_exec:
                    # Scan for opportunities
                    logger.info("[LIVE] Scanning...")
                    # Logic here...
                    pass
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"[LIVE] Error")
                time.sleep(5)

    def start(self):
        """Start bot"""
        print("\n" + "=" * 50)
        print("5MIN TRADING BOT")
        if self.paper_enabled: print("Paper: ON")
        if self.live_enabled: print("Live: ON (REAL MONEY)")
        print("=" * 50 + "\n")
        
        self.running = True
        self._init_systems()
        
        if self.telegram:
            self.telegram.start()
            time.sleep(2)
            print()
        
        if self.paper_enabled:
            t = threading.Thread(target=self._paper_loop, name="Paper", daemon=True)
            t.start()
            self.threads.append(t)
        
        if self.live_enabled:
            t = threading.Thread(target=self._live_loop, name="Live", daemon=True)
            t.start()
            self.threads.append(t)
        
        logger.info("Running (Ctrl+C to stop)")
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            logger.info("Shutting down...")
            self.stop()

    def stop(self):
        logger.info("Stopping...")
        self.running = False
        
        if self.telegram:
            self.telegram.stop()
        
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=3)
        
        logger.info("Stopped")

    def run(self):
        try:
            self.start()
        except Exception as e:
            logger.critical(f"Fatal error")
            raise

def main():
    bot = TradingBot()
    bot.run()

if __name__ == "__main__":
    main()
