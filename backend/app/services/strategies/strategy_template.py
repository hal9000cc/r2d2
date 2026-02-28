from app.services.tasks.strategy import Strategy
from typing import Dict, Tuple, Any
import numpy as np


class MyStrategy(Strategy):
    """
    My strategy template
    
    This is a template for creating new strategies.
    Replace MyStrategy with your strategy class name.
    """
    
    def __init__(self):
        super().__init__()
    
    @staticmethod
    def get_parameters_description() -> Dict[str, Tuple[Any, str]]:
        """
        Get parameters description of the strategy.
        
        Returns:
            Dictionary where keys are parameter names (str) and values are tuples
            of (default_value, description). Type is determined automatically from default_value.
            For example:
            {
                'fast_ma': (10, 'Fast moving average period'),
                'slow_ma': (20, 'Slow moving average period'),
                'bb_period': (20, 'Bollinger Bands period'),
                'bb_deviation': (2.0, 'Bollinger Bands deviation')
            }
        """
        return {}
    
    def on_start(self):
        """
        Called before the start of trading.
        Use this method to initialize any strategy-specific data structures or variables.
        """
        self.logging("Strategy started (example log message)")
    
    def on_bar(self):
        """
        Called when a new bar is received.
        Implement your strategy logic here.
        """
        # Example: Calculate indicators
        # pyita returns IndicatorResult object - access series via dot notation
        # 
        # Simple indicators (single series)
        # sma = self.ta.sma(period=20, value='close')
        # rsi = self.ta.rsi(period=14)
        # Access: sma[-1], rsi[-1]
        # 
        # Bollinger Bands (returns object with multiple series)
        # bb = self.ta.bollinger_bands(period=20, deviation=2.0)
        # Access series: bb.mid_line, bb.up_line, bb.down_line, bb.width, bb.z_score
        # Example: if self.close[-1] < bb.down_line[-1]:
        # 
        # Optional: Configure line visualization (for chart display)
        # bb = self.ta.bollinger_bands(
        #     period=20,
        #     deviation=2.0,
        #     lines={
        #         'mid_line': {'color': '#0066CC', 'lineWidth': 1, 'lineStyle': 'dotted'},
        #         'up_line': {'color': '#FFD700', 'lineWidth': 2, 'lineStyle': 'solid'},
        #         'down_line': {'color': '#0066CC', 'lineWidth': 1, 'lineStyle': 'dotted'}
        #     }
        # )
        # 
        # MACD example (returns object with multiple series)
        # macd = self.ta.macd(period_fast=12, period_slow=26, period_signal=9)
        # Access series: macd.macd, macd.signal, macd.hist
        # Example: if macd.macd[-1] > macd.signal[-1]:
        # 
        # Example: Place orders
        # self.buy(quantity=0.001)  # Market order
        # self.sell(quantity=0.001, price=50000.0)  # Limit order
        pass
    
    def on_finish(self):
        """
        Called after the testing loop completes (only for backtesting).
        In real trading, the loop is infinite, so this method is not called.
        Use this method to perform any final calculations or cleanup.
        """
        pass
