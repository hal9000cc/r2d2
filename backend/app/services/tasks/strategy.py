from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Union, List, Tuple, Dict, Any, Callable, TYPE_CHECKING
import traceback
import numpy as np
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide, OrderStatus
from pydantic import BaseModel, Field
from app.core.logger import get_logger
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

# Import Order for runtime use (needed for OrderOperationResult)
from app.services.tasks.broker_backtesting import Order

if TYPE_CHECKING:
    from app.services.tasks.broker_backtesting import BrokerBacktesting as Broker, ta_proxy

logger = get_logger(__name__)


class OrderOperationResult(BaseModel):
    """
    Result of order operation (buy/sell/cancel).
    Contains orders, error messages, and categorized order IDs by status.
    """
    orders: List['Order'] = Field(default_factory=list, description="List of orders created by this operation")
    error_messages: List[str] = Field(default_factory=list, description="List of error messages (if any)")
    active: List[int] = Field(default_factory=list, description="List of active order IDs")
    executed: List[int] = Field(default_factory=list, description="List of executed order IDs")
    canceled: List[int] = Field(default_factory=list, description="List of canceled order IDs")
    error: List[int] = Field(default_factory=list, description="List of error order IDs")


class Strategy(ABC):
    def __init__(self):
        """
        Initialize strategy.
        """
        self.time: Optional[np.ndarray] = None  # dtype: TIME_TYPE
        self.open: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.high: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.low: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.close: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.volume: Optional[np.ndarray] = None  # dtype: VOLUME_TYPE
        
        # Equity tracking (updated on each bar)
        self.equity_usd: PRICE_TYPE = 0.0
        self.equity_symbol: VOLUME_TYPE = 0.0
        
        # Parameters will be set in on_start callback
        self.parameters: Optional[Dict[str, Any]] = None
        
        # Broker will be set when callbacks are created
        self.broker: Optional[Broker] = None

        # TA proxy will be set when callbacks are created
        self.talib: Optional[ta_proxy] = None

    def on_start(self):
        """
        Called before the testing loop starts.
        Use this method to initialize any strategy-specific data structures or variables.
        Default implementation does nothing.
        """
        pass

    @abstractmethod
    def on_bar(self):
        """
        Called when a new bar is received.
        """
        pass

    def on_finish(self):
        """
        Called after the testing loop completes.
        Use this method to perform any final calculations or cleanup.
        Default implementation does nothing.
        """
        pass

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
        Default implementation returns empty dictionary (no parameters).
        """
        return {}

    def buy(
        self,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        trigger_price: Optional[PRICE_TYPE] = None,
        stop_loss: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None,
        take_profit: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None
    ) -> OrderOperationResult:
        """
        Place a buy order. Supports market, limit, and stop orders.
        
        Args:
            quantity: Order quantity (volume)
            price: Limit price. If None and trigger_price is None, order is placed as market order.
            trigger_price: Trigger price for stop order (breakout order).
            stop_loss: Stop loss price. Raises NotImplementedError (not realized).
            take_profit: Take profit price. Raises NotImplementedError (not realized).
        
        Returns:
            OrderOperationResult with orders, error_messages, and categorized order IDs
        """
        # Check if stop loss/take profit are specified
        if stop_loss is not None or take_profit is not None:
            raise NotImplementedError("not realized")
        
        # Execute through broker (returns List[Order])
        orders = self.broker.buy(quantity, price=price, trigger_price=trigger_price)
        
        # Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        error_ids = [order.order_id for order in orders if order.status == OrderStatus.ERROR]
        
        # Log errors if any
        if all_errors:
            self._log_result_errors(all_errors, "buy")
        
        return OrderOperationResult(
            orders=orders,
            error_messages=all_errors,
            active=active_ids,
            executed=executed_ids,
            error=error_ids
        )
    
    def sell(
        self,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        trigger_price: Optional[PRICE_TYPE] = None,
        stop_loss: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None,
        take_profit: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None
    ) -> OrderOperationResult:
        """
        Place a sell order. Supports market, limit, and stop orders.
        
        Args:
            quantity: Order quantity (volume)
            price: Limit price. If None and trigger_price is None, order is placed as market order.
            trigger_price: Trigger price for stop order (breakout order).
            stop_loss: Stop loss price. Raises NotImplementedError (not realized).
            take_profit: Take profit price. Raises NotImplementedError (not realized).
        
        Returns:
            OrderOperationResult with orders, error_messages, and categorized order IDs
        """
        # Check if stop loss/take profit are specified
        if stop_loss is not None or take_profit is not None:
            raise NotImplementedError("not realized")
        
        # Execute through broker (returns List[Order])
        orders = self.broker.sell(quantity, price=price, trigger_price=trigger_price)
        
        # Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        error_ids = [order.order_id for order in orders if order.status == OrderStatus.ERROR]
        
        # Log errors if any
        if all_errors:
            self._log_result_errors(all_errors, "sell")
        
        return OrderOperationResult(
            orders=orders,
            error_messages=all_errors,
            active=active_ids,
            executed=executed_ids,
            error=error_ids
        )
    
    def logging(self, message: str, level: str = "info") -> None:
        """
        Send log message to frontend via broker.
        Proxies to broker.logging().
        
        Args:
            message: Message text (required)
            level: Message level (optional, default: "info")
                  Valid levels: info, warning, error, success, debug
        """
        if self.broker is None:
            raise RuntimeError("Broker not initialized. Cannot send log message.")
        self.broker.logging(message, level)
    
    def _log_result_errors(self, errors: List[str], method_name: str) -> None:
        """
        Log errors from result objects (OrderOperationResult).
        Logs to both frontend messages and logger.
        
        Args:
            errors: List of error messages
            method_name: Name of the method that produced the errors (for prefix)
        """
        for error in errors:
            self.logging(f"{method_name}(): {error}", level="error")
            logger.info(f"{method_name}(): {error}")
    
    def cancel_orders(self, order_ids: List[int]) -> OrderOperationResult:
        """
        Cancel orders by their IDs.
        
        Args:
            order_ids: List of order IDs to cancel
        
        Returns:
            OrderOperationResult with canceled order IDs and any errors
        """
        canceled_orders = self.broker.cancel_orders(order_ids)
        
        # Extract canceled order IDs
        canceled_ids = [order.order_id for order in canceled_orders]
        
        # Find orders that were not found (not in canceled list)
        error_ids = []
        error_messages = []
        for order_id in order_ids:
            if order_id not in canceled_ids:
                error_ids.append(order_id)
                error_messages.append(f"cancel_orders(): Order {order_id} not found")
        
        # Log errors if any
        if error_messages:
            self._log_result_errors(error_messages, "cancel_orders")
        
        return OrderOperationResult(
            orders=[order.model_copy(deep=True) for order in canceled_orders],
            error_messages=error_messages,
            canceled=canceled_ids,
            error=error_ids
        )
    
    @staticmethod
    def is_strategy_error(exception: Exception) -> Tuple[bool, Optional[str]]:
        """
        Analyze exception traceback to determine if error occurred in strategy code.
        
        Args:
            exception: Exception that occurred
            
        Returns:
            Tuple of (is_strategy_error: bool, error_message: Optional[str])
            If is_strategy_error is True, error_message contains formatted message with line number.
        """
        tb = exception.__traceback__
        if tb is None:
            return False, None
        
        # Collect all traceback frames
        frames = traceback.extract_tb(tb)
        
        # Look for strategy-related frames
        strategy_frame = None
        for frame in frames:
            func_name = frame.name
            
            # Check if frame is in strategy code by method names: on_bar, on_start, on_finish
            if func_name in ('on_bar', 'on_start', 'on_finish'):
                strategy_frame = frame
                break
        
        if strategy_frame is None:
            return False, None
        
        # Format error message
        method_name = strategy_frame.name
        line_no = strategy_frame.lineno
        line_text = strategy_frame.line or ""
        
        error_msg = (
            f"Error in strategy code: {exception.__class__.__name__}: {str(exception)}\n"
            f"Location: method '{method_name}' at line {line_no}"
        )
        
        if line_text.strip():
            error_msg += f"\nCode: {line_text.strip()}"
        
        return True, error_msg
    
    @staticmethod
    def create_strategy_callbacks(strategy: 'Strategy') -> Dict[str, Callable]:
        """
        Create callbacks for broker with closure on strategy.
        
        Args:
            strategy: Strategy instance
            
        Returns:
            Dictionary with callback functions for broker
        """
        def __on_start(parameters: Dict[str, Any], ta_proxies: Dict[str, ta_proxy]):
            strategy.parameters = parameters
            # Set TA library proxies as strategy attributes
            for name, proxy in ta_proxies.items():
                setattr(strategy, name, proxy)
            strategy.on_start()
        
        def __on_bar(
            price: PRICE_TYPE,
            current_time: np.datetime64,
            time: np.ndarray,
            open: np.ndarray,
            high: np.ndarray,
            low: np.ndarray,
            close: np.ndarray,
            volume: np.ndarray,
            equity_usd: PRICE_TYPE,
            equity_symbol: VOLUME_TYPE
        ):
            strategy.time = time
            strategy.open = open
            strategy.high = high
            strategy.low = low
            strategy.close = close
            strategy.volume = volume
            strategy.equity_usd = equity_usd
            strategy.equity_symbol = equity_symbol
            strategy.on_bar()
        
        def __on_finish():
            strategy.on_finish()
        
        return {
            'on_start': __on_start,
            'on_bar': __on_bar,
            'on_finish': __on_finish
        }

    