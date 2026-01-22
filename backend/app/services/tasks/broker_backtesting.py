from typing import List, Optional, Dict, Any, Tuple, Callable
import numpy as np

from app.services.tasks.broker import Broker, Order, OrderStatus, OrderType, OrderSide
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.datetime_utils import parse_utc_datetime
from app.core.logger import get_logger
from app.services.tasks.tasks import Task

logger = get_logger(__name__)


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
        # Order must be in NEW status before creation
        assert order.status == OrderStatus.NEW, f"Order {order.order_id} must be in NEW status to be created"
        
        # For backtesting, use internal order_id as exchange_order_id
        order.exchange_order_id = order.order_id
        order.update_modify_time(self)
        
        # Handle different order types
        if order.order_type == OrderType.MARKET:
            # Market orders are filled immediately in backtesting
            # Delegate to internal fill logic (currently stub with exception)
            self._fill_order(order)
        elif order.order_type == OrderType.STOP:
            # Register order in numpy tracking arrays (similar to _add_order_to_arrays in old BrokerBacktesting)
            # Stop order: track by trigger_price
            if order.side == OrderSide.BUY:
                # Long stop orders
                self.long_stop_order_ids = np.append(self.long_stop_order_ids, order.order_id)
                self.long_stop_trigger_prices = np.append(self.long_stop_trigger_prices, order.trigger_price)
            else:
                # Short stop orders
                self.short_stop_order_ids = np.append(self.short_stop_order_ids, order.order_id)
                self.short_stop_trigger_prices = np.append(self.short_stop_trigger_prices, order.trigger_price)
        elif order.order_type == OrderType.LIMIT:
            # Limit order: track by price
            if order.side == OrderSide.BUY:
                # Long limit orders
                self.long_order_ids = np.append(self.long_order_ids, order.order_id)
                self.long_order_prices = np.append(self.long_order_prices, order.price)
            else:
                # Short limit orders
                self.short_order_ids = np.append(self.short_order_ids, order.order_id)
                self.short_order_prices = np.append(self.short_order_prices, order.price)
        else:
            raise ValueError(f"Invalid order type: {order.order_type} for order {order.order_id}")
        
        # Set status to ACTIVE after successful registration / handling
        order._set_sync_field('status', OrderStatus.ACTIVE)
        
        # Mark order as actual (successfully registered on exchange)
        order.actual = True
        
        # Update modify_time after all changes
        order.update_modify_time(self)
        
        # No errors in backtesting create_order
        return []
    
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
        # Initialize numpy arrays for fast order lookup (similar to old BrokerBacktesting implementation)
        # Limit orders tracking
        self.long_order_ids = np.array([], dtype=np.int64)
        self.long_order_prices = np.array([], dtype=PRICE_TYPE)
        self.short_order_ids = np.array([], dtype=np.int64)
        self.short_order_prices = np.array([], dtype=PRICE_TYPE)
        
        # Stop orders tracking
        self.long_stop_order_ids = np.array([], dtype=np.int64)
        self.long_stop_trigger_prices = np.array([], dtype=PRICE_TYPE)
        self.short_stop_order_ids = np.array([], dtype=np.int64)
        self.short_stop_trigger_prices = np.array([], dtype=PRICE_TYPE)

    def _fill_order(self, order: Order) -> None:
        """
        Fill a market order immediately (backtesting implementation).
        
        Stub implementation.
        """
        pass
    
    def fetch_orders(self) -> None:
        """
        Fetch and execute orders for backtesting.
        
        Backtesting implementation stub. Will be implemented with full
        order triggering logic later.
        """
        raise NotImplementedError("fetch_orders must be implemented by BrokerBacktesting")
    
    def initialize_quotes(self, history_size: int, ta_proxies: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initialize quotes data for strategy execution (backtesting implementation).
        
        Args:
            history_size: Number of bars to load for strategy initialization (unused, taken from self.task.history_size)
            ta_proxies: Dictionary of TA proxies (e.g., {'talib': ta_proxy_talib(...)})
                       Should call set_quotes() on each proxy with initial quotes data
        
        Returns:
            Dictionary with quotes data (structure is implementation-specific)
        """
        # Get history_size from task
        history_size = self.task.history_size
        
        # Convert timeframe string to Timeframe object
        try:
            timeframe = Timeframe.cast(self.task.timeframe)
        except Exception as e:
            raise RuntimeError(f"Failed to parse timeframe '{self.task.timeframe}': {e}") from e
        
        # Convert date strings to datetime objects
        try:
            date_start = parse_utc_datetime(self.task.dateStart)
            date_end = parse_utc_datetime(self.task.dateEnd)
        except Exception as e:
            raise RuntimeError(f"Failed to parse dateStart/dateEnd: {e}") from e
        
        # Calculate initial load date: dateStart - (history_size * timeframe.timedelta())
        history_start = date_start - (history_size * timeframe.timedelta())
        
        # Get quotes data from QuotesClient
        client = QuotesClient()
        logger.debug(f"Getting quotes for {self.task.source}:{self.task.symbol}:{self.task.timeframe} from {history_start} to {date_end}")
        quotes_data = client.get_quotes(self.task.source, self.task.symbol, timeframe, history_start, date_end)
        logger.debug(f"Quotes received: {len(quotes_data['time'])} bars")
        
        # Validate that we have quotes data
        if len(quotes_data['time']) == 0:
            raise RuntimeError("No quotes data available for backtesting")
        
        # Call set_quotes() on each TA proxy
        for proxy_name, proxy in ta_proxies.items():
            if hasattr(proxy, 'set_quotes'):
                proxy.set_quotes(quotes_data)
        
        return quotes_data
    
    def get_next_bar(
        self, 
        quotes_data: Dict[str, Any], 
        ta_proxies: Dict[str, Any]
    ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.datetime64, PRICE_TYPE]]:
        """
        Get next bar data for strategy execution (backtesting implementation).
        
        Args:
            quotes_data: Quotes data dictionary (from initialize_quotes)
            ta_proxies: Dictionary of TA proxies (for backtesting, set_quotes() is not called)
        
        Returns:
            Tuple of (time_array, open_array, high_array, low_array, close_array, volume_array, current_time, current_price)
            or None if no more data available
        """
        # Extract arrays from quotes_data
        all_time = quotes_data['time']
        all_close = quotes_data['close']
        
        # Check if we've reached the end of data
        if self.i_time >= len(all_close):
            return None
        
        # Get current time and price
        current_time = all_time[self.i_time]
        current_price = all_close[self.i_time]
        
        # Return slices up to current index (inclusive) and current time/price
        return (
            all_time[:self.i_time+1],
            quotes_data['open'][:self.i_time+1],
            quotes_data['high'][:self.i_time+1],
            quotes_data['low'][:self.i_time+1],
            all_close[:self.i_time+1],
            quotes_data['volume'][:self.i_time+1],
            current_time,
            current_price
        )
    

