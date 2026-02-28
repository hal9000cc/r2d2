from datetime import datetime
from typing import Optional, Dict, List
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


class QuotesClient:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(QuotesClient, cls).__new__(cls)
        return cls._instance

    def __init__(self, redis_params: Optional[Dict] = None, request_list: str = 'quotes:requests', response_prefix: str = 'quotes:responses', timeout: int = 30):
        if not QuotesClient._initialized:
            if redis_params is None:
                raise RuntimeError("Quotes Client must be initialized with redis_params on first call")

            # Required Redis parameters
            try:
                self.redis_host = redis_params['host']
                self.redis_port = redis_params['port']
                self.redis_db = redis_params['db']
            except KeyError as e:
                raise RuntimeError(f"Missing required Redis parameter for Quotes Client: {e}") from e

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
            QuotesClient._initialized = True
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

        if result is None:
            raise R2D2QuotesExceptionDataNotReceived(symbol, history_start, history_end)
        
        logger.debug(f"Response from service {len(result)} records")

        _, response_bytes = result
        
        # Deserialize MessagePack response
        response_data = msgpack.unpackb(response_bytes, raw=False)
        
        # Check response status
        metadata = response_data.get('metadata', {})
        if metadata.get('status') == 'error':
            raise R2D2QuotesExceptionDataNotReceived(symbol, history_start, history_end, metadata.get('error'))

        filled_indices: List[int] = metadata.get('filled_indices', [])

        # Extract binary data
        binary_data = response_data.get('binary_data', {})

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
            'volume': volume_array,
            'filled_indices': filled_indices,
        }
