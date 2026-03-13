#!/usr/bin/env python3
"""
5Min Trading Bot - Independent Dual Systems
System A: Paper Trading (Shimmer API) - Simulation
System B: Live Trading (Polymarket) - Real Money
No connection between systems - Run separately or together
"""

import os
import sys
import time
import json
import logging
import threading
import asyncio
from typing import Dict, Any, Optional

# ═══════════════════════════════════════════════════════════
# VALIDATION - Check what's enabled and validate accordingly
# ═══════════════════════════════════════════════════════════

def validate_environment():
    """Validate env vars based on which systems are enabled"""
    paper = os.getenv('PAPER_ENABLED', 'false').lower() == 'true'
    live = os.getenv('LIVE_ENABLED', 'false').lower() == 'true'
    
    if not paper and not live:
        print("\n❌ ERROR: Enable at least one trading system")
        print("   Set PAPER_ENABLED=true or LIVE_ENABLED=true (or both)")
        sys.exit(1)
    
    errors = []
    
    # Telegram always required for bot control
    if not os.getenv('TELEGRAM_TOKEN'):
        errors.append("TELEGRAM_TOKEN - Required for bot notifications")
    
    # Validate Paper system requirements
    if paper:
        if not os.getenv('SHIMMER_MOCK_MODE') and not os.getenv('SHIMMER_API_KEY'):
            print("⚠️  PAPER: Running in mock mode (no API key provided)")
    
    # Validate Live system requirements ( STRICT )
    if live:
        if not os.getenv('POLYMARKET_PK'):
            errors.append("POLYMARKET_PK - Required for live trading (real money!)")
        if not os.getenv('POLYMARKET_API_KEY'):
            errors.append("POLYMARKET_API_KEY - Required for live trading")
        if not os.getenv('POLYMARKET_SECRET'):
            errors.append("POLYMARKET_SECRET - Required for live trading")
    
    if errors:
        print("\n" + "═" * 60)
        print("❌  MANDATORY VARIABLES MISSING")
        print("═" * 60)
        for err in errors:
            print(f"  • {err}")
        print("\nSet variables and restart.")
        sys.exit(1)

validate_environment()

# ═══════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════

class CleanFormatter(logging.Formatter):
    def format(self, record):
        icons = {'INFO': '✓', 'WARNING': '⚠', 'ERROR': '✗', 'CRITICAL': '🔥'}
        icon = icons.get(record.levelname, '•')
        name = record.name.split('.')[-1].upper()[:8].ljust(8)
        return f"{icon}  {name} | {record.getMessage()}"

logging.basicConfig(level=logging.INFO, format='%(message)s',
                   handlers=[logging.StreamHandler(sys.stdout)])
for handler in logging.getLogger().handlers:
    handler.setFormatter(CleanFormatter())

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
# BOT CLASS - COMPLETELY INDEPENDENT SYSTEMS
# ═══════════════════════════════════════════════════════════

