"""Market closure checker for settling positions."""
import time
from typing import Optional

from api.clob_client import CLOBClient
from config import DAILY_LOSS_LIMIT_USD
from state.store import StateStore
from paper_trading.paper_store import PaperStateStore
from paper_trading.paper_db import PaperDB
from telegram_bot.notifier import TelegramNotifier
from utils.logger import get_logger

logger = get_logger(__name__)


class ClosureChecker:
    """Checks for market closures and settles positions."""
    
    def __init__(
        self,
        clob: CLOBClient,
        live_store: StateStore,
        paper_store: Optional[PaperStateStore],
        paper_db: PaperDB,
        notifier: TelegramNotifier,
        live: bool = True,
        paper: bool = True
    ):
        self.clob = clob
        self.live_store = live_store
        self.paper_store = paper_store
        self.paper_db = paper_db
        self.notifier = notifier
        self.live = live
        self.paper = paper
    
    def check_and_record(self, market_id: str):
        """
        Check if a market has closed and settle positions.
        
        Args:
            market_id: Market ID to check
        """
        try:
            # Get market from CLOB
            market = self.clob.get_market(market_id)
            
            if not market:
                logger.warning(f"Market {market_id} not found")
                return
            
            # Check if market is closed
            is_closed = market.get("closed", False) or market.get("archived", False)
            winner = market.get("winner", "")
            
            if not is_closed and not winner:
                return
            
            logger.info(f"Market {market_id} closed. Winner: {winner}")
            
            # Settle live position
            if self.live:
                self._settle_live_position(market_id, market, winner)
            
            # Settle paper position
            if self.paper and self.paper_store:
                self._settle_paper_position(market_id, market, winner)
                
        except Exception as e:
            logger.error(f"Error checking market closure for {market_id}: {e}")
    
    def _settle_live_position(self, market_id: str, market: Dict, winner: str):
        """Settle a live trading position."""
        position = self.live_store.get_position(market_id)
        if not position or not position.has_any_position():
            return
        
        # Calculate PnL
        if winner.upper() == "UP" or winner == "0" or winner == "Yes":
            pnl = position.pnl_if_up_wins()
        elif winner.upper() == "DOWN" or winner == "1" or winner == "No":
            pnl = position.pnl_if_down_wins()
        else:
            logger.warning(f"Unknown winner format: {winner}")
            pnl = 0
        
        # Update stats
        self.live_store.add_realized_pnl(pnl)
        
        # Send notification
        self.notifier.send_market_closed(
            market_id=market_id,
            question=market.get("question", position.question),
            winner=winner,
            pnl=pnl,
            up_shares=position.up_shares,
            down_shares=position.down_shares,
            total_cost=position.total_cost
        )
        
        # Check daily loss limit
        daily_pnl = self.live_store.get_daily_realized_pnl()
        if daily_pnl < -DAILY_LOSS_LIMIT_USD:
            self.live_store.set_trading_halted(True)
            self.notifier.send_loss_limit_alert(daily_pnl, DAILY_LOSS_LIMIT_USD)
        
        # Remove position
        self.live_store.remove_position(market_id)
        self.live_store.remove_market_meta(market_id)
        self.live_store.clear_price_history(market_id)
        
        logger.info(f"Live position settled: {market_id}, PnL: ${pnl:.4f}")
    
    def _settle_paper_position(self, market_id: str, market: Dict, winner: str):
        """Settle a paper trading position."""
        if not self.paper_store:
            return
        
        position = self.paper_store.get_position(market_id)
        if not position or not position.has_any_position():
            return
        
        # Calculate PnL
        if winner.upper() == "UP" or winner == "0" or winner == "Yes":
            pnl = position.pnl_if_up_wins()
        elif winner.upper() == "DOWN" or winner == "1" or winner == "No":
            pnl = position.pnl_if_down_wins()
        else:
            logger.warning(f"Unknown winner format: {winner}")
            pnl = 0
        
        # Create result record
        result = {
            "market_id": market_id,
            "question": market.get("question", position.question),
            "winner": winner,
            "up_shares": position.up_shares,
            "down_shares": position.down_shares,
            "total_cost": position.total_cost,
            "pnl": pnl,
            "trade_count": len(position.trades),
            "trades": position.trades
        }
        
        # Record in store
        self.paper_store.record_closed_market(result)
        
        # Save to database
        session_id = self.paper_db.get_current_session_id()
        if session_id:
            self.paper_db.save_market_result(
                session_id=session_id,
                market_id=market_id,
                question=market.get("question", position.question),
                winner=winner,
                up_shares=position.up_shares,
                down_shares=position.down_shares,
                total_cost=position.total_cost,
                pnl=pnl,
                trade_count=len(position.trades)
            )
        
        # Send notification
        self.notifier.send_paper_market_closed(
            market_id=market_id,
            question=market.get("question", position.question),
            winner=winner,
            pnl=pnl,
            up_shares=position.up_shares,
            down_shares=position.down_shares,
            total_cost=position.total_cost
        )
        
        # Remove position
        self.paper_store.remove_position(market_id)
        self.paper_store.remove_market_meta(market_id)
        self.paper_store.clear_price_history(market_id)
        
        logger.info(f"Paper position settled: {market_id}, PnL: ${pnl:.4f}")
