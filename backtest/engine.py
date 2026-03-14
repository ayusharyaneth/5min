"""
Strategy Backtesting & Paper Trading Validation
Tests profitability before live deployment
"""

import logging
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import asyncio

logger = logging.getLogger('Backtest')

@dataclass
class Trade:
    timestamp: datetime
    symbol: str
    side: str  # BUY or SELL
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    exit_reason: str  # TP, SL, Signal, or Expiry

class StrategyValidator:
    def __init__(self, config: Dict):
        self.config = config
        self.trades: List[Trade] = []
        self.initial_balance = config.get('initial_balance', 10000)
        self.current_balance = self.initial_balance
        self.peak_balance = self.initial_balance
        self.max_drawdown = 0
        
        # Strategy parameters
        self.min_confidence = config.get('min_confidence', 0.75)
        self.take_profit = config.get('take_profit', 0.05)  # 5%
        self.stop_loss = config.get('stop_loss', 0.03)      # 3%
        self.trade_size = config.get('trade_size', 100)
        
        logger.info(f"🧪 Strategy Validator initialized with ${self.initial_balance}")

    async def run_backtest(self, historical_data: List[Dict], days: int = 30):
        """
        Run backtest on historical market data
        Returns performance metrics
        """
        logger.info(f"📊 Running backtest on {len(historical_data)} market events...")
        
        for event in historical_data:
            # Simulate strategy decision
            signal = self._generate_signal(event)
            
            if signal and signal['confidence'] >= self.min_confidence:
                # Simulate trade execution
                trade_result = self._simulate_trade(event, signal)
                if trade_result:
                    self.trades.append(trade_result)
                    self._update_balance(trade_result)
        
        return self._calculate_metrics()

    def _generate_signal(self, market_event: Dict) -> Optional[Dict]:
        """
        Your actual strategy logic goes here
        This simulates the signal generation
        """
        # Example: Simple momentum strategy
        price_change = market_event.get('price_change_5m', 0)
        volume = market_event.get('volume', 0)
        avg_volume = market_event.get('avg_volume', 1)
        
        # Volume spike + price momentum
        volume_spike = volume > (avg_volume * 1.5)
        
        if volume_spike:
            if price_change > 0.02:  # 2% up
                return {
                    'side': 'BUY',
                    'confidence': min(abs(price_change) * 10, 0.95),
                    'reason': 'momentum_up'
                }
            elif price_change < -0.02:  # 2% down
                return {
                    'side': 'SELL',
                    'confidence': min(abs(price_change) * 10, 0.95),
                    'reason': 'momentum_down'
                }
        
        return None

    def _simulate_trade(self, event: Dict, signal: Dict) -> Optional[Trade]:
        """Simulate a single trade with entry/exit logic"""
        entry_price = event.get('price', 0.50)
        
        # Calculate exit scenarios
        if signal['side'] == 'BUY':
            tp_price = entry_price * (1 + self.take_profit)
            sl_price = entry_price * (1 - self.stop_loss)
        else:  # SELL
            tp_price = entry_price * (1 - self.take_profit)
            sl_price = entry_price * (1 + self.stop_loss)
        
        # Simulate price movement over 5 minutes
        future_prices = event.get('future_prices', [])
        exit_price = entry_price
        exit_reason = 'expiry'
        
        for future_price in future_prices:
            if signal['side'] == 'BUY':
                if future_price >= tp_price:
                    exit_price = tp_price
                    exit_reason = 'take_profit'
                    break
                elif future_price <= sl_price:
                    exit_price = sl_price
                    exit_reason = 'stop_loss'
                    break
            else:  # SELL
                if future_price <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'take_profit'
                    break
                elif future_price >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'stop_loss'
                    break
        
        # Calculate PnL
        if signal['side'] == 'BUY':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl = self.trade_size * pnl_pct
        
        return Trade(
            timestamp=event.get('timestamp', datetime.now()),
            symbol=event.get('symbol', 'BTC-5M'),
            side=signal['side'],
            entry_price=entry_price,
            exit_price=exit_price,
            size=self.trade_size,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason
        )

    def _update_balance(self, trade: Trade):
        """Update running balance and track drawdown"""
        self.current_balance += trade.pnl
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def _calculate_metrics(self) -> Dict:
        """Calculate comprehensive performance metrics"""
        if not self.trades:
            return {
                'status': 'NO_TRADES',
                'message': 'No trades generated during backtest'
            }
        
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
        
        total_pnl = sum(t.pnl for t in self.trades)
        avg_pnl = total_pnl / total_trades
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        # Profit factor
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')
        
        # Sharpe ratio (simplified)
        returns = [t.pnl_pct for t in self.trades]
        sharpe = np.mean(returns) / np.std(returns) if np.std(returns) != 0 else 0
        
        # Return metrics
        total_return = ((self.current_balance - self.initial_balance) / self.initial_balance) * 100
        
        metrics = {
            'status': 'SUCCESS',
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': f"{win_rate:.2f}%",
            'total_pnl': f"${total_pnl:.2f}",
            'total_return': f"{total_return:.2f}%",
            'avg_pnl_per_trade': f"${avg_pnl:.2f}",
            'avg_win': f"${avg_win:.2f}",
            'avg_loss': f"${avg_loss:.2f}",
            'profit_factor': f"{profit_factor:.2f}",
            'sharpe_ratio': f"{sharpe:.2f}",
            'max_drawdown': f"{self.max_drawdown*100:.2f}%",
            'final_balance': f"${self.current_balance:.2f}",
            'is_profitable': total_pnl > 0,
            'recommendation': 'PROCEED_TO_LIVE' if (total_pnl > 0 and win_rate > 50 and profit_factor > 1.5) else 'OPTIMIZE_STRATEGY'
        }
        
        self._print_report(metrics)
        return metrics

    def _print_report(self, metrics: Dict):
        """Print formatted performance report"""
        print("\n" + "="*60)
        print("📊 STRATEGY VALIDATION REPORT")
        print("="*60)
        
        emoji = "✅" if metrics['is_profitable'] else "❌"
        print(f"\n{emoji} PROFITABILITY: {'PROFITABLE' if metrics['is_profitable'] else 'UNPROFITABLE'}")
        
        print(f"\n📈 Performance Metrics:")
        print(f"   Total Return:     {metrics['total_return']}")
        print(f"   Total P&L:        {metrics['total_pnl']}")
        print(f"   Final Balance:    {metrics['final_balance']}")
        print(f"   Max Drawdown:     {metrics['max_drawdown']}")
        
        print(f"\n🎯 Trade Statistics:")
        print(f"   Total Trades:     {metrics['total_trades']}")
        print(f"   Win Rate:         {metrics['win_rate']}")
        print(f"   Profit Factor:    {metrics['profit_factor']}")
        print(f"   Sharpe Ratio:     {metrics['sharpe_ratio']}")
        
        print(f"\n💡 Verdict:")
        if metrics['recommendation'] == 'PROCEED_TO_LIVE':
            print("   ✅ Strategy is profitable. Ready for live trading!")
        else:
            print("   ⚠️  Strategy needs optimization before live trading.")
            print("      Consider adjusting parameters or reviewing logic.")
        
        print("="*60)

    def export_results(self, filename: str = "backtest_results.json"):
        """Export detailed results to file"""
        results = {
            'config': self.config,
            'metrics': self._calculate_metrics(),
            'trades': [
                {
                    'timestamp': t.timestamp.isoformat(),
                    'symbol': t.symbol,
                    'side': t.side,
                    'entry': t.entry_price,
                    'exit': t.exit_price,
                    'pnl': t.pnl,
                    'reason': t.exit_reason
                } for t in self.trades
            ]
        }
        
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"📁 Results exported to {filename}")