class TradingBot:
    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.running = False
        self.threads = []
        
        # System flags (completely independent)
        self.paper_enabled = self.config.get('paper_enabled', False)
        self.live_enabled = self.config.get('live_enabled', False)
        
        # Paper System Components (Shimmer)
        self.shimmer = None
        self.paper_exec = None
        self.paper_finder = None
        
        # Live System Components (Polymarket) - ISOLATED
        self.polymarket = None
        self.live_exec = None
        self.live_finder = None
        
        # Shared UI
        self.telegram = None

    def _load_config(self, path: str) -> Dict:
        defaults = {
            # System switches
            "paper_enabled": os.getenv("PAPER_ENABLED", "false").lower() == "true",
            "live_enabled": os.getenv("LIVE_ENABLED", "false").lower() == "true",
            
            # Telegram
            "telegram_token": os.getenv("TELEGRAM_TOKEN"),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
            
            # Paper (Shimmer) settings
            "shimmer_api_key": os.getenv("SHIMMER_API_KEY", ""),
            "shimmer_mock_mode": os.getenv("SHIMMER_MOCK_MODE", "true").lower() == "true",
            "paper_auto_trade": os.getenv("PAPER_AUTO_TRADE", "false").lower() == "true",
            "paper_trade_size": float(os.getenv("PAPER_TRADE_SIZE", "10")),
            "paper_initial_balance": 10000.0,
            
            # Live (Polymarket) settings - INDEPENDENT
            "polymarket_pk": os.getenv("POLYMARKET_PK"),
            "polymarket_api_key": os.getenv("POLYMARKET_API_KEY"),
            "polymarket_secret": os.getenv("POLYMARKET_SECRET"),
            "live_auto_trade": os.getenv("LIVE_AUTO_TRADE", "false").lower() == "true",
            "live_trade_size": float(os.getenv("LIVE_TRADE_SIZE", "5")),
            "live_max_size": float(os.getenv("LIVE_MAX_SIZE", "50")),
            
            "check_interval": 60
        }
        
        if os.path.exists(path):
            with open(path) as f:
                defaults.update(json.load(f))
        return defaults

    def _init_systems(self):
        """Initialize independent trading systems"""
        logger.info("═" * 60)
        logger.info("INITIALIZING TRADING SYSTEMS")
        logger.info("═" * 60)
        
        # ═══════════════════════════════════════════════════════
        # SYSTEM A: PAPER TRADING (Shimmer)
        # ═══════════════════════════════════════════════════════
        if self.paper_enabled:
            logger.info("[PAPER] Initializing Shimmer Simulation...")
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
                
                self.paper_finder = MarketFinder(
                    clob=self.shimmer,
                    config={**self.config, 'auto_trade': self.config['paper_auto_trade']},
                    paper_executor=self.paper_exec
                )
                
                mode = "MOCK" if self.shimmer.mock_mode else "API"
                logger.info(f"[PAPER] ✓ Ready | Mode: {mode} | Balance: ${self.config['paper_initial_balance']:,.0f}")
                
            except Exception as e:
                logger.error(f"[PAPER] ✗ Failed: {e}")
                self.paper_enabled = False
        
        # ═══════════════════════════════════════════════════════
        # SYSTEM B: LIVE TRADING (Polymarket) - COMPLETELY SEPARATE
        # ═══════════════════════════════════════════════════════
        if self.live_enabled:
            logger.info("[LIVE] Initializing Polymarket Connection...")
            logger.warning("[LIVE] ⚠️  REAL MONEY - CHECK SETTINGS!")
            
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
                
                # Live uses its own market finder (Polymarket markets)
                self.live_finder = MarketFinder(
                    clob=self.polymarket,  # Uses Polymarket data, not Shimmer!
                    config={**self.config, 'auto_trade': self.config['live_auto_trade']},
                    paper_executor=None,  # Not connected to paper system
                    live_executor=self.live_exec
                )
                
                balance = self.polymarket.get_balance()
                logger.info(f"[LIVE] ✓ CONNECTED | Wallet: {balance.get('usdc', 0)} USDC")
                logger.info(f"[LIVE] ✓ Trading Size: {self.config['live_trade_size']} USDC")
                
            except Exception as e:
                logger.error(f"[LIVE] ✗ Failed: {e}")
                self.live_enabled = False
        
        # ═══════════════════════════════════════════════════════
        # TELEGRAM (Shared UI for both systems)
        # ═══════════════════════════════════════════════════════
        if TelegramBotRunner and self.config.get('telegram_token'):
            self.telegram = TelegramBotRunner(
                token=self.config['telegram_token'],
                config=self.config,
                paper_executor=self.paper_exec,
                live_executor=self.live_exec
            )
            
            if self.paper_exec:
                self.paper_exec._external_notifier = self.telegram
            if self.live_exec:
                self.live_exec._external_notifier = self.telegram
            
            logger.info("[UI] Telegram Connected")
        
        # Summary
        active = []
        if self.paper_enabled: active.append("PAPER")
        if self.live_enabled: active.append("LIVE")
        logger.info("═" * 60)
        logger.info(f"ACTIVE: {' + '.join(active)}")
        logger.info("═" * 60)

    def _paper_trading_loop(self):
        """
        SYSTEM A: Independent Paper Trading Loop
        Uses Shimmer markets, executes paper trades
        """
        logger.info("[PAPER] Trading loop started")
        interval = self.config.get('check_interval', 60)
        
        while self.running and self.paper_enabled:
            try:
                if self.paper_finder:
                    markets = self.paper_finder.find_active_btc_5m_markets()
                    
                    if markets:
                        logger.info(f"[PAPER] Found {len(markets)} markets")
                        
                        for market in markets[:2]:
                            symbol = market.get('symbol')
                            opportunities = self.paper_finder.find_opportunities([symbol])
                            
                            if opportunities and self.config['paper_auto_trade']:
                                for opp in opportunities:
                                    logger.info(f"[PAPER] Signal: {symbol} {opp['signal']} ({opp['confidence']:.0%})")
                                    result = self.paper_exec.execute_trade(
                                        symbol=symbol,
                                        side=opp['signal'],
                                        size=self.config['paper_trade_size']
                                    )
                                    if result.get('success'):
                                        logger.info(f"[PAPER] ✓ Executed")
                    else:
                        logger.debug("[PAPER] No markets")
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"[PAPER] Error: {e}")
                time.sleep(5)

    def _live_trading_loop(self):
        """
        SYSTEM B: Independent Live Trading Loop  
        Uses Polymarket markets, executes REAL trades
        Completely separate from Paper system!
        """
        logger.info("[LIVE] Trading loop started - REAL MONEY ACTIVE")
        interval = self.config.get('check_interval', 60)
        
        while self.running and self.live_enabled:
            try:
                if self.live_finder:
                    # Get REAL Polymarket markets (not Shimmer!)
                    markets = self.live_finder.find_active_btc_5m_markets()
                    
                    if markets:
                        logger.info(f"[LIVE] Found {len(markets)} Polymarket markets")
                        
                        for market in markets[:2]:
                            symbol = market.get('symbol')
                            market_id = market.get('market_id')
                            
                            opportunities = self.live_finder.find_opportunities([symbol])
                            
                            if opportunities and self.config['live_auto_trade']:
                                for opp in opportunities:
                                    conf = opp['confidence']
                                    # STRICT: Only high confidence for live
                                    if conf >= 0.85:
                                        logger.warning(f"[LIVE] HIGH CONFIDENCE: {symbol} {opp['signal']} ({conf:.0%})")
                                        logger.warning(f"[LIVE] Executing REAL TRADE with {self.config['live_trade_size']} USDC!")
                                        
                                        result = self.live_exec.execute_trade(
                                            market_id=market_id,
                                            side=opp['signal'],
                                            size=min(self.config['live_trade_size'], 
                                                    self.config['live_max_size']),
                                            price=opp.get('price', 0.5)
                                        )
                                        
                                        if result.get('status') == 'filled':
                                            logger.info(f"[LIVE] ✓ REAL ORDER FILLED: {result.get('order_id')}")
                                        else:
                                            logger.error(f"[LIVE] ✗ Failed: {result.get('error')}")
                                    else:
                                        logger.info(f"[LIVE] Low confidence ({conf:.0%}), skipping")
                    else:
                        logger.debug("[LIVE] No markets")
                
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"[LIVE] Error: {e}")
                time.sleep(5)

    def start(self):
        """Start independent systems"""
        print()
        logger.info("════════════════════════════════════════════")
        logger.info("   5MIN TRADING BOT")
        if self.paper_enabled:
            logger.info("   📘 PAPER: Shimmer Simulation")
        if self.live_enabled:
            logger.info("   💰 LIVE:  Polymarket (REAL MONEY!)")
        logger.info("════════════════════════════════════════════")
        
        self.running = True
        self._init_systems()
        
        if self.telegram:
            self.telegram.start()
            time.sleep(2)
        
        # Start Paper System Thread (if enabled)
        if self.paper_enabled:
            t = threading.Thread(target=self._paper_trading_loop, name="Paper-Trader", daemon=True)
            t.start()
            self.threads.append(t)
        
        # Start Live System Thread (if enabled) - COMPLETELY SEPARATE!
        if self.live_enabled:
            t = threading.Thread(target=self._live_trading_loop, name="Live-Trader", daemon=True)
            t.start()
            self.threads.append(t)
        
        logger.info("All systems running. Ctrl+C to stop.")
        self._main_loop()

    def _main_loop(self):
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            logger.info("Shutdown signal...")
            self.stop()

    def stop(self):
        logger.info("Stopping all systems...")
        self.running = False
        
        if self.telegram:
            self.telegram.stop()
        
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=3)
        
        logger.info("Bot stopped")

    def run(self):
        try:
            self.start()
        except Exception as e:
            logger.critical(f"Fatal: {e}")
            raise

# ═══════════════════════════════════════════════════════════
# ENTRY
# ═══════════════════════════════════════════════════════════

def main():
    bot = TradingBot()
    bot.run()

if __name__ == "__main__":
    main()
