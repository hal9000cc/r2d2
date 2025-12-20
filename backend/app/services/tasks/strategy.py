from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Union, List, Tuple, Dict, Any, Callable, TYPE_CHECKING
import numpy as np
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.core.logger import get_logger
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

if TYPE_CHECKING:
    from app.services.tasks.broker import Broker

logger = get_logger(__name__)


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class Deal:
    """
    Represents a trading deal with buy/sell mechanics.
    """
    def __init__(self, side: OrderSide, entry_time: np.datetime64, entry_price: PRICE_TYPE, initial_balance: PRICE_TYPE = 0.0):
        self.side = side  # Order side (BUY or SELL)
        self.entry_time = entry_time  # Time when position was opened
        self.exit_time: Optional[np.datetime64] = None  # Time when position was closed (None if still open)
        self.entry_price = entry_price  # Price at which position was opened
        self.exit_price: Optional[PRICE_TYPE] = None  # Price at which position was closed (None if still open)
        self.max_volume: VOLUME_TYPE = 0.0  # Maximum absolute value of symbol_balance
        self.profit: PRICE_TYPE = 0.0  # Total profit/loss from the deal (symbol_balance after closing)
        self.fees: PRICE_TYPE = 0.0  # Total fees paid for the deal
        
        # Internal state
        self._symbol_balance: VOLUME_TYPE = 0.0  # Current symbol balance (can go negative)
        self._balance: PRICE_TYPE = initial_balance  # Current cash balance
    
    def buy(self, volume: VOLUME_TYPE, price: PRICE_TYPE, fee: PRICE_TYPE):
        """
        Execute a buy operation.
        
        Args:
            volume: Volume to buy
            price: Price per unit
            fee: Fee rate (as fraction, e.g., 0.001 for 0.1%)
        """
        fees = volume * price * fee
        self._symbol_balance += volume
        self._balance -= fees + volume * price
        self.fees += fees
        
        # Update max_volume (maximum absolute value of symbol_balance)
        if self.max_volume < abs(self._symbol_balance):
            self.max_volume = abs(self._symbol_balance)
    
    def sell(self, volume: VOLUME_TYPE, price: PRICE_TYPE, fee: PRICE_TYPE):
        """
        Execute a sell operation.
        
        Args:
            volume: Volume to sell
            price: Price per unit
            fee: Fee rate (as fraction, e.g., 0.001 for 0.1%)
        """
        fees = volume * price * fee
        self._symbol_balance -= volume
        self._balance += volume * price - fees
        self.fees += fees
        
        # Update max_volume (maximum absolute value of symbol_balance)
        if self.max_volume < abs(self._symbol_balance):
            self.max_volume = abs(self._symbol_balance)
    
    def close(self, exit_time: np.datetime64, exit_price: PRICE_TYPE, fee: PRICE_TYPE):
        """
        Close the deal by closing the position first.
        
        Args:
            exit_time: Time when position was closed
            exit_price: Price at which position was closed
            fee: Fee rate (as fraction, e.g., 0.001 for 0.1%)
        """
        # Close the position: if in long (symbol_balance > 0), sell; if in short (symbol_balance < 0), buy
        if self._symbol_balance > 0:
            # We are in long position, need to sell
            self.sell(self._symbol_balance, exit_price, fee)
        elif self._symbol_balance < 0:
            # We are in short position, need to buy
            self.buy(abs(self._symbol_balance), exit_price, fee)
        
        self.exit_time = exit_time
        self.exit_price = exit_price
        # Profit is the balance after closing (with fees already accounted for)
        self.profit = self._balance
    
    def has_zero_balance(self) -> bool:
        """
        Check if the position has zero balance (symbol_balance == 0).
        This means the position is balanced (no open position).
        
        Returns:
            True if balance is zero, False otherwise
        """
        return self._symbol_balance == 0


class Order:
    def __init__(self, strategy: 'Strategy'):
        self.strategy = strategy


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

    def _init_stats(self):
        """
        Initialize statistics.
        """
        self.total_deals = 0
        self.short_deals = 0
        self.long_deals = 0
        self.total_profit = 0
        self.total_fees = 0

    def _update_stats(self, deal: Deal):
        """
        Update statistics.
        """
        self.total_deals += 1
        if deal.side == OrderSide.SELL:
            self.short_deals += 1
        else:
            self.long_deals += 1
        self.total_profit += deal.profit
        self.total_fees += deal.fees

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
    def create_strategy_callbacks(strategy: 'Strategy') -> Dict[str, Callable]:
        """
        Create callbacks for broker with closure on strategy.
        
        Args:
            strategy: Strategy instance
            
        Returns:
            Dictionary with callback functions for broker
        """
        def __on_start(parameters: Dict[str, Any]):
            strategy.parameters = parameters
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

    