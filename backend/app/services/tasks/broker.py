"""
Broker class for handling trading operations and backtesting execution.
"""
from typing import Optional, Dict, Callable, List
from enum import Enum
import numpy as np
import time
from pydantic import BaseModel
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.core.logger import get_logger
from app.core.datetime_utils import parse_utc_datetime, parse_utc_datetime64, datetime64_to_iso
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

logger = get_logger(__name__)


class Trade(BaseModel):
    """
    Represents a single trade (buy or sell operation).
    """
    price: PRICE_TYPE
    quantity: VOLUME_TYPE
    fee: PRICE_TYPE
    sum: PRICE_TYPE


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class Broker:
    """
    Broker class for handling trading operations and backtesting execution.
    Minimal working version with buy/sell stubs.
    """
    
    # Note: This is a minimal version. All deal-related code has been removed
    # since buy() and sell() are stubs and don't create any deals.
    
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
    
    def reset(self):
        """
        Reset broker state.
        """
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
        
        # Reset equity
        self.equity_usd = 0.0
        self.equity_symbol = 0.0
        self.trades = []
    
    def buy(self, quantity: VOLUME_TYPE):
        """
        Execute buy operation.
        Increases equity_symbol and decreases equity_usd.
        
        Args:
            quantity: Quantity to buy
        """
        if self.price is None:
            raise RuntimeError("Cannot execute buy: price is not set")
        
        # Calculate trade amount and fee
        trade_amount = quantity * self.price
        trade_fee = trade_amount * self.fee
        
        # Update equity
        self.equity_symbol += quantity
        self.equity_usd -= trade_amount + trade_fee
        
        # Create and store trade
        trade = Trade(
            price=self.price,
            quantity=quantity,
            fee=trade_fee,
            sum=trade_amount
        )
        self.trades.append(trade)
    
    def sell(self, quantity: VOLUME_TYPE):
        """
        Execute sell operation.
        Decreases equity_symbol and increases equity_usd.
        
        Args:
            quantity: Quantity to sell
        """
        if self.price is None:
            raise RuntimeError("Cannot execute sell: price is not set")
        
        # Calculate trade amount and fee
        trade_amount = quantity * self.price
        trade_fee = trade_amount * self.fee
        
        # Update equity
        self.equity_symbol -= quantity
        self.equity_usd += trade_amount - trade_fee
        
        # Create and store trade
        trade = Trade(
            price=self.price,
            quantity=quantity,
            fee=trade_fee,
            sum=trade_amount
        )
        self.trades.append(trade)
    
    def close_deals(self):
        """
        Close all open positions by executing opposite trades.
        If equity_symbol > 0, sell it. If equity_symbol < 0, buy it.
        """
        if self.equity_symbol > 0:
            self.sell(self.equity_symbol)
        elif self.equity_symbol < 0:
            self.buy(abs(self.equity_symbol))
    
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
        
        # Convert datetime64 to ISO strings for frontend
        date_start_iso = datetime64_to_iso(self.date_start) if self.date_start is not None else None
        current_time_iso = datetime64_to_iso(self.current_time) if self.current_time is not None else None
        
        # Send progress update via event
        self.task.send_message(
            MessageType.EVENT, 
            {
                "event": "backtesting_progress", 
                "progress": self.progress,
                "date_start": date_start_iso,
                "current_time": current_time_iso
            }
        )
        
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
        client = QuotesClient()
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
        
        state_update_period = 1.0
        last_update_time = time.time()
        
        # Call on_start callback with task parameters
        if 'on_start' in self.callbacks:
            self.callbacks['on_start'](task.parameters)
        
        for i in range(len(all_close)):
            # Set current time and price
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
        
        # Close all open positions
        self.close_deals()
        
        # Set current_time to date_end to ensure progress is 100% for final update
        self.current_time = self.date_end
        self.update_state()


class Deal:
    """
    Represents a trading deal with buy/sell mechanics.
    """
    def __init__(self, side: Optional[OrderSide], entry_time: np.datetime64, entry_price: PRICE_TYPE, initial_balance: PRICE_TYPE = 0.0):
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


class BrokerOld:
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
        
        # Convert datetime64 to ISO strings for frontend
        date_start_iso = datetime64_to_iso(self.date_start) if self.date_start is not None else None
        current_time_iso = datetime64_to_iso(self.current_time) if self.current_time is not None else None
        
        # Send progress update via event
        self.task.send_message(
            MessageType.EVENT, 
            {
                "event": "backtesting_progress", 
                "progress": self.progress,
                "date_start": date_start_iso,
                "current_time": current_time_iso
            }
        )
        
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
        client = QuotesClient()
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


