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

logger = logging.getLogger('Backtest')

@dataclass
class Trade:
    timestamp: datetime
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    exit_reason: str

class StrategyValidator:
    def __init__(self, config: Dict):
        self.config = config
        self.trades: List[Trade] = []
        self.initial_balance = config.get('initial_balance', 10000)
        self.current_balance = self.initial_balance
        self.peak_balance = self.initial_balance
        self.max_drawdown = 0
        
        self.min_confidence = config.get('min_confidence', 0.75)
        self.take_profit = config.get('take_profit', 0.05)
        self.stop_loss = config.get('stop_loss', 0.03)
        self.trade_size = config.get('trade_size', 100)
        
        logger.info(f"🧪 Validator initialized with ${self.initial_balance}")

    async def run_backtest(self, historical_data: List[Dict], days: int = 30):
        logger.info(f"📊 Backtesting {len(historical_data)} events...")
        
        for event in historical_data:
            signal = self._generate_signal(event)
            
            if signal and signal['confidence'] >= self.min_confidence:
                trade_result = self._simulate_trade(event, signal)
                if trade_result:
                    self.trades.append(trade_result)
                    self._update_balance(trade_result)
        
        return self._calculate_metrics()

    def _generate_signal(self, market_event: Dict) -> Optional[Dict]:
        price_change = market_event.get('price_change_5m', 0)
        volume = market_event.get('volume', 0)
        avg_volume = market_event.get('avg_volume', 1)
        
        volume_spike = volume > (avg_volume * 1.5)
        
        if volume_spike:
            if price_change > 0.02:
                return {
                    'side': 'BUY',
                    'confidence': min(abs(price_change) * 10, 0.95),
                    'reason': 'momentum_up'
                }
            elif price_change < -0.02:
                return {
                    'side': 'SELL',
                    'confidence': min(abs(price_change) * 10, 0.95),
                    'reason': 'momentum_down'
                }
        
        return None

    def _simulate_trade(self, event: Dict, signal: Dict) -> Optional[Trade]:
        entry_price = event.get('price', 0.50)
        
        if signal['side'] == 'BUY':
            tp_price = entry_price * (1 + self.take_profit)
            sl_price = entry_price * (1 - self.stop_loss)
        else:
            tp_price = entry_price * (1 - self.take_profit)
            sl_price = entry_price * (1 + self.stop_loss)
        
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
            else:
                if future_price <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'take_profit'
                    break
                elif future_price >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'stop_loss'
                    break
        
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
        self.current_balance += trade.pnl
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def _calculate_metrics(self) -> Dict:
        if not self.trades:
            return {
                'status': 'NO_TRADES',
                'message': 'No trades generated'
            }
        
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
        
        total_pnl = sum(t.pnl for t in self.trades)
        avg_pnl = total_pnl / total_trades
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')
        
        returns = [t.pnl_pct for t in self.trades]
        sharpe = np.mean(returns) / np.std(returns) if np.std(returns) != 0 else 0
        
        total_return = ((self.current_balance - self.initial_balance) / self.initial_balance) * 100
        
        # FIX: Convert numpy types to Python native types
        metrics = {
            'status': 'SUCCESS',
            'total_trades': int(total_trades),
            'winning_trades': int(len(winning_trades)),
            'losing_trades': int(len(losing_trades)),
            'win_rate': float(win_rate),
            'total_pnl': float(total_pnl),
            'total_return': float(total_return),
            'avg_pnl_per_trade': float(avg_pnl),
            'avg_win': float(avg_win),
            'avg_loss': float(avg_loss),
            'profit_factor': float(profit_factor),
            'sharpe_ratio': float(sharpe),
            'max_drawdown': float(self.max_drawdown * 100),
            'final_balance': float(self.current_balance),
            'is_profitable': bool(total_pnl > 0),  # FIX: Convert to Python bool
            'recommendation': 'PROCEED_TO_LIVE' if (total_pnl > 0 and win_rate > 50 and profit_factor > 1.5) else 'OPTIMIZE_STRATEGY'
        }
        
        self._print_report(metrics)
        return metrics

    def _print_report(self, metrics: Dict):
        print("\n" + "="*60)
        print("📊 STRATEGY VALIDATION REPORT")
        print("="*60)
        
        emoji = "✅" if metrics['is_profitable'] else "❌"
        print(f"\n{emoji} PROFITABILITY: {'PROFITABLE' if metrics['is_profitable'] else 'UNPROFITABLE'}")
        
        print(f"\n📈 Performance:")
        print(f"   Total Return:     {metrics['total_return']:.2f}%")
        print(f"   Total P&L:        ${metrics['total_pnl']:.2f}")
        print(f"   Final Balance:    ${metrics['final_balance']:.2f}")
        print(f"   Max Drawdown:     {metrics['max_drawdown']:.2f}%")
        
        print(f"\n🎯 Statistics:")
        print(f"   Total Trades:     {metrics['total_trades']}")
        print(f"   Win Rate:         {metrics['win_rate']:.2f}%")
        print(f"   Profit Factor:    {metrics['profit_factor']:.2f}")
        print(f"   Sharpe Ratio:     {metrics['sharpe_ratio']:.2f}")
        
        print(f"\n💡 Verdict:")
        if metrics['recommendation'] == 'PROCEED_TO_LIVE':
            print("   ✅ Strategy is profitable. Ready for live trading!")
        else:
            print("   ⚠️  Strategy needs optimization before live trading.")
        
        print("="*60)

    def export_results(self, filename: str = "backtest_results.json"):
        """Export detailed results to file"""
        metrics = self._calculate_metrics()
        
        # FIX: Convert all numpy types to Python native types
        def convert_to_native(obj):
            if isinstance(obj, dict):
                return {k: convert_to_native(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_native(item) for item in obj]
            elif isinstance(obj, (np.bool_, bool)):
                return bool(obj)
            elif isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, datetime):
                return obj.isoformat()
            return obj
        
        results = {
            'config': convert_to_native(self.config),
            'metrics': convert_to_native(metrics),
            'trades': [
                {
                    'timestamp': t.timestamp.isoformat(),
                    'symbol': t.symbol,
                    'side': t.side,
                    'entry': float(t.entry_price),
                    'exit': float(t.exit_price),
                    'pnl': float(t.pnl),
                    'reason': t.exit_reason
                } for t in self.trades
            ]
        }
        
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"📁 Results exported to {filename}")
