import logging
import asyncio
import threading
from typing import Optional, Dict, Any
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, config: Optional[Dict] = None):
        self.token = token
        self.config = config or {}
        self.application = None
        self.running = False
        self._loop = None
        self._thread = None
        
    def register_handlers(self):
        """Register command handlers"""
        handlers = [
            CommandHandler("start", self.cmd_start),
            CommandHandler("status", self.cmd_status),
            CommandHandler("balance", self.cmd_balance),
            CommandHandler("positions", self.cmd_positions),
            CommandHandler("history", self.cmd_history),
            CommandHandler("help", self.cmd_help),
            CommandHandler("stop", self.cmd_stop),
            CommandHandler("pnl", self.cmd_pnl),
            CommandHandler("trade", self.cmd_trade),
            CommandHandler("markets", self.cmd_markets),
            CommandHandler("alert", self.cmd_alert),
            CommandHandler("settings", self.cmd_settings),
            CommandHandler("restart", self.cmd_restart),
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
            
        logger.info(f"Registered {len(handlers)} command handlers")

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🤖 Bot started! Use /help for commands.")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("✅ System operational")

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("💰 Balance check...")

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📊 Positions check...")

    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📜 History check...")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
Available commands:
/start - Start the bot
/status - Check system status
/balance - Check balance
/positions - View open positions
/history - View trade history
/pnl - View P&L summary
/trade - Execute manual trade
/markets - List active markets
/alert - Set price alert
/settings - Bot settings
/stop - Stop the bot
/restart - Restart bot
/help - Show this help
        """
        await update.message.reply_text(help_text)

    async def cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🛑 Stopping bot...")
        self.stop()

    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📈 P&L Summary...")

    async def cmd_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("💱 Trade execution panel...")

    async def cmd_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📊 Active markets...")

    async def cmd_alert(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔔 Alert settings...")

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⚙️ Current settings...")

    async def cmd_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔄 Restarting...")

    def start(self):
        """Start the bot in a separate thread with its own event loop"""
        if self.running:
            logger.warning("Bot already running")
            return
            
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Telegram bot thread started")

    def _run(self):
        """Internal run method that creates event loop and runs bot"""
        try:
            # Create new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # Build application
            self.application = Application.builder().token(self.token).build()
            self.register_handlers()
            
            self.running = True
            logger.info("Telegram bot initialized in thread")
            
            # Run the bot (this blocks until stop())
            self.application.run_polling(
                drop_pending_updates=True,
                close_loop=False
            )
            
        except Exception as e:
            logger.error(f"Telegram bot error: {e}")
        finally:
            self.running = False
            if self._loop:
                self._loop.close()

    def stop(self):
        """Stop the bot gracefully"""
        if self.application:
            asyncio.run_coroutine_threadsafe(
                self.application.stop(), 
                self._loop
            )
        self.running = False
        logger.info("Telegram bot stopped")

    def send_message_sync(self, chat_id: int, message: str):
        """Send message synchronously from other threads"""
        if not self.running or not self._loop:
            logger.error("Bot not running, cannot send message")
            return
            
        try:
            # Create coroutine and run it in the bot's event loop
            async def _send():
                await self.application.bot.send_message(
                    chat_id=chat_id, 
                    text=message,
                    parse_mode='HTML'
                )
            
            future = asyncio.run_coroutine_threadsafe(_send(), self._loop)
            future.result(timeout=10)  # Wait for result
            
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    # Async methods for internal use
    async def send_message(self, chat_id: int, message: str):
        """Async method to send message"""
        if self.application:
            await self.application.bot.send_message(
                chat_id=chat_id, 
                text=message,
                parse_mode='HTML'
            )

    async def send_trade_notification(self, trade: Dict):
        """Send trade notification to configured chat"""
        if not self.config.get('notifications_enabled', True):
            return
            
        chat_id = self.config.get('chat_id')
        if not chat_id:
            logger.warning("No chat_id configured for notifications")
            return
            
        message = (
            f"📝 <b>Trade Executed</b>\n"
            f"Symbol: {trade.get('symbol')}\n"
            f"Side: {trade.get('side')}\n"
            f"Size: {trade.get('size')}\n"
            f"Price: ${trade.get('price', 0):.2f}"
        )
        
        await self.send_message(chat_id, message)

    async def send_opportunity_alert(self, opportunity: Dict):
        """Send opportunity alert"""
        chat_id = self.config.get('chat_id')
        if not chat_id:
            return
            
        message = (
            f"🔍 <b>Opportunity Detected</b>\n"
            f"Symbol: {opportunity.get('symbol')}\n"
            f"Signal: {opportunity.get('signal')}\n"
            f"Confidence: {opportunity.get('confidence', 0):.1%}"
        )
        
        await self.send_message(chat_id, message)

    async def send_closure_notification(self, market_id: str, winner: str, pnl: float, details: Dict = None):
        """Send market closure notification"""
        chat_id = self.config.get('chat_id')
        if not chat_id:
            return
            
        emoji = "🟢" if pnl >= 0 else "🔴"
        message = (
            f"{emoji} <b>Market Closed</b>\n"
            f"ID: {market_id}\n"
            f"Winner: {winner}\n"
            f"PnL: ${pnl:,.2f}"
        )
        
        await self.send_message(chat_id, message)
