from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Union, List, Tuple, Dict, Any
import numpy as np
import time
import weakref
from app.services.quotes.client import QuotesBackTest
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE, TIME_TYPE
from app.services.tasks.tasks import Task
from app.core.growing_data2redis import GrowingData2Redis
from app.core.logger import get_logger
from app.core.datetime_utils import parse_utc_datetime64

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
    def __init__(self, task: Task, results_save_period: float = 1.0):
        """
        Initialize strategy.
        
        Args:
            task: Task instance
            results_save_period: Period for saving results in seconds (default: 1.0)
        """
        self.task = task
        self.results_save_period = results_save_period

        self.time: Optional[np.ndarray] = None  # dtype: TIME_TYPE
        self.open: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.high: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.low: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.close: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.volume: Optional[np.ndarray] = None  # dtype: VOLUME_TYPE

    def init_stats(self):
        """
        Initialize statistics.
        """
        self.total_deals = 0
        self.short_deals = 0
        self.long_deals = 0
        self.total_profit = 0
        self.total_fees = 0

    def update_stats(self, deal: Deal):
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

    @abstractmethod
    def on_bar(self):
        """
        Called when a new bar is received.
        """
        pass

    @staticmethod
    @abstractmethod
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
        pass

    @abstractmethod
    def order(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        stop_loss: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None,
        take_profit: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None
    ) -> Order:
        """
        Place an order.
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Order quantity (volume)
            price: Limit price. If None, order is placed as market order.
                  If specified, order is placed as limit order, but may be executed
                  at market price if market price is better than the limit price.
            stop_loss: Stop loss price or list of tuples (volume, price) for partial stop loss levels.
                      If a single price is provided, stop loss is set for the entire order quantity.
                      If a list of tuples is provided, each tuple defines a partial stop loss level
                      with specific volume and price.
            take_profit: Take profit price or list of tuples (volume, price) for partial take profit levels.
                        If a single price is provided, take profit is set for the entire order quantity.
                        If a list of tuples is provided, each tuple defines a partial take profit level
                        with specific volume and price.
        
        Returns:
            Order object representing the placed order
        """
        pass
    

