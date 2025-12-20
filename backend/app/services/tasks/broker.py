"""
Broker class for handling trading operations and backtesting execution.
"""
from typing import Optional, Dict, Callable, List
import numpy as np
import time
from app.services.quotes.client import Client
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.strategy import Deal, OrderSide
from app.core.logger import get_logger
from app.core.datetime_utils import parse_utc_datetime, parse_utc_datetime64
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

logger = get_logger(__name__)


class Broker:
    """
    Broker class for handling trading operations and backtesting execution.
    Manages deals, statistics, limit orders, and runs the backtesting loop.
    """
    
    def __init__(
        self, 
        fee: float, 
        task: Task, 
        result_id: str,
        callbacks_dict: Dict[str, Callable],
        results_save_period: float = TRADE_RESULTS_SAVE_PERIOD
    ):
        """
        Initialize broker.
        
        Args:
            fee: Trading fee rate (as fraction, e.g., 0.001 for 0.1%)
            task: Task instance
            result_id: Unique ID for this backtesting run
            callbacks_dict: Dictionary with callback functions:
                - 'on_start': Callable(parameters: Dict[str, Any])
                - 'on_bar': Callable(price, current_time, time, open, high, low, close, volume)
                - 'on_finish': Callable with no arguments
            results_save_period: Period for saving results in seconds (default: TRADE_RESULTS_SAVE_PERIOD)
        """
        self.fee = fee
        self.task = task
        self.result_id = result_id
        self.results_save_period = results_save_period
        self.callbacks = callbacks_dict
        
        # Trading state
        self.price: Optional[PRICE_TYPE] = None
        self.current_time: Optional[np.datetime64] = None
        
        # Progress tracking
        self.progress: float = 0.0
        self.date_start: Optional[np.datetime64] = None
        self.date_end: Optional[np.datetime64] = None
        
        # Limit orders
        self.limit_orders: List = []
        self.limit_orders_ix = np.array([], dtype=np.int32)
        self.limit_orders_price = np.array([], dtype=PRICE_TYPE)
        self.limit_orders_type = np.array([], dtype=np.int8)  # 1 - buy, -1 - sell
        self.limit_orders_quantity = np.array([], dtype=VOLUME_TYPE)
        
        # Deals
        self.deals: List[Deal] = []  # List of closed deals only
        self.global_deal: Optional[Deal] = None
        self.current_deal: Optional[Deal] = None
        
        # Statistics
        self.total_deals = 0
        self.short_deals = 0
        self.long_deals = 0
        self.total_profit = 0.0
        self.total_fees = 0.0
    
    def _init_stats(self):
        """
        Initialize statistics.
        """
        self.total_deals = 0
        self.short_deals = 0
        self.long_deals = 0
        self.total_profit = 0.0
        self.total_fees = 0.0
    
    def _update_stats(self, deal: Deal):
        """
        Update statistics.
        
        Args:
            deal: Deal instance to update statistics from
        """
        self.total_deals += 1
        if deal.side == OrderSide.SELL:
            self.short_deals += 1
        else:
            self.long_deals += 1
        self.total_profit += deal.profit
        self.total_fees += deal.fees
    
    def reset(self):
        """
        Reset broker state (clear deals, statistics, limit orders).
        """
        self.limit_orders = []
        self.limit_orders_ix = np.array([], dtype=np.int32)
        self.limit_orders_price = np.array([], dtype=PRICE_TYPE)
        self.limit_orders_type = np.array([], dtype=np.int8)
        self.limit_orders_quantity = np.array([], dtype=VOLUME_TYPE)
        
        self.deals = []
        self.price = None
        
        # Initialize date range for progress calculation
        try:
            self.date_start = parse_utc_datetime64(self.task.dateStart)
            self.date_end = parse_utc_datetime64(self.task.dateEnd)
        except Exception as e:
            raise RuntimeError(
                f"Failed to parse task dateStart/dateEnd for progress calculation: {e}"
            ) from e
        
        # Initialize progress to 0
        self.progress = 0.0
        
        # Initialize global deal (will be set in run() when we have current_time)
        self.global_deal = None
        self.current_deal = None
        
        self._init_stats()
    
    def __buy(self, volume: VOLUME_TYPE):
        """
        Execute a buy operation on both current and global deals.
        
        Args:
            volume: Volume to buy
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
        
        Args:
            volume: Volume to sell
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
    
    def buy(self, volume: VOLUME_TYPE):
        """
        Public method to execute buy operation.
        
        Args:
            volume: Volume to buy
        """
        self.__buy(volume)
    
    def sell(self, volume: VOLUME_TYPE):
        """
        Public method to execute sell operation.
        
        Args:
            volume: Volume to sell
        """
        self.__sell(volume)
    
    def update_state(self) -> None:
        """
        Update task state and progress.
        Checks if task is still running by reading isRunning flag from Redis.
        Calculates and sends progress update via MessageType.EVENT.
        If isRunning is False, sends error notification and raises exception to stop backtesting.
        
        Raises:
            RuntimeError: If task is stopped (isRunning == False) or duplicate worker detected
        """
        # Check if task is associated with a list (has Redis connection)
        if self.task._list is None:
            # If no list, skip state update (standalone mode)
            return
        
        # Calculate and update progress based on current_time and date range
        total_delta = self.date_end - self.date_start
        current_delta = self.current_time - self.date_start
        # Progress from 0 to 100 as we move from date_start to date_end
        progress = float(current_delta / total_delta * 100.0)
        # Clamp to [0, 100] and round to 1 decimal place
        self.progress = round(max(0.0, min(100.0, progress)), 1)
        
        # Send progress update via event
        self.task.send_message(MessageType.EVENT, {"event": "backtesting_progress", "progress": self.progress})
        
        # Load task from Redis to get current state
        current_task = self.task.load()
        if current_task is None:
            logger.warning(f"Task {self.task.id} not found in Redis during state update")
            return
        
        # Check if result_id matches (detect duplicate workers)
        if current_task.result_id != self.result_id:
            # Another worker is running, send error notification and raise exception
            error_message = f"Another backtesting worker is running for this task (expected result_id: {current_task.result_id}, got: {self.result_id})"
            logger.error(f"Task {self.task.id} result_id mismatch: {error_message}")
            
            # Send error notification
            self.task.backtesting_error(error_message)
            
            # Raise exception to exit from run() loop
            raise RuntimeError(error_message)
        
        # Check if task is still running
        if not current_task.isRunning:
            # Task was stopped, send error notification and raise exception
            cancel_message = "Backtesting was stopped by user request"
            logger.info(f"Task {self.task.id} stopped: {cancel_message}")
            
            # Send error notification
            self.task.backtesting_error(cancel_message)
            
            # Raise exception to exit from run() loop
            raise RuntimeError(cancel_message)
    
    def logging(self, message: str, level: str = "info") -> None:
        """
        Send log message to frontend via task.
        
        Args:
            message: Message text (required)
            level: Message level (optional, default: "info")
                  Valid levels: info, warning, error, success, debug
        """
        self.task.send_message(MessageType.MESSAGE, {"level": level, "message": message})
    
    def run(self, task: Task):
        """
        Run backtest strategy.
        Loads market data and iterates through bars, calling on_bar for each bar.
        Periodically updates state and progress based on results_save_period.
        
        Args:
            task: Task instance (used to get symbol, timeframe, dateStart, dateEnd, source)
        """
        # Reset broker state
        self.reset()
        
        # Convert timeframe string to Timeframe object
        try:
            timeframe = Timeframe.cast(task.timeframe)
        except Exception as e:
            raise RuntimeError(f"Failed to parse timeframe '{task.timeframe}': {e}") from e
        
        # Convert date strings to datetime objects using datetime_utils
        try:
            history_start = parse_utc_datetime(task.dateStart)
            history_end = parse_utc_datetime(task.dateEnd)
        except Exception as e:
            raise RuntimeError(f"Failed to parse dateStart/dateEnd: {e}") from e
        
        # Get quotes data directly from Client
        client = Client()
        logger.debug(f"Getting quotes for {task.source}:{task.symbol}:{task.timeframe} from {history_start} to {history_end}")
        quotes_data = client.get_quotes(task.source, task.symbol, timeframe, history_start, history_end)
        logger.debug(f"Quotes received: {len(quotes_data['time'])} bars")
        
        # Extract numpy arrays directly
        all_time = quotes_data['time']
        all_open = quotes_data['open']
        all_high = quotes_data['high']
        all_low = quotes_data['low']
        all_close = quotes_data['close']
        all_volume = quotes_data['volume']
        
        # Initialize current_time from first bar
        if len(all_time) > 0:
            self.current_time = all_time[0]
        else:
            raise RuntimeError("No quotes data available for backtesting")
        
        # Initialize global deal
        self.global_deal = Deal(
            side=None,
            entry_time=self.current_time,
            entry_price=0.0,
            initial_balance=0.0
        )
        
        state_update_period = 1.0
        last_update_time = time.time()
        
        # Call on_start callback with task parameters
        if 'on_start' in self.callbacks:
            self.callbacks['on_start'](task.parameters)
        
        for i in range(len(all_close)):
            # Set current time and price for deal operations
            self.current_time = all_time[i]
            self.price = all_close[i]
            
            # Prepare arrays for this bar
            time_array = all_time[:i+1]
            open_array = all_open[:i+1]
            high_array = all_high[:i+1]
            low_array = all_low[:i+1]
            close_array = all_close[:i+1]
            volume_array = all_volume[:i+1]
            
            # Call on_bar callback with all necessary data
            if 'on_bar' in self.callbacks:
                self.callbacks['on_bar'](
                    self.price,
                    self.current_time,
                    time_array,
                    open_array,
                    high_array,
                    low_array,
                    close_array,
                    volume_array
                )
            
            # Check if it's time to update state and progress
            current_time = time.time()
            if current_time - last_update_time >= self.results_save_period:
                self.update_state()
                last_update_time = current_time
                state_update_period = min(state_update_period + 1.0, self.results_save_period)
        
        # Call on_finish callback
        if 'on_finish' in self.callbacks:
            self.callbacks['on_finish']()
        
        # Finalize any open deal
        if self.current_deal is not None:
            self.current_deal.close(self.current_time, self.price, self.fee)
            self.deals.append(self.current_deal)
            self._update_stats(self.current_deal)
            self.current_deal = None
        
        # Close global deal
        self.global_deal.close(self.current_time, self.price, self.fee)
        
        # Set current_time to date_end to ensure progress is 100% for final update
        self.current_time = self.date_end
        self.update_state()

