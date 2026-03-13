"""Market discovery for BTC 5-minute markets."""
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests

from api.clob_client import CLOBClient
from config import GAMMA_API_URL
from state.store import StateStore
from paper_trading.paper_store import PaperStateStore
from telegram_bot.notifier import TelegramNotifier
from strategy.position import Position
from utils.logger import get_logger

logger = get_logger(__name__)


class MarketFinder:
    """Finds and tracks active BTC 5-minute markets."""
    
    def __init__(
        self,
        clob: CLOBClient,
        live_store: StateStore,
        paper_store: Optional[PaperStateStore],
        notifier: TelegramNotifier,
        live: bool = True,
        paper: bool = True
    ):
        self.clob = clob
        self.live_store = live_store
        self.paper_store = paper_store
        self.notifier = notifier
        self.live = live
        self.paper = paper
        self.session = requests.Session()
    
    def find_active_btc_5m_markets(self) -> List[Dict]:
        """
        Query Gamma API for active BTC 5-minute markets.
        
        Returns:
            List of market dictionaries
        """
        markets = []
        
        try:
            # Query Gamma API for BTC markets
            params = {
                "active": "true",
                "archived": "false",
                "closed": "false",
                "limit": 100
            }
            
            response = self.session.get(
                f"{GAMMA_API_URL}/markets",
                params=params,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            all_markets = data if isinstance(data, list) else data.get("markets", [])
            
            # Filter for BTC 5-minute markets
            for market in all_markets:
                question = market.get("question", "").lower()
                description = market.get("description", "").lower()
                
                # Check for BTC/Bitcoin keywords and 5-minute timeframe
                is_btc = "btc" in question or "bitcoin" in question or "btc" in description or "bitcoin" in description
                is_5m = "5 min" in question or "5min" in question or "5 minute" in question or "5-minute" in question
                
                if is_btc and is_5m:
                    market_id = market.get("conditionId") or market.get("market_slug") or market.get("id")
                    
                    if not market_id:
                        continue
                    
                    # Extract token IDs from outcomes
                    outcomes = market.get("outcomes", "")
                    outcome_prices = market.get("outcomePrices", "")
                    
                    # Get clob token IDs from the market data
                    clob_token_ids = market.get("clobTokenIds", [])
                    
                    if len(clob_token_ids) >= 2:
                        up_token_id = clob_token_ids[0]
                        down_token_id = clob_token_ids[1]
                    else:
                        # Try to get from outcomes
                        up_token_id = market.get("yes_token_id", "")
                        down_token_id = market.get("no_token_id", "")
                    
                    # Get end date
                    end_date = market.get("endDate") or market.get("resolutionTime")
                    
                    market_info = {
                        "market_id": market_id,
                        "question": market.get("question", ""),
                        "description": market.get("description", ""),
                        "up_token_id": up_token_id,
                        "down_token_id": down_token_id,
                        "end_date_iso": end_date,
                        "slug": market.get("market_slug", ""),
                        "condition_id": market.get("conditionId", "")
                    }
                    
                    markets.append(market_info)
                    
                    # Register in stores if new
                    self._register_market(market_info)
            
            if markets:
                logger.info(f"Found {len(markets)} active BTC 5m markets")
            
        except Exception as e:
            logger.error(f"Error finding markets: {e}")
        
        return markets
    
    def _register_market(self, market_info: Dict):
        """Register a market in the stores."""
        market_id = market_info["market_id"]
        
        # Register in live store
        if self.live and not self.live_store.has_position(market_id):
            self.live_store.set_market_meta(market_id, market_info)
            position = Position(market_id=market_id, question=market_info.get("question", ""))
            self.live_store.set_position(market_id, position)
            self.notifier.send_log(f"📊 New market tracked: {market_info.get('question', '')[:60]}...", "INFO")
        
        # Register in paper store
        if self.paper and self.paper_store and not self.paper_store.has_position(market_id):
            self.paper_store.set_market_meta(market_id, market_info)
            position = Position(market_id=market_id, question=market_info.get("question", ""))
            self.paper_store.set_position(market_id, position)
            self.notifier.send_paper_log(f"📊 New paper market tracked: {market_info.get('question', '')[:60]}...", "INFO")
    
    @staticmethod
    def get_time_remaining(market: Dict) -> float:
        """
        Get time remaining in seconds for a market.
        
        Args:
            market: Market dictionary
            
        Returns:
            Seconds remaining (0 if expired)
        """
        end_date_str = market.get("end_date_iso")
        if not end_date_str:
            return 0
        
        try:
            # Parse ISO format
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            now = datetime.now(end_date.tzinfo)
            remaining = (end_date - now).total_seconds()
            return max(0, remaining)
        except Exception as e:
            logger.error(f"Error parsing end date: {e}")
            return 0
