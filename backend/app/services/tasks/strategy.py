from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Union, List, Tuple, Dict, Any, Callable, TYPE_CHECKING
import traceback
import numpy as np
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide
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

    def order(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        stop_loss: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None,
        take_profit: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None
    ) -> None:
        """
        Place an order. Currently only market orders are supported.
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Order quantity (volume)
            price: Limit price. If None, order is placed as market order.
                  If specified, raises NotImplementedError (not realized).
            stop_loss: Stop loss price. Raises NotImplementedError (not realized).
            take_profit: Take profit price. Raises NotImplementedError (not realized).
        
        Returns:
            None (currently, Order object will be returned in future)
        """
        # Check if limit order or stop loss/take profit are specified
        if price is not None or stop_loss is not None or take_profit is not None:
            raise NotImplementedError("not realized")
        
        # Market order: execute immediately through broker
        if side == OrderSide.BUY:
            self.broker.buy(quantity)
        elif side == OrderSide.SELL:
            self.broker.sell(quantity)
        else:
            raise ValueError(f"Unknown order side: {side}")
    
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
            volume: np.ndarray
        ):
            strategy.time = time
            strategy.open = open
            strategy.high = high
            strategy.low = low
            strategy.close = close
            strategy.volume = volume
            strategy.on_bar()
        
        def __on_finish():
            strategy.on_finish()
        
        return {
            'on_start': __on_start,
            'on_bar': __on_bar,
            'on_finish': __on_finish
        }

    