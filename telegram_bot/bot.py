import logging
import asyncio
import threading
from typing import Optional, Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest

logger = logging.getLogger(__name__)


class TelegramBotRunner:
    def __init__(self, 
                 token: str, 
                 config: Optional[Dict] = None,
                 dashboard: Any = None,
                 db: Any = None,
                 store: Any = None,
                 paper_executor: Any = None,
                 market_finder: Any = None,
                 closure_checker: Any = None,
                 **kwargs):
        self.token = token
        self.config = config or {}
        self.dashboard = dashboard
        self.db = db
        self.store = store
        self.paper_executor = paper_executor
        self.market_finder = market_finder
        self.closure_checker = closure_checker
        
        for key, value in kwargs.items():
            setattr(self, key, value)
            
        self.application = None
        self.running = False
        self._loop = None
        self._thread = None
        
        logger.info(f"Bot initialized with: "
                   f"paper_executor={paper_executor is not None}, "
                   f"market_finder={market_finder is not None}")

    def register_handlers(self):
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
        
        # Refresh callbacks
        self.application.add_handler(CallbackQueryHandler(self.refresh_balance_callback, pattern="^refresh_balance$"))
        self.application.add_handler(CallbackQueryHandler(self.refresh_history_callback, pattern="^refresh_history$"))
        self.application.add_handler(CallbackQueryHandler(self.refresh_pnl_callback, pattern="^refresh_pnl$"))
        self.application.add_handler(CallbackQueryHandler(self.refresh_status_callback, pattern="^refresh_status$"))
        
        # CRITICAL: Auto-trade toggle callback
        self.application.add_handler(CallbackQueryHandler(self.toggle_auto_trade_callback, pattern="^toggle_auto_trade$"))
        
        logger.info(f"Registered {len(handlers)} command handlers and 5 callbacks")

    def get_refresh_markup(self, callback_data: str) -> InlineKeyboardMarkup:
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=callback_data)]]
        return InlineKeyboardMarkup(keyboard)

    async def safe_edit_message(self, update: Update, text: str, markup: InlineKeyboardMarkup, parse_mode: str = 'HTML'):
        """Safely edit message, handling 'Message is not modified' error"""
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    text=text, 
                    parse_mode=parse_mode, 
                    reply_markup=markup
                )
            else:
                await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=markup)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                if update.callback_query:
                    await update.callback_query.answer("✅ Already up to date")
                logger.debug("Refresh requested but data unchanged")
            else:
                raise
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            raise

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        welcome_text = (
            "🤖 <b>5Min Trading Bot Started</b>\n\n"
            f"Paper Trading: {'✅ Active' if self.paper_executor else '❌ Not Connected'}\n"
            f"Market Finder: {'✅ Active' if self.market_finder else '❌ Not Connected'}\n"
            f"Closure Monitor: {'✅ Active' if self.closure_checker else '❌ Not Connected'}\n"
            f"Auto-Trade: {'✅ ON' if self.config.get('auto_trade', False) else '❌ OFF'}\n\n"
            "Use /help for available commands"
        )
        await update.message.reply_text(welcome_text, parse_mode='HTML')

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Show detailed system status with refresh button"""
        status_lines = ["📊 <b>System Status</b>"]
        
        if self.paper_executor:
            try:
                portfolio = self.paper_executor.get_portfolio_value() if hasattr(self.paper_executor, 'get_portfolio_value') else None
                if portfolio:
                    status_lines.append(
                        f"💰 Balance: ${portfolio.get('total_value', 0):,.2f} "
                        f"({'🟢' if portfolio.get('total_return', 0) >= 0 else '🔴'} "
                        f"${portfolio.get('total_return', 0):,.2f})"
                    )
                else:
                    status_lines.append("💰 Paper Trading: Connected")
            except Exception as e:
                status_lines.append(f"💰 Error: {str(e)}")
        else:
            status_lines.append("❌ Paper Trading: Not initialized")
        
        if self.market_finder:
            active_markets = len(self.market_finder.active_monitors) if hasattr(self.market_finder, 'active_monitors') else 0
            status_lines.append(f"🔍 Market Finder: Connected ({active_markets} monitors)")
        else:
            status_lines.append("❌ Market Finder: Not initialized")
            
        if self.closure_checker:
            active = len(self.closure_checker.active_markets) if hasattr(self.closure_checker, 'active_markets') else 0
            status_lines.append(f"🔒 Closure Checker: Connected ({active} markets)")
        else:
            status_lines.append("❌ Closure Checker: Not initialized")
        
        status_lines.append(f"🗄 Database: {'✅' if self.db else '❌'}")
        status_lines.append(f"🤖 Auto-Trade: {'✅ ON' if self.config.get('auto_trade', False) else '❌ OFF'}")
        
        from datetime import datetime
        status_lines.append(f"\n<i>Last updated: {datetime.now().strftime('%H:%M:%S')}</i>")
        
        text = "\n".join(status_lines)
        markup = self.get_refresh_markup("refresh_status")
        
        if edit:
            await self.safe_edit_message(update, text, markup)
        else:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=markup)

    async def refresh_status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer("Refreshing...")
        await self.cmd_status(update, context, edit=True)

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Show balance with refresh button"""
        if not self.paper_executor:
            text = "❌ <b>Paper Trading not connected</b>"
            if edit:
                await self.safe_edit_message(update, text, None)
            else:
                await update.message.reply_text(text, parse_mode='HTML')
            return
            
        try:
            portfolio = self.paper_executor.get_portfolio_value()
            from datetime import datetime
            
            balance_text = (
                f"💰 <b>Portfolio Balance</b>\n\n"
                f"Cash: <code>${portfolio.get('cash_balance', 0):,.2f}</code>\n"
                f"Positions: <code>${portfolio.get('positions_value', 0):,.2f}</code>\n"
                f"Total: <code>${portfolio.get('total_value', 0):,.2f}</code>\n"
                f"Initial: <code>${self.paper_executor.initial_balance:,.2f}</code>\n\n"
                f"Unrealized: {'🟢' if portfolio.get('unrealized_pnl', 0) >= 0 else '🔴'} ${portfolio.get('unrealized_pnl', 0):,.2f}\n"
                f"Return: {'🟢' if portfolio.get('total_return', 0) >= 0 else '🔴'} ${portfolio.get('total_return', 0):,.2f} ({portfolio.get('return_pct', 0):.2f}%)\n\n"
                f"<i>Updated: {datetime.now().strftime('%H:%M:%S')}</i>"
            )
            
            markup = self.get_refresh_markup("refresh_balance")
            
            if edit:
                await self.safe_edit_message(update, balance_text, markup)
            else:
                await update.message.reply_text(balance_text, parse_mode='HTML', reply_markup=markup)
            
        except Exception as e:
            logger.error(f"Balance error: {e}")
            text = f"❌ Error: {str(e)}"
            if edit:
                await self.safe_edit_message(update, text, None)
            else:
                await update.message.reply_text(text, parse_mode='HTML')

    async def refresh_balance_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer("Refreshing balance...")
        await self.cmd_balance(update, context, edit=True)

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show open positions"""
        if not self.paper_executor:
            await update.message.reply_text("❌ Paper Trading not connected")
            return
            
        try:
            positions = getattr(self.paper_executor, 'positions', {})
            
            if not positions:
                await update.message.reply_text("📭 <b>No open positions</b>", parse_mode='HTML')
                return
            
            pos_lines = ["📊 <b>Open Positions</b>\n"]
            
            for symbol, pos in positions.items():
                qty = pos.get('quantity', 0)
                avg_price = pos.get('avg_entry_price', 0)
                current_price = 0
                
                if hasattr(self.paper_executor, '_get_market_price'):
                    try:
                        current_price = self.paper_executor._get_market_price(symbol)
                    except:
                        pass
                
                if qty > 0 and current_price > 0:
                    pnl = (current_price - avg_price) * qty
                    pnl_emoji = '🟢' if pnl >= 0 else '🔴'
                    pos_lines.append(
                        f"<b>{symbol}</b>\n"
                        f"  Size: {qty}\n"
                        f"  Entry: ${avg_price:,.2f}\n"
                        f"  Current: ${current_price:,.2f}\n"
                        f"  {pnl_emoji} PnL: ${pnl:,.2f}\n"
                    )
                else:
                    pos_lines.append(
                        f"<b>{symbol}</b>\n"
                        f"  Size: {qty}\n"
                        f"  Avg: ${avg_price:,.2f}\n"
                    )
            
            await update.message.reply_text("\n".join(pos_lines), parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Positions error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Show trade history with refresh button"""
        if not self.paper_executor:
            text = "❌ Paper Trading not connected"
            if edit:
                await self.safe_edit_message(update, text, None)
            else:
                await update.message.reply_text(text, parse_mode='HTML')
            return
            
        try:
            history = []
            if hasattr(self.paper_executor, 'get_trade_history'):
                history = self.paper_executor.get_trade_history(limit=5)
            elif hasattr(self.paper_executor, 'trade_history'):
                history = self.paper_executor.trade_history[-5:]
            
            from datetime import datetime
            
            if not history:
                text = "📜 <b>No trades yet</b>\nHistory will appear here once trades are executed."
                markup = self.get_refresh_markup("refresh_history")
                if edit:
                    await self.safe_edit_message(update, text, markup)
                else:
                    await update.message.reply_text(text, parse_mode='HTML', reply_markup=markup)
                return
            
            hist_lines = [f"📜 <b>Recent Trades</b> <i>({datetime.now().strftime('%H:%M:%S')})</i>\n"]
            
            for trade in history:
                side = trade.get('side', 'UNKNOWN')
                emoji = '🟢' if side == 'BUY' else '🔴' if side == 'SELL' else '⚪'
                time_str = trade.get('timestamp', 'Unknown')
                if isinstance(time_str, datetime):
                    time_str = time_str.strftime('%H:%M')
                
                hist_lines.append(
                    f"{emoji} <b>{trade.get('symbol', 'Unknown')}</b> {side}\n"
                    f"   {trade.get('size', 0)} @ ${trade.get('price', 0):,.2f} = ${trade.get('total_value', 0):,.2f}\n"
                    f"   <i>{time_str}</i>\n"
                )
            
            markup = self.get_refresh_markup("refresh_history")
            text = "\n".join(hist_lines)
            
            if edit:
                await self.safe_edit_message(update, text, markup)
            else:
                await update.message.reply_text(text, parse_mode='HTML', reply_markup=markup)
            
        except Exception as e:
            logger.error(f"History error: {e}")
            text = f"❌ Error: {str(e)}"
            if edit:
                await self.safe_edit_message(update, text, None)
            else:
                await update.message.reply_text(text, parse_mode='HTML')

    async def refresh_history_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer("Refreshing history...")
        await self.cmd_history(update, context, edit=True)

    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Show P&L summary with refresh button"""
        if not self.paper_executor:
            text = "❌ Paper Trading not connected"
            if edit:
                await self.safe_edit_message(update, text, None)
            else:
                await update.message.reply_text(text, parse_mode='HTML')
            return
            
        try:
            portfolio = self.paper_executor.get_portfolio_value()
            total_return = portfolio.get('total_return', 0)
            return_pct = portfolio.get('return_pct', 0)
            from datetime import datetime
            
            pnl_text = (
                f"📈 <b>P&L Summary</b> <i>{datetime.now().strftime('%H:%M:%S')}</i>\n\n"
                f"Total Return: {'🟢' if total_return >= 0 else '🔴'} ${total_return:,.2f}\n"
                f"Return %: {'🟢' if return_pct >= 0 else '🔴'} {return_pct:.2f}%\n\n"
                f"Unrealized: ${portfolio.get('unrealized_pnl', 0):,.2f}\n"
                f"Realized: ${portfolio.get('realized_pnl', 0):,.2f}\n"
                f"Trades: {len(getattr(self.paper_executor, 'trade_history', []))}"
            )
            
            markup = self.get_refresh_markup("refresh_pnl")
            
            if edit:
                await self.safe_edit_message(update, pnl_text, markup)
            else:
                await update.message.reply_text(pnl_text, parse_mode='HTML', reply_markup=markup)
            
        except Exception as e:
            logger.error(f"PnL error: {e}")
            text = f"❌ Error: {str(e)}"
            if edit:
                await self.safe_edit_message(update, text, None)
            else:
                await update.message.reply_text(text, parse_mode='HTML')

    async def refresh_pnl_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer("Refreshing P&L...")
        await self.cmd_pnl(update, context, edit=True)

    async def cmd_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show trade execution panel"""
        if not self.paper_executor:
            await update.message.reply_text("❌ Paper Trading not connected")
            return
            
        try:
            portfolio = self.paper_executor.get_portfolio_value() if hasattr(self.paper_executor, 'get_portfolio_value') else {}
            balance = portfolio.get('cash_balance', 0)
            
            trade_text = (
                f"💱 <b>Trade Execution</b>\n\n"
                f"Available: <code>${balance:,.2f}</code>\n\n"
                f"Format: <code>/buy SYMBOL SIZE</code> or <code>/sell SYMBOL SIZE</code>\n"
                f"Example: <code>/buy BTC-USD 0.5</code>"
            )
            await update.message.reply_text(trade_text, parse_mode='HTML')
            
        except Exception as e:
            await update.message.reply_text(f"💱 Error: {str(e)}")

    async def cmd_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show active markets"""
        markets_text = ["📊 <b>Active Markets</b>\n"]
        
        if self.market_finder and hasattr(self.market_finder, 'find_active_btc_5m_markets'):
            try:
                btc_markets = self.market_finder.find_active_btc_5m_markets()
                if btc_markets:
                    markets_text.append(f"\n<b>BTC 5m ({len(btc_markets)}):</b>")
                    for m in btc_markets[:5]:
                        markets_text.append(f"• {m.get('symbol', m.get('market_id', 'Unknown'))}")
                else:
                    markets_text.append("\n<i>No BTC 5m markets active</i>")
            except Exception as e:
                markets_text.append(f"\n<i>Error: {str(e)}</i>")
        else:
            markets_text.append("\n<i>Market finder not connected</i>")
        
        await update.message.reply_text("\n".join(markets_text), parse_mode='HTML')

    async def cmd_alert(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        alert_text = (
            "🔔 <b>Alert Settings</b>\n\n"
            f"Status: {'✅ Enabled' if self.config.get('notifications_enabled', True) else '❌ Disabled'}\n"
            f"Chat ID: <code>{self.config.get('chat_id', 'Not set')}</code>"
        )
        await update.message.reply_text(alert_text, parse_mode='HTML')

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Show settings with Auto-Trade toggle button"""
        from datetime import datetime
        
        is_auto_trade = self.config.get('auto_trade', False)
        
        settings_text = (
            "⚙️ <b>Bot Configuration</b>\n\n"
            f"Auto-Trade: {'✅ ON' if is_auto_trade else '❌ OFF'}\n"
            f"Trade Size: {self.config.get('default_trade_size', 'Not set')}\n"
            f"Check Interval: {self.config.get('check_interval', '60')}s\n\n"
            f"Components:\n"
            f"  Paper: {'✅' if self.paper_executor else '❌'}\n"
            f"  Finder: {'✅' if self.market_finder else '❌'}\n"
            f"  Checker: {'✅' if self.closure_checker else '❌'}\n\n"
            f"<i>Updated: {datetime.now().strftime('%H:%M:%S')}</i>"
        )
        
        # Create toggle button
        toggle_text = "🔴 Disable Auto-Trade" if is_auto_trade else "🟢 Enable Auto-Trade"
        keyboard = [
            [InlineKeyboardButton(toggle_text, callback_data="toggle_auto_trade")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_settings")]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        
        if edit and update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    settings_text, 
                    parse_mode='HTML', 
                    reply_markup=markup
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    await update.callback_query.answer("✅ Settings unchanged")
                else:
                    raise
        else:
            await update.message.reply_text(settings_text, parse_mode='HTML', reply_markup=markup)

    async def toggle_auto_trade_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle Auto-Trade toggle button click"""
        query = update.callback_query
        
        # Toggle the value
        current = self.config.get('auto_trade', False)
        self.config['auto_trade'] = not current
        
        new_status = "ON ✅" if self.config['auto_trade'] else "OFF ❌"
        logger.info(f"Auto-Trade toggled to: {new_status}")
        
        # Notify user
        await query.answer(f"Auto-Trade is now {new_status}")
        
        # Update market_finder if available to apply changes immediately
        if self.market_finder:
            self.market_finder.config['auto_trade'] = self.config['auto_trade']
        
        # Refresh the settings message
        await self.cmd_settings(update, context, edit=True)

    async def cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🛑 <b>Stopping bot...</b>\nGoodbye!", parse_mode='HTML')
        self.stop()

    async def cmd_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔄 <b>Restarting...</b>\nPlease wait.", parse_mode='HTML')

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
<b>📱 Commands</b>
/balance - Portfolio balance ↻
/history - Trade history ↻
/pnl - P&L summary ↻
/status - System status ↻
/settings - Configuration & Auto-Trade toggle 🔄
/positions - Open positions
/markets - Active markets
/trade - Trade panel
/stop - Stop bot
/help - This help

<i>↻ = Refresh button</i>
<i>🔄 = Toggle button</i>
        """
        await update.message.reply_text(help_text, parse_mode='HTML')

    def start(self):
        if self.running:
            logger.warning("Bot already running")
            return
            
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Telegram bot thread started")

    def _run(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            self.application = Application.builder().token(self.token).build()
            self.register_handlers()
            
            self.running = True
            logger.info("Telegram bot initialized and polling...")
            
            self.application.run_polling(
                drop_pending_updates=True,
                close_loop=False,
                stop_signals=None
            )
            
        except Exception as e:
            logger.error(f"Telegram bot fatal error: {e}")
        finally:
            self.running = False
            if self._loop:
                try:
                    self._loop.close()
                except Exception:
                    pass

    def stop(self):
        if self.application and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.application.stop(), 
                    self._loop
                )
            except Exception as e:
                logger.error(f"Error stopping bot: {e}")
        self.running = False

    def send_message_sync(self, chat_id: int, message: str):
        if not self.running or not self._loop:
            logger.error("Bot not running, cannot send message")
            return
            
        try:
            async def _send():
                await self.application.bot.send_message(
                    chat_id=chat_id, 
                    text=message,
                    parse_mode='HTML'
                )
            
            future = asyncio.run_coroutine_threadsafe(_send(), self._loop)
            future.result(timeout=10)
            
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def send_message(self, chat_id: int, message: str):
        if self.application:
            await self.application.bot.send_message(
                chat_id=chat_id, 
                text=message,
                parse_mode='HTML'
            )

    async def send_trade_notification(self, trade: Dict):
        if not self.config.get('notifications_enabled', True):
            return
        chat_id = self.config.get('chat_id')
        if not chat_id:
            return
            
        message = (
            f"📝 <b>Trade Executed</b>\n"
            f"{trade.get('symbol')} {trade.get('side')} {trade.get('size')} @ ${trade.get('price', 0):,.2f}"
        )
        await self.send_message(chat_id, message)

    async def send_opportunity_alert(self, opportunity: Dict):
        chat_id = self.config.get('chat_id')
        if not chat_id:
            return
            
        message = (
            f"🔍 <b>Opportunity</b>\n"
            f"{opportunity.get('symbol')} {opportunity.get('signal')} "
            f"({opportunity.get('confidence', 0):.0%})"
        )
        await self.send_message(chat_id, message)

    async def send_closure_notification(self, market_id: str, winner: str, pnl: float, details: Dict = None):
        chat_id = self.config.get('chat_id')
        if not chat_id:
            return
            
        emoji = "🟢" if pnl >= 0 else "🔴"
        message = f"{emoji} <b>Closed</b> {market_id}\nWinner: {winner}\nPnL: ${pnl:,.2f}"
        await self.send_message(chat_id, message)
