"""
Shimmer API Client for Paper Trading/Simulation
Handles mock/paper trading via Shimmer testnet API
"""
import logging
import random
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger('Shimmer')

class ShimmerClient:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.api_key = config.get('shimmer_api_key', '')
        self.base_url = config.get('shimmer_url', 'https://api.shimmer.network')
        self.mock_mode = config.get('mock_mode', True)
        self.connected = False
        
        if self.mock_mode:
            logger.info("Shimmer: MOCK mode (simulation)")
            self.connected = True
        else:
            self.connected = self._test_connection()
    
    def _test_connection(self) -> bool:
        try:
            # Test API endpoint
            response = requests.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Shimmer connection failed: {e}")
            return False
    
    def get_active_markets(self) -> List[Dict]:
        """Get active 5-minute prediction markets"""
        if self.mock_mode:
            return self._generate_mock_markets()
        
        try:
            headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
            response = requests.get(
                f"{self.base_url}/markets/active",
                headers=headers,
                params={'timeframe': '5m', 'status': 'active'},
                timeout=10
            )
            response.raise_for_status()
            return response.json().get('markets', [])
        except Exception as e:
            logger.error(f"Failed to fetch Shimmer markets: {e}")
            return []
    
    def get_market_orderbook(self, market_id: str) -> Dict:
        """Get orderbook for a specific market"""
        if self.mock_mode:
            return self._mock_orderbook(market_id)
        
        try:
            response = requests.get(
                f"{self.base_url}/markets/{market_id}/orderbook",
                headers={'Authorization': f'Bearer {self.api_key}'} if self.api_key else {},
                timeout=5
            )
            return response.json()
        except Exception as e:
            logger.error(f"Orderbook fetch failed: {e}")
            return {}
    
    def place_paper_order(self, market_id: str, side: str, size: float, price: Optional[float] = None) -> Dict:
        """
        Place paper/simulated order on Shimmer
        Returns simulated fill
        """
        if self.mock_mode:
            return {
                'order_id': f"paper-{random.randint(10000, 99999)}",
                'status': 'filled',
                'market_id': market_id,
                'side': side,
                'size': size,
                'filled_price': price or random.uniform(0.45, 0.55),
                'timestamp': datetime.now().isoformat(),
                'pnl': 0.0,
                'is_paper': True
            }
        
        try:
            payload = {
                'market_id': market_id,
                'side': side,
                'size': size,
                'price': price,
                'type': 'paper'
            }
            response = requests.post(
                f"{self.base_url}/orders/paper",
                json=payload,
                headers={'Authorization': f'Bearer {self.api_key}'} if self.api_key else {},
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Paper order failed: {e}")
            return {'status': 'failed', 'error': str(e)}
    
    def get_positions(self) -> List[Dict]:
        """Get paper trading positions"""
        if self.mock_mode:
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/positions",
                headers={'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
            )
            return response.json().get('positions', [])
        except:
            return []
    
    def _generate_mock_markets(self) -> List[Dict]:
        """Generate realistic 5m prediction markets"""
        now = datetime.now()
        markets = []
        
        for i in range(3):
            expiry = now + timedelta(minutes=5)
            market_id = f"SHIMMER-BTC-5M-{expiry.strftime('%H%M')}-{i}"
            
            markets.append({
                'market_id': market_id,
                'symbol': f'BTC-5M-{i}',
                'base_asset': 'BTC',
                'quote_asset': 'USDC',
                'timeframe': '5m',
                'duration': 300,
                'expiry': expiry.isoformat(),
                'status': 'active',
                'outcomes': [{'name': 'Yes', 'price': 0.52}, {'name': 'No', 'price': 0.48}],
                'volume': random.randint(10000, 50000),
                'liquidity': random.randint(5000, 20000),
                'is_simulation': True
            })
        
        return markets
    
    def _mock_orderbook(self, market_id: str) -> Dict:
        base = 0.50
        return {
            'bids': [{'price': base - 0.02, 'size': 100}, {'price': base - 0.01, 'size': 200}],
            'asks': [{'price': base + 0.01, 'size': 150}, {'price': base + 0.02, 'size': 300}],
            'timestamp': datetime.now().isoformat()
          }
