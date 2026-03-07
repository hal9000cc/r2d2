from datetime import datetime
from typing import Optional, Dict, List
import time as _time
import redis
import numpy as np
import msgpack
import uuid
from .timeframe import Timeframe
from .exceptions import R2D2QuotesException, R2D2QuotesExceptionDataNotReceived
from .constants import (
    TIME_TYPE,
    SUB_MSG_BAR,
    SUB_MSG_ERROR,
    SUB_MSG_SHUTDOWN,
    SUB_ACTION_SUBSCRIBE,
    SUB_ACTION_UNSUBSCRIBE,
)
from .serialization import decode_bar_message, build_bar_channel
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

            # Pub/Sub state for real-time subscriptions
            self._pubsub = None  # Created lazily on first subscribe()
            self._subscribed_channels: Dict[str, bool] = {}  # channel -> active

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

    def _send_action_request(
        self,
        action: str,
        source: str,
        symbol: str,
        timeframe: Timeframe,
        confirm_timeout: int = 10,
    ) -> None:
        """
        Send a subscribe or unsubscribe action request to QuotesServer and wait
        for a confirmation response.

        Args:
            action: SUB_ACTION_SUBSCRIBE or SUB_ACTION_UNSUBSCRIBE
            source: Exchange name
            symbol: Trading pair symbol
            timeframe: Timeframe object
            confirm_timeout: Seconds to wait for confirmation (default: 10)

        Raises:
            RuntimeError: If server does not respond within confirm_timeout
            R2D2QuotesException: If server reports an error
        """
        request_id = str(uuid.uuid4())
        request = {
            "request_id": request_id,
            "action": action,
            "source": source,
            "symbol": symbol,
            "timeframe": str(timeframe),
        }
        self.redis_client.lpush(
            self.request_list,
            msgpack.packb(request, use_bin_type=True),
        )

        response_list = f"{self.response_prefix}:{request_id}"
        result = self.redis_client.brpop(response_list, timeout=confirm_timeout)

        if result is None:
            raise RuntimeError(
                f"QuotesServer did not confirm {action} for "
                f"{source}:{symbol}:{timeframe} within {confirm_timeout}s"
            )

        _, response_bytes = result
        response_data = msgpack.unpackb(response_bytes, raw=False)
        metadata = response_data.get("metadata", {})

        if metadata.get("status") != "success":
            raise R2D2QuotesException(
                f"{action} failed: {metadata.get('error', 'Unknown error')}"
            )

    def subscribe(self, source: str, symbol: str, timeframe: Timeframe) -> None:
        """
        Subscribe to real-time completed bar stream for the given instrument.

        Sends a subscribe request to QuotesServer (which starts a watch_ohlcv
        WebSocket task if one is not already running), then registers a local
        Redis Pub/Sub listener for the corresponding channel.

        Must be called before wait_next_bar(). Safe to call multiple times for
        the same instrument — each call increments the server-side reference count.

        Args:
            source: Exchange name (e.g., 'binance')
            symbol: Trading pair symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe object
        """
        timeframe_str = str(timeframe)
        channel = build_bar_channel(source, symbol, timeframe_str)

        self._send_action_request(SUB_ACTION_SUBSCRIBE, source, symbol, timeframe)

        if self._pubsub is None:
            self._pubsub = self.redis_client.pubsub()

        if channel not in self._subscribed_channels:
            self._pubsub.subscribe(channel)
            self._subscribed_channels[channel] = True
            logger.info("Subscribed to bar channel: %s", channel)
        else:
            logger.debug("Already subscribed to bar channel: %s", channel)

    def unsubscribe(self, source: str, symbol: str, timeframe: Timeframe) -> None:
        """
        Unsubscribe from the real-time bar stream for the given instrument.

        Removes the local Redis Pub/Sub listener, then sends an unsubscribe
        request to QuotesServer (which decrements the reference count and tears
        down the WebSocket task when it reaches zero).

        Args:
            source: Exchange name
            symbol: Trading pair symbol
            timeframe: Timeframe object
        """
        timeframe_str = str(timeframe)
        channel = build_bar_channel(source, symbol, timeframe_str)

        if self._pubsub is not None and channel in self._subscribed_channels:
            self._pubsub.unsubscribe(channel)
            del self._subscribed_channels[channel]
            logger.info("Unsubscribed from bar channel: %s", channel)

        # Notify server (best-effort, short timeout)
        try:
            self._send_action_request(
                SUB_ACTION_UNSUBSCRIBE, source, symbol, timeframe,
                confirm_timeout=5,
            )
        except Exception as exc:
            logger.warning("Unsubscribe confirmation failed (non-critical): %s", exc)

    def wait_next_bar(
        self,
        source: str,
        symbol: str,
        timeframe: Timeframe,
        timeout: float = 0,
    ) -> Optional[Dict]:
        """
        Block until the next completed bar arrives for the given instrument.

        subscribe() must be called first.

        Polls the Redis Pub/Sub channel. On error messages the exception is
        propagated to let the caller decide whether to reconnect. On a shutdown
        message a RuntimeError is raised.

        Args:
            source: Exchange name
            symbol: Trading pair symbol
            timeframe: Timeframe object
            timeout: Maximum wait time in seconds.
                     0 (default) means wait indefinitely.

        Returns:
            dict with 1-element numpy arrays {time, open, high, low, close, volume},
            or None if timeout elapsed.

        Raises:
            RuntimeError: If subscribe() was not called, or server sent shutdown.
            R2D2QuotesException: If server sent an error message.
        """
        timeframe_str = str(timeframe)
        channel = build_bar_channel(source, symbol, timeframe_str)

        if self._pubsub is None or channel not in self._subscribed_channels:
            raise RuntimeError(
                f"Not subscribed to {channel}. Call subscribe() first."
            )

        start = _time.monotonic()

        while True:
            # get_message with internal_timeout polls for up to 1 s per call
            message = self._pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0,
            )

            if message is not None and message["type"] == "message":
                raw_channel = message["channel"]
                msg_channel = (
                    raw_channel.decode("utf-8")
                    if isinstance(raw_channel, bytes)
                    else raw_channel
                )
                if msg_channel == channel:
                    decoded = decode_bar_message(message["data"])

                    if decoded["type"] == SUB_MSG_BAR:
                        return decoded["bar_data"]

                    if decoded["type"] == SUB_MSG_ERROR:
                        raise R2D2QuotesException(
                            f"Subscription error on {channel}: {decoded['error']}"
                        )

                    if decoded["type"] == SUB_MSG_SHUTDOWN:
                        raise RuntimeError(
                            f"QuotesServer shut down while waiting on {channel}"
                        )

            # Check timeout
            if timeout > 0 and (_time.monotonic() - start) >= timeout:
                return None