class StrategyBacktest(Strategy):
    def __init__(self, task: Task):
        super().__init__(task)
        self.__quotes = QuotesBackTest(task.symbol, task.timeframe, task.dateStart, task.dateEnd, task.source)
        self.fee = 0.001
        self.progress: float = 0.0
        self.date_start: Optional[np.datetime64] = None
        self.date_end: Optional[np.datetime64] = None
        
        # Initialize data uploader
        redis_params = task.get_redis_params()
        redis_key = f"backtesting_tasks:result:{task.id}"
        property_names = [
            "total_deals",
            "short_deals",
            "long_deals",
            "total_profit",
            "total_fees",
            "deals",
            "progress",
        ]
        self._data_uploader = GrowingData2Redis(
            redis_params=redis_params,
            redis_key=redis_key,
            source_object=self,
            property_names=property_names,
        )
        
        self.__reset()

    def __reset(self):

        self.limit_orders = []
        self.limit_orders_ix = np.array([], dtype=np.int32)
        self.limit_orders_price = np.array([], dtype=PRICE_TYPE)
        self.limit_orders_type = np.array([], dtype=np.int8) # 1 - buy, -1 - sell
        self.limit_orders_quantity = np.array([], dtype=VOLUME_TYPE)

        self.deals = []  # List of closed deals only

        self.price = None
        self.current_time = self.__quotes.time.values[0]

        # Initialize date range for progress calculation (must be valid)
        try:
            self.date_start = parse_utc_datetime64(self.task.dateStart)
            self.date_end = parse_utc_datetime64(self.task.dateEnd)
        except Exception as e:
            raise RuntimeError(
                f"Failed to parse task dateStart/dateEnd for progress calculation: {e}"
            ) from e

        # Initialize progress to 0
        self.progress = 0.0

        self.global_deal = Deal(
            side=None,
            entry_time=self.current_time,
            entry_price=0.0,
            initial_balance=0.0
        )
        
        # Current deal (None initially, created on first buy/sell)
        self.current_deal: Optional[Deal] = None

        self.init_stats()
        
        # Reset data uploader
        self._data_uploader.reset()

    def __buy(self, volume: VOLUME_TYPE):
        """
        Execute a buy operation on both current and global deals.
        """
        # Create current deal if it doesn't exist
        if self.current_deal is None:
            self.current_deal = Deal(
                side=OrderSide.BUY,
                entry_time=self.current_time,
                entry_price=self.price,
                initial_balance=0.0
            )
        
        # Execute buy on both deals
        self.current_deal.buy(volume, self.price, self.fee)
        self.global_deal.buy(volume, self.price, self.fee)
        
        # Check if position is balanced (symbol_balance == 0)
        # If so, finalize the deal and move it to completed deals
        if self.current_deal.has_zero_balance():
            self.current_deal.close(self.current_time, self.price, self.fee)
            self.deals.append(self.current_deal)
            self.update_stats(self.current_deal)
            self.current_deal = None

    def __sell(self, volume: VOLUME_TYPE):
        """
        Execute a sell operation on both current and global deals.
        """
        # Create current deal if it doesn't exist
        if self.current_deal is None:
            self.current_deal = Deal(
                side=OrderSide.SELL,
                entry_time=self.current_time,
                entry_price=self.price,
                initial_balance=0.0
            )
        
        # Execute sell on both deals
        self.current_deal.sell(volume, self.price, self.fee)
        self.global_deal.sell(volume, self.price, self.fee)
        
        # Check if position is balanced (symbol_balance == 0)
        # If so, finalize the deal and move it to completed deals
        if self.current_deal.has_zero_balance():
            self.current_deal.close(self.current_time, self.price, self.fee)
            self.deals.append(self.current_deal)
            self.update_stats(self.current_deal)
            self.current_deal = None

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
            Order object representing the placed order
        """
        # Check if limit order or stop loss/take profit are specified
        if price is not None or stop_loss is not None or take_profit is not None:
            raise NotImplementedError("not realized")
        
        # Market order: execute immediately
        if side == OrderSide.BUY:
            self.__buy(quantity)
        elif side == OrderSide.SELL:
            self.__sell(quantity)
        else:
            raise ValueError(f"Unknown order side: {side}")
        

    def run(self):
        """
        Run backtest strategy.
        Loads market data and iterates through bars, calling on_bar for each bar.
        Periodically saves results based on results_save_period.
        """

        last_save_time =  time.time()

        all_time = self.__quotes.time.values
        all_open = self.__quotes.open.values
        all_high = self.__quotes.high.values
        all_low = self.__quotes.low.values
        all_close = self.__quotes.close.values
        all_volume = self.__quotes.volume.values
        
        for i in range(len(all_close)):
            self.time = all_time[:i+1]
            self.open = all_open[:i+1]
            self.high = all_high[:i+1]
            self.low = all_low[:i+1]
            self.close = all_close[:i+1]
            self.volume = all_volume[:i+1]
            
            # Set current time and price for deal operations
            self.current_time = all_time[i]
            self.price = all_close[i]
            
            self.on_bar()
            
            # Check if it's time to save results
            current_time = time.time()
            if current_time - last_save_time >= self.results_save_period:
                self.save_results()
                last_save_time = current_time

        if self.current_deal is not None:
            self.current_deal.close(self.current_time, self.price, self.fee)
            self.deals.append(self.current_deal)
            self.update_stats(self.current_deal)
            self.current_deal = None

        self.global_deal.close(self.current_time, self.price, self.fee)
        
        # Finalize data upload
        try:
            self._data_uploader.finish()
        except Exception as e:
            logger.error(f"Failed to finish data upload to Redis: {e}", exc_info=True)
            raise
    
    def save_results(self) -> None:
        """
        Save results periodically during backtesting.
        Uploads changes to Redis.
        """
        # Update progress based on current_time and date range
        total_delta = self.date_end - self.date_start
        current_delta = self.current_time - self.date_start
        # Progress from 0 to 100 as we move from date_start to date_end
        progress = float(current_delta / total_delta * 100.0)
        # Clamp to [0, 100] and round to integer
        self.progress = round(max(0.0, min(100.0, progress)))

        try:
            self._data_uploader.send_changes()
        except Exception as e:
            logger.error(f"Failed to save results to Redis: {e}", exc_info=True)
            raise
    
    def on_bar(self):
        pass

    