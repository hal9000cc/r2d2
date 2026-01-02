from app.services.tasks.strategy import Strategy
from app.services.tasks.broker import OrderSide
from typing import Dict, Tuple, Any


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
                'slow_ma': (20, 'Slow moving average period')
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
        # Example: self.order(OrderSide.BUY, quantity=0.001)
        pass
    
    def on_finish(self):
        """
        Called after the testing loop completes (only for backtesting).
        In real trading, the loop is infinite, so this method is not called.
        Use this method to perform any final calculations or cleanup.
        """
        pass
