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
        self.get_uptime = kwargs.get('get_uptime', lambda: "Unknown")
        
        # Security
        self.authorized_user_id = str(config.get('authorized_user_id', ''))
        self.logs_channel_id = config.get('logs_channel_id', '')
        
        self.app = None
        self.running = False
        self._loop = None
        self._thread = None
        
        # Track unauthorized attempts
        self.blocked_users = set()

    def _check_authorization(self, update: Update) -> bool:
        """
        Check if user is authorized to use the bot.
        Returns True if authorized, False if not.
        Sends alert to logs channel if unauthorized.
        """
        if not self.authorized_user_id:
            logger.warning("No authorized_user_id set in config!")
            return True  # Allow all if not configured (for safety)
        
        user = update.effective_user
        user_id = str(user.id) if user else None
        
        if not user_id:
            return False
        
        # Check if authorized
        if user_id == str(self.authorized_user_id):
            return True
        
        # UNAUTHORIZED - Send alert
        username = user.username or "No username"
        first_name = user.first_name or "Unknown"
        last_name = user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        
        # Prevent spam - only alert once per user
        if user_id not in self.blocked_users:
            self.blocked_users.add(user_id)
            
            alert_message = (
                f"🚨 **UNAUTHORIZED ACCESS ATTEMPT**\n\n"
                f"👤 **User Details:**\n"
                f"• ID: `{user_id}`\n"
                f"• Username: @{username}\n"
                f"• Name: {full_name}\n"
                f"• Time: `{fmt_ist()}`\n\n"
                f"⚠️ **Action:** User attempted to use your private bot!\n"
                f"🛡️ **Status:** Access Denied"
            )
            
            # Send to logs channel
            if self.logs_channel_id and self._loop:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._send_alert_to_logs(alert_message),
                        self._loop
                    )
                except Exception as e:
                    logger.error(f"Failed to send security alert: {e}")
            
            # Log locally
            logger.warning(f"🔒 BLOCKED: {full_name} (@{username}, ID: {user_id}) tried to access bot")
        
        return False

    async def _send_alert_to_logs(self, message: str):
        """Send alert to logs channel"""
        if not self.logs_channel_id or not self.app:
            return
        
        try:
            await self.app.bot.send_message(
                chat_id=self.logs_channel_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send to logs channel: {e}")

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

    async def _unauthorized_response(self, update: Update):
        """Send denial message to unauthorized user"""
        text = (
            f"⛔ **ACCESS DENIED**\n\n"
            f"This is a private bot.\n"
            f"You are not authorized to use this bot.\n\n"
            f"🕐 {fmt_ist()}"
        )
        
        try:
            await update.message.reply_text(text, parse_mode='Markdown')
        except:
            pass

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
            CommandHandler("ping", self.cmd_ping),
        ]
        
        for h in handlers:
            self.app.add_handler(h)
        
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))
        logger.info("✅ Handlers registered with security")

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command with authorization check"""
        if not self._check_authorization(update):
            await self._unauthorized_response(update)
            return
        
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
        """Main menu with authorization check"""
        if not self._check_authorization(update):
            if not edit:  # Only send denial on new command, not on callback
                await self._unauthorized_response(update)
            return
        
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
            f"📘 Paper Balance: `{paper_bal}`\n"
            f"💰 Live Balance: `{live_bal}`\n"
            f"⏰ `{fmt_ist()}`\n\n"
            f"Select option:"
        )
        
        keyboard = [
            [InlineKeyboardButton("💰 Balance", callback_data="nav_balance"),
             InlineKeyboardButton("📊 Markets", callback_data="nav_markets")],
            [InlineKeyboardButton("📜 History", callback_data="nav_history"),
             InlineKeyboardButton("📈 P&L", callback_data="nav_pnl")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="nav_settings"),
             InlineKeyboardButton("🏓 Ping", callback_data="nav_ping")],
        ]
        
        await self._send_or_edit(update, text, InlineKeyboardMarkup(keyboard), edit)

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        if not self._check_authorization(update):
            return
        
        lines = ["*💰 Account Balances*\n"]
        
        if self.paper_executor:
            try:
                pf = self.paper_executor.get_portfolio_value()
                lines.append(
                    f"*📘 Paper Account*\n"
                    f"Cash: `${pf['cash_balance']:,.2f}`\n"
                    f"Positions: `${pf['positions_value']:,.2f}`\n"
                    f"Total: `{pf['total_value']:,.2f}`\n"
                    f"PnL: `{pf['total_return']:+,.2f}`\n"
                )
            except:
                lines.append("*📘 Paper Account*\n⚠️ Error\n")
        else:
            lines.append("*📘 Paper Account*\n_Status: Offline_\n")
        
        if self.live_executor:
            try:
                pf = self.live_executor.get_portfolio_value()
                lines.append(
                    f"\n*💰 Live Account*\n"
                    f"USDC: `{pf.get('cash_balance', 0):,.2f}`\n"
                    f"Wallet: `{str(pf.get('wallet', 'N/A'))[:10]}...`\n"
                )
            except:
                lines.append(f"\n*💰 Live Account*\n⚠️ Error\n")
        else:
            lines.append(f"\n*💰 Live Account*\n_Status: Offline_")
        
        lines.append(f"\n⏰ `{fmt_ist()}`")
        
        keyboard = InlineKeyboardMarkup([self._nav_row("balance")])
        await self._send_or_edit(update, "\n".join(lines), keyboard, edit)

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._check_authorization(update):
            return
        
        lines = ["*📊 Open Positions*\n"]
        
        if not self.paper_executor and not self.live_executor:
            lines.append("❌ Trading systems offline")
            lines.append(f"\n⏰ `{fmt_ist()}`")
            keyboard = InlineKeyboardMarkup([[self._back_btn()]])
            await self._send_or_edit(update, "\n".join(lines), keyboard)
            return
        
        if self.paper_executor:
            try:
                positions = getattr(self.paper_executor, 'positions', {})
                if positions:
                    lines.append("*Paper Positions:*")
                    for sym, pos in positions.items():
                        lines.append(f"• {sym}: `{pos.get('quantity', 0)}` @ `${pos.get('avg_entry_price', 0):,.2f}`")
                else:
                    lines.append("*Paper:* No open positions")
            except:
                lines.append("*Paper:* ⚠️ Error")
        
        lines.append(f"\n⏰ `{fmt_ist()}`")
        keyboard = InlineKeyboardMarkup([[self._back_btn()]])
        await self._send_or_edit(update, "\n".join(lines), keyboard)

    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        if not self._check_authorization(update):
            return
        
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
        if not self._check_authorization(update):
            return
        
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
        if not self._check_authorization(update):
            return
        
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
        if not self._check_authorization(update):
            return
        
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

    async def cmd_ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ping command with authorization check"""
        if not self._check_authorization(update):
            return
        
        start = time.time()
        uptime = self.get_uptime()
        response_time = (time.time() - start) * 1000
        
        status_emoji = "🟢" if self.running else "🔴"
        
        paper_status = "🟢 Online" if self.paper_executor else "🔴 Offline"
        live_status = "🟢 Online" if self.live_executor else "🔴 Offline"
        
        text = (
            f"🏓 *Pong!* {status_emoji}\n\n"
            f"⚡ Response: `{response_time:.1f}ms`\n"
            f"⏱ Uptime: `{uptime}`\n"
            f"🕐 Time: `{fmt_ist()}`\n\n"
            f"*Systems:*\n"
            f"📘 Paper: {paper_status}\n"
            f"💰 Live: {live_status}\n\n"
            f"_All operational ✅_"
        )
        
        keyboard = InlineKeyboardMarkup([[self._back_btn()]])
        await self._send_or_edit(update, text, keyboard)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
        if not self._check_authorization(update):
            return
        
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
            f"/ping - Bot status\n\n"
            f"⏰ IST (UTC+5:30)\n"
            f"`{fmt_ist()}`"
        )
        keyboard = InlineKeyboardMarkup([[self._back_btn()]])
        await self._send_or_edit(update, text, keyboard, edit)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callbacks with authorization check"""
        query = update.callback_query
        
        # Check authorization for callbacks too
        if not self._check_authorization(update):
            await query.answer("⛔ Access Denied", show_alert=True)
            return
        
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
                elif page == "ping": await self.cmd_ping(update, context)
                    
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
