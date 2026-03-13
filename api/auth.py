"""Authentication module for Polymarket CLOB API."""
import base64
import hashlib
import hmac
import secrets
import time
from typing import Dict

from eth_account import Account
from eth_account.messages import encode_defunct

from utils.logger import get_logger

logger = get_logger(__name__)


class PolyAuth:
    """Handles Polymarket CLOB authentication."""
    
    def __init__(
        self,
        private_key: str,
        api_key: str,
        api_secret: str,
        passphrase: str,
        wallet_address: str
    ):
        self.private_key = private_key
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.wallet_address = wallet_address.lower()
        
        # Initialize Ethereum account
        if private_key:
            if private_key.startswith("0x"):
                private_key = private_key[2:]
            self.account = Account.from_key(private_key)
        else:
            self.account = None
    
    def get_auth_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """
        Generate authentication headers for CLOB API requests.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path
            body: Request body (for POST requests)
            
        Returns:
            Dictionary of headers
        """
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        
        # Create HMAC-SHA256 signature
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256
            ).digest()
        ).decode("utf-8")
        
        return {
            "POLY_ADDRESS": self.wallet_address,
            "POLY_TIMESTAMP": timestamp,
            "POLY_NONCE": "0",
            "POLY_API_KEY": self.api_key,
            "POLY_PASSPHRASE": self.passphrase,
            "POLY_SIGNATURE": signature,
            "Content-Type": "application/json"
        }
    
    def sign_order(self, order_data: Dict) -> str:
        """
        Sign an order using Ethereum private key.
        
        Args:
            order_data: Order data dictionary
            
        Returns:
            Signature string
        """
        if not self.account:
            raise ValueError("No private key available for signing")
        
        # Create order hash
        order_str = (
            f"{order_data['maker']}{order_data['taker']}"
            f"{order_data['tokenId']}{order_data['makerAmount']}"
            f"{order_data['takerAmount']}{order_data['expiration']}"
            f"{order_data['salt']}{order_data['feeRateBps']}"
        )
        
        message = encode_defunct(text=order_str)
        signed_message = self.account.sign_message(message)
        
        return signed_message.signature.hex()
    
    def build_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        expiration: int = 0
    ) -> Dict:
        """
        Build and sign an order.
        
        Args:
            token_id: Token ID to trade
            side: "BUY" or "SELL"
            size: Number of shares
            price: Price per share (0-1)
            expiration: Order expiration timestamp (0 for no expiration)
            
        Returns:
            Complete order dictionary with signature
        """
        if not self.account:
            raise ValueError("No private key available for order building")
        
        # Convert to micro-units (6 decimals)
        maker_amount = int(size * price * 1_000_000)
        taker_amount = int(size * 1_000_000)
        
        # Random salt
        salt = str(secrets.randbits(256))
        
        order_data = {
            "maker": self.wallet_address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": token_id,
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": str(expiration),
            "salt": salt,
            "feeRateBps": "0",
            "side": side.upper(),
            "price": str(price)
        }
        
        # Sign the order
        signature = self.sign_order(order_data)
        order_data["signature"] = signature
        
        return order_data
