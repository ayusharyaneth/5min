#!/usr/bin/env python3
"""
5Min Trading Bot - Private & Secure
Auto-Trade ON by Default | Dual Channel Alerts | Unauthorized Access Protection
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
        print("❌ ERROR: Enable PAPER_ENABLED or LIVE_ENABLED")
        sys.exit(1)
    
    if not os.getenv('TELEGRAM_TOKEN'):
        print("❌ ERROR: TELEGRAM_TOKEN not set")
        sys.exit(1)
    
    # Validate channel IDs
    if not os.getenv('TRADES_CHANNEL_ID'):
        print("⚠️  WARNING: TRADES_CHANNEL_ID not set - trade notifications disabled")
    if not os.getenv('LOGS_CHANNEL_ID'):
        print("⚠️  WARNING: LOGS_CHANNEL_ID not set - log alerts disabled")
    
    if live:
        missing = []
        if not os.getenv('POLYMARKET_PK'): missing.append('POLYMARKET_PK')
        if not os.getenv('POLYMARKET_API_KEY'): missing.append('POLYMARKET_API_KEY')
        if not os.getenv('POLYMARKET_SECRET'): missing.append('POLYMARKET_SECRET')
        if missing:
            print(f"❌ ERROR: Missing {', '.join(missing)}")
            sys.exit(1)
    
    return paper, live

paper_enabled, live_enabled = validate_environment()

import logging
import json
import threading
import asyncio
import time
import traceback
from datetime import datetime
from typing import Dict, Any

class SecureFormatter(logging.Formatter):
    EMOJIS = {
        'INFO': '✅', 'WARNING': '⚠️', 'ERROR': '❌', 
        'CRITICAL': '🔥', 'DEBUG': '🔍',
        'MAIN': '🤖', 'PAPER': '📘', 'LIVE': '💰',
        'TELEGRAM': '📱', 'SECURITY': '🔒', 'TRADE': '💸'
    }
    
    def format(self, record):
        name = record.name.split('.')[-1].upper()
        emoji = self.EMOJIS.get(name, self.EMOJIS.get(record.levelname, '•'))
        time_str = datetime.now().strftime('%H:%M:%S')
        msg = record.getMessage()
        import re
        msg = re.sub(r'0x[a-fA-F0-9]{10,}', '***', msg)
        return f"{emoji} {time_str} │ {msg}"

logging.basicConfig(level=logging.INFO, format='%(message)s',
                   handlers=[logging.StreamHandler(sys.stdout)])
for handler in logging.getLogger().handlers:
    handler.setFormatter(SecureFormatter())

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logger = logging.getLogger('MAIN')

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

class TradingBot:
    def __init__(self):
        self.config = self._load_config()
        self.running = False
        self.threads = []
        self.start_time = time.time()
        
        self.paper_enabled = paper_enabled
        self.live_enabled = live_enabled
        
        # Components
        self.shimmer = None
        self.paper_exec = None
        self.polymarket = None
        self.live_exec = None
        self.market_finder = None
        self.telegram = None
        
        # Alert tracking
        self.error_count = 0
        self.last_error_time = None

    def _load_config(self) -> Dict:
        return {
            "telegram_token": os.getenv("TELEGRAM_TOKEN"),
            "authorized_user_id": os.getenv("AUTHORIZED_USER_ID", ""),  # Your Telegram user ID
            "trades_channel_id": os.getenv("TRADES_CHANNEL_ID", ""),     # Channel for trades
            "logs_channel_id": os.getenv("LOGS_CHANNEL_ID", ""),         # Channel for logs/alerts
            
            "paper_enabled": paper_enabled,
            "live_enabled": live_enabled,
            "shimmer_api_key": os.getenv("SHIMMER_API_KEY", ""),
            "shimmer_mock_mode": os.getenv("SHIMMER_MOCK_MODE", "true").lower() == "true",
            "auto_trade": os.getenv("PAPER_AUTO_TRADE", "true").lower() == "true",
            "default_trade_size": float(os.getenv("PAPER_TRADE_SIZE", "10")),
            "initial_balance": 10000.0,
            
            "polymarket_pk": os.getenv("POLYMARKET_PK", ""),
            "polymarket_api_key": os.getenv("POLYMARKET_API_KEY", ""),
            "polymarket_secret": os.getenv("POLYMARKET_SECRET", ""),
            "live_auto_trade": os.getenv("LIVE_AUTO_TRADE", "true").lower() == "true",
            "live_trade_size": float(os.getenv("LIVE_TRADE_SIZE", "5")),
            "live_max_size": float(os.getenv("LIVE_MAX_SIZE", "50")),
            
            "check_interval": 60,
            "min_confidence": 0.75  # Minimum confidence to trade
        }

    def _get_uptime(self) -> str:
        uptime = time.time() - self.start_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        return f"{hours}h {minutes}m"

    def _init_systems(self):
        """Initialize all systems"""
        logger.info("══════════════════════════════════════════")
        logger.info("🚀 INITIALIZING TRADING SYSTEMS")
        logger.info("══════════════════════════════════════════")
        
        # Show auto-trade status
        if self.config['auto_trade']:
            logger.info("🤖 PAPER AUTO-TRADE: ✅ ENABLED")
        if self.config['live_auto_trade']:
            logger.info("🤖 LIVE AUTO-TRADE: ✅ ENABLED")
        
        # Initialize Paper System
        if self.paper_enabled:
            logger.info("📘 Initializing Paper Trading...")
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
                
                mode = "MOCK" if self.shimmer.mock_mode else "API"
                logger.info(f"📘 Paper Ready │ {mode} │ ${self.config['initial_balance']:,.0f}")
                
            except Exception as e:
                logger.error(f"📘 Paper Failed: {e}")
                self.paper_enabled = False
                self._send_log_alert(f"❌ Paper System Failed\nError: {str(e)[:200]}")
        
        # Initialize Live System
        if self.live_enabled:
            logger.info("💰 Initializing Live Trading...")
            logger.warning("💰 ⚠️ REAL MONEY MODE")
            
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
                
                wallet = self.polymarket.wallet_address or "Unknown"
                masked = f"{wallet[:6]}...{wallet[-4]}" if len(wallet) > 10 else "***"
                balance = self.polymarket.get_balance()
                
                logger.info(f"💰 Live Connected │ {masked}")
                logger.info(f"💰 Balance: {balance.get('usdc', 0)} USDC")
                
                if self.config['live_auto_trade']:
                    logger.warning("💰 🔥 AUTO-TRADE ACTIVE - REAL MONEY!")
                
            except Exception as e:
                logger.error(f"💰 Live Failed")
                self.live_enabled = False
                self._send_log_alert(f"❌ Live System Failed\nError: {str(e)[:200]}")
        
        # Initialize Telegram
        if TelegramBotRunner and self.config.get('telegram_token'):
            logger.info("📱 Starting Telegram...")
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
                    get_uptime=self._get_uptime,
                    send_trade_notification=self._send_trade_notification,  # Pass callback
                    send_log_alert=self._send_log_alert,  # Pass callback
                    check_authorization=self._check_authorization  # Pass auth check
                )
                
                if self.paper_exec:
                    self.paper_exec._external_notifier = self.telegram
                if self.live_exec:
                    self.live_exec._external_notifier = self.telegram
                
                logger.info("📱 Telegram Ready")
            except Exception as e:
                logger.error(f"📱 Telegram Failed: {e}")

        # Send startup notification
        active = []
        if self.paper_enabled: active.append("📘 Paper")
        if self.live_enabled: active.append("💰 Live")
        
        logger.info("══════════════════════════════════════════")
        logger.info(f"🎯 Active: {' + '.join(active) if active else 'None'}")
        logger.info("══════════════════════════════════════════")
        
        self._send_log_alert(
            f"🚀 Bot Started\n"
            f"Active: {', '.join(active)}\n"
            f"Auto-Trade: {'ON' if self.config['auto_trade'] else 'OFF'}\n"
            f"Uptime: {self._get_uptime()}"
        )

    def _check_authorization(self, user_id: str, username: str, first_name: str) -> bool:
        """Check if user is authorized to use the bot"""
        authorized = str(self.config.get('authorized_user_id', ''))
        
        if not authorized or str(user_id) == authorized:
            return True
        
        # Unauthorized access attempt - send alert
        alert = (
            f"🚨 **UNAUTHORIZED ACCESS ATTEMPT**\n\n"
            f"User ID: `{user_id}`\n"
            f"Username: @{username or 'N/A'}\n"
            f"Name: {first_name or 'N/A'}\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"⚠️ This user tried to use your private bot!"
        )
        
        self._send_log_alert(alert)
        logger.warning(f"🔒 Unauthorized access by {username} ({user_id})")
        return False

    def _send_trade_notification(self, trade: Dict):
        """Send trade notification to trades channel"""
        channel = self.config.get('trades_channel_id')
        if not channel or not self.telegram:
            return
        
        # Determine if paper or live
        is_live = trade.get('is_live', False)
        emoji = "💰 LIVE" if is_live else "📘 PAPER"
        
        text = (
            f"{emoji} **Trade Executed**\n\n"
            f"Symbol: `{trade.get('symbol', 'N/A')}`\n"
            f"Side: {'🟢 BUY' if trade.get('side') == 'BUY' else '🔴 SELL'}\n"
            f"Size: `{trade.get('size', 0)}`\n"
            f"Price: `${trade.get('price', 0):,.4f}`\n"
            f"Time: `{datetime.now().strftime('%H:%M:%S')}`\n\n"
            f"Status: ✅ Filled"
        )
        
        try:
            asyncio.run_coroutine_threadsafe(
                self.telegram.app.bot.send_message(
                    chat_id=channel,
                    text=text,
                    parse_mode='Markdown'
                ),
                self.telegram._loop
            )
        except Exception as e:
            logger.error(f"Failed to send trade notification: {e}")

    def _send_log_alert(self, message: str):
        """Send alert to logs channel"""
        channel = self.config.get('logs_channel_id')
        if not channel or not self.telegram or not self.telegram._loop:
            return
        
        try:
            asyncio.run_coroutine_threadsafe(
                self.telegram.app.bot.send_message(
                    chat_id=channel,
                    text=message,
                    parse_mode='Markdown'
                ),
                self.telegram._loop
            )
        except Exception as e:
            logger.error(f"Failed to send log alert: {e}")

    def _paper_loop(self):
        """Paper trading loop - FIXED to actually execute trades"""
        logger.info("📘 Paper loop started")
        interval = self.config.get('check_interval', 60)
        
        while self.running and self.paper_enabled:
            try:
                if self.market_finder and self.paper_exec:
                    # Find markets
                    markets = self.market_finder.find_active_btc_5m_markets()
                    
                    if markets:
                        logger.info(f"📊 Found {len(markets)} markets")
                        
                        for market in markets:
                            symbol = market.get('symbol')
                            
                            # Analyze for opportunities
                            opportunities = self.market_finder.find_opportunities([symbol])
                            
                            if opportunities:
                                for opp in opportunities:
                                    confidence = opp.get('confidence', 0)
                                    
                                    # Check minimum confidence
                                    if confidence < self.config.get('min_confidence', 0.75):
                                        logger.info(f"⏭️  Low confidence ({confidence:.0%}), skipping {symbol}")
                                        continue
                                    
                                    # Check auto-trade
                                    if not self.config.get('auto_trade', True):
                                        logger.info(f"⏸️  Auto-trade OFF, skipping {symbol}")
                                        continue
                                    
                                    logger.info(f"🎯 SIGNAL: {symbol} {opp['signal']} ({confidence:.0%})")
                                    
                                    # EXECUTE TRADE
                                    try:
                                        result = self.paper_exec.execute_trade(
                                            symbol=symbol,
                                            side=opp['signal'],
                                            size=self.config.get('default_trade_size', 10),
                                            price=opp.get('price'),
                                            metadata={'confidence': confidence, 'source': 'auto'}
                                        )
                                        
                                        if result and result.get('success'):
                                            logger.info(f"✅ TRADE EXECUTED: {symbol} {opp['signal']}")
                                            
                                            # Send notification
                                            self._send_trade_notification({
                                                'symbol': symbol,
                                                'side': opp['signal'],
                                                'size': self.config.get('default_trade_size', 10),
                                                'price': result.get('price', opp.get('price', 0)),
                                                'is_live': False
                                            })
                                            
                                        else:
                                            error = result.get('error', 'Unknown error') if result else 'No result'
                                            logger.error(f"❌ Trade failed: {error}")
                                            self._send_log_alert(f"❌ Paper Trade Failed\n{symbol} {opp['signal']}\nError: {error}")
                                            
                                    except Exception as e:
                                        logger.error(f"❌ Trade execution error: {e}")
                                        self._send_log_alert(f"❌ Paper Trade Error\n{str(e)[:200]}")
                    else:
                        logger.debug("🔍 No markets found")
                
                time.sleep(interval)
                
            except Exception as e:
                self.error_count += 1
                self.last_error_time = datetime.now()
                logger.error(f"❌ Paper loop error: {e}")
                self._send_log_alert(f"⚠️ Paper Loop Error #{self.error_count}\n{str(e)[:200]}")
                time.sleep(5)

    def _live_loop(self):
        """Live trading loop"""
        logger.info("💰 Live loop started - REAL MONEY")
        interval = self.config.get('check_interval', 60)
        
        while self.running and self.live_enabled:
            try:
                if self.live_exec and self.live_finder:
                    markets = self.live_finder.find_active_btc_5m_markets()
                    
                    if markets:
                        logger.info(f"💰 Found {len(markets)} Polymarket markets")
                        
                        for market in markets:
                            symbol = market.get('symbol')
                            market_id = market.get('market_id')
                            
                            opportunities = self.live_finder.find_opportunities([symbol])
                            
                            if opportunities:
                                for opp in opportunities:
                                    confidence = opp.get('confidence', 0)
                                    
                                    # STRICT: High confidence only for live
                                    if confidence < 0.85:
                                        logger.info(f"💰 Low confidence ({confidence:.0%}), skipping")
                                        continue
                                    
                                    if not self.config.get('live_auto_trade', True):
                                        logger.info("💰 Auto-trade OFF")
                                        continue
                                    
                                    logger.warning(f"🔥 LIVE SIGNAL: {symbol} {opp['signal']} ({confidence:.0%})")
                                    
                                    # Execute live trade
                                    try:
                                        result = self.live_exec.execute_trade(
                                            market_id=market_id,
                                            side=opp['signal'],
                                            size=min(self.config.get('live_trade_size', 5), 
                                                    self.config.get('live_max_size', 50)),
                                            price=opp.get('price', 0.5)
                                        )
                                        
                                        if result.get('status') == 'filled':
                                            logger.info(f"💰✅ LIVE TRADE FILLED: {result.get('order_id')}")
                                            
                                            self._send_trade_notification({
                                                'symbol': symbol,
                                                'side': opp['signal'],
                                                'size': self.config.get('live_trade_size', 5),
                                                'price': result.get('filled_price', opp.get('price', 0)),
                                                'is_live': True,
                                                'tx_hash': result.get('tx_hash', 'N/A')
                                            })
                                            
                                            self._send_log_alert(
                                                f"💰 **LIVE TRADE EXECUTED**\n"
                                                f"{symbol} {opp['signal']}\n"
                                                f"Size: {self.config.get('live_trade_size')} USDC\n"
                                                f"Real money at stake!"
                                            )
                                        else:
                                            logger.error(f"💰❌ Live trade failed: {result.get('error')}")
                                            self._send_log_alert(f"❌ Live Trade Failed\n{result.get('error', 'Unknown')}")
                                            
                                    except Exception as e:
                                        logger.error(f"💰❌ Live trade error: {e}")
                                        self._send_log_alert(f"🔥 Live Trade Error\n{str(e)[:200]}")
                    else:
                        logger.debug("💰 No Polymarket markets")
                
                time.sleep(interval)
                
            except Exception as e:
                self.error_count += 1
                logger.error(f"❌ Live loop error: {e}")
                self._send_log_alert(f"⚠️ Live Loop Error #{self.error_count}\n{str(e)[:200]}")
                time.sleep(5)

    def start(self):
        """Start bot"""
        print("\n╔" + "═" * 48 + "╗")
        print("║" + " " * 12 + "🤖 5MIN TRADING BOT" + " " * 17 + "║")
        if self.paper_enabled:
            auto = "AUTO-ON" if self.config['auto_trade'] else "MANUAL"
            print("║" + " " * 12 + f"📘 Paper: {auto}" + " " * 19 + "║")
        if self.live_enabled:
            auto = "AUTO-ON" if self.config['live_auto_trade'] else "MANUAL"
            print("║" + " " * 12 + f"💰 Live: {auto}" + " " * 20 + "║")
        print("╚" + "═" * 48 + "╝\n")
        
        self.running = True
        self._init_systems()
        
        if self.telegram:
            self.telegram.start()
            time.sleep(2)
        
        # Start threads
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
            logger.info("🛑 Shutdown...")
            self.stop()

    def stop(self):
        logger.info("🛑 Stopping...")
        self._send_log_alert(f"🛑 Bot Stopped\nUptime: {self._get_uptime()}\nErrors: {self.error_count}")
        
        self.running = False
        if self.telegram:
            self.telegram.stop()
        
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=3)
        
        logger.info("👋 Stopped")
        logger.info("══════════════════════════════════════════")

    def run(self):
        try:
            self.start()
        except Exception as e:
            logger.critical(f"💥 Fatal: {e}")
            self._send_log_alert(f"💥 **FATAL ERROR**\n```{traceback.format_exc()[:800]}```")
            raise

def main():
    bot = TradingBot()
    bot.run()

if __name__ == "__main__":
    main()
