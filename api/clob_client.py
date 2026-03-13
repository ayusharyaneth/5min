"""CLOB API client for Polymarket."""
import time
from typing import Dict, List, Optional

import requests

from api.auth import PolyAuth
from config import CLOB_API_URL
from utils.logger import get_logger

logger = get_logger(__name__)


class CLOBClient:
    """Client for Polymarket CLOB REST API."""
    
    def __init__(self, auth: PolyAuth):
        self.auth = auth
        self.base_url = CLOB_API_URL
        self.session = requests.Session()
    
    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        retry_429: int = 2,
        retry_5xx: int = 1
    ) -> Dict:
        """
        Make an authenticated request to the CLOB API.
        
        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            json_data: JSON body
            retry_429: Number of retries for 429 errors
            retry_5xx: Number of retries for 5xx errors
            
        Returns:
            Response JSON as dictionary
        """
        url = f"{self.base_url}{path}"
        body = "" if json_data is None else str(json_data)
        headers = self.auth.get_auth_headers(method, path, body)
        
        attempt = 0
        max_retries = max(retry_429, retry_5xx)
        
        while attempt <= max_retries:
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    timeout=30
                )
                
                # Handle rate limiting
                if response.status_code == 429:
                    if attempt < retry_429:
                        logger.warning(f"Rate limited, retrying in 2s...")
                        time.sleep(2)
                        attempt += 1
                        continue
                
                # Handle server errors
                if 500 <= response.status_code < 600:
                    if attempt < retry_5xx:
                        logger.warning(f"Server error {response.status_code}, retrying in 1s...")
                        time.sleep(1)
                        attempt += 1
                        continue
                
                response.raise_for_status()
                return response.json() if response.content else {}
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e}")
                if attempt >= max_retries:
                    raise
                attempt += 1
                time.sleep(1)
        
        return {}
    
    def get_best_ask(self, token_id: str) -> float:
        """
        Get the best (lowest) ask price for a token.
        
        Args:
            token_id: Token ID
            
        Returns:
            Best ask price, or 0.5 if not available
        """
        try:
            book = self.get_order_book(token_id)
            asks = book.get("asks", [])
            if asks:
                # Asks are sorted by price ascending, take the first
                return float(asks[0].get("price", 0.5))
            return 0.5
        except Exception as e:
            logger.error(f"Error getting best ask for {token_id}: {e}")
            return 0.5
    
    def get_order_book(self, token_id: str) -> Dict:
        """
        Get the full order book for a token.
        
        Args:
            token_id: Token ID
            
        Returns:
            Order book dictionary with bids and asks
        """
        return self._request(
            "GET",
            "/book",
            params={"token_id": token_id}
        )
    
    def place_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float
    ) -> Dict:
        """
        Place a signed order.
        
        Args:
            token_id: Token ID to trade
            side: "BUY" or "SELL"
            size: Number of shares
            price: Price per share
            
        Returns:
            Order response from API
        """
        order = self.auth.build_order(token_id, side, size, price)
        
        return self._request(
            "POST",
            "/order",
            json_data=order
        )
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if successful
        """
        try:
            self._request("DELETE", f"/order/{order_id}")
            return True
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")
            return False
    
    def cancel_all_orders(self) -> Dict:
        """
        Cancel all open orders.
        
        Returns:
            Cancellation response
        """
        try:
            return self._request("DELETE", "/orders")
        except Exception as e:
            logger.error(f"Error canceling all orders: {e}")
            return {"cancelled": 0}
    
    def get_open_orders(self) -> List[Dict]:
        """
        Get all open orders for the maker.
        
        Returns:
            List of open orders
        """
        try:
            response = self._request(
                "GET",
                "/orders",
                params={
                    "maker": self.auth.wallet_address,
                    "status": "LIVE"
                }
            )
            return response if isinstance(response, list) else []
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []
    
    def get_wallet_balance(self) -> Dict:
        """
        Get wallet balance.
        
        Returns:
            Balance dictionary with "balance" key
        """
        try:
            response = self._request("GET", "/balance")
            balance = response.get("balance", "0")
            return {"balance": float(balance) / 1_000_000}  # Convert from micro-USDC
        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
            return {"balance": 0.0}
    
    def get_market(self, market_id: str) -> Dict:
        """
        Get market details.
        
        Args:
            market_id: Market ID
            
        Returns:
            Market dictionary
        """
        return self._request("GET", f"/markets/{market_id}")
    
    def get_markets(self, params: Optional[Dict] = None) -> List[Dict]:
        """
        Get markets list.
        
        Args:
            params: Query parameters
            
        Returns:
            List of markets
        """
        response = self._request("GET", "/markets", params=params)
        return response if isinstance(response, list) else response.get("markets", [])
