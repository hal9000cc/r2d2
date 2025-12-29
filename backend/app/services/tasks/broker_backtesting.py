"""
Broker class for handling trading operations and backtesting execution.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Callable, List, Tuple, Union
import inspect
import numpy as np
import time
import talib
from pydantic import BaseModel
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import Broker, OrderSide
from app.services.tasks.backtesting_result import BackTestingResults
from app.core.logger import get_logger
from app.core.datetime_utils import parse_utc_datetime, parse_utc_datetime64, datetime64_to_iso
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

logger = get_logger(__name__)


class IndicatorDescription(BaseModel):
    """
    Description of technical analysis indicator.
    """
    values: List[str]  # List of positional parameter names (open, high, low, close, volume) in order


class ta_proxy(ABC):
    """
    Abstract base class for technical analysis indicator proxy.
    Different implementations for different TA libraries (talib, ta, etc.)
    """
    
    def __init__(self, broker, quotes_data: dict):
        """
        Initialize TA proxy.
        
        Args:
            broker: Reference to broker instance
            quotes_data: Dictionary with quotes data (time, open, high, low, close, volume)
        """
        self.broker = broker
        self.quotes_data = quotes_data
        self._cache = {}
    
    @abstractmethod
    def calc_indicator(self, name: str, **kwargs) -> Union[np.ndarray, Tuple[np.ndarray, ...]]:
        """
        Calculate indicator values for entire dataset.
        Must be implemented in subclasses for specific TA libraries.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters
            
        Returns:
            Numpy array or tuple of numpy arrays with indicator values for entire dataset
        """
        pass
    
    def get_indicator(self, name: str, **kwargs) -> Union[np.ndarray, Tuple[np.ndarray, ...]]:
        """
        Get indicator values with caching and slicing to current bar.
        Common implementation for all TA libraries.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters
            
        Returns:
            Numpy array or tuple of numpy arrays with indicator values sliced to current bar
        """
        # Create cache key from name and sorted parameters
        cache_key = (name, tuple(sorted(kwargs.items())))
        
        # Check cache
        if cache_key not in self._cache:
            # Calculate indicator for entire dataset
            self._cache[cache_key] = self.calc_indicator(name, **kwargs)
        
        # Return slice up to current bar (inclusive)
        full_data = self._cache[cache_key]
        
        # Check if result is a tuple (multiple return values)
        if isinstance(full_data, tuple):
            # Return tuple of slices
            return tuple(arr[:self.broker.i_time + 1] for arr in full_data)
        else:
            # Return single array slice
            return full_data[:self.broker.i_time + 1]
    
    def __getattr__(self, indicator_name: str):
        """
        Intercept indicator name access (e.g., self.talib.SMA).
        Returns a callable that will call get_indicator.
        
        Args:
            indicator_name: Name of the indicator (e.g., 'SMA', 'EMA')
            
        Returns:
            Callable that accepts **kwargs and returns indicator values
        """
        # Don't intercept private/special attributes
        if indicator_name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{indicator_name}'")
        
        def indicator_caller(**kwargs):
            return self.get_indicator(indicator_name, **kwargs)
        
        return indicator_caller


class ta_proxy_talib(ta_proxy):
    """
    Technical analysis proxy for TA-Lib library.
    """
    
    # Valid positional parameter names
    VALID_POSITIONAL_PARAMS = {'open', 'high', 'low', 'close', 'volume', 'real'}
    
    def __init__(self, broker, quotes_data: dict):
        """
        Initialize TA-Lib proxy.
        Analyzes talib functions and builds indicator descriptions.
        
        Args:
            broker: Reference to broker instance
            quotes_data: Dictionary with quotes data (time, open, high, low, close, volume)
        """
        super().__init__(broker, quotes_data)
        
        # Dictionary to store indicator descriptions
        self._indicator_descriptions: Dict[str, IndicatorDescription] = {}
        
        # Analyze talib functions
        self._analyze_talib_functions()
    
    def _analyze_talib_functions(self):
        """
        Analyze talib functions and build indicator descriptions.
        Only includes functions with valid positional parameters (open, high, low, close, volume).
        """
        for name in dir(talib):
            # Skip private/special attributes
            if name.startswith('_'):
                continue
            
            # Get attribute from talib
            attr = getattr(talib, name)
            
            # Check if it's callable
            if not callable(attr):
                continue
            
            try:
                # Get function signature
                sig = inspect.signature(attr)
                
                # Extract positional parameter names that are in VALID_POSITIONAL_PARAMS
                positional_params = []
                skip_function = False
                
                for param_name, param in sig.parameters.items():
                    # Check if parameter has default value (then it's in kwargs, not positional)
                    if param.default != inspect.Parameter.empty:
                        # This parameter will be in kwargs, skip it
                        continue
                    
                    # This is a positional parameter (no default value)
                    if param_name in self.VALID_POSITIONAL_PARAMS:
                        positional_params.append(param_name)
                    else:
                        # Invalid positional parameter - skip this function
                        logger.warning(
                            f"TA-Lib function '{name}' has invalid positional parameter '{param_name}'. "
                            f"Only {self.VALID_POSITIONAL_PARAMS} are allowed. Skipping."
                        )
                        skip_function = True
                        break
                
                if not skip_function and positional_params:
                    # All positional params are valid - save indicator description
                    self._indicator_descriptions[name] = IndicatorDescription(values=positional_params)
            except Exception as e:
                # Skip functions that can't be analyzed
                logger.debug(f"Could not analyze function '{name}': {e}")
                continue
    
    def calc_indicator(self, name: str, **kwargs) -> Union[np.ndarray, Tuple[np.ndarray, ...]]:
        """
        Calculate indicator values using TA-Lib.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters (non-positional)
            
        Returns:
            Numpy array or tuple of numpy arrays with indicator values for entire dataset
            
        Raises:
            ValueError: If indicator name is not found in descriptions
        """
        # Get indicator description
        if name not in self._indicator_descriptions:
            raise ValueError(f"TA-Lib indicator '{name}' is not available or has invalid parameters")
        
        description = self._indicator_descriptions[name]
        
        # Get function from talib
        talib_function = getattr(talib, name)
        
        # Build positional arguments from quotes_data
        args = []
        # Create a copy of kwargs to modify it (remove 'value' if used)
        call_kwargs = kwargs.copy()
        
        for param_name in description.values:
            if param_name == 'real':
                # For 'real' parameter, get series name from kwargs['value']
                if 'value' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'real' (series name), "
                        f"but 'value' parameter is not provided in kwargs"
                    )
                # Get series name from value parameter
                series_name = kwargs['value']
                # Remove 'value' from kwargs as it's not a talib parameter
                call_kwargs.pop('value', None)
                # Get data from quotes_data using series name
                if series_name not in self.quotes_data:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value' parameter, but it's not available in quotes_data"
                    )
                args.append(self.quotes_data[series_name])
            else:
                # Regular parameter - get directly from quotes_data
                args.append(self.quotes_data[param_name])
        
        try:
            # Call talib function with *args and **kwargs (without 'value')
            result = talib_function(*args, **call_kwargs)
            return result
        except Exception as e:
            # Re-raise with more context
            raise RuntimeError(f"Error calling talib.{name}(*args, **kwargs): {e}") from e


class BrokerBacktesting(Broker):
    """
    Broker class for handling trading operations and backtesting execution.
    Minimal working version with buy/sell stubs.
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
        super().__init__(result_id)
        self.fee = fee
        self.task = task
        self.results_save_period = results_save_period
        self.callbacks = callbacks_dict
        
        # Trading state
        self.price: Optional[PRICE_TYPE] = None
        self.current_time: Optional[np.datetime64] = None
        self.i_time: int = 0  # Current bar index in backtesting loop
        
        # Progress tracking
        self.progress: float = 0.0
        self.date_start: Optional[np.datetime64] = None
        self.date_end: Optional[np.datetime64] = None
        
        # Equity tracking for backtesting
        self.equity_usd: PRICE_TYPE = 0.0
        self.equity_symbol: VOLUME_TYPE = 0.0
    
    def reset(self) -> None:
        """
        Reset broker state.
        """
        super().reset()
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
        
        self.reg_buy(quantity, trade_fee, self.price, self.current_time)
    
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
        
        self.reg_sell(quantity, trade_fee, self.price, self.current_time)
    
    def close_deals(self):
        """
        Close all open positions by executing opposite trades.
        If equity_symbol > 0, sell it. If equity_symbol < 0, buy it.
        """
        if self.equity_symbol > 0:
            self.sell(self.equity_symbol)
        elif self.equity_symbol < 0:
            self.buy(abs(self.equity_symbol))
    
    def update_state(self, results: BackTestingResults, is_finish: bool = False) -> None:
        """
        Update task state and progress.
        Checks if task is still running by reading isRunning flag from Redis.
        Calculates and sends progress update via MessageType.EVENT.
        If isRunning is False, sends error notification and raises exception to stop backtesting.
        
        Args:
            results: BackTestingResults instance to save results to Redis
            is_finish: If True, marks the backtesting result as completed. Default: False.
        
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
        progress = float(current_delta / total_delta * 100.0)
        self.progress = round(max(0.0, min(100.0, progress)), 1)
        
        # Convert datetime64 to ISO strings for frontend
        date_start_iso = datetime64_to_iso(self.date_start) if self.date_start is not None else None
        current_time_iso = datetime64_to_iso(self.current_time) if self.current_time is not None else None
        
        # Save results to Redis
        results.put_result(is_finish=is_finish)
        
        self.task.send_message(
            MessageType.EVENT, 
            {
                "event": "backtesting_progress",
                "result_id": self.result_id,
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
        
        # Create BackTestingResults instance
        results = BackTestingResults(self.task, self)
        
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
        
        # Create TA proxies dictionary
        ta_proxies = {
            'talib': ta_proxy_talib(broker=self, quotes_data=quotes_data)
        }
        
        # Call on_start callback with task parameters and TA proxies
        if 'on_start' in self.callbacks:
            self.callbacks['on_start'](task.parameters, ta_proxies)
        
        for i_time in range(len(all_close)):
            # Update current bar index
            self.i_time = i_time
            
            # Set current time and price
            self.current_time = all_time[i_time]
            self.price = all_close[i_time]
            
            # Prepare arrays for this bar
            time_array = all_time[:i_time+1]
            open_array = all_open[:i_time+1]
            high_array = all_high[:i_time+1]
            low_array = all_low[:i_time+1]
            close_array = all_close[:i_time+1]
            volume_array = all_volume[:i_time+1]
            
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
                self.update_state(results)
                last_update_time = current_time
                state_update_period = min(state_update_period + 1.0, self.results_save_period)
        
        # Close all open positions
        self.close_deals()
        assert self.equity_symbol == 0.0, "Equity symbol is not 0 after closing deals"
        
        # Check trading results for consistency (only in debug mode)
        if __debug__:
            errors = self.check_trading_results()
            if errors:
                error_message = f"Trading results validation failed:\n" + "\n".join(errors)
                logger.error(error_message)
                self.task.backtesting_error(error_message)
                raise RuntimeError(error_message)

        # Call on_finish callback
        if 'on_finish' in self.callbacks:
            self.callbacks['on_finish']()
                
        # Set current_time to date_end to ensure progress is 100% for final update
        self.current_time = self.date_end
        self.update_state(results, is_finish=True) 
