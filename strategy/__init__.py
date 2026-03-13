"""Strategy module for trading decisions."""
from strategy.position import Position, OpenOrder
from strategy.trend import detect_trend, detect_up_trend, detect_down_trend
from strategy.decision import TradeDecision, make_decision

__all__ = [
    "Position", "OpenOrder",
    "detect_trend", "detect_up_trend", "detect_down_trend",
    "TradeDecision", "make_decision"
]
