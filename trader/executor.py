"""Live trading executor."""
import time
from typing import Dict

from api.clob_client import CLOBClient
from state.store import StateStore
from strategy.decision import TradeDecision
from strategy.position import Position, OpenOrder
from telegram_bot.notifier import TelegramNotifier
from utils.logger import get_logger

logger = get_logger(__name__)


class Executor:
    """Executor for live trading."""
    
    def __init__(
        self,
        clob: CLOBClient,
        store: StateStore,
        notifier: TelegramNotifier
    ):
        self.clob = clob
        self.store = store
        self.notifier = notifier
    
    def execute(
        self,
        market: Dict,
        decision: TradeDecision,
        position: Position
    ) -> bool:
        """
        Execute a live trade decision.
        
        Args:
            market: Market dictionary
            decision: Trade decision
            position: Current position
            
        Returns:
            True if executed successfully
        """
        if decision.action == "HOLD":
            return True
        
        # Check if trading should proceed
        if not self.store.should_trade():
            logger.warning("Trading halted or panic mode - skipping execution")
            return False
        
        market_id = market.get("market_id")
        token_id = market.get("up_token_id") if decision.action == "BUY_UP" else market.get("down_token_id")
        side = "BUY"
        
        try:
            # Log the trade signal
            self.notifier.send_log(
                f"📡 Trade signal: {decision.action} {decision.shares} @ {decision.price:.4f} "
                f"(rule: {decision.rule}, reason: {decision.reason[:50]}...)",
                "INFO"
            )
            
            # Place order with retries
            result = self._place_order_with_retry(
                token_id=token_id,
                side=side,
                size=decision.shares,
                price=decision.price
            )
            
            if not result:
                logger.error("Order placement failed after retries")
                return False
            
            order_id = result.get("orderID", "")
            status = result.get("status", "")
            
            # Update position
            if decision.action == "BUY_UP":
                position.apply_buy_up(decision.shares, decision.price, order_id)
            else:
                position.apply_buy_down(decision.shares, decision.price, order_id)
            
            # Add to open orders if not immediately matched
            if status != "MATCHED":
                open_order = OpenOrder(
                    order_id=order_id,
                    side=decision.action,
                    shares=decision.shares,
                    price=decision.price,
                    placed_at=time.time()
                )
                position.add_open_order(open_order)
            
            # Update store stats
            self.store.increment_trade_count()
            self.store.add_usdc_spent(decision.shares * decision.price)
            
            # Send trade notification
            trade_data = {
                "market_id": market_id,
                "question": market.get("question", ""),
                "side": decision.action,
                "shares": decision.shares,
                "price": decision.price,
                "cost": decision.shares * decision.price,
                "order_id": order_id,
                "status": status,
                "rule": decision.rule,
                "pnl_if_up": position.pnl_if_up_wins(),
                "pnl_if_down": position.pnl_if_down_wins()
            }
            self.notifier.send_trade(trade_data)
            
            logger.info(f"Live trade executed: {decision.action} {decision.shares} @ {decision.price}")
            return True
            
        except Exception as e:
            logger.error(f"Live trade execution failed: {e}")
            self.notifier.send_error(f"Trade execution failed for {market_id}", str(e))
            return False
    
    def _place_order_with_retry(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        max_retries: int = 3
    ) -> Dict:
        """
        Place an order with retry logic.
        
        Args:
            token_id: Token ID
            side: BUY or SELL
            size: Number of shares
            price: Price per share
            max_retries: Maximum retry attempts
            
        Returns:
            Order response dictionary
        """
        for attempt in range(max_retries):
            try:
                result = self.clob.place_order(
                    token_id=token_id,
                    side=side,
                    size=size,
                    price=price
                )
                return result
            except Exception as e:
                error_str = str(e)
                
                # Check for rate limit
                if "429" in error_str:
                    if attempt < max_retries - 1:
                        logger.warning(f"Rate limited, retrying in 2s... (attempt {attempt + 1})")
                        time.sleep(2)
                        continue
                
                # Check for server error
                if any(code in error_str for code in ["500", "502", "503", "504"]):
                    if attempt < max_retries - 1:
                        logger.warning(f"Server error, retrying in 1s... (attempt {attempt + 1})")
                        time.sleep(1)
                        continue
                
                raise
        
        return {}
    
    def cancel_all_open_orders(self) -> int:
        """
        Cancel all open orders.
        
        Returns:
            Number of orders cancelled
        """
        cancelled_count = 0
        
        try:
            # Try bulk cancel first
            result = self.clob.cancel_all_orders()
            cancelled_count = result.get("cancelled", 0)
            
            # Also clear from positions
            for market_id in self.store.list_active_markets():
                position = self.store.get_position(market_id)
                if position:
                    for order_id in position.get_all_order_ids():
                        if self.clob.cancel_order(order_id):
                            cancelled_count += 1
                        position.remove_open_order(order_id)
            
            logger.info(f"Cancelled {cancelled_count} orders")
            return cancelled_count
            
        except Exception as e:
            logger.error(f"Error canceling orders: {e}")
            return cancelled_count
