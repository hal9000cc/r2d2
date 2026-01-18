from typing import List, Optional, Dict, Any, Tuple, Callable
import numpy as np

from app.services.tasks.broker_new import Broker, Order
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.services.tasks.tasks import Task


class BrokerBacktesting(Broker):
    """
    Backtesting broker implementation.
    
    Inherits from Broker and implements abstract methods for backtesting scenarios.
    """
    
    def __init__(
        self, 
        task: Task, 
        result_id: str,
        callbacks_dict: Dict[str, Callable],
        results_save_period: float = TRADE_RESULTS_SAVE_PERIOD
    ):
        """
        Initialize backtesting broker.
        
        Args:
            task: Task instance (contains fee_taker, fee_maker, price_step, precision_amount, precision_price, slippage_in_steps)
            result_id: Unique ID for this backtesting run
            callbacks_dict: Dictionary with callback functions:
                - 'on_start': Callable(parameters: Dict[str, Any])
                - 'on_bar': Callable(price, current_time, time, open, high, low, close, volume, equity_usd, equity_symbol)
                - 'on_finish': Callable with no arguments
            results_save_period: Period for saving results in seconds (default: TRADE_RESULTS_SAVE_PERIOD)
        """
        super().__init__(task=task, result_id=result_id, callbacks_dict=callbacks_dict, results_save_period=results_save_period)
        
        # Get fee and slippage from task, with defaults
        self.fee_taker: float = task.fee_taker if task.fee_taker > 0 else 0.001  # Default to 0.1% if not set
        self.fee_maker: float = task.fee_maker if task.fee_maker > 0 else 0.001  # Default to 0.1% if not set
        # Calculate slippage from slippage_in_steps and price_step
        self.slippage: float = (task.slippage_in_steps * task.price_step) if task.price_step > 0 else 0.0
        
        # Progress tracking
        self.progress: float = 0.0
        self.date_start: Optional[np.datetime64] = None
        self.date_end: Optional[np.datetime64] = None
        
        # Equity tracking for backtesting
        self.equity_usd: PRICE_TYPE = 0.0
        self.equity_symbol: VOLUME_TYPE = 0.0
    
    def create_order(self, order: Order) -> List[str]:
        """
        Create an order (backtesting implementation).
        
        Args:
            order: Order object to create
        
        Returns:
            List of errors. Empty list if order was created successfully.
        """
        raise NotImplementedError("create_order must be implemented by BrokerBacktesting")
    
    def cancel_order(self, order_id: str, symbol: str) -> List[str]:
        """
        Cancel an order by its ID (backtesting implementation).
        
        Args:
            order_id: Order ID to cancel
            symbol: Trading symbol (e.g., 'BTC/USDT')
        
        Returns:
            List of error messages. Empty list means success (order was canceled successfully).
            Non-empty list contains error descriptions if cancellation failed.
        """
        raise NotImplementedError("cancel_order must be implemented by BrokerBacktesting")
    
    def initialize_run(self) -> None:
        """
        Initialize broker for running strategy (backtesting implementation).
        
        Called at the start of run() method to set up broker state.
        """
        raise NotImplementedError("initialize_run must be implemented by BrokerBacktesting")
    
    def initialize_quotes(self, history_size: int, ta_proxies: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initialize quotes data for strategy execution (backtesting implementation).
        
        Args:
            history_size: Number of bars to load for strategy initialization
            ta_proxies: Dictionary of TA proxies (e.g., {'talib': ta_proxy_talib(...)})
                       Should call set_quotes() on each proxy with initial quotes data
        
        Returns:
            Dictionary with quotes data (structure is implementation-specific)
        """
        raise NotImplementedError("initialize_quotes must be implemented by BrokerBacktesting")
    
    def get_next_bar(
        self, 
        quotes_data: Dict[str, Any], 
        i_time: int, 
        ta_proxies: Dict[str, Any]
    ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.datetime64, PRICE_TYPE]]:
        """
        Get next bar data for strategy execution (backtesting implementation).
        
        Args:
            quotes_data: Quotes data dictionary (from initialize_quotes)
            i_time: Current bar index
            ta_proxies: Dictionary of TA proxies (for backtesting, set_quotes() is not called)
        
        Returns:
            Tuple of (time_array, open_array, high_array, low_array, close_array, volume_array, current_time, current_price)
            or None if no more data available
        """
        raise NotImplementedError("get_next_bar must be implemented by BrokerBacktesting")
    

