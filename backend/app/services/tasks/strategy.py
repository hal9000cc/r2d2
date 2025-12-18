from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Union, List, Tuple, Dict, Any
import numpy as np
import time
from app.services.quotes.client import QuotesBackTest
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.core.growing_data2redis import GrowingData2Redis
from app.core.logger import get_logger
from app.core.datetime_utils import parse_utc_datetime64
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

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
    def __init__(self, task: Task, results_save_period: float = TRADE_RESULTS_SAVE_PERIOD):
        """
        Initialize strategy.
        
        Args:
            task: Task instance
            results_save_period: Period for saving results in seconds (default: TRADE_RESULTS_SAVE_PERIOD)
        """
        self.task = task
        self.results_save_period = results_save_period

        self.time: Optional[np.ndarray] = None  # dtype: TIME_TYPE
        self.open: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.high: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.low: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.close: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.volume: Optional[np.ndarray] = None  # dtype: VOLUME_TYPE

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

    @abstractmethod
    def on_start(self):
        """
        Called before the testing loop starts.
        Use this method to initialize any strategy-specific data structures or variables.
        """
        pass

    @abstractmethod
    def on_bar(self):
        """
        Called when a new bar is received.
        """
        pass

    @abstractmethod
    def on_finish(self):
        """
        Called after the testing loop completes.
        Use this method to perform any final calculations or cleanup.
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
    def __init__(self, task: Task, id_result: str):
        super().__init__(task)
        self.id_result = id_result  # Unique ID for this backtesting run
        self.__quotes = QuotesBackTest(task.symbol, task.timeframe, task.dateStart, task.dateEnd, task.source)
        self.fee = 0.001
        self.progress: float = 0.0
        self.date_start: Optional[np.datetime64] = None
        self.date_end: Optional[np.datetime64] = None
        self.time = self.__quotes.time.values[:0]
        self.open = self.__quotes.open.values[:0]
        self.high = self.__quotes.high.values[:0]
        self.low = self.__quotes.low.values[:0]
        self.close = self.__quotes.close.values[:0]
        self.volume = self.__quotes.volume.values[:0]

        
        # Initialize data uploader (optional, depends on task having Redis params)
        self._data_uploader = None
        redis_params = task.get_redis_params()
        if redis_params is not None:
            redis_key = f"backtesting_tasks:result:{task.id}"
            property_names = [
                "time", 
                "open",
                "high",
                "low",
                "close",
                "volume",
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
                id_result=id_result,
            )
            self._data_uploader = None
        
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

        self._init_stats()
        
        # Reset data uploader (if configured)
        if self._data_uploader is not None:
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
            self._update_stats(self.current_deal)
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
            self._update_stats(self.current_deal)
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

        results_save_period = 1.0
        last_save_time =  time.time()

        all_time = self.__quotes.time.values
        all_open = self.__quotes.open.values
        all_high = self.__quotes.high.values
        all_low = self.__quotes.low.values
        all_close = self.__quotes.close.values
        all_volume = self.__quotes.volume.values
        
        self.on_start()
        
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
                self.check_state()
                self.save_results()
                last_save_time = current_time
                results_save_period = min(results_save_period + 1.0, self.results_save_period)

        # Call on_finish after the testing loop
        self.on_finish()

        if self.current_deal is not None:
            self.current_deal.close(self.current_time, self.price, self.fee)
            self.deals.append(self.current_deal)
            self._update_stats(self.current_deal)
            self.current_deal = None

        self.global_deal.close(self.current_time, self.price, self.fee)
        
        # Finalize data upload
        self._finalize_data_upload()

    def _finalize_data_upload(self) -> None:
        """
        Finalize data upload to Redis (if uploader is configured).
        Separated from run() to keep main simulation code clean.
        """
        if self._data_uploader is None:
            return
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

        # Save results to Redis only if uploader is configured
        if self._data_uploader is not None:
            try:
                self._data_uploader.send_changes()
            except Exception as e:
                logger.error(f"Failed to save results to Redis: {e}", exc_info=True)
                raise
    
    def check_state(self) -> None:
        """
        Check if task is still running by reading isRunning flag from Redis.
        If isRunning is False, sends error packet and raises exception to stop backtesting.
        
        Raises:
            RuntimeError: If task is stopped (isRunning == False)
        """
        # Check if task is associated with a list (has Redis connection)
        if self.task._list is None:
            # If no list, skip state check (standalone mode)
            return
        
        try:
            # Load task from Redis to get current state
            current_task = self.task.load()
            if current_task is None:
                logger.warning(f"Task {self.task.id} not found in Redis during state check")
                return
            
            # Check if id_result matches (detect duplicate workers)
            if current_task.id_result != self.id_result:
                # Another worker is running, send error packet and raise exception
                error_message = f"Another backtesting worker is running for this task (expected id_result: {current_task.id_result}, got: {self.id_result})"
                logger.error(f"Task {self.task.id} id_result mismatch: {error_message}")
                
                # Send error packet if uploader is configured
                if self._data_uploader is not None:
                    try:
                        self._data_uploader.send_error_packet(error_message)
                    except Exception as e:
                        logger.error(f"Failed to send error packet: {e}", exc_info=True)
                
                # Raise exception to exit from run() loop
                raise RuntimeError(error_message)

            # Check if task is still running
            if not current_task.isRunning:
                # Task was stopped, send cancel packet and raise exception
                cancel_message = "Backtesting was stopped by user request"
                logger.info(f"Task {self.task.id} stopped: {cancel_message}")
                
                # Send cancel packet if uploader is configured
                if self._data_uploader is not None:
                    try:
                        self._data_uploader.send_cancel_packet(cancel_message)
                    except Exception as e:
                        logger.error(f"Failed to send cancel packet: {e}", exc_info=True)
                
                # Raise exception to exit from run() loop
                raise RuntimeError(cancel_message)
            
        except RuntimeError:
            # Re-raise RuntimeError (task stopped)
            raise
        except Exception as e:
            # Log other errors but don't stop backtesting
            logger.error(f"Failed to check task state: {e}", exc_info=True)
    
    def logging(self, message: str, level: str = "info") -> None:
        """
        Send log message to frontend via task.
        
        Args:
            message: Message text (required)
            level: Message level (optional, default: "info")
                  Valid levels: info, warning, error, success, debug
        """
        self.task.send_message(MessageType.MESSAGE, {"level": level, "message": message})
    
    def on_start(self):
        """
        Called before the testing loop starts.
        Default implementation does nothing.
        """
        pass

    def on_bar(self):
        pass

    def on_finish(self):
        """
        Called after the testing loop completes.
        Default implementation does nothing.
        """
        pass

    