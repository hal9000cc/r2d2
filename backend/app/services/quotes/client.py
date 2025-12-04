from abc import ABC, abstractmethod
from datetime import datetime, date
from typing import Optional, Dict, Union
import redis
import numpy as np
import msgpack
import uuid
from .timeframe import Timeframe
from .exceptions import R2D2QuotesExceptionDataNotReceived
from .constants import TIME_TYPE
from app.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_HISTORY_SIZE = 1000


def parse_datetime(value: Optional[Union[datetime, date, str]]) -> Optional[datetime]:
    """
    Parse datetime from various input types.
    
    Args:
        value: Can be datetime, date, ISO string, or None
    
    Returns:
        datetime object or None
    """
    if value is None:
        return None
    
    if isinstance(value, datetime):
        return value
    
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    
    raise TypeError(f"Unsupported type for datetime conversion: {type(value)}")

class Client:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Client, cls).__new__(cls)
        return cls._instance

    def __init__(self, redis_params: Optional[Dict] = None, request_list: str = 'quotes:requests', response_prefix: str = 'quotes:responses', timeout: int = 30):
        if not Client._initialized:
            # Default Redis parameters
            redis_params = redis_params or {}
            self.redis_host = redis_params.get('host', 'localhost')
            self.redis_port = redis_params.get('port', 6379)
            self.redis_db = redis_params.get('db', 0)
            self.redis_password = redis_params.get('password', None)
            
            # Initialize Redis client
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=False  # Keep binary for numpy arrays
            )
            self.request_list = request_list
            self.response_prefix = response_prefix
            self.timeout = timeout
            Client._initialized = True
            logger.debug(f"Quotes client initialized with Redis connection parameters: host {self.redis_host}, port {self.redis_port}, db {self.redis_db}")

    def get_redis_key(self, source: str, symbol: str, timeframe: Timeframe, history_start: datetime, history_end: Optional[datetime] = None) -> str:
        """Generate Redis key for quotes data with human-readable dates."""
        # Format dates in human-readable format (ISO 8601)
        start_str = history_start.strftime('%Y-%m-%dT%H:%M:%S')
        if history_end is not None:
            end_str = history_end.strftime('%Y-%m-%dT%H:%M:%S')
            return f"quotes:{source}:{symbol}:{timeframe}:{start_str}:{end_str}"
        else:
            return f"quotes:{source}:{symbol}:{timeframe}:{start_str}"

    def get_quotes(self, source: str, symbol: str, timeframe: Timeframe, history_start: datetime, history_end: Optional[datetime] = None, timeout: int = 30) -> Dict[str, np.ndarray]:
        """
        Get quotes data from Redis via service.
        
        Sends request to quotes service and receives response with 6 numpy arrays:
        - time: np.datetime64
        - open, high, low, close, volume: float64
        
        Args:
            source: Data source (e.g., 'binance')
            symbol: Trading symbol (e.g., 'btc/usdt')
            timeframe: Timeframe object
            history_start: Start time for historical data
            history_end: End time for historical data (optional)
        
        Returns:
            dict with keys: 'time', 'open', 'high', 'low', 'close', 'volume'
            Each value is a numpy array
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        
        # Prepare request
        request = {
            'request_id': request_id,
            'source': source,
            'symbol': symbol,
            'timeframe': str(timeframe),
            'history_start': history_start.isoformat(),
            'history_end': history_end.isoformat() if history_end is not None else None
        }
        
        # Send request to service using MessagePack
        request_bytes = msgpack.packb(request, use_bin_type=True)
        self.redis_client.lpush(self.request_list, request_bytes)
        logger.debug(f"Request sent to service {len(request_bytes)} bytes")
        
        # Wait for response from service
        response_list = f"{self.response_prefix}:{request_id}"
        logger.debug(f"Waiting for response from service: {response_list}")
        result = self.redis_client.brpop(response_list, timeout=timeout if timeout > 0 else self.timeout)
        logger.debug(f"Response from service {len(result)} records")

        if result is None:
            raise R2D2QuotesExceptionDataNotReceived(symbol, history_start, history_end)
        
        _, response_bytes = result
        
        # Deserialize MessagePack response
        response_data = msgpack.unpackb(response_bytes, raw=False)
        
        # Check response status
        metadata = response_data.get('metadata', {})
        if metadata.get('status') == 'error':
            raise R2D2QuotesExceptionDataNotReceived(symbol, history_start, history_end, metadata.get('error'))
        
        # Extract binary data
        binary_data = response_data.get('binary_data', {})
        
        # Convert binary data to numpy arrays
        time_array = np.frombuffer(binary_data['time'], dtype=TIME_TYPE)
        open_array = np.frombuffer(binary_data['open'], dtype=np.float64)
        high_array = np.frombuffer(binary_data['high'], dtype=np.float64)
        low_array = np.frombuffer(binary_data['low'], dtype=np.float64)
        close_array = np.frombuffer(binary_data['close'], dtype=np.float64)
        volume_array = np.frombuffer(binary_data['volume'], dtype=np.float64)
        
        return {
            'time': time_array,
            'open': open_array,
            'high': high_array,
            'low': low_array,
            'close': close_array,
            'volume': volume_array
        }


class PriceSeries:
    def __init__(self, parent: 'Quotes', values: np.ndarray):
        """
        Initialize PriceSeries.
        
        Args:
            parent: Quotes object that owns this series
            values: numpy array with price/time values
        """
        self.parent = parent
        self.values = values

    def __getitem__(self, item):
        """
        Get slice or item from PriceSeries.
        
        Args:
            item: slice or index
        
        Returns:
            numpy array for slices, single value for index
        """
        # Delegate slice handling to parent Quotes object
        if isinstance(item, slice):
            return self.parent.series_handle_slice(self, item)
        return self.values[item]


    def __len__(self):
        """Return length of the series."""
        return len(self.values)

    def __str__(self):
        """String representation of PriceSeries."""
        return f"PriceSeries(length={len(self.values)})"

    def __repr__(self):
        """Representation of PriceSeries."""
        return f"PriceSeries(parent={self.parent}, length={len(self.values)})"


class Quotes(ABC):
    _default_source = None

    def __init__(self, symbol, timeframe, source, history_size: int):
        
        self.symbol = symbol
        self.timeframe = timeframe
        self.history_size = history_size
        
        if Quotes._default_source is not None:
            self.source = Quotes._default_source

        self.source = source if source is not None else Quotes._default_source
        if self.source is None:
            raise ValueError("Source is required when creating Quotes")

        if Quotes._default_source is None:
            Quotes._default_source = self.source

        self._close_series = None
        self._open_series = None
        self._high_series = None
        self._low_series = None
        self._volume_series = None
        self._time_series = None

    @property
    @abstractmethod
    def close(self):
        """Returns PriceSeries object for close prices."""
        pass

    @property
    @abstractmethod
    def open(self):
        """Returns PriceSeries object for open prices."""
        pass

    @property
    @abstractmethod
    def high(self):
        """Returns PriceSeries object for high prices."""
        pass

    @property
    @abstractmethod
    def low(self):
        """Returns PriceSeries object for low prices."""
        pass

    @property
    @abstractmethod
    def volume(self):
        """Returns PriceSeries object for volume."""
        pass

    @property
    @abstractmethod
    def time(self):
        """Returns PriceSeries object for time."""
        pass

    @abstractmethod
    def series_handle_slice(self, series: 'PriceSeries', slice_obj: slice) -> np.ndarray:
        """
        Handle special slice operations.
        
        Examples:
            series[1:5]      # Standard slice
            series[-5:-1]    # Negative indices
            series[::2]       # Step slice
            series[:10]      # From start
            series[10:]       # To end
        
        Args:
            series: PriceSeries object that called this method
            slice_obj: slice object
        
        Returns:
            numpy array with sliced values
        """
        pass

    @abstractmethod
    def series_normalize_slice(self, series: 'PriceSeries', slice_obj: slice) -> slice:
        """
        Normalize slice indices (e.g., handle negative indices).
        
        Examples:
            series[-5:-1]    # Normalize negative indices to positive
            series[-10:]     # Normalize negative start to 0
        
        Args:
            series: PriceSeries object that called this method
            slice_obj: slice object
        
        Returns:
            normalized slice object
        """
        pass

    @abstractmethod
    def series_reverse_slice(self, series: 'PriceSeries', slice_obj: slice) -> np.ndarray:
        """
        Handle reverse slice (e.g., [-2:-12] should give 10 elements in reverse order).
        
        Examples:
            series[-2:-12]   # Get 10 elements in reverse order (from -2 to -12)
            series[10:0:-1]   # Reverse slice with step
        
        Args:
            series: PriceSeries object that called this method
            slice_obj: slice object
        
        Returns:
            numpy array with reversed slice
        """
        pass


class QuotesRealtime(Quotes):
    """Quotes class for real-time data."""

    def __init__(self, symbol, timeframe, source=None, history_size=DEFAULT_HISTORY_SIZE):
        super().__init__(symbol, timeframe, source, history_size)
        # For real-time, we don't have data yet, so use empty arrays as placeholders
        self._quotes_data = {
            'close': np.array([], dtype=np.float64),
            'open': np.array([], dtype=np.float64),
            'high': np.array([], dtype=np.float64),
            'low': np.array([], dtype=np.float64),
            'volume': np.array([], dtype=np.float64),
            'time': np.array([], dtype=TIME_TYPE)
        }

    @property
    def close(self):
        """Returns PriceSeries object for close prices."""
        if self._close_series is None:
            self._close_series = PriceSeries(self, self._quotes_data['close'])
        return self._close_series

    @property
    def open(self):
        """Returns PriceSeries object for open prices."""
        if self._open_series is None:
            self._open_series = PriceSeries(self, self._quotes_data['open'])
        return self._open_series

    @property
    def high(self):
        """Returns PriceSeries object for high prices."""
        if self._high_series is None:
            self._high_series = PriceSeries(self, self._quotes_data['high'])
        return self._high_series

    @property
    def low(self):
        """Returns PriceSeries object for low prices."""
        if self._low_series is None:
            self._low_series = PriceSeries(self, self._quotes_data['low'])
        return self._low_series

    @property
    def volume(self):
        """Returns PriceSeries object for volume."""
        if self._volume_series is None:
            self._volume_series = PriceSeries(self, self._quotes_data['volume'])
        return self._volume_series

    @property
    def time(self):
        """Returns PriceSeries object for time."""
        if self._time_series is None:
            self._time_series = PriceSeries(self, self._quotes_data['time'])
        return self._time_series

    def series_handle_slice(self, series: 'PriceSeries', slice_obj: slice) -> np.ndarray:
        """
        Handle special slice operations.
        
        Examples:
            series[1:5]      # Standard slice
            series[-5:-1]    # Negative indices
            series[::2]      # Step slice
            series[:10]      # From start
            series[10:]      # To end
        """
        pass

    def series_normalize_slice(self, series: 'PriceSeries', slice_obj: slice) -> slice:
        """
        Normalize slice indices (e.g., handle negative indices).
        
        Examples:
            series[-5:-1]    # Normalize negative indices to positive
            series[-10:]     # Normalize negative start to 0
        """
        pass

    def series_reverse_slice(self, series: 'PriceSeries', slice_obj: slice) -> np.ndarray:
        """
        Handle reverse slice (e.g., [-2:-12] should give 10 elements in reverse order).
        
        Examples:
            series[-2:-12]   # Get 10 elements in reverse order (from -2 to -12)
            series[10:0:-1]  # Reverse slice with step
        """
        pass


class QuotesBackTest(Quotes):
    """Quotes class for backtesting data."""

    def __init__(self, symbol, timeframe, history_start, history_end, source=None, history_size=DEFAULT_HISTORY_SIZE, timeout=30):
        super().__init__(symbol, timeframe, source, history_size)
        
        # Convert to datetime if needed
        self.history_start = parse_datetime(history_start)
        self.history_end = parse_datetime(history_end)

        self.client = Client()
        self._quotes_data = self.client.get_quotes(self.source, self.symbol, self.timeframe, self.history_start, self.history_end, timeout)

    @property
    def close(self):
        """Returns PriceSeries object for close prices."""
        if self._close_series is None:
            self._close_series = PriceSeries(self, self._quotes_data['close'])
        return self._close_series

    @property
    def open(self):
        """Returns PriceSeries object for open prices."""
        if self._open_series is None:
            self._open_series = PriceSeries(self, self._quotes_data['open'])
        return self._open_series

    @property
    def high(self):
        """Returns PriceSeries object for high prices."""
        if self._high_series is None:
            self._high_series = PriceSeries(self, self._quotes_data['high'])
        return self._high_series

    @property
    def low(self):
        """Returns PriceSeries object for low prices."""
        if self._low_series is None:
            self._low_series = PriceSeries(self, self._quotes_data['low'])
        return self._low_series

    @property
    def volume(self):
        """Returns PriceSeries object for volume."""
        if self._volume_series is None:
            self._volume_series = PriceSeries(self, self._quotes_data['volume'])
        return self._volume_series

    @property
    def time(self):
        """Returns PriceSeries object for time."""
        if self._time_series is None:
            self._time_series = PriceSeries(self, self._quotes_data['time'])
        return self._time_series

    def series_handle_slice(self, series: 'PriceSeries', slice_obj: slice) -> np.ndarray:
        """
        Handle special slice operations.
        
        Examples:
            series[1:5]      # Standard slice
            series[-5:-1]    # Negative indices
            series[::2]      # Step slice
            series[:10]      # From start
            series[10:]      # To end
        
        Args:
            series: PriceSeries object that called this method
            slice_obj: slice object
        
        Returns:
            numpy array with sliced values
        """
        # Placeholder for special slice handling logic
        # This will handle negative indices, reverse slices, etc.
        return series.values[slice_obj]

    def series_normalize_slice(self, series: 'PriceSeries', slice_obj: slice) -> slice:
        """
        Normalize slice indices (e.g., handle negative indices).
        
        Examples:
            series[-5:-1]    # Normalize negative indices to positive
            series[-10:]     # Normalize negative start to 0
        
        Args:
            series: PriceSeries object that called this method
            slice_obj: slice object
        
        Returns:
            normalized slice object
        """
        # Placeholder for slice normalization
        return slice_obj

    def series_reverse_slice(self, series: 'PriceSeries', slice_obj: slice) -> np.ndarray:
        """
        Handle reverse slice (e.g., [-2:-12] should give 10 elements in reverse order).
        
        Examples:
            series[-2:-12]   # Get 10 elements in reverse order (from -2 to -12)
            series[10:0:-1]  # Reverse slice with step
        
        Args:
            series: PriceSeries object that called this method
            slice_obj: slice object
        
        Returns:
            numpy array with reversed slice
        """
        # Placeholder for reverse slice handling
        return series.values[slice_obj]