import logging
import asyncio
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest

# IST Timezone setup
try:
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
except ImportError:
    IST = timezone(timedelta(hours=5, minutes=30))

logger = logging.getLogger('Telegram')


def get_ist_now() -> datetime:
    """Get current IST time"""
    return datetime.now(IST)


def fmt_ist(dt: Optional[datetime] = None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Format time in IST"""
    if dt is None:
        dt = get_ist_now()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime(fmt)


def escape_md(text: str) -> str:
    """Escape markdown v2 special characters"""
    chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for ch in chars:
        text = text.replace(ch, f'\\{ch}')
    return text


class TelegramBotRunner:
    def __init__(self, token: str, config: Optional[Dict] = None, **kwargs):
        self.token = token
        self.config = config or {}
        self.paper_executor = kwargs.get('paper_executor')
        self.market_finder = kwargs.get('market_finder')
        self.closure_checker = kwargs.get('closure_checker')
        
        self.app = None
        self.running = False
        self._loop = None
        self._thread = None

    def register_handlers(self):
        """Register all handlers"""
        handlers = [
            CommandHandler("start", self.cmd_start),
            CommandHandler("menu", self.cmd_menu),
            CommandHandler("balance", self.cmd_balance),
            CommandHandler("positions", self.cmd_positions),
            CommandHandler("history", self.cmd_history),
            CommandHandler("pnl", self.cmd_pnl),
            CommandHandler("markets", self.cmd_markets),
            CommandHandler("settings", self.cmd_settings),
            CommandHandler("help", self.cmd_help),
        ]
        
        for h in handlers:
            self.app.add_handler(h)
        
        # Callbacks
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))
        
        logger.info("✅ Bot handlers registered")

    def _keyboard(self, buttons: List[List[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
        """Create inline keyboard"""
        return InlineKeyboardMarkup(buttons)

    def _nav_buttons(self, current: str) -> List[List[InlineKeyboardButton]]:
        """Navigation row"""
        nav = [
            InlineKeyboardButton("💰 Balance", callback_data="nav_balance"),
            InlineKeyboardButton("📊 Markets", callback_data="nav_markets"),
        ]
        refresh = InlineKeyboardButton("↻ Refresh", callback_data=f"refresh_{current}")
        return [nav, [refresh]]

    async def _edit_or_send(self, update: Update, text: str, keyboard=None, edit: bool = False):
        """Edit message or send new"""
        try:
            if edit and update.callback_query:
                await update.callback_query.edit_message_text(
                    text=text, 
                    reply_markup=keyboard,
                    parse_mode='MarkdownV2',
                    disable_web_page_preview=True
                )
            else:
                await update.message.reply_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode='MarkdownV2',
                    disable_web_page_preview=True
                )
        except BadRequest as e:
            if "not modified" in str(e).lower():
                if update.callback_query:
                    await update.callback_query.answer("✓ Updated")
            else:
                # Try without markdown
                plain_text = text.replace('*', '').replace('_', '').replace('`', '')
                if edit and update.callback_query:
                    await update.callback_query.edit_message_text(text=plain_text, reply_markup=keyboard)
                else:
                    await update.message.reply_text(text=plain_text, reply_markup=keyboard)

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command - Welcome"""
        time_str = fmt_ist()
        mode = "🟢 LIVE" if self.config.get('trading_mode') == 'live' else "🔵 PAPER"
        
        text = (
            f"*Welcome to 5Min Trader* 🤖\n\n"
            f"Mode: {escape_md(mode)}\n"
            f"Auto-Trade: {'✅ ON' if self.config.get('auto_trade') else '⭕ OFF'}\n"
            f"Time: `{escape_md(time_str)}`\n\n"
            f"Use /menu for dashboard or /help for commands"
        )
        
        # Main menu button
        keyboard = [[InlineKeyboardButton("📱 Open Dashboard", callback_data="nav_menu")]]
        await self._edit_or_send(update, text, self._keyboard(keyboard))

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Main dashboard menu"""
        # Get quick stats
        bal_str = "$0.00"
        pnl_str = "0.00"
        
        if self.paper_executor:
            try:
                pf = self.paper_executor.get_portfolio_value()
                bal_str = f"${pf.get('total_value', 0):,.2f}"
                pnl = pf.get('total_return', 0)
                pnl_str = f"{pnl:+.2f}"
            except:
                pass
        
        text = (
            f"*📱 Dashboard*\n\n"
            f"💰 Balance: `{escape_md(bal_str)}`\n"
            f"📈 PnL: `{escape_md(pnl_str)}%`\n"
            f"🕐 {escape_md(fmt_ist())}\n\n"
            f"Select option:"
        )
        
        keyboard = [
            [InlineKeyboardButton("💰 Portfolio", callback_data="nav_balance"),
             InlineKeyboardButton("📊 Markets", callback_data="nav_markets")],
            [InlineKeyboardButton("📜 History", callback_data="nav_history"),
             InlineKeyboardButton("📈 P&L", callback_data="nav_pnl")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="nav_settings"),
             InlineKeyboardButton("❓ Help", callback_data="nav_help")],
        ]
        
        await self._edit_or_send(update, text, self._keyboard(keyboard), edit)

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Balance view"""
        if not self.paper_executor:
            text = "❌ Trading not initialized"
            await self._edit_or_send(update, text, None, edit)
            return
        
        try:
            pf = self.paper_executor.get_portfolio_value()
            
            text = (
                f"*💰 Portfolio Balance*\n\n"
                f"Cash: `${pf['cash_balance']:,.2f}`\n"
                f"Positions: `${pf['positions_value']:,.2f}`\n"
                f"────────────────────\n"
                f"Total: *`${pf['total_value']:,.2f}`*\n\n"
                f"PnL: `{pf['total_return']:+,.2f}` \\({pf['return_pct']:+.2f}%\\)\n"
                f"Updated: {escape_md(fmt_ist())}"
            )
            
            keyboard = self._nav_buttons("balance")
            await self._edit_or_send(update, text, self._keyboard(keyboard), edit)
            
        except Exception as e:
            logger.error(f"Balance error: {e}")
            await self._edit_or_send(update, "❌ Error loading balance", None, edit)

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Positions list"""
        if not self.paper_executor:
            await update.message.reply_text("❌ Trading offline")
            return
        
        positions = getattr(self.paper_executor, 'positions', {})
        
        if not positions:
            text = "*📭 Positions*\n\nNo open positions\n\n" + f"`{fmt_ist()}`"
            await update.message.reply_text(text, parse_mode='MarkdownV2')
            return
        
        lines = ["*📊 Open Positions*\n"]
        for sym, pos in positions.items():
            qty = pos.get('quantity', 0)
            avg = pos.get('avg_entry_price', 0)
            lines.append(f"• {sym}: `{qty}` @ `${avg:,.2f}`")
        
        lines.append(f"\n`{fmt_ist()}`")
        await update.message.reply_text('\n'.join(lines), parse_mode='MarkdownV2')

    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Trade history"""
        if not self.paper_executor:
            text = "❌ Trading offline"
            await self._edit_or_send(update, text, None, edit)
            return
        
        history = []
        if hasattr(self.paper_executor, 'get_trade_history'):
            history = self.paper_executor.get_trade_history(limit=5)
        elif hasattr(self.paper_executor, 'trade_history'):
            history = self.paper_executor.trade_history[-5:]
        
        if not history:
            text = "*📜 Trade History*\n\nNo trades yet\n\n" + f"`{fmt_ist()}`"
            keyboard = [[InlineKeyboardButton("↻ Refresh", callback_data="refresh_history")]]
            await self._edit_or_send(update, text, self._keyboard(keyboard), edit)
            return
        
        lines = [f"*📜 Last {len(history)} Trades*\n"]
        
        for trade in history:
            side = trade.get('side', '?')
            symbol = trade.get('symbol', '?')
            size = trade.get('size', 0)
            price = trade.get('price', 0)
            ts = trade.get('timestamp')
            
            time_str = ""
            if ts:
                if isinstance(ts, str):
                    try:
                        from dateutil import parser
                        dt = parser.parse(ts)
                        time_str = fmt_ist(dt, "%H:%M")
                    except:
                        time_str = str(ts)[11:16]
                else:
                    time_str = fmt_ist(ts, "%H:%M")
            
            icon = "🟢" if side == "BUY" else "🔴"
            lines.append(f"{icon} {symbol} `{side}` {size} @ ${price:,.2f}  {time_str}")
        
        lines.append(f"\n`{fmt_ist()}`")
        keyboard = self._nav_buttons("history")
        await self._edit_or_send(update, '\n'.join(lines), self._keyboard(keyboard), edit)

    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """P&L summary"""
        if not self.paper_executor:
            text = "❌ Trading offline"
            await self._edit_or_send(update, text, None, edit)
            return
        
        try:
            pf = self.paper_executor.get_portfolio_value()
            trades = len(getattr(self.paper_executor, 'trade_history', []))
            
            # Determine emoji based on PnL
            pnl_emoji = "🟢" if pf['total_return'] >= 0 else "🔴"
            
            text = (
                f"*📈 Performance Summary*\n\n"
                f"{pnl_emoji} Total Return: `${pf['total_return']:+,.2f}`\n"
                f"📊 Return %: `{pf['return_pct']:+.2f}%`\n"
                f"💵 Unrealized: `${pf['unrealized_pnl']:,.2f}`\n"
                f"📝 Total Trades: `{trades}`\n\n"
                f"{escape_md(fmt_ist())}"
            )
            
            keyboard = self._nav_buttons("pnl")
            await self._edit_or_send(update, text, self._keyboard(keyboard), edit)
            
        except Exception as e:
            logger.error(f"Pnl error: {e}")
            await self._edit_or_send(update, "❌ Error loading P&L", None, edit)

    async def cmd_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Markets view"""
        if not self.market_finder:
            text = "❌ Market finder offline"
            await self._edit_or_send(update, text, None, edit)
            return
        
        try:
            markets = self.market_finder.find_active_btc_5m_markets()
            
            if not markets:
                text = (
                    f"*📊 Markets*\n\n"
                    f"No active markets found\n"
                    f"_Check configuration or wait for markets to open_\n\n"
                    f"`{fmt_ist()}`"
                )
                keyboard = [[InlineKeyboardButton("↻ Refresh", callback_data="refresh_markets")]]
                await self._edit_or_send(update, text, self._keyboard(keyboard), edit)
                return
            
            lines = [f"*📊 Active Markets* ({len(markets)} found)\n"]
            
            for m in markets[:5]:
                sym = m.get('symbol', 'Unknown')
                expiry = m.get('expiry', '')
                if expiry:
                    try:
                        from dateutil import parser
                        exp_dt = parser.parse(expiry) if isinstance(expiry, str) else expiry
                        exp_str = fmt_ist(exp_dt, "%H:%M")
                    except:
                        exp_str = "Soon"
                else:
                    exp_str = "Active"
                
                lines.append(f"• {sym}  _Exp: {exp_str}_")
            
            lines.append(f"\n`{fmt_ist()}`")
            
            keyboard = self._nav_buttons("markets")
            await self._edit_or_send(update, '\n'.join(lines), self._keyboard(keyboard), edit)
            
        except Exception as e:
            logger.error(f"Markets error: {e}")
            await self._edit_or_send(update, f"❌ Error: {str(e)}", None, edit)

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Settings with toggle"""
        is_auto = self.config.get('auto_trade', False)
        mode = self.config.get('trading_mode', 'paper').upper()
        
        text = (
            f"*⚙️ Settings*\n\n"
            f"🎚 Mode: `{mode}`\n"
            f"🤖 Auto-Trade: `{'ON ✅' if is_auto else 'OFF ❌'}`\n"
            f"💵 Trade Size: `{self.config.get('default_trade_size', 1.0)}`\n"
            f"⏱ Check Interval: `{self.config.get('check_interval', 60)}s`\n\n"
            f"Status:\n"
            f"• Trading: {'🟢' if self.paper_executor else '🔴'}\n"
            f"• Markets: {'🟢' if self.market_finder else '🔴'}\n"
            f"• Monitor: {'🟢' if self.closure_checker else '🔴'}\n\n"
            f"`{fmt_ist()}`"
        )
        
        # Toggle button
        toggle_text = "🔴 Disable Auto" if is_auto else "🟢 Enable Auto"
        keyboard = [
            [InlineKeyboardButton(toggle_text, callback_data="toggle_auto")],
            [InlineKeyboardButton("↻ Refresh", callback_data="refresh_settings"),
             InlineKeyboardButton("📱 Menu", callback_data="nav_menu")]
        ]
        
        await self._edit_or_send(update, text, self._keyboard(keyboard), edit)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """Help command"""
        text = (
            f"*📖 Help Guide*\n\n"
            f"*Dashboard:*\n"
            f"/menu \\- Main dashboard\n"
            f"/balance \\- Portfolio & PnL\n"
            f"/positions \\- Current holdings\n\n"
            f"*Trading:*\n"
            f"/markets \\- Active markets\n"
            f"/history \\- Past trades\n"
            f"/pnl \\- Performance stats\n\n"
            f"*Config:*\n"
            f"/settings \\- Auto\\-trade toggle\n"
            f"/help \\- Show this help\n\n"
            f"⏰ All times in IST \\(UTC\\+5:30\\)\n"
            f"`{fmt_ist()}`"
        )
        
        keyboard = [[InlineKeyboardButton("📱 Back to Menu", callback_data="nav_menu")]]
        await self._edit_or_send(update, text, self._keyboard(keyboard), edit)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all button callbacks"""
        query = update.callback_query
        data = query.data
        
        try:
            if data.startswith("nav_"):
                # Navigation
                page = data.replace("nav_", "")
                await query.answer(f"Loading {page}...")
                
                if page == "menu":
                    await self.cmd_menu(update, context, edit=True)
                elif page == "balance":
                    await self.cmd_balance(update, context, edit=True)
                elif page == "markets":
                    await self.cmd_markets(update, context, edit=True)
                elif page == "history":
                    await self.cmd_history(update, context, edit=True)
                elif page == "pnl":
                    await self.cmd_pnl(update, context, edit=True)
                elif page == "settings":
                    await self.cmd_settings(update, context, edit=True)
                elif page == "help":
                    await self.cmd_help(update, context, edit=True)
                    
            elif data.startswith("refresh_"):
                # Refresh buttons
                page = data.replace("refresh_", "")
                await query.answer("Refreshing...")
                
                if page == "balance":
                    await self.cmd_balance(update, context, edit=True)
                elif page == "markets":
                    await self.cmd_markets(update, context, edit=True)
                elif page == "history":
                    await self.cmd_history(update, context, edit=True)
                elif page == "pnl":
                    await self.cmd_pnl(update, context, edit=True)
                elif page == "settings":
                    await self.cmd_settings(update, context, edit=True)
                    
            elif data == "toggle_auto":
                # Auto-trade toggle
                current = self.config.get('auto_trade', False)
                self.config['auto_trade'] = not current
                
                new_status = "ON ✅" if self.config['auto_trade'] else "OFF ❌"
                await query.answer(f"Auto-Trade: {new_status}")
                
                # Update market finder config
                if self.market_finder:
                    self.market_finder.config['auto_trade'] = self.config['auto_trade']
                
                logger.info(f"Auto-Trade toggled to: {new_status}")
                await self.cmd_settings(update, context, edit=True)
                
        except Exception as e:
            logger.error(f"Callback error: {e}")
            await query.answer("Error occurred")

    def start(self):
        """Start bot in thread"""
        if self.running:
            return
        
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("🚀 Bot started")

    def _run(self):
        """Run bot"""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            self.app = Application.builder().token(self.token).build()
            self.register_handlers()
            
            self.running = True
            logger.info("✅ Bot polling active")
            
            self.app.run_polling(
                drop_pending_updates=True,
                close_loop=False,
                stop_signals=None
            )
        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            self.running = False
            if self._loop:
                try:
                    self._loop.close()
                except:
                    pass

    def stop(self):
        """Stop bot"""
        if self.app and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self.app.stop(), self._loop)
            except:
                pass
        self.running = False

    # Notification helpers
    async def send_trade_notification(self, trade: Dict):
        if not self.config.get('notifications_enabled', True):
            return
        chat_id = self.config.get('chat_id')
        if not chat_id:
            return
        
        text = (
            f"📝 *Trade Executed*\n\n"
            f"{trade.get('symbol')} {trade.get('side')}\n"
            f"Size: `{trade.get('size')}`\n"
            f"Price: `${trade.get('price', 0):,.2f}`\n\n"
            f"`{fmt_ist()}`"
        )
        
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, parse_mode='MarkdownV2')
        except:
            pass

    async def send_opportunity_alert(self, opportunity: Dict):
        chat_id = self.config.get('chat_id')
        if not chat_id:
            return
        
        text = (
            f"🔍 *Signal Detected*\n\n"
            f"Market: {opportunity.get('symbol')}\n"
            f"Direction: `{opportunity.get('signal')}`\n"
            f"Confidence: `{opportunity.get('confidence', 0):.0%}`\n\n"
            f"`{fmt_ist()}`"
        )
        
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, parse_mode='MarkdownV2')
        except:
            pass

    async def send_closure_notification(self, market_id: str, winner: str, pnl: float, details: Dict = None):
        chat_id = self.config.get('chat_id')
        if not chat_id:
            return
        
        emoji = "✅" if pnl >= 0 else "❌"
        text = (
            f"{emoji} *Market Settled*\n\n"
            f"ID: `{market_id[:20]}...`\n"
            f"Result: {winner}\n"
            f"PnL: `${pnl:+,.2f}`\n\n"
            f"`{fmt_ist()}`"
        )
        
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, parse_mode='MarkdownV2')
        except:
            pass
