"""
Polymarket Live Trading Client
Uses private key for direct blockchain interaction
Requires: pip install py-polymarket web3
"""
import logging
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
import json

logger = logging.getLogger('Polymarket')

class PolymarketClient:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.private_key = config.get('polymarket_private_key') or os.getenv('POLYMARKET_PK')
        self.api_key = config.get('polymarket_api_key')
        self.api_secret = config.get('polymarket_secret')
        self.wallet_address = config.get('polymarket_wallet_address')
        
        self.base_url = "https://clob.polymarket.com"
        self.connected = False
        self.client = None
        
        if self.private_key:
            self._init_client()
        else:
            logger.error("No private key provided for Polymarket")
    
    def _init_client(self):
        """Initialize Polymarket client"""
        try:
            # Try importing polymarket libraries
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            
            # Initialize client
            host = self.base_url
            key = self.private_key
            creds = None
            
            if self.api_key and self.api_secret:
                creds = ApiCreds(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    passphrase="default"  # Adjust as needed
                )
            
            self.client = ClobClient(host, key=key, creds=creds)
            self.wallet_address = self.client.get_address()
            self.connected = True
            
            logger.info(f"Polymarket connected | Wallet: {self.wallet_address[:10]}...")
            
            # Verify balance
            balance = self.get_balance()
            logger.info(f"Balance: {balance.get('usdc', 0)} USDC")
            
        except ImportError:
            logger.error("Polymarket SDK not installed. Run: pip install py-polymarket")
        except Exception as e:
            logger.error(f"Polymarket init failed: {e}")
    
    def get_balance(self) -> Dict:
        """Get USDC and token balances"""
        if not self.client:
            return {'usdc': 0, 'positions': []}
        
        try:
            # Get USDC balance (ERC20 on Polygon)
            balance = self.client.get_balance()
            return {
                'usdc': float(balance) / 1e6,  # Convert from wei-like
                'wallet': self.wallet_address
            }
        except Exception as e:
            logger.error(f"Balance check failed: {e}")
            return {'usdc': 0, 'wallet': self.wallet_address}
    
    def get_active_markets(self) -> List[Dict]:
        """Fetch active Polymarket markets"""
        if not self.client:
            return []
        
        try:
            markets = self.client.get_markets()
            # Filter for 5-minute or active markets
            active = []
            for m in markets.get('data', []):
                if m.get('active', False) and '5m' in m.get('slug', '').lower():
                    active.append({
                        'market_id': m['condition_id'],
                        'symbol': m['slug'],
                        'question': m['question'],
                        'base_asset': 'USDC',
                        'outcomes': m.get('outcomes', ['Yes', 'No']),
                        'status': 'active',
                        'is_live': True
                    })
            return active
        except Exception as e:
            logger.error(f"Failed to fetch Polymarket markets: {e}")
            return []
    
    def place_order(self, market_id: str, side: str, size: float, price: float) -> Dict:
        """
        Place LIVE order on Polymarket (REAL MONEY)
        side: 'BUY' or 'SELL'
        size: Amount in USDC
        price: Limit price (0.01 to 0.99)
        """
        if not self.client:
            return {'status': 'failed', 'error': 'Client not initialized'}
        
        try:
            from py_clob_client.clob_types import OrderArgs
            
            # Create order
            order_args = OrderArgs(
                price=price,
                size=size,
                side=side.lower(),
                token_id=market_id
            )
            
            # Sign and place
            signed_order = self.client.create_order(order_args)
            response = self.client.post_order(signed_order)
            
            logger.info(f"LIVE ORDER PLACED: {side} {size} @ {price}")
            
            return {
                'order_id': response.get('orderID'),
                'status': 'filled' if response.get('takingAmount') else 'open',
                'market_id': market_id,
                'side': side,
                'size': size,
                'price': price,
                'tx_hash': response.get('transactionHash'),
                'timestamp': datetime.now().isoformat(),
                'is_live': True
            }
            
        except Exception as e:
            logger.error(f"LIVE ORDER FAILED: {e}")
            return {'status': 'failed', 'error': str(e)}
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        if not self.client:
            return False
        
        try:
            self.client.cancel_order(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False
    
    def get_positions(self) -> List[Dict]:
        """Get current open positions"""
        if not self.client:
            return []
        
        try:
            positions = self.client.get_positions()
            return positions
        except Exception as e:
            logger.error(f"Positions fetch failed: {e}")
            return []
    
    def redeem_positions(self, market_id: str):
        """Redeem winnings after market resolution"""
        try:
            result = self.client.redeem_positions(market_id)
            logger.info(f"Redeemed positions for {market_id}")
            return result
        except Exception as e:
            logger.error(f"Redeem failed: {e}")
            return None
