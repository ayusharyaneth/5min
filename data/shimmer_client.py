"""
Shimmer API Client - Real Implementation
Docs: https://docs.simmer.markets/
"""
import logging
import requests
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger('Shimmer')

class ShimmerClient:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.api_key = config.get('api_key', '')
        self.mock_mode = config.get('mock_mode', False)
        
        # Base URL from Shimmer docs
        self.base_url = config.get('base_url', 'https://api.simmer.markets/v1')
        
        # Setup headers with authentication
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        if self.api_key:
            self.headers['Authorization'] = f'Bearer {self.api_key}'
        
        self.connected = False
        
        if self.mock_mode:
            logger.info("Shimmer: Running in MOCK mode")
            self.connected = True
        else:
            self.connected = self._test_connection()
            if self.connected:
                logger.info(f"✅ Connected to Shimmer API: {self.base_url}")
            else:
                logger.error("❌ Failed to connect to Shimmer API")

    def _test_connection(self) -> bool:
        """Test API connectivity"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                headers=self.headers,
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make authenticated request to Shimmer API"""
        if self.mock_mode:
            return self._mock_response(endpoint, data)
        
        url = f"{self.base_url}/{endpoint}"
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, timeout=15)
            elif method == 'POST':
                response = requests.post(url, headers=self.headers, json=data, timeout=15)
            else:
                return {'error': 'Invalid method'}
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return {'error': str(e)}
        except json.JSONDecodeError:
            logger.error("Invalid JSON response from API")
            return {'error': 'Invalid response format'}

    def get_active_markets(self, market_type: str = "5m") -> List[Dict]:
        """
        Fetch active prediction markets from Shimmer
        Default: 5-minute markets
        """
        if self.mock_mode:
            return self._generate_mock_markets()
        
        try:
            # Fetch markets from Shimmer API
            params = {
                'status': 'active',
                'type': 'prediction',
                'duration': '5m'  # 5 minute markets
            }
            
            response = self._make_request('GET', 'markets', params)
            
            if 'error' in response:
                logger.error(f"Failed to fetch markets: {response['error']}")
                return []
            
            markets = response.get('data', [])
            
            # Format markets to match expected structure
            formatted_markets = []
            for market in markets:
                formatted_markets.append({
                    'market_id': market.get('id'),
                    'symbol': market.get('symbol', f"BTC-5M-{market.get('id', '0')[:8]}"),
                    'base_asset': market.get('base_asset', 'BTC'),
                    'quote_asset': market.get('quote_asset', 'USD'),
                    'timeframe': '5m',
                    'duration': 300,
                    'expiry': market.get('expires_at'),
                    'status': 'active',
                    'outcomes': market.get('outcomes', ['Yes', 'No']),
                    'current_price': float(market.get('current_price', 0.5)),
                    'volume': float(market.get('volume', 0)),
                    'liquidity': float(market.get('liquidity', 0)),
                    'is_simulation': False
                })
            
            logger.info(f"✨ Fetched {len(formatted_markets)} active markets from Shimmer")
            return formatted_markets
            
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []

    def get_orderbook(self, market_id: str) -> Dict:
        """Get orderbook for a specific market"""
        if self.mock_mode:
            return self._mock_orderbook(market_id)
        
        try:
            response = self._make_request('GET', f'markets/{market_id}/orderbook')
            
            if 'error' in response:
                return self._mock_orderbook(market_id)  # Fallback
            
            return {
                'market_id': market_id,
                'bids': response.get('bids', []),
                'asks': response.get('asks', []),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error fetching orderbook: {e}")
            return self._mock_orderbook(market_id)

    def get_balance(self) -> Dict:
        """Get paper trading balance"""
        if self.mock_mode:
            return {
                'cash_balance': 10000.0,
                'positions_value': 0.0,
                'total_value': 10000.0,
                'currency': 'USD'
            }
        
        try:
            response = self._make_request('GET', 'account/balance')
            
            if 'error' in response:
                logger.error(f"Balance fetch error: {response['error']}")
                return {'cash_balance': 0, 'positions_value': 0, 'total_value': 0}
            
            return {
                'cash_balance': float(response.get('available_balance', 0)),
                'positions_value': float(response.get('positions_value', 0)),
                'total_value': float(response.get('total_balance', 0)),
                'currency': response.get('currency', 'USD')
            }
            
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return {'cash_balance': 0, 'positions_value': 0, 'total_value': 0}

    def place_paper_order(self, market_id: str, side: str, size: float, price: Optional[float] = None) -> Dict:
        """
        Place paper/simulated order on Shimmer
        Returns order details
        """
        if self.mock_mode:
            return self._mock_order_response(market_id, side, size, price)
        
        try:
            payload = {
                'market_id': market_id,
                'side': side.lower(),  # 'buy' or 'sell'
                'size': float(size),
                'type': 'paper',  # Explicitly paper trading
                'price': float(price) if price else None
            }
            
            response = self._make_request('POST', 'orders/paper', payload)
            
            if 'error' in response:
                logger.error(f"Order failed: {response['error']}")
                return {
                    'success': False,
                    'error': response['error'],
                    'market_id': market_id
                }
            
            return {
                'success': True,
                'order_id': response.get('id'),
                'status': response.get('status', 'filled'),
                'market_id': market_id,
                'side': side,
                'size': size,
                'filled_price': float(response.get('filled_price', price or 0.5)),
                'timestamp': datetime.now().isoformat(),
                'is_paper': True
            }
            
        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return {
                'success': False,
                'error': str(e),
                'market_id': market_id
            }

    def get_positions(self) -> List[Dict]:
        """Get current paper trading positions"""
        if self.mock_mode:
            return []
        
        try:
            response = self._make_request('GET', 'account/positions')
            
            if 'error' in response:
                return []
            
            positions = []
            for pos in response.get('data', []):
                positions.append({
                    'market_id': pos.get('market_id'),
                    'symbol': pos.get('symbol'),
                    'quantity': float(pos.get('size', 0)),
                    'avg_entry_price': float(pos.get('entry_price', 0)),
                    'side': pos.get('side', 'buy').upper()
                })
            
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def get_market_ticker(self, market_id: str) -> Dict:
        """Get current price ticker for a market"""
        try:
            response = self._make_request('GET', f'markets/{market_id}/ticker')
            
            if 'error' in response:
                return {'last_price': 0.5, 'change_24h': 0}
            
            return {
                'market_id': market_id,
                'last_price': float(response.get('last_price', 0.5)),
                'bid': float(response.get('bid', 0.49)),
                'ask': float(response.get('ask', 0.51)),
                'volume': float(response.get('volume', 0)),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error fetching ticker: {e}")
            return {'last_price': 0.5}

    # ═══════════════════════════════════════════════════════
    # MOCK METHODS (Fallback when API is unavailable)
    # ═══════════════════════════════════════════════════════

    def _generate_mock_markets(self) -> List[Dict]:
        """Generate realistic mock 5m prediction markets"""
        import random
        
        now = datetime.now()
        markets = []
        
        for i in range(3):
            expiry = now + timedelta(minutes=5)
            market_id = f"simmer-btc-5m-{expiry.strftime('%H%M')}-{i}"
            
            markets.append({
                'market_id': market_id,
                'symbol': f'BTC-5M-{i}',
                'base_asset': 'BTC',
                'quote_asset': 'USD',
                'timeframe': '5m',
                'duration': 300,
                'expiry': expiry.isoformat(),
                'status': 'active',
                'outcomes': [{'name': 'Yes', 'price': 0.52}, {'name': 'No', 'price': 0.48}],
                'current_price': 0.50 + random.uniform(-0.05, 0.05),
                'volume': random.uniform(1000, 10000),
                'is_simulation': True
            })
        
        return markets

    def _mock_orderbook(self, market_id: str) -> Dict:
        """Mock orderbook"""
        import random
        base = 0.50
        
        return {
            'market_id': market_id,
            'bids': [{'price': base - 0.02, 'size': 100}, {'price': base - 0.01, 'size': 200}],
            'asks': [{'price': base + 0.01, 'size': 150}, {'price': base + 0.02, 'size': 300}],
            'timestamp': datetime.now().isoformat()
        }

    def _mock_order_response(self, market_id: str, side: str, size: float, price: Optional[float]) -> Dict:
        """Mock successful order"""
        import random
        
        fill_price = price or (0.50 + random.uniform(-0.02, 0.02))
        
        return {
            'success': True,
            'order_id': f"paper-{random.randint(10000, 99999)}",
            'status': 'filled',
            'market_id': market_id,
            'side': side,
            'size': size,
            'filled_price': fill_price,
            'timestamp': datetime.now().isoformat(),
            'is_paper': True
        }

    def _mock_response(self, endpoint: str, data: Dict = None) -> Dict:
        """Generic mock response handler"""
        if 'markets' in endpoint and 'orderbook' not in endpoint:
            return {'data': self._generate_mock_markets()}
        elif 'orderbook' in endpoint:
            return self._mock_orderbook(data.get('market_id', 'mock'))
        elif 'balance' in endpoint:
            return {'available_balance': 10000, 'positions_value': 0, 'total_balance': 10000}
        return {}
