import logging
import asyncio
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest

# IST Timezone
try:
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
except ImportError:
    IST = timezone(timedelta(hours=5, minutes=30))

logger = logging.getLogger('Telegram')


def get_ist_now() -> datetime:
    return datetime.now(IST)


def fmt_ist(dt: Optional[datetime] = None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    if dt is None:
        dt = get_ist_now()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime(fmt)


class TelegramBotRunner:
    def __init__(self, token: str, config: Optional[Dict] = None, **kwargs):
        self.token = token
        self.config = config or {}
        
        self.paper_executor = kwargs.get('paper_executor')
        self.live_executor = kwargs.get('live_executor')
        self.market_finder = kwargs.get('market_finder')
        self.paper_enabled = kwargs.get('paper_enabled', False)
        self.live_enabled = kwargs.get('live_enabled', False)
        self.get_uptime = kwargs.get('get_uptime', lambda: "Unknown")  # Uptime function
        
        self.app = None
        self.running = False
        self._loop = None
        self._thread = None
        self.start_time = time.time()

    def register_handlers(self):
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
            CommandHandler("ping", self.cmd_ping),  # NEW: Ping command
        ]
        
        for h in handlers:
            self.app.add_handler(h)
        
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))
        logger.info("✅ Handlers registered")

    def _back_btn(self) -> InlineKeyboardButton:
        return InlineKeyboardButton("⬅️ Back to Menu", callback_data="nav_menu")

    def _nav_row(self, current: str) -> List[InlineKeyboardButton]:
        return [
            InlineKeyboardButton("↻ Refresh", callback_data=f"refresh_{current}"),
            self._back_btn()
        ]

    async def _send_or_edit(self, update: Update, text: str, keyboard=None, edit=False):
        try:
            if edit and update.callback_query:
                await update.callback_query.edit_message_text(
                    text=text, reply_markup=keyboard, parse_mode='Markdown', disable_web_page_preview=True
                )
            else:
                await update.message.reply_text(
                    text=text, reply_markup=keyboard, parse_mode='Markdown', disable_web_page_preview=True
                )
        except Exception as e:
            plain = text.replace('*', '').replace('_', '').replace('`', '')
            try:
                if edit and update.callback_query:
                    await update.callback_query.edit_message_text(text=plain, reply_markup=keyboard)
                else:
                    await update.message.reply_text(text=plain, reply_markup=keyboard)
            except:
                pass

    async def cmd_ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        🏓 Ping command - Check bot health and status
        """
        # Calculate response time
        start = time.time()
        uptime = self.get_uptime()
        response_time = (time.time() - start) * 1000  # ms
        
        # System status
        status_emoji = "🟢" if self.running else "🔴"
        
        paper_status = "🟢 Online" if self.paper_executor else "🔴 Offline"
        live_status = "🟢 Online" if self.live_executor else "🔴 Offline"
        market_status = "🟢 Online" if self.market_finder else "🔴 Offline"
        
        text = (
            f"🏓 *Pong!* Bot is alive {status_emoji}\n\n"
            f"⚡ *Response Time:* `{response_time:.1f}ms`\n"
            f"⏱ *Uptime:* `{uptime}`\n"
            f"🕐 *Current Time:* `{fmt_ist()}`\n\n"
            f"*System Status:*\n"
            f"📘 Paper Trading: {paper_status}\n"
            f"💰 Live Trading: {live_status}\n"
            f"📊 Market Finder: {market_status}\n\n"
            f"_All systems operational ✅_"
        )
        
        keyboard = InlineKeyboardMarkup([[self._back_btn()]])
        await self._send_or_edit(update, text, keyboard)

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status = []
        if self.paper_executor: status.append("📘 Paper: Online")
        else: status.append("📘 Paper: Offline")
        
        if self.live_executor: status.append("💰 Live: Online")
        else: status.append("💰 Live: Offline")
        
        text = (
            f"*🤖 5Min Trading Bot*\n\n"
            f"{'\n'.join(status)}\n\n"
            f"⏰ `{fmt_ist()}`\n\n"
            f"Use /menu for dashboard or /ping to check status"
        )
        
        keyboard = [[InlineKeyboardButton("📱 Open Menu", callback_data="nav_menu")]]
        await self._send_or_edit(update, text, InlineKeyboardMarkup(keyboard))

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        # Get balances
        paper_bal = "Offline"
        live_bal = "Offline"
        
        if self.paper_executor:
            try:
                pf = self.paper_executor.get_portfolio_value()
                paper_bal = f"${pf.get('total_value', 0):,.2f}"
            except: paper_bal = "Error"
        
        if self.live_executor:
            try:
                pf = self.live_executor.get_portfolio_value()
                live_bal = f"${pf.get('total_value', 0):,.2f} USDC"
            except: live_bal = "Error"
        
        text = (
            f"*📱 Dashboard*\n\n"
            f"📘 Paper: `{paper_bal}`\n"
            f"💰 Live: `{live_bal}`\n"
            f"⏰ `{fmt_ist()}`\n\n"
            f"Select option:"
        )
        
        keyboard = [
            [InlineKeyboardButton("💰 Balance", callback_data="nav_balance"),
             InlineKeyboardButton("📊 Markets", callback_data="nav_markets")],
            [InlineKeyboardButton("📜 History", callback_data="nav_history"),
             InlineKeyboardButton("📈 P&L", callback_data="nav_pnl")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="nav_settings"),
             InlineKeyboardButton("🏓 Ping", callback_data="nav_ping")],  # Added ping to menu
        ]
        
        await self._send_or_edit(update, text, InlineKeyboardMarkup(keyboard), edit)

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        lines = ["*💰 Account Balances*\n"]
        
        if self.paper_executor:
            try:
                pf = self.paper_executor.get_portfolio_value()
                lines.append(
                    f"*📘 Paper Account*\n"
                    f"💵 Cash: `${pf['cash_balance']:,.2f}`\n"
                    f"📊 Positions: `${pf['positions_value']:,.2f}`\n"
                    f"💎 Total: `{pf['total_value']:,.2f}`\n"
                    f"📈 PnL: `{pf['total_return']:+,.2f}`\n"
                )
            except:
                lines.append("*📘 Paper Account*\n⚠️ Error loading\n")
        else:
            lines.append("*📘 Paper Account*\n🔴 Offline\n")
        
        if self.live_executor:
            try:
                pf = self.live_executor.get_portfolio_value()
                lines.append(
                    f"\n*💰 Live Account*\n"
                    f"💵 USDC: `{pf.get('cash_balance', 0):,.2f}`\n"
                    f"👛 Wallet: `{str(pf.get('wallet', 'N/A'))[:10]}...`\n"
                )
            except:
                lines.append(f"\n*💰 Live Account*\n⚠️ Error loading\n")
        else:
            lines.append(f"\n*💰 Live Account*\n🔴 Offline")
        
        lines.append(f"\n⏰ `{fmt_ist()}`")
        
        keyboard = InlineKeyboardMarkup([self._nav_row("balance")])
        await self._send_or_edit(update, "\n".join(lines), keyboard, edit)

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lines = ["*📊 Open Positions*\n"]
        
        if not self.paper_executor and not self.live_executor:
            lines.append("🔴 Both systems offline")
            keyboard = InlineKeyboardMarkup([[self._back_btn()]])
            await self._send_or_edit(update, "\n".join(lines), keyboard)
            return
        
        if self.paper_executor:
            try:
                positions = getattr(self.paper_executor, 'positions', {})
                if positions:
                    lines.append("📘 *Paper Positions:*")
                    for sym, pos in positions.items():
                        lines.append(f"• {sym}: `{pos.get('quantity', 0)}` @ `${pos.get('avg_entry_price', 0):,.2f}`")
                else:
                    lines.append("📘 Paper: No open positions")
            except:
                lines.append("📘 Paper: ⚠️ Error")
        
        lines.append(f"\n⏰ `{fmt_ist()}`")
        keyboard = InlineKeyboardMarkup([[self._back_btn()]])
        await self._send_or_edit(update, "\n".join(lines), keyboard)

    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        if not self.paper_executor:
            text = "*📜 History*\n\n🔴 Paper offline\n\n⏰ " + fmt_ist()
            keyboard = InlineKeyboardMarkup([self._nav_row("history")])
            await self._send_or_edit(update, text, keyboard, edit)
            return
        
        try:
            history = self.paper_executor.get_trade_history(limit=5) if hasattr(self.paper_executor, 'get_trade_history') else []
            if not history:
                history = getattr(self.paper_executor, 'trade_history', [])[-5:]
            
            if not history:
                text = "*📜 History*\n\n📝 No trades yet\n\n⏰ " + fmt_ist()
            else:
                lines = [f"*📜 Last {len(history)} Trades*"]
                for trade in history:
                    icon = "🟢" if trade.get('side') == "BUY" else "🔴"
                    lines.append(f"{icon} {trade.get('symbol')} `{trade.get('side')}` @ `${trade.get('price', 0):,.2f}`")
                lines.append(f"\n⏰ `{fmt_ist()}`")
                text = "\n".join(lines)
            
            keyboard = InlineKeyboardMarkup([self._nav_row("history")])
            await self._send_or_edit(update, text, keyboard, edit)
            
        except Exception as e:
            text = f"*📜 History*\n\n❌ Error\n\n⏰ {fmt_ist()}"
            await self._send_or_edit(update, text, InlineKeyboardMarkup([[self._back_btn()]]), edit)

    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        if not self.paper_executor:
            text = "*📈 P&L*\n\n🔴 Offline\n\n⏰ " + fmt_ist()
            keyboard = InlineKeyboardMarkup([self._nav_row("pnl")])
            await self._send_or_edit(update, text, keyboard, edit)
            return
        
        try:
            pf = self.paper_executor.get_portfolio_value()
            trades = len(getattr(self.paper_executor, 'trade_history', []))
            icon = "🟢" if pf['total_return'] >= 0 else "🔴"
            
            text = (
                f"*📈 Performance*\n\n"
                f"{icon} Return: `${pf['total_return']:+,.2f}`\n"
                f"📊 %: `{pf['return_pct']:+.2f}%`\n"
                f"💵 Unrealized: `${pf['unrealized_pnl']:,.2f}`\n"
                f"📝 Trades: `{trades}`\n\n"
                f"⏰ `{fmt_ist()}`"
            )
            
            keyboard = InlineKeyboardMarkup([self._nav_row("pnl")])
            await self._send_or_edit(update, text, keyboard, edit)
            
        except:
            text = f"*📈 P&L*\n\n❌ Error\n\n⏰ {fmt_ist()}"
            await self._send_or_edit(update, text, InlineKeyboardMarkup([[self._back_btn()]]), edit)

    async def cmd_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        if not self.market_finder:
            text = "*📊 Markets*\n\n🔴 Finder offline\n\n⏰ " + fmt_ist()
            keyboard = InlineKeyboardMarkup([self._nav_row("markets")])
            await self._send_or_edit(update, text, keyboard, edit)
            return
        
        try:
            markets = self.market_finder.find_active_btc_5m_markets()
            if not markets:
                text = f"*📊 Markets*\n\n🔍 No active markets\n\n⏰ `{fmt_ist()}`"
            else:
                lines = [f"*📊 Active Markets* ({len(markets)})"]
                for m in markets[:5]:
                    lines.append(f"• {m.get('symbol', 'Unknown')}")
                lines.append(f"\n⏰ `{fmt_ist()}`")
                text = "\n".join(lines)
            
            keyboard = InlineKeyboardMarkup([self._nav_row("markets")])
            await self._send_or_edit(update, text, keyboard, edit)
            
        except Exception as e:
            text = f"*📊 Markets*\n\n❌ Error\n\n⏰ {fmt_ist()}"
            await self._send_or_edit(update, text, InlineKeyboardMarkup([[self._back_btn()]]), edit)

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        is_auto = self.config.get('auto_trade', False)
        
        text = (
            f"*⚙️ Settings*\n\n"
            f"🤖 Auto-Trade: `{'ON ✅' if is_auto else 'OFF ❌'}`\n"
            f"💵 Size: `{self.config.get('default_trade_size', 1.0)}`\n\n"
            f"Status:\n"
            f"📘 Paper: `{'🟢' if self.paper_executor else '🔴'}`\n"
            f"💰 Live: `{'🟢' if self.live_executor else '🔴'}`\n\n"
            f"⏰ `{fmt_ist()}`"
        )
        
        toggle = "🔴 Disable" if is_auto else "🟢 Enable"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(toggle, callback_data="toggle_auto")],
            [InlineKeyboardButton("↻ Refresh", callback_data="refresh_settings"), self._back_btn()]
        ])
        
        await self._send_or_edit(update, text, keyboard, edit)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        text = (
            f"*📖 Help*\n\n"
            f"*Commands:*\n"
            f"/menu - Dashboard\n"
            f"/balance - Balances\n"
            f"/positions - Holdings\n"
            f"/markets - Markets\n"
            f"/history - History\n"
            f"/pnl - Performance\n"
            f"/settings - Config\n"
            f"/ping - Bot status ⭐\n\n"
            f"⏰ IST (UTC+5:30)\n"
            f"`{fmt_ist()}`"
        )
        keyboard = InlineKeyboardMarkup([[self._back_btn()]])
        await self._send_or_edit(update, text, keyboard, edit)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data
        
        try:
            if data.startswith("nav_"):
                page = data.replace("nav_", "")
                await query.answer(f"Loading {page}...")
                
                if page == "menu": await self.cmd_menu(update, context, edit=True)
                elif page == "balance": await self.cmd_balance(update, context, edit=True)
                elif page == "markets": await self.cmd_markets(update, context, edit=True)
                elif page == "history": await self.cmd_history(update, context, edit=True)
                elif page == "pnl": await self.cmd_pnl(update, context, edit=True)
                elif page == "settings": await self.cmd_settings(update, context, edit=True)
                elif page == "help": await self.cmd_help(update, context, edit=True)
                elif page == "ping": await self.cmd_ping(update, context)  # Handle ping from menu
                    
            elif data.startswith("refresh_"):
                page = data.replace("refresh_", "")
                await query.answer("Refreshing...")
                
                if page == "balance": await self.cmd_balance(update, context, edit=True)
                elif page == "markets": await self.cmd_markets(update, context, edit=True)
                elif page == "history": await self.cmd_history(update, context, edit=True)
                elif page == "pnl": await self.cmd_pnl(update, context, edit=True)
                elif page == "settings": await self.cmd_settings(update, context, edit=True)
                    
            elif data == "toggle_auto":
                current = self.config.get('auto_trade', False)
                self.config['auto_trade'] = not current
                status = "ON ✅" if self.config['auto_trade'] else "OFF ❌"
                await query.answer(f"Auto: {status}")
                logger.info(f"Auto-trade toggled: {status}")
                await self.cmd_settings(update, context, edit=True)
                
        except Exception as e:
            logger.error(f"Callback error: {e}")
            await query.answer("❌ Error")

    def start(self):
        if self.running: return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self.app = Application.builder().token(self.token).build()
            self.register_handlers()
            self.running = True
            logger.info("📱 Bot polling started")
            self.app.run_polling(drop_pending_updates=True, close_loop=False, stop_signals=None)
        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            self.running = False

    def stop(self):
        if self.app and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self.app.stop(), self._loop)
            except:
                pass
        self.running = False

    async def send_trade_notification(self, trade: Dict):
        if not self.config.get('notifications_enabled', True): return
        chat_id = self.config.get('chat_id')
        if not chat_id: return
        
        text = (
            f"📝 *Trade Executed*\n\n"
            f"{trade.get('symbol')} {trade.get('side')}\n"
            f"Size: `{trade.get('size')}` @ `${trade.get('price', 0):,.2f}`\n\n"
            f"⏰ `{fmt_ist()}`"
        )
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
        except:
            pass

    async def send_opportunity_alert(self, opportunity: Dict):
        chat_id = self.config.get('chat_id')
        if not chat_id: return
        
        text = (
            f"🔍 *Signal*\n\n"
            f"{opportunity.get('symbol')} `{opportunity.get('signal')}`\n"
            f"Confidence: `{opportunity.get('confidence', 0):.0%}`\n\n"
            f"⏰ `{fmt_ist()}`"
        )
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
        except:
            pass

    async def send_closure_notification(self, market_id: str, winner: str, pnl: float, details: Dict = None):
        chat_id = self.config.get('chat_id')
        if not chat_id: return
        
        emoji = "✅" if pnl >= 0 else "❌"
        text = (
            f"{emoji} *Market Closed*\n\n"
            f"ID: `{market_id[:15]}...`\n"
            f"Result: {winner}\n"
            f"PnL: `${pnl:+,.2f}`\n\n"
            f"⏰ `{fmt_ist()}`"
        )
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
        except:
            pass
