from app.services.tasks.strategy import StrategyBacktest, OrderSide
from app.services.tasks.tasks import Task
from typing import Dict, Tuple, Any


class MyStrategy(StrategyBacktest):
    """
    My strategy template
    
    This is a template for creating new strategies.
    Replace MyStrategy with your strategy class name.
    """
    
    def __init__(self, task: Task, id_result: str):
        super().__init__(task, id_result)
    
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
    
    def on_bar(self):
        """
        Called when a new bar is received.
        Implement your strategy logic here.
        """
        # Example: self.order(OrderSide.BUY, quantity=0.001)
        pass
