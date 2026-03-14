"""
Live Executor - Polymarket Real Money Trading
"""

import logging
from typing import Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger('LiveExecutor')

class LiveExecutor:
    def __init__(self, 
                 polymarket_client,
                 config: Optional[Dict] = None,
                 notifier=None):
        """
        Execute live trades on Polymarket with real money
        """
        self.client = polymarket_client
        self.config = config or {}
        self.notifier = notifier
        
        # Risk management
        self.max_trade_size = config.get('live_max_size', 50)
        self.default_size = config.get('live_trade_size', 5)
        self.daily_pnl = 0.0
        self.trade_history = []
        
        logger.info("💰 LiveExecutor initialized")
        logger.warning("⚠️  REAL MONEY - All trades use actual USDC!")

    def execute_trade(self, 
                     market_id: str, 
                     side: str, 
                     size: float,
                     price: Optional[float] = None,
                     metadata: Optional[Dict] = None) -> Dict:
        """
        Execute a live trade on Polymarket
        
        Args:
            market_id: Polymarket condition ID
            side: 'BUY' or 'SELL'
            size: Amount in USDC
            price: Limit price (optional)
            metadata: Additional trade info
            
        Returns:
            Trade result dict
        """
        # Safety checks
        if size > self.max_trade_size:
            logger.error(f"❌ Trade size {size} exceeds max {self.max_trade_size}")
            return {'success': False, 'error': 'Size limit exceeded'}
        
        try:
            logger.info(f"🚨 EXECUTING LIVE TRADE: {side} {size} USDC on {market_id}")
            
            # Execute via Polymarket client
            if hasattr(self.client, 'place_order'):
                result = self.client.place_order(
                    market_id=market_id,
                    side=side,
                    size=size,
                    price=price
                )
                
                if result.get('status') == 'filled':
                    # Record trade
                    trade_record = {
                        'timestamp': datetime.now().isoformat(),
                        'market_id': market_id,
                        'symbol': metadata.get('symbol', market_id) if metadata else market_id,
                        'side': side,
                        'size': size,
                        'price': result.get('filled_price', price),
                        'order_id': result.get('order_id'),
                        'tx_hash': result.get('tx_hash'),
                        'is_live': True
                    }
                    self.trade_history.append(trade_record)
                    
                    # Notify
                    if self.notifier:
                        self.notifier.send_trade_notification(trade_record)
                    
                    logger.info(f"✅ LIVE TRADE FILLED: {result.get('order_id')}")
                    return {'success': True, 'trade': trade_record}
                else:
                    error = result.get('error', 'Unknown error')
                    logger.error(f"❌ LIVE TRADE FAILED: {error}")
                    return {'success': False, 'error': error}
            else:
                return {'success': False, 'error': 'Client missing place_order method'}
                
        except Exception as e:
            logger.error(f"💥 LIVE TRADE EXCEPTION: {e}")
            return {'success': False, 'error': str(e)}

    def get_portfolio_value(self) -> Dict:
        """Get current portfolio status"""
        try:
            if hasattr(self.client, 'get_balance'):
                balance = self.client.get_balance()
                return {
                    'cash_balance': balance.get('usdc', 0),
                    'wallet': getattr(self.client, 'wallet_address', 'Unknown'),
                    'total_trades': len(self.trade_history)
                }
            return {'cash_balance': 0, 'wallet': 'Unknown', 'total_trades': 0}
        except:
            return {'cash_balance': 0, 'wallet': 'Error', 'total_trades': 0}

    def get_trade_history(self, limit: int = 50) -> list:
        """Get recent trade history"""
        return self.trade_history[-limit:]

    def stop(self):
        """Graceful shutdown"""
        logger.info("💰 LiveExecutor stopped")
