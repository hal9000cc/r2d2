from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Union, List, Tuple, Dict, Any, Callable, TYPE_CHECKING
import traceback
import numpy as np
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide, OrderResult, CancelOrderResult
from app.core.logger import get_logger
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

if TYPE_CHECKING:
    from app.services.tasks.broker_backtesting import BrokerBacktesting as Broker, ta_proxy

logger = get_logger(__name__)

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
    ) -> OrderResult:
        """
        Place a buy order. Supports market, limit, and stop orders.
        
        Args:
            quantity: Order quantity (volume)
            price: Limit price. If None and trigger_price is None, order is placed as market order.
            trigger_price: Trigger price for stop order (breakout order).
            stop_loss: Stop loss price. Raises NotImplementedError (not realized).
            take_profit: Take profit price. Raises NotImplementedError (not realized).
        
        Returns:
            OrderResult with 'trades', 'deals', 'orders', and 'errors' lists
        """
        # Check if stop loss/take profit are specified
        if stop_loss is not None or take_profit is not None:
            raise NotImplementedError("not realized")
        
        # Validate: either price or trigger_price, but not both
        if price is not None and trigger_price is not None:
            error_result = OrderResult(
                trades=[],
                deals=[],
                orders=[],
                errors=["Cannot specify both price and trigger_price"]
            )
            self._log_result_errors(error_result.errors, "buy")
            return error_result
        
        # Execute through broker
        result = self.broker.buy(quantity, price=price, trigger_price=trigger_price)
        
        # Log errors if any
        self._log_result_errors(result.errors, "buy")
        
        return result
    
    def sell(
        self,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        trigger_price: Optional[PRICE_TYPE] = None,
        stop_loss: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None,
        take_profit: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None
    ) -> OrderResult:
        """
        Place a sell order. Supports market, limit, and stop orders.
        
        Args:
            quantity: Order quantity (volume)
            price: Limit price. If None and trigger_price is None, order is placed as market order.
            trigger_price: Trigger price for stop order (breakout order).
            stop_loss: Stop loss price. Raises NotImplementedError (not realized).
            take_profit: Take profit price. Raises NotImplementedError (not realized).
        
        Returns:
            OrderResult with 'trades', 'deals', 'orders', and 'errors' lists
        """
        # Check if stop loss/take profit are specified
        if stop_loss is not None or take_profit is not None:
            raise NotImplementedError("not realized")
        
        # Validate: either price or trigger_price, but not both
        if price is not None and trigger_price is not None:
            error_result = OrderResult(
                trades=[],
                deals=[],
                orders=[],
                errors=["Cannot specify both price and trigger_price"]
            )
            self._log_result_errors(error_result.errors, "sell")
            return error_result
        
        # Execute through broker
        result = self.broker.sell(quantity, price=price, trigger_price=trigger_price)
        
        # Log errors if any
        self._log_result_errors(result.errors, "sell")
        
        return result
    
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
        Log errors from result objects (OrderResult, CancelOrderResult).
        Logs to both frontend messages and logger.
        
        Args:
            errors: List of error messages
            method_name: Name of the method that produced the errors (for prefix)
        """
        for error in errors:
            self.logging(f"{method_name}(): {error}", level="error")
            logger.info(f"{method_name}(): {error}")
    
    def cancel_orders(self, order_ids: List[int]) -> CancelOrderResult:
        """
        Cancel orders by their IDs.
        
        Args:
            order_ids: List of order IDs to cancel
        
        Returns:
            CancelOrderResult with failed_orders and errors lists
        """
        result = self.broker.cancel_orders(order_ids)
        
        # Log errors if any
        self._log_result_errors(result.errors, "cancel_orders")
        
        return result
    
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

    