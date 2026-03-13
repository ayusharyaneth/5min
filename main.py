"""Main entry point for Polymarket Trading Bot."""
import sys
import threading
import time
from typing import Optional

from config import (
    LIVE_TRADING, PAPER_TRADING,
    POLYMARKET_PRIVATE_KEY, POLYMARKET_WALLET_ADDRESS,
    POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_API_PASSPHRASE,
    TELEGRAM_BOT_TOKEN, TELEGRAM_LOGS_CHANNEL_ID, TELEGRAM_TRADES_CHANNEL_ID,
    TELEGRAM_ALLOWED_USER_ID,
    PAPER_STARTING_BALANCE, PAPER_DB_PATH,
    BASE_SIZE, MAX_BUYS_PER_TICK, COOLDOWN_SECS,
    TREND_WINDOW, MARKET_POLL_INTERVAL, CLOSURE_CHECK_INTERVAL
)
from utils.logger import get_logger
from state.store import StateStore
from strategy.decision import make_decision
from strategy.position import Position
from api.auth import PolyAuth
from api.clob_client import CLOBClient
from paper_trading.paper_db import PaperDB
from paper_trading.paper_store import PaperStateStore
from paper_trading.paper_clob import PaperCLOBClient
from paper_trading.paper_executor import PaperExecutor
from monitor.market_finder import MarketFinder
from monitor.closure_checker import ClosureChecker
from trader.executor import Executor
from telegram_bot.notifier import TelegramNotifier
from telegram_bot.dashboard import Dashboard
from telegram_bot.bot import TelegramBotRunner

logger = get_logger(__name__)


