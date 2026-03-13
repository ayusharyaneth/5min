import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
# Keep your other imports here (requests, pandas, etc.)
# REMOVE or comment out this line if present:
# from telegram_bot.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class MarketFinder:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.opportunities = []
        self.active_monitors = {}
        
        # LAZY IMPORT: Break circular dependency by importing inside __init__
        from telegram_bot.notifier import TelegramNotifier
        self.notifier = TelegramNotifier()
        
        logger.info("MarketFinder initialized")

    def find_opportunities(self, symbols: List[str]) -> List[Dict]:
        """Scan for trading opportunities and notify"""
        opportunities = []
        
        for symbol in symbols:
            # Your existing analysis logic here...
            opportunity = self._analyze_symbol(symbol)
            
            if opportunity and opportunity.get('signal'):
                opportunities.append(opportunity)
                
                # Notify via Telegram
                try:
                    self.notifier.send_opportunity_alert(opportunity)
                except Exception as e:
                    logger.error(f"Failed to send notification: {e}")
        
        self.opportunities = opportunities
        return opportunities

    def _analyze_symbol(self, symbol: str) -> Optional[Dict]:
        """Analyze a single symbol for opportunities"""
        # Your existing analysis logic here...
        # Example:
        return {
            'symbol': symbol,
            'signal': 'BUY',
            'confidence': 0.85,
            'timestamp': datetime.now()
        }

    def scan_markets(self, market_type: str = "crypto") -> List[Dict]:
        """Scan specific market type"""
        # Your existing scan logic...
        logger.info(f"Scanning {market_type} markets")
        return self.find_opportunities([])  # Pass your symbols list

    # Keep all your other existing methods here...
    # Just ensure any method using TelegramNotifier uses self.notifier