class PolymarketBot:
    """Main bot orchestrator."""
    
    def __init__(self):
        self.stop_event = threading.Event()
        
        # Components (initialized in start())
        self.live_store: Optional[StateStore] = None
        self.paper_store: Optional[PaperStateStore] = None
        self.notifier: Optional[TelegramNotifier] = None
        self.paper_db: Optional[PaperDB] = None
        self.auth: Optional[PolyAuth] = None
        self.real_clob: Optional[CLOBClient] = None
        self.paper_clob: Optional[PaperCLOBClient] = None
        self.live_exec: Optional[Executor] = None
        self.paper_exec: Optional[PaperExecutor] = None
        self.market_finder: Optional[MarketFinder] = None
        self.closure_checker: Optional[ClosureChecker] = None
        self.telegram_bot: Optional[TelegramBotRunner] = None
    
    def _validate_config(self):
        """Validate configuration before starting."""
        if not LIVE_TRADING and not PAPER_TRADING:
            logger.error("Both LIVE_TRADING and PAPER_TRADING are disabled. Exiting.")
            sys.exit(1)
        
        if LIVE_TRADING:
            if not all([
                POLYMARKET_PRIVATE_KEY,
                POLYMARKET_WALLET_ADDRESS,
                POLYMARKET_API_KEY,
                POLYMARKET_API_SECRET,
                POLYMARKET_API_PASSPHRASE
            ]):
                logger.error("Live trading enabled but wallet/API credentials missing. Exiting.")
                sys.exit(1)
        
        logger.info(f"Mode: {'LIVE' if LIVE_TRADING else ''}{'+' if LIVE_TRADING and PAPER_TRADING else ''}{'PAPER' if PAPER_TRADING else ''}")
    
    def _init_components(self):
        """Initialize all bot components."""
        logger.info("Initializing components...")
        
        # State stores
        self.live_store = StateStore(trend_window=TREND_WINDOW)
        
        if PAPER_TRADING:
            self.paper_store = PaperStateStore(
                trend_window=TREND_WINDOW,
                starting_balance=PAPER_STARTING_BALANCE
            )
            self.paper_db = PaperDB(db_path=PAPER_DB_PATH)
            self.paper_db.start_session(PAPER_STARTING_BALANCE)
        
        # Telegram notifier
        self.notifier = TelegramNotifier(
            token=TELEGRAM_BOT_TOKEN,
            logs_channel_id=TELEGRAM_LOGS_CHANNEL_ID,
            trades_channel_id=TELEGRAM_TRADES_CHANNEL_ID
        )
        
        # Initialize live trading components
        if LIVE_TRADING:
            self.auth = PolyAuth(
                private_key=POLYMARKET_PRIVATE_KEY,
                api_key=POLYMARKET_API_KEY,
                api_secret=POLYMARKET_API_SECRET,
                passphrase=POLYMARKET_API_PASSPHRASE,
                wallet_address=POLYMARKET_WALLET_ADDRESS
            )
            self.real_clob = CLOBClient(auth=self.auth)
            self.live_exec = Executor(
                clob=self.real_clob,
                store=self.live_store,
                notifier=self.notifier
            )
        
        # Initialize paper trading components
        if PAPER_TRADING:
            # Paper CLOB uses real CLOB for prices if live, or creates its own
            if LIVE_TRADING:
                self.paper_clob = PaperCLOBClient(
                    real_clob=self.real_clob,
                    paper_store=self.paper_store
                )
            else:
                # Paper-only mode still needs price feed
                auth = PolyAuth(
                    private_key="",
                    api_key=POLYMARKET_API_KEY,
                    api_secret=POLYMARKET_API_SECRET,
                    passphrase=POLYMARKET_API_PASSPHRASE,
                    wallet_address=""
                )
                real_clob = CLOBClient(auth=auth)
                self.paper_clob = PaperCLOBClient(
                    real_clob=real_clob,
                    paper_store=self.paper_store
                )
            
            self.paper_exec = PaperExecutor(
                paper_clob=self.paper_clob,
                paper_store=self.paper_store,
                paper_db=self.paper_db,
                notifier=self.notifier
            )
        
        # Market finder
        self.market_finder = MarketFinder(
            clob=self.real_clob if LIVE_TRADING else self.paper_clob.real_clob,
            live_store=self.live_store,
            paper_store=self.paper_store,
            notifier=self.notifier,
            live=LIVE_TRADING,
            paper=PAPER_TRADING
        )
        
        # Closure checker
        self.closure_checker = ClosureChecker(
            clob=self.real_clob if LIVE_TRADING else self.paper_clob.real_clob,
            live_store=self.live_store,
            paper_store=self.paper_store,
            paper_db=self.paper_db,
            notifier=self.notifier,
            live=LIVE_TRADING,
            paper=PAPER_TRADING
        )
        
        # Telegram bot
        dashboard = Dashboard(
            live_store=self.live_store,
            paper_store=self.paper_store,
            clob=self.real_clob,
            paper_clob=self.paper_clob,
            live_exec=self.live_exec,
            paper_exec=self.paper_exec,
            paper_db=self.paper_db,
            notifier=self.notifier,
            stop_event=self.stop_event,
            allowed_user_id=TELEGRAM_ALLOWED_USER_ID,
            paper_starting_balance=PAPER_STARTING_BALANCE
        )
        
        self.telegram_bot = TelegramBotRunner(
            token=TELEGRAM_BOT_TOKEN,
            dashboard=dashboard
        )
        
        logger.info("Components initialized successfully")
    
    def _send_startup_log(self):
        """Send startup notification."""
        mode = ""
        if LIVE_TRADING and PAPER_TRADING:
            mode = "LIVE + PAPER"
        elif LIVE_TRADING:
            mode = "LIVE ONLY"
        else:
            mode = "PAPER ONLY"
        
        wallet_prefix = POLYMARKET_WALLET_ADDRESS[:10] + "..." if POLYMARKET_WALLET_ADDRESS else "N/A"
        
        message = (
            f"🚀 <b>Bot Started</b>\n"
            f"Mode: <code>{mode}</code>\n"
            f"Wallet: <code>{wallet_prefix}</code>\n"
            f"Paper Balance: <code>${PAPER_STARTING_BALANCE:.2f}</code>\n"
            f"Base Size: <code>{BASE_SIZE}</code>\n"
            f"Cooldown: <code>{COOLDOWN_SECS}s</code>\n"
            f"Trend Window: <code>{TREND_WINDOW}</code>"
        )
        
        self.notifier.send_log(message, "INFO")
    
    def _start_background_threads(self):
        """Start background daemon threads."""
        # Market discovery thread
        def market_discovery_loop():
            while not self.stop_event.is_set():
                try:
                    self.market_finder.find_active_btc_5m_markets()
                except Exception as e:
                    logger.error(f"Market discovery error: {e}")
                time.sleep(MARKET_POLL_INTERVAL)
        
        discovery_thread = threading.Thread(target=market_discovery_loop, daemon=True)
        discovery_thread.start()
        logger.info("Market discovery thread started")
        
        # Closure check thread
        def closure_check_loop():
            while not self.stop_event.is_set():
                try:
                    for market_id in self.live_store.list_active_markets():
                        self.closure_checker.check_and_record(market_id)
                except Exception as e:
                    logger.error(f"Closure check error: {e}")
                time.sleep(CLOSURE_CHECK_INTERVAL)
        
        closure_thread = threading.Thread(target=closure_check_loop, daemon=True)
        closure_thread.start()
        logger.info("Closure check thread started")
    
    def _run_main_loop(self):
        """Run the main trading loop."""
        logger.info("Starting main trading loop...")
        
        while not self.stop_event.is_set():
            try:
                for market_id in self.live_store.list_active_markets():
                    try:
                        # Get market metadata
                        market = self.live_store.get_market_meta(market_id)
                        if not market:
                            continue
                        
                        up_token_id = market.get("up_token_id")
                        down_token_id = market.get("down_token_id")
                        
                        if not up_token_id or not down_token_id:
                            continue
                        
                        # Get prices from real CLOB
                        up_ask = self.real_clob.get_best_ask(up_token_id) if LIVE_TRADING else self.paper_clob.get_best_ask(up_token_id)
                        dn_ask = self.real_clob.get_best_ask(down_token_id) if LIVE_TRADING else self.paper_clob.get_best_ask(down_token_id)
                        
                        # Append prices to both stores
                        self.live_store.append_price(market_id, "up", up_ask)
                        self.live_store.append_price(market_id, "down", dn_ask)
                        
                        if PAPER_TRADING:
                            self.paper_store.append_price(market_id, "up", up_ask)
                            self.paper_store.append_price(market_id, "down", dn_ask)
                        
                        # Get price history
                        up_hist = self.live_store.get_price_history(market_id, "up")
                        dn_hist = self.live_store.get_price_history(market_id, "down")
                        
                        # Get time remaining
                        time_rem = MarketFinder.get_time_remaining(market)
                        if time_rem <= 0:
                            continue
                        
                        # === LIVE TRADING BLOCK ===
                        if LIVE_TRADING:
                            live_pos = self.live_store.get_position(market_id)
                            if not live_pos:
                                live_pos = Position(market_id=market_id, question=market.get("question", ""))
                                self.live_store.set_position(market_id, live_pos)
                            
                            # Execute up to MAX_BUYS_PER_TICK
                            for _ in range(MAX_BUYS_PER_TICK):
                                if not self.live_store.should_trade():
                                    break
                                
                                # Re-evaluate decision after each trade
                                up_hist_live = self.live_store.get_price_history(market_id, "up")
                                dn_hist_live = self.live_store.get_price_history(market_id, "down")
                                
                                decision = make_decision(
                                    pos=live_pos,
                                    up_ask=up_ask,
                                    dn_ask=dn_ask,
                                    up_hist=up_hist_live,
                                    dn_hist=dn_hist_live,
                                    time_rem=time_rem,
                                    base_size=BASE_SIZE
                                )
                                
                                if decision.action == "HOLD":
                                    break
                                
                                success = self.live_exec.execute(market, decision, live_pos)
                                if not success:
                                    break
                        
                        # === PAPER TRADING BLOCK ===
                        if PAPER_TRADING:
                            paper_pos = self.paper_store.get_position(market_id)
                            if not paper_pos:
                                paper_pos = Position(market_id=market_id, question=market.get("question", ""))
                                self.paper_store.set_position(market_id, paper_pos)
                            
                            # Execute up to MAX_BUYS_PER_TICK
                            for _ in range(MAX_BUYS_PER_TICK):
                                # Re-evaluate decision after each trade
                                up_hist_paper = self.paper_store.get_price_history(market_id, "up")
                                dn_hist_paper = self.paper_store.get_price_history(market_id, "down")
                                
                                decision = make_decision(
                                    pos=paper_pos,
                                    up_ask=up_ask,
                                    dn_ask=dn_ask,
                                    up_hist=up_hist_paper,
                                    dn_hist=dn_hist_paper,
                                    time_rem=time_rem,
                                    base_size=BASE_SIZE
                                )
                                
                                if decision.action == "HOLD":
                                    break
                                
                                success = self.paper_exec.execute(market, decision, paper_pos)
                                if not success:
                                    break
                    
                    except Exception as e:
                        logger.error(f"Error processing market {market_id}: {e}")
                        self.notifier.send_error(f"Market processing error: {market_id}", str(e))
                
                # Sleep between ticks
                time.sleep(max(COOLDOWN_SECS, 1))
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(5)
    
    def _shutdown(self):
        """Perform graceful shutdown."""
        logger.info("Shutting down...")
        
        # End paper session
        if PAPER_TRADING and self.paper_store and self.paper_db:
            try:
                stats = self.paper_store.get_paper_stats()
                self.paper_db.end_session(
                    ending_balance=self.paper_store.get_virtual_balance(),
                    pnl=stats.get("realized_pnl", 0),
                    count=stats.get("trade_count", 0),
                    notes="Bot shutdown"
                )
                self.notifier.send_log("🛑 Bot stopped. Paper session archived.", "INFO")
            except Exception as e:
                logger.error(f"Error ending paper session: {e}")
        
        logger.info("Shutdown complete")
    
    def start(self):
        """Start the bot."""
        try:
            # Validate and initialize
            self._validate_config()
            self._init_components()
            self._send_startup_log()
            
            # Start Telegram bot
            self.telegram_bot.start()
            
            # Start background threads
            self._start_background_threads()
            
            # Run main loop
            self._run_main_loop()
            
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            self._shutdown()


def main():
    """Main entry point."""
    bot = PolymarketBot()
    bot.start()


if __name__ == "__main__":
    main()
