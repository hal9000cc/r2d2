from datetime import datetime, UTC
from typing import Optional, Dict, List, Tuple, Callable, TypeVar, Any
import redis.asyncio as redis
import redis as redis_sync
import numpy as np
import msgpack
import logging
import multiprocessing
import os
import signal
import time
from pathlib import Path
import clickhouse_connect
import ccxt.async_support as ccxt
import ccxt.pro as ccxt_pro  # WebSocket support (watch_ohlcv)
import asyncio
import traceback
from .timeframe import Timeframe
from .exceptions import R2D2QuotesException, R2D2QuotesExceptionDataNotReceived
from .constants import (
    TIME_TYPE,
    TIME_TYPE_UNIT,
    TIME_UNITS_IN_ONE_SECOND,
    SUB_MSG_COMPLETED_BAR,
    SUB_MSG_MARKET_SNAPSHOT,
    SUB_MSG_ERROR,
    SUB_MSG_SHUTDOWN,
    SUB_ACTION_SUBSCRIBE,
    SUB_ACTION_UNSUBSCRIBE,
    WS_RECONNECT_DELAY,
    WS_RECONNECT_MAX_DELAY,
)
from .serialization import encode_bar_message, build_bar_channel
from app.core.config import (
    QUOTES_FETCH_RETRY_ATTEMPTS,
    QUOTES_FETCH_RETRY_DELAY,
    QUOTES_SERVICE_PID_KEY,
    build_ccxt_exchange_config,
    redis_params as get_runtime_redis_params,
)

T = TypeVar('T')

logger = logging.getLogger(__name__)

SERVER_CODE_MARKER = "quotes-server-2026-03-22-subscription-diagnostics-v2"


def _create_subscription_manager(server: 'QuotesServer') -> 'SubscriptionManager':
    """Create SubscriptionManager with explicit diagnostics if module state is invalid."""
    manager_cls = globals().get("SubscriptionManager")
    if manager_cls is None:
        available = sorted(name for name in globals().keys() if not name.startswith("__"))
        raise RuntimeError(
            "SubscriptionManager is not available in app.services.quotes.server globals. "
            f"Available names: {available}"
        )
    return manager_cls(server)


def summarize_exchange_result(result: Any) -> str:
    """Build a short summary for exchange call results."""
    if isinstance(result, list):
        count = len(result)
        if count > 0 and isinstance(result[0], list) and len(result[0]) >= 6:
            first_ts = result[0][0]
            last_ts = result[-1][0]
            return f"items={count}, first_ts={first_ts}, last_ts={last_ts}"
        return f"items={count}"
    if isinstance(result, dict):
        return f"keys={sorted(result.keys())}"
    return str(result)

# Global variables for service management
_service_process: Optional[multiprocessing.Process] = None
_stop_event: Optional[multiprocessing.Event] = None
_ready_event: Optional[multiprocessing.Event] = None


def _get_sync_redis_client(redis_params: Dict) -> redis_sync.Redis:
    """Create a synchronous Redis client for startup/shutdown coordination."""
    return redis_sync.Redis(
        host=redis_params["host"],
        port=redis_params["port"],
        db=redis_params["db"],
        password=redis_params.get("password"),
        decode_responses=True,
        socket_connect_timeout=5,
    )


def _is_pid_alive(pid: int) -> bool:
    """Return True when the given PID exists and can be signalled."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_stored_service_pid(redis_params: Dict) -> Optional[int]:
    """Read the stored QuotesServer PID from Redis."""
    try:
        raw_pid = _get_sync_redis_client(redis_params).get(QUOTES_SERVICE_PID_KEY)
        return int(raw_pid) if raw_pid else None
    except Exception as exc:
        logger.warning("Failed to read QuotesServer PID from Redis: %s", exc)
        return None


def _store_service_pid(redis_params: Dict, pid: int) -> None:
    """Persist QuotesServer PID in Redis for orphan detection."""
    try:
        _get_sync_redis_client(redis_params).set(QUOTES_SERVICE_PID_KEY, str(pid))
    except Exception as exc:
        logger.warning("Failed to store QuotesServer PID %s in Redis: %s", pid, exc)


def _clear_stored_service_pid(redis_params: Dict, expected_pid: Optional[int] = None) -> None:
    """Remove the QuotesServer PID key if it is stale or matches expected_pid."""
    try:
        client = _get_sync_redis_client(redis_params)
        current = client.get(QUOTES_SERVICE_PID_KEY)
        if current is None:
            return
        if expected_pid is None or current == str(expected_pid):
            client.delete(QUOTES_SERVICE_PID_KEY)
    except Exception as exc:
        logger.warning("Failed to clear QuotesServer PID from Redis: %s", exc)


def _terminate_stale_quotes_service(redis_params: Dict, timeout: float = 5.0) -> None:
    """
    Stop an orphan QuotesServer process recorded in Redis before starting a new one.

    If the stored PID is already dead, only the Redis key is cleared.
    """
    stored_pid = _read_stored_service_pid(redis_params)
    if stored_pid is None:
        return

    if _service_process is not None and _service_process.is_alive() and _service_process.pid == stored_pid:
        return

    if not _is_pid_alive(stored_pid):
        logger.info("Removing stale QuotesServer PID from Redis: PID=%s is not alive", stored_pid)
        _clear_stored_service_pid(redis_params, expected_pid=stored_pid)
        return

    logger.warning("Found orphan QuotesServer process PID=%s, stopping it before restart", stored_pid)

    try:
        os.kill(stored_pid, signal.SIGTERM)
    except Exception as exc:
        logger.warning("Failed to send SIGTERM to orphan QuotesServer PID=%s: %s", stored_pid, exc)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _is_pid_alive(stored_pid):
                break
            time.sleep(0.1)

    if _is_pid_alive(stored_pid):
        logger.error("Orphan QuotesServer PID=%s did not stop gracefully, sending SIGKILL", stored_pid)
        try:
            os.kill(stored_pid, signal.SIGKILL)
        except Exception as exc:
            logger.warning("Failed to send SIGKILL to orphan QuotesServer PID=%s: %s", stored_pid, exc)
        else:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not _is_pid_alive(stored_pid):
                    break
                time.sleep(0.1)

    if _is_pid_alive(stored_pid):
        logger.error("Orphan QuotesServer PID=%s is still alive after SIGKILL", stored_pid)
    else:
        logger.info("Orphan QuotesServer PID=%s stopped", stored_pid)

    _clear_stored_service_pid(redis_params, expected_pid=stored_pid)


async def retry_async(
    func: Callable[..., Any],
    max_attempts: int = QUOTES_FETCH_RETRY_ATTEMPTS,
    delay: float = QUOTES_FETCH_RETRY_DELAY,
    *args,
    **kwargs
) -> Any:
    """
    Retry an async function with fixed delay between attempts.
    
    Args:
        func: Async function to retry
        max_attempts: Maximum number of attempts (default: from config)
        delay: Delay in seconds between retries (default: from config)
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func
        
    Returns:
        Result of func(*args, **kwargs)
        
    Raises:
        Exception: Last exception if all attempts fail
    """
    last_exception = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < max_attempts:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed: {e}. "
                    f"Retrying in {delay} seconds..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"All {max_attempts} attempts failed. Last error: {e}",
                    exc_info=True
                )
    
    # If we get here, all attempts failed
    raise last_exception


class QuotesServer:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(QuotesServer, cls).__new__(cls)
        return cls._instance

    def __init__(self, redis_params: Dict, clickhouse_params: Dict):
        if not QuotesServer._initialized:
            # Required Redis parameters
            if not redis_params:
                raise ValueError("redis_params must be provided and cannot be empty")
            self.redis_host = redis_params['host']
            self.redis_port = redis_params['port']
            self.redis_db = redis_params['db']
            self.redis_password = redis_params.get('password', None)
            
            # Initialize asynchronous Redis client
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=False  # Keep binary for numpy arrays
            )
            
            # Required ClickHouse parameters
            if not clickhouse_params:
                raise ValueError("clickhouse_params must be provided and cannot be empty")
            self.clickhouse_host = clickhouse_params['host']
            self.clickhouse_port = clickhouse_params['port']
            self.clickhouse_username = clickhouse_params['username']
            self.clickhouse_password = clickhouse_params.get('password', '')
            self.clickhouse_database = clickhouse_params['database']
            
            self.init_database()
            
            # Dictionary of locks for synchronizing requests by (source, symbol, timeframe)
            # Prevents parallel processing of requests for the same symbol and timeframe
            # Note: Locks are never removed from this dictionary to avoid race conditions
            self._request_locks: Dict[Tuple[str, str, str], asyncio.Lock] = {}
            self._locks_lock = asyncio.Lock()  # For thread-safe access to _request_locks

            # Subscription manager (lazily initialized on first subscribe request)
            self.subscription_manager: Optional['SubscriptionManager'] = None

            QuotesServer._initialized = True

    def connect_database(self, database: Optional[str] = None):
        """
        Create ClickHouse client connection.
        
        Args:
            database: Database name (optional). If None, connects without specifying database.
        
        Returns:
            ClickHouse client instance
        """
        params = {
            'host': self.clickhouse_host,
            'port': self.clickhouse_port,
            'username': self.clickhouse_username,
            'password': self.clickhouse_password
        }
        
        if database is not None:
            params['database'] = database
        
        return clickhouse_connect.get_client(**params, compression=True)

    def init_database(self) -> None:
        """
        Initialize database connection and schema.
        
        Raises:
            R2D2Exception: If database initialization fails
        """
        logger.info(f"Connecting to ClickHouse: {self.clickhouse_host}:{self.clickhouse_port}, database: {self.clickhouse_database}")
        
        # Try to connect to the target database
        try:
            self.clickhouse_client = self.connect_database(database=self.clickhouse_database)
        except Exception as e:
            # Database doesn't exist, connect to default and create it
            logger.info(f"Database '{self.clickhouse_database}' doesn't exist, creating it: {e}")
            
            # Connect to default database
            default_client = self.connect_database()
            
            # Create database
            default_client.command(f"CREATE DATABASE IF NOT EXISTS {self.clickhouse_database}")
            logger.info(f"Database '{self.clickhouse_database}' created")
            
            # Now connect to the created database
            self.clickhouse_client = self.connect_database(database=self.clickhouse_database)
        
        # Check if database is already initialized
        try:
            result = self.clickhouse_client.query("SELECT version FROM db_quotes_version LIMIT 1")
            if result.result_rows:
                version = result.result_rows[0][0]
                logger.info(f"Database initialized, version: {version}")
                return
        except Exception as e:
            logger.info(f"Initializing database schema: {e}")
        
        # Schema file is in the same directory as this script
        schema_file = Path(__file__).parent / 'schema.sql'
        if not schema_file.exists():
            raise R2D2QuotesException(f"Schema file not found: {schema_file}")
        
        logger.info(f"Executing schema script: {schema_file}")
        with open(schema_file, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        
        # Execute schema SQL
        for statement in schema_sql.split(';'):
            statement = statement.strip()
            if statement:
                self.clickhouse_client.command(statement)
        
        logger.info("Database schema initialized successfully")

    def get_quotes_base(self, source: str, symbol: str, timeframe: Timeframe, date_start: datetime, date_end: datetime) -> Dict[str, np.ndarray]:
        """
        Get quotes data from ClickHouse database.
        
        Args:
            source: Exchange name (e.g., 'binance')
            symbol: Trading pair symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe object
            date_start: Start datetime for historical data
            date_end: End datetime for historical data
        
        Returns:
            dict with keys: 'time', 'open', 'high', 'low', 'close', 'volume'
            Each value is a numpy array
            
        Raises:
            R2D2Exception: If query fails
        """
        # Create local client to avoid concurrent query issues
        client = self.connect_database(database=self.clickhouse_database)

        date_start_str = date_start.strftime('%Y-%m-%d %H:%M:%S')
        date_end_str = date_end.strftime('%Y-%m-%d %H:%M:%S')
        
        query = f"""
        SELECT 
            time,
            open,
            high,
            low,
            close,
            volume
        FROM quotes
        WHERE source = '{source}'
          AND symbol = '{symbol}'
          AND timeframe = '{str(timeframe)}'
          AND time >= '{date_start_str}'
          AND time <= '{date_end_str}'
        ORDER BY time
        """
        
        # Read data directly as numpy array (more efficient than reading rows)
        result_array = client.query_np(query)
        # Check if we have any results
        if result_array.size == 0 or len(result_array) == 0:
            # Return empty arrays if no data
            return {
                'time': np.array([], dtype=TIME_TYPE),
                'open': np.array([], dtype=np.float64),
                'high': np.array([], dtype=np.float64),
                'low': np.array([], dtype=np.float64),
                'close': np.array([], dtype=np.float64),
                'volume': np.array([], dtype=np.float64)
            }
        
        # Extract columns directly from numpy array
        # query_np returns structured array (since we have different types: DateTime64 and Float64)
        # Access columns by name from the structured array
        time_array = np.asarray(result_array['time'], dtype=TIME_TYPE)
        open_array = np.asarray(result_array['open'], dtype=np.float64)
        high_array = np.asarray(result_array['high'], dtype=np.float64)
        low_array = np.asarray(result_array['low'], dtype=np.float64)
        close_array = np.asarray(result_array['close'], dtype=np.float64)
        volume_array = np.asarray(result_array['volume'], dtype=np.float64)
        
        return {
            'time': time_array,
            'open': open_array,
            'high': high_array,
            'low': low_array,
            'close': close_array,
            'volume': volume_array
        }
            
    def find_gaps(self, time_array: np.ndarray, timeframe: Timeframe, history_start: datetime, history_end: datetime) -> List[tuple]:
        """
        Find gaps (missing quotes) in the time array.
        
        If time_array is empty, returns the entire range as a single gap.
        
        Args:
            time_array: Array of timestamps as numpy datetime64 (can be empty)
            timeframe: Timeframe object
            history_start: Start datetime
            history_end: End datetime
        
        Returns:
            List of tuples (gap_start, gap_end) representing gaps as datetime objects
        """
        gaps = []
        
        # If no data at all - entire range is a gap
        if len(time_array) == 0:
            return [(history_start, history_end)]
        
        # Convert history_start and history_end to numpy datetime64
        history_start_dt64 = np.datetime64(history_start.replace(tzinfo=None), TIME_TYPE_UNIT)
        history_end_dt64 = np.datetime64(history_end.replace(tzinfo=None), TIME_TYPE_UNIT)
        
        # Get timeframe interval as timedelta64
        timeframe_delta = timeframe.timedelta64()
        
        # Check gap at the beginning
        first_time = time_array[0]
        if first_time > history_start_dt64:
            # Gap from history_start to first_time - timeframe_delta (inclusive on both ends)
            # Since fetch_bar_async loads inclusively, gap_end should be one timeframe before first_time
            # to avoid loading the bar that already exists
            gap_end_dt64 = first_time - timeframe_delta
            gap_start_dt = datetime.fromtimestamp(history_start_dt64.astype('datetime64[ms]').astype('int64') / 1000, UTC)
            gap_end_dt = datetime.fromtimestamp(gap_end_dt64.astype('datetime64[ms]').astype('int64') / 1000, UTC)
            gaps.append((gap_start_dt, gap_end_dt))
        # Note: If first_time == history_start_dt64, gaps will be detected by the "between bars" check below
        
        # Check gaps between bars using vectorized operations
        if len(time_array) > 1:
            # Get current times and next times
            current_times = time_array[:-1]
            next_times = time_array[1:]
            
            # Calculate expected next times (current + timeframe interval)
            expected_next_times = current_times + timeframe_delta
            
            # Find gaps: where next_time > expected_next_time
            gap_mask = next_times > expected_next_times
            
            # Convert gap positions to datetime tuples
            gap_indices = np.where(gap_mask)[0]
            for idx in gap_indices:
                gap_start_dt64 = expected_next_times[idx]
                # Gap ends one timeframe before next_time (since fetch_bar_async loads inclusively)
                gap_end_dt64 = next_times[idx] - timeframe_delta
                # Convert back to datetime
                gap_start_dt = datetime.fromtimestamp(gap_start_dt64.astype('datetime64[ms]').astype('int64') / 1000, UTC)
                gap_end_dt = datetime.fromtimestamp(gap_end_dt64.astype('datetime64[ms]').astype('int64') / 1000, UTC)
                gaps.append((gap_start_dt, gap_end_dt))
        
        # Check gap at the end
        last_time = time_array[-1]
        expected_next = last_time + timeframe_delta
        if expected_next <= history_end_dt64:
            # Gap from expected_next to history_end (inclusive on both ends)
            gap_start_dt = datetime.fromtimestamp(expected_next.astype('datetime64[ms]').astype('int64') / 1000, UTC)
            gap_end_dt = datetime.fromtimestamp(history_end_dt64.astype('datetime64[ms]').astype('int64') / 1000, UTC)
            gaps.append((gap_start_dt, gap_end_dt))
        
        return gaps

    async def _get_request_lock(self, source: str, symbol: str, timeframe_str: str) -> asyncio.Lock:
        """
        Get or create a lock for a specific (source, symbol, timeframe) combination.
        This ensures that requests for the same symbol and timeframe are processed sequentially.
        
        Args:
            source: Data source (e.g., 'binance')
            symbol: Trading symbol (e.g., 'btc/usdt')
            timeframe_str: Timeframe as string (e.g., '1h')
        
        Returns:
            asyncio.Lock instance for the given key
        """
        key = (source, symbol, timeframe_str)
        
        # Thread-safe access to locks dictionary
        async with self._locks_lock:
            if key not in self._request_locks:
                self._request_locks[key] = asyncio.Lock()
            return self._request_locks[key]

    def validate_bars(self, bars: List[list], tf: Timeframe) -> List[list]:
        """
        Validate OHLCV bars and filter out invalid ones.

        Each bar is [timestamp_ms, open, high, low, close, volume].

        Filters out bars where:
        - timestamp is not aligned to timeframe grid
        - open <= 0 or close <= 0
        - high < open or high < close
        - low > open or low > close
        - volume < 0
        - duplicate timestamps within the batch

        Args:
            bars: List of bars from CCXT
            tf: Timeframe object

        Returns:
            List of valid, deduplicated bars
        """
        if not bars:
            return []

        timeframe_ms = int(tf.value / TIME_UNITS_IN_ONE_SECOND * 1000)
        valid_bars = []
        invalid_count = 0
        seen_times = set()
        intra_dup_count = 0

        for bar in bars:
            timestamp_ms = bar[0]
            open_price = bar[1]
            high_price = bar[2]
            low_price = bar[3]
            close_price = bar[4]
            volume = bar[5]

            if timestamp_ms in seen_times:
                intra_dup_count += 1
                continue
            seen_times.add(timestamp_ms)

            if timestamp_ms % timeframe_ms != 0:
                invalid_count += 1
                continue

            if open_price <= 0 or close_price <= 0:
                invalid_count += 1
                continue

            if high_price < open_price or high_price < close_price:
                invalid_count += 1
                continue

            if low_price > open_price or low_price > close_price:
                invalid_count += 1
                continue

            if volume < 0:
                invalid_count += 1
                continue

            valid_bars.append(bar)

        if invalid_count > 0 or intra_dup_count > 0:
            logger.warning(
                "Bar validation: %d invalid, %d intra-batch duplicates filtered out of %d bars",
                invalid_count, intra_dup_count, len(bars)
            )

        return valid_bars

    async def get_quotes(self, source: str, symbol: str, timeframe: Timeframe, history_start: datetime, history_end: Optional[datetime] = None) -> Tuple[Dict[str, np.ndarray], List[int]]:
        """
        Get quotes data from database, filling gaps from exchange if needed.

        After fetching missing data from the exchange, applies forward fill
        to internal gaps (between first and last available bar).
        Gaps before the first bar and after the last bar are NOT filled.

        Args:
            source: Data source (e.g., 'binance')
            symbol: Trading symbol (e.g., 'btc/usdt')
            timeframe: Timeframe object
            history_start: Start time for historical data
            history_end: End time for historical data (optional)

        Returns:
            Tuple of (quotes_data, filled_indices) where:
            - quotes_data: dict with keys 'time', 'open', 'high', 'low', 'close', 'volume'
            - filled_indices: list of bar indices that were forward-filled

        Raises:
            R2D2QuotesExceptionDataNotReceived: If no data available at all
        """
        if history_end is None:
            history_end = datetime.now(UTC)

        overall_start = datetime.now(UTC)

        # Step 1: Get history from database
        loop = asyncio.get_running_loop()
        quotes_data = await loop.run_in_executor(
            None,
            self.get_quotes_base,
            source,
            symbol,
            timeframe,
            history_start,
            history_end,
        )

        # Step 2: Find gaps (find_gaps handles empty arrays internally)
        gaps = self.find_gaps(quotes_data['time'], timeframe, history_start, history_end)

        # Step 3: Fill gaps by fetching from exchange
        if gaps:
            exchange_class = getattr(ccxt, source.lower())
            logger.info("Exchange client create request: exchange=%s auth=%s mode=rest-history", source, False)
            exchange = exchange_class(build_ccxt_exchange_config(source))
            logger.info("Exchange client create result: exchange=%s client=%s mode=rest-history", source, exchange_class.__name__)
            try:
                for gap_start, gap_end in gaps:
                    logger.info(
                        "Filling gap for %s/%s/%s from %s to %s",
                        source,
                        symbol,
                        timeframe,
                        gap_start,
                        gap_end,
                    )
                    await self.fetch_bar_async(
                        exchange=exchange,
                        exchange_name=source,
                        symbol=symbol,
                        tf=timeframe,
                        time_start=gap_start,
                        time_end=gap_end,
                        max_bars=1000,
                    )
            finally:
                try:
                    logger.info("Exchange request: method=close exchange=%s mode=rest-history", source)
                    await exchange.close()
                    logger.info("Exchange result: method=close exchange=%s mode=rest-history status=success", source)
                except Exception as e:
                    logger.warning(f"Failed to close exchange {source}: {e}", exc_info=True)

            # Step 4: Re-read history after filling gaps
            loop = asyncio.get_running_loop()
            quotes_data = await loop.run_in_executor(
                None,
                self.get_quotes_base,
                source,
                symbol,
                timeframe,
                history_start,
                history_end,
            )

        # Step 5: Check that we have data
        if len(quotes_data['time']) == 0:
            raise R2D2QuotesExceptionDataNotReceived(symbol, history_start, history_end)

        # Step 6: Fill internal gaps with forward fill
        quotes_data, filled_indices = self.fill_gaps_forward(quotes_data, timeframe)

        overall_duration = (datetime.now(UTC) - overall_start).total_seconds()
        logger.info(
            "get_quotes finished for %s/%s/%s in %.3f s (bars: %d, filled: %d)",
            source,
            symbol,
            timeframe,
            overall_duration,
            len(quotes_data['time']),
            len(filled_indices),
        )
        return quotes_data, filled_indices

    def save_bars(self, exchange_name: str, symbol: str, tf: Timeframe, bars: List[list]):
        """
        Save bars to ClickHouse database.

        Validates bars (filters invalid OHLCV), deduplicates against existing
        data in the database, and inserts only new valid bars.

        Args:
            exchange_name: Exchange name (e.g., 'binance')
            symbol: Trading symbol (e.g., 'BTC/USDT')
            tf: Timeframe object
            bars: List of bars, each bar is [timestamp, open, high, low, close, volume]
        """
        if not bars:
            return

        valid_bars = self.validate_bars(bars, tf)
        if not valid_bars:
            logger.info("No valid bars to save for %s/%s/%s", exchange_name, symbol, tf)
            return

        client = self.connect_database(database=self.clickhouse_database)
        tf_str = str(tf)

        try:
            min_time_ms = min(bar[0] for bar in valid_bars)
            max_time_ms = max(bar[0] for bar in valid_bars)
            min_time = datetime.fromtimestamp(min_time_ms / 1000.0, UTC)
            max_time = datetime.fromtimestamp(max_time_ms / 1000.0, UTC)
            min_time_str = min_time.strftime('%Y-%m-%d %H:%M:%S')
            max_time_str = max_time.strftime('%Y-%m-%d %H:%M:%S')

            esc_source = exchange_name.replace("'", "''")
            esc_symbol = symbol.replace("'", "''")
            esc_tf = tf_str.replace("'", "''")

            # Get existing timestamps in this range to skip duplicates
            existing_result = client.query(f"""
                SELECT time FROM quotes
                WHERE source = '{esc_source}'
                  AND symbol = '{esc_symbol}'
                  AND timeframe = '{esc_tf}'
                  AND time >= '{min_time_str}'
                  AND time <= '{max_time_str}'
            """)

            existing_times_ms = set()
            for row in existing_result.result_rows:
                existing_times_ms.add(int(row[0].replace(tzinfo=UTC).timestamp() * 1000))

            new_bars = [bar for bar in valid_bars if bar[0] not in existing_times_ms]
            duplicate_count = len(valid_bars) - len(new_bars)

            if not new_bars:
                if duplicate_count > 0:
                    logger.info(
                        "All %d bars are duplicates, nothing to save (%s/%s/%s)",
                        duplicate_count, exchange_name, symbol, tf_str
                    )
                return

            data = [
                [exchange_name, symbol, tf_str,
                 datetime.fromtimestamp(bar[0] / 1000.0, UTC),
                 bar[1], bar[2], bar[3], bar[4], bar[5]]
                for bar in new_bars
            ]

            client.insert(
                'quotes',
                data,
                column_names=['source', 'symbol', 'timeframe', 'time', 'open', 'high', 'low', 'close', 'volume']
            )

            if duplicate_count > 0:
                logger.info(
                    "Saved %d new bars, skipped %d duplicates (%s/%s/%s)",
                    len(new_bars), duplicate_count, exchange_name, symbol, tf_str
                )
            else:
                logger.info("Saved %d bars (%s/%s/%s)", len(new_bars), exchange_name, symbol, tf_str)

        except Exception as e:
            logger.error(f"Error saving bars to database: {e}", exc_info=True)
            raise

    def fill_gaps_forward(self, quotes_data: Dict[str, np.ndarray], timeframe: Timeframe) -> Tuple[Dict[str, np.ndarray], List[int]]:
        """
        Fill internal gaps in quotes data using forward fill.

        Generates an ideal time grid from first to last bar. Gaps between
        existing bars are filled with the previous bar's close price
        (open=high=low=close=prev_close, volume=0).

        Gaps before the first bar and after the last bar are NOT filled.

        Args:
            quotes_data: Dictionary with numpy arrays (time, open, high, low, close, volume)
            timeframe: Timeframe object

        Returns:
            Tuple of (filled_data, filled_indices) where:
            - filled_data: Dictionary with continuous time grid and filled values
            - filled_indices: List of indices in the output that were forward-filled
        """
        time_array = quotes_data['time']

        if len(time_array) <= 1:
            return quotes_data, []

        first_time_int = time_array[0].astype(np.int64)
        last_time_int = time_array[-1].astype(np.int64)
        tf_value = np.int64(timeframe.value)

        n_expected = int((last_time_int - first_time_int) // tf_value) + 1

        if len(time_array) == n_expected:
            return quotes_data, []

        # Generate ideal time grid
        tf_delta = np.timedelta64(timeframe.value, TIME_TYPE_UNIT)
        time_grid = time_array[0] + np.arange(n_expected, dtype=np.int64) * tf_delta

        open_out = np.empty(n_expected, dtype=np.float64)
        high_out = np.empty(n_expected, dtype=np.float64)
        low_out = np.empty(n_expected, dtype=np.float64)
        close_out = np.empty(n_expected, dtype=np.float64)
        volume_out = np.zeros(n_expected, dtype=np.float64)

        # Map existing bars to grid positions via integer arithmetic
        time_ints = time_array.astype(np.int64)
        indices = ((time_ints - first_time_int) // tf_value).astype(np.int64)

        has_data = np.zeros(n_expected, dtype=bool)
        has_data[indices] = True

        open_out[indices] = quotes_data['open']
        high_out[indices] = quotes_data['high']
        low_out[indices] = quotes_data['low']
        close_out[indices] = quotes_data['close']
        volume_out[indices] = quotes_data['volume']

        # Forward fill (vectorized)
        data_positions = np.where(has_data)[0]
        gap_positions = np.where(~has_data)[0]

        filled_indices: List[int] = []

        if len(gap_positions) > 0:
            # For each gap position find the nearest previous bar with data
            insert_pos = np.searchsorted(data_positions, gap_positions, side='right') - 1
            source_positions = data_positions[insert_pos]

            prev_close = close_out[source_positions]
            open_out[gap_positions] = prev_close
            high_out[gap_positions] = prev_close
            low_out[gap_positions] = prev_close
            close_out[gap_positions] = prev_close

            filled_indices = gap_positions.tolist()

        result = {
            'time': time_grid,
            'open': open_out,
            'high': high_out,
            'low': low_out,
            'close': close_out,
            'volume': volume_out,
        }

        if filled_indices:
            logger.info("Forward-filled %d gaps in %d total bars", len(filled_indices), n_expected)

        return result, filled_indices

    async def fetch_bar_async(self, exchange: ccxt.Exchange, exchange_name: str, symbol: str, tf: Timeframe, time_start: datetime, time_end: datetime, max_bars: int = 1000) -> tuple:
        """
        Asynchronously fetch historical bars from exchange and save them to ClickHouse.

        Args:
            exchange: CCXT exchange instance
            exchange_name: Name of the exchange (for logging)
            symbol: Trading pair symbol
            tf: Timeframe object
            time_start: Start time as datetime (required)
            time_end: End time as datetime (required)
            max_bars: Maximum number of bars per REST request

        Returns:
            Tuple (exchange_name, symbol, tf, []) — bars are saved to ClickHouse during fetch,
            the returned list is always empty.
        """
        tf_str = str(tf)
        current_since = int(time_start.replace(tzinfo=UTC).timestamp() * 1000)
        time_end_ms = int(time_end.replace(tzinfo=UTC).timestamp() * 1000.0) if time_end else None
        prev_bars = []
        
        # Calculate timeframe duration in milliseconds
        timeframe_ms = tf.value / TIME_UNITS_IN_ONE_SECOND * 1000
        
        while True:
        
            if current_since > time_end_ms:
                break
            
            time_diff_ms = time_end_ms - current_since
            bars_needed = int(time_diff_ms / timeframe_ms) + 2  # +2 because we need to fetch +1 bars more to be sure that we have the last complete bar
            request_limit = min(bars_needed, max_bars)
            
            # Use retry mechanism for fetching bars
            logger.info(
                "Exchange request: method=fetch_ohlcv exchange=%s symbol=%s timeframe=%s since=%s limit=%s",
                exchange_name,
                symbol,
                tf_str,
                current_since,
                request_limit,
            )
            bars = await retry_async(
                exchange.fetch_ohlcv,
                max_attempts=QUOTES_FETCH_RETRY_ATTEMPTS,
                delay=QUOTES_FETCH_RETRY_DELAY,
                symbol=symbol,
                timeframe=tf_str,
                since=current_since,
                limit=request_limit
            )
            logger.info(
                "Exchange result: method=fetch_ohlcv exchange=%s symbol=%s timeframe=%s %s",
                exchange_name,
                symbol,
                tf_str,
                summarize_exchange_result(bars),
            )
            
            if not bars or len(bars) == 0:
                break
            
            if prev_bars:
                self.save_bars(exchange_name, symbol, tf, prev_bars)

            prev_bars = bars
            current_since = int(bars[-1][0] + timeframe_ms)
        
        if prev_bars:
            del prev_bars[-1]
            if prev_bars:
                self.save_bars(exchange_name, symbol, tf, prev_bars)

        # Historical mode: all bars are saved, return empty list
        return exchange_name, symbol, tf, []


class SubscriptionManager:
    """
    Manages WebSocket bar subscriptions with reference counting.

    Each unique (source, symbol, timeframe) gets exactly one watch_ohlcv asyncio task.
    Multiple clients can subscribe to the same key; the WebSocket is shared and
    only torn down when the last subscriber unsubscribes.
    """

    def __init__(self, server: QuotesServer):
        self._server = server
        # Key: (source, symbol, timeframe_str)
        # Value: dict {task: asyncio.Task, ref_count: int, exchange: ccxt.Exchange}
        self._subscriptions: Dict[Tuple[str, str, str], dict] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, source: str, symbol: str, timeframe_str: str) -> None:
        """Add a subscriber. If the first one, start the watch_ohlcv task."""
        key = (source, symbol, timeframe_str)
        async with self._lock:
            if key in self._subscriptions:
                self._subscriptions[key]["ref_count"] += 1
                logger.info(
                    "Subscription %s: ref_count incremented to %d",
                    key, self._subscriptions[key]["ref_count"],
                )
                return

            exchange_class = getattr(ccxt_pro, source.lower())
            logger.info("Exchange client create request: exchange=%s auth=%s mode=ws", source, False)
            exchange = exchange_class(build_ccxt_exchange_config(source))
            logger.info("Exchange client create result: exchange=%s client=%s mode=ws", source, exchange_class.__name__)

            task = asyncio.create_task(
                self._watch_ohlcv_loop(source, symbol, timeframe_str, exchange)
            )
            self._subscriptions[key] = {
                "task": task,
                "ref_count": 1,
                "exchange": exchange,
            }
            logger.info("Subscription %s: created (ref_count=1)", key)

    async def unsubscribe(self, source: str, symbol: str, timeframe_str: str) -> None:
        """Remove a subscriber. If the last one, stop the watch_ohlcv task."""
        key = (source, symbol, timeframe_str)
        async with self._lock:
            if key not in self._subscriptions:
                logger.warning("Subscription %s: not found for unsubscribe", key)
                return

            self._subscriptions[key]["ref_count"] -= 1

            if self._subscriptions[key]["ref_count"] <= 0:
                self._subscriptions[key]["task"].cancel()
                try:
                    logger.info("Exchange request: method=close exchange=%s mode=ws", source)
                    await self._subscriptions[key]["exchange"].close()
                    logger.info("Exchange result: method=close exchange=%s mode=ws status=success", source)
                except Exception as exc:
                    logger.warning("Failed to close exchange for %s: %s", key, exc)
                del self._subscriptions[key]
                logger.info("Subscription %s: removed (ref_count=0)", key)
            else:
                logger.info(
                    "Subscription %s: ref_count decremented to %d",
                    key, self._subscriptions[key]["ref_count"],
                )

    async def shutdown_all(self) -> None:
        """
        Graceful shutdown: publish shutdown message to every channel,
        cancel all tasks, close all exchange connections.
        Called by run_quotes_service on exit.
        """
        async with self._lock:
            for key, sub_info in self._subscriptions.items():
                source, symbol, timeframe_str = key
                channel = build_bar_channel(source, symbol, timeframe_str)
                shutdown_msg = encode_bar_message(SUB_MSG_SHUTDOWN)
                try:
                    await self._server.redis_client.publish(channel, shutdown_msg)
                except Exception as exc:
                    logger.warning("Failed to publish shutdown for %s: %s", key, exc)

                sub_info["task"].cancel()
                try:
                    logger.info("Exchange request: method=close exchange=%s mode=ws", source)
                    await sub_info["exchange"].close()
                    logger.info("Exchange result: method=close exchange=%s mode=ws status=success", source)
                except Exception:
                    pass

            self._subscriptions.clear()
            logger.info("All subscriptions shut down")

    def _detect_completed_bar(
        self,
        candles: list,
        last_bar_timestamp: Optional[int],
        last_forming_candle: Optional[list] = None,
    ) -> Tuple[Optional[list], int, Optional[list]]:
        """
        Determine whether a bar has just completed given a new batch of candles.

        In watch_ohlcv the *last* candle is the currently forming bar.
        A bar is considered completed when its timestamp changes to a new value.

        The completed bar is taken from our OWN cache (last_forming_candle),
        not from the exchange's candle list.  This is critical because many
        exchanges (e.g. Binance) only include the current forming bar in their
        watch_ohlcv response and immediately evict the just-closed bar.

        Args:
            candles: Raw candle list from watch_ohlcv.
            last_bar_timestamp: Timestamp of the forming bar seen in the
                                previous call, or None on the very first call.
            last_forming_candle: Our cached copy of the forming bar from the
                                 previous call.

        Returns:
            Tuple (completed_bar, new_last_timestamp, new_last_forming_candle):
            - completed_bar: The just-completed candle (our cached copy), or
                             None if no bar completed yet.
            - new_last_timestamp: Updated forming-bar timestamp.
            - new_last_forming_candle: Updated forming-bar candle to cache.
        """
        current_candle = candles[-1]
        current_timestamp: int = current_candle[0]

        if last_bar_timestamp is None or current_timestamp == last_bar_timestamp:
            # First update or bar still forming — update our cached copy and continue
            return None, current_timestamp, current_candle

        # Timestamp changed: last_forming_candle is the completed bar
        return last_forming_candle, current_timestamp, current_candle

    async def _process_completed_bar(
        self,
        source: str,
        symbol: str,
        timeframe_str: str,
        tf: Timeframe,
        channel: str,
        completed_bar: list,
    ) -> None:
        """
        Validate, persist, and publish a single completed bar.

        Steps:
        1. Validate OHLCV values via QuotesServer.validate_bars().
        2. Save to ClickHouse in a thread-pool executor (non-blocking).
        3. Publish a SUB_MSG_COMPLETED_BAR message to the Redis Pub/Sub channel.

        Args:
            source: Exchange name.
            symbol: Trading pair symbol.
            timeframe_str: Timeframe string (e.g., '15m').
            tf: Timeframe object.
            channel: Redis Pub/Sub channel name.
            completed_bar: Raw candle [timestamp_ms, o, h, l, c, v].
        """
        valid_bars = self._server.validate_bars([completed_bar], tf)
        if not valid_bars:
            logger.warning(
                "Completed bar failed validation for %s:%s:%s at %d",
                source, symbol, timeframe_str, completed_bar[0],
            )
            return

        # Persist to ClickHouse without blocking the event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._server.save_bars,
            source, symbol, tf, valid_bars,
        )

        # Build 1-element numpy arrays and publish
        bar = valid_bars[0]
        bar_data = {
            "time": np.array([np.datetime64(int(bar[0]), "ms")], dtype=TIME_TYPE),
            "open": np.array([bar[1]], dtype=np.float64),
            "high": np.array([bar[2]], dtype=np.float64),
            "low": np.array([bar[3]], dtype=np.float64),
            "close": np.array([bar[4]], dtype=np.float64),
            "volume": np.array([bar[5]], dtype=np.float64),
        }
        msg = encode_bar_message(SUB_MSG_COMPLETED_BAR, bar_data=bar_data)
        await self._server.redis_client.publish(channel, msg)

        logger.debug(
            "Published completed bar for %s:%s:%s at %d",
            source, symbol, timeframe_str, bar[0],
        )

    async def _publish_market_snapshot(
        self,
        source: str,
        symbol: str,
        timeframe_str: str,
        channel: str,
        forming_candle: list,
    ) -> None:
        """Publish the latest forming-bar snapshot without persisting it."""
        bar_data = {
            "time": np.array([np.datetime64(int(forming_candle[0]), "ms")], dtype=TIME_TYPE),
            "open": np.array([forming_candle[1]], dtype=np.float64),
            "high": np.array([forming_candle[2]], dtype=np.float64),
            "low": np.array([forming_candle[3]], dtype=np.float64),
            "close": np.array([forming_candle[4]], dtype=np.float64),
            "volume": np.array([forming_candle[5]], dtype=np.float64),
        }
        msg = encode_bar_message(SUB_MSG_MARKET_SNAPSHOT, bar_data=bar_data)
        await self._server.redis_client.publish(channel, msg)

        # logger.debug(
        #     "Published market snapshot for %s:%s:%s at %d",
        #     source, symbol, timeframe_str, forming_candle[0],
        # )

    async def _watch_ohlcv_loop(
        self,
        source: str,
        symbol: str,
        timeframe_str: str,
        exchange: ccxt.Exchange,
    ) -> None:
        """
        Outer WebSocket loop for a single subscription.

        Drives the connection lifecycle: polls watch_ohlcv, delegates bar
        detection to _detect_completed_bar() and processing to
        _process_completed_bar().  On any exception the loop publishes an
        error message to subscribers and reconnects with exponential backoff.
        """
        channel = build_bar_channel(source, symbol, timeframe_str)
        tf = Timeframe.cast(timeframe_str)
        last_bar_timestamp: Optional[int] = None
        last_forming_candle: Optional[list] = None
        reconnect_delay = WS_RECONNECT_DELAY

        while True:
            try:
                # logger.debug(
                #     "Exchange request: method=watch_ohlcv exchange=%s symbol=%s timeframe=%s",
                #     source,
                #     symbol,
                #     timeframe_str,
                # )
                candles = await exchange.watch_ohlcv(symbol, timeframe_str)
                reconnect_delay = WS_RECONNECT_DELAY  # reset on successful response
                # logger.debug(
                #     "Exchange result: method=watch_ohlcv exchange=%s symbol=%s timeframe=%s %s",
                #     source,
                #     symbol,
                #     timeframe_str,
                #     summarize_exchange_result(candles),
                # )

                if not candles:
                    continue

                await self._publish_market_snapshot(
                    source, symbol, timeframe_str, channel, candles[-1]
                )

                completed_bar, last_bar_timestamp, last_forming_candle = self._detect_completed_bar(
                    candles, last_bar_timestamp, last_forming_candle,
                )

                if completed_bar is None:
                    # Bar still forming or first call
                    continue

                await self._process_completed_bar(
                    source, symbol, timeframe_str, tf, channel, completed_bar
                )

            except asyncio.CancelledError:
                logger.info(
                    "watch_ohlcv task cancelled for %s:%s:%s",
                    source, symbol, timeframe_str,
                )
                break
            except Exception as exc:
                logger.error(
                    "watch_ohlcv error for %s:%s:%s: %s",
                    source, symbol, timeframe_str, exc,
                    exc_info=True,
                )
                await self._handle_reconnect(
                    source, symbol, timeframe_str, channel, exchange, exc, reconnect_delay
                )
                reconnect_delay = min(reconnect_delay * 2, WS_RECONNECT_MAX_DELAY)

                # Replace exchange instance after reconnect (use ccxt.pro for WebSocket)
                exchange_class = getattr(ccxt_pro, source.lower())
                logger.info(
                    "Exchange reconnect: exchange=%s symbol=%s timeframe=%s next_delay=%s",
                    source,
                    symbol,
                    timeframe_str,
                    reconnect_delay,
                )
                logger.info("Exchange client create request: exchange=%s auth=%s mode=ws-reconnect", source, False)
                exchange = exchange_class(build_ccxt_exchange_config(source))
                logger.info("Exchange client create result: exchange=%s client=%s mode=ws-reconnect", source, exchange_class.__name__)
                key = (source, symbol, timeframe_str)
                async with self._lock:
                    if key in self._subscriptions:
                        self._subscriptions[key]["exchange"] = exchange

    async def _handle_reconnect(
        self,
        source: str,
        symbol: str,
        timeframe_str: str,
        channel: str,
        exchange: ccxt.Exchange,
        exc: Exception,
        reconnect_delay: float,
    ) -> None:
        """
        Publish an error notification and wait before reconnecting.

        Args:
            source: Exchange name.
            symbol: Trading pair symbol.
            timeframe_str: Timeframe string.
            channel: Redis Pub/Sub channel name.
            exchange: Current (broken) exchange instance to close.
            exc: The exception that triggered the reconnect.
            reconnect_delay: Seconds to sleep before the caller retries.
        """
        error_msg = encode_bar_message(
            SUB_MSG_ERROR,
            error=f"WebSocket error: {exc}. Reconnecting in {reconnect_delay}s...",
        )
        try:
            await self._server.redis_client.publish(channel, error_msg)
        except Exception as pub_exc:
            logger.error("Failed to publish error message: %s", pub_exc)

        logger.warning(
            "Exchange reconnect wait: exchange=%s symbol=%s timeframe=%s delay=%s error=%s",
            source,
            symbol,
            timeframe_str,
            reconnect_delay,
            exc,
        )
        await asyncio.sleep(reconnect_delay)

        try:
            logger.info("Exchange request: method=close exchange=%s mode=ws-reconnect", source)
            await exchange.close()
            logger.info("Exchange result: method=close exchange=%s mode=ws-reconnect status=success", source)
        except Exception:
            pass


async def process_request_async(
    server: QuotesServer,
    request_data: Dict,
    request_id: str,
    response_prefix: str,
    response_ttl: int
):
    """
    Process a single request asynchronously.
    
    Args:
        server: QuotesServer instance
        request_data: Parsed request data
        request_id: Request ID
        response_prefix: Prefix for response list names
        response_ttl: TTL for response lists in seconds
    """
    async def _send_response(status: str, **extra) -> None:
        """Helper to push a msgpack response and set TTL."""
        resp = {
            "metadata": {
                "request_id": request_id,
                "status": status,
                "server_pid": os.getpid(),
                "server_code_marker": SERVER_CODE_MARKER,
                **extra,
            }
        }
        resp_bytes = msgpack.packb(resp, use_bin_type=True)
        key = f"{response_prefix}:{request_id}"
        await server.redis_client.lpush(key, resp_bytes)
        await server.redis_client.expire(key, response_ttl)

    try:
        action = request_data.get("action", "get_quotes")
        source = request_data.get('source')
        symbol = request_data.get('symbol')
        timeframe_str = request_data.get('timeframe')
        logger.info(
            "Processing request: id=%s action=%s target=%s:%s:%s pid=%s marker=%s",
            request_id,
            action,
            source,
            symbol,
            timeframe_str,
            os.getpid(),
            SERVER_CODE_MARKER,
        )

        # --- subscribe ---
        if action == SUB_ACTION_SUBSCRIBE:
            if server.subscription_manager is None:
                logger.info(
                    "Initializing SubscriptionManager for %s:%s:%s",
                    source,
                    symbol,
                    timeframe_str,
                )
                server.subscription_manager = _create_subscription_manager(server)
            else:
                logger.info(
                    "Reusing SubscriptionManager: type=%s id=%s active_subscriptions=%s",
                    type(server.subscription_manager).__name__,
                    id(server.subscription_manager),
                    len(getattr(server.subscription_manager, "_subscriptions", {})),
                )
            await server.subscription_manager.subscribe(source, symbol, timeframe_str)
            await _send_response("success", action="subscribed")
            logger.info("Subscribed %s:%s:%s (request %s)", source, symbol, timeframe_str, request_id)
            return

        # --- unsubscribe ---
        if action == SUB_ACTION_UNSUBSCRIBE:
            if server.subscription_manager is not None:
                await server.subscription_manager.unsubscribe(source, symbol, timeframe_str)
            await _send_response("success", action="unsubscribed")
            logger.info("Unsubscribed %s:%s:%s (request %s)", source, symbol, timeframe_str, request_id)
            return

        # --- get_quotes (default) ---
        history_start_str = request_data.get('history_start')
        history_end_str = request_data.get('history_end')
        
        # Convert string to datetime
        history_start = datetime.fromisoformat(history_start_str)
        history_end = datetime.fromisoformat(history_end_str) if history_end_str else None
        
        # Convert timeframe string to Timeframe object
        timeframe = Timeframe.cast(timeframe_str)
        
        # Get lock for this (source, symbol, timeframe) to prevent parallel processing
        lock = await server._get_request_lock(source, symbol, timeframe_str)
        
        # Process request with lock - ensures only one request per (source, symbol, timeframe) at a time
        async with lock:
            quotes_data, filled_indices = await server.get_quotes(source, symbol, timeframe, history_start, history_end)

            response_data = {
                'metadata': {
                    'request_id': request_id,
                    'status': 'success',
                    'filled_indices': filled_indices,
                    'array_sizes': {
                        'time': len(quotes_data['time']),
                        'open': len(quotes_data['open']),
                        'high': len(quotes_data['high']),
                        'low': len(quotes_data['low']),
                        'close': len(quotes_data['close']),
                        'volume': len(quotes_data['volume'])
                    }
                },
                'binary_data': {
                    'time': quotes_data['time'].tobytes(),
                    'open': quotes_data['open'].tobytes(),
                    'high': quotes_data['high'].tobytes(),
                    'low': quotes_data['low'].tobytes(),
                    'close': quotes_data['close'].tobytes(),
                    'volume': quotes_data['volume'].tobytes()
                }
            }
            
            # Serialize with MessagePack (supports binary data)
            response_bytes = msgpack.packb(response_data, use_bin_type=True)
            
            # Push response to individual response list for this request (async I/O)
            individual_response_list = f"{response_prefix}:{request_id}"
            await server.redis_client.lpush(individual_response_list, response_bytes)
            
            # Set TTL for response list (async I/O)
            await server.redis_client.expire(individual_response_list, response_ttl)
            logger.info(f"Processed request {request_id} for {source}:{symbol}:{timeframe}")
        
    except R2D2QuotesExceptionDataNotReceived as e:
        # Send error response
        error_message = e.error if e.error else str(e)
        response_data = {
            'metadata': {
                'request_id': request_id,
                'status': 'error',
                'error': error_message
            }
        }
        individual_response_list = f"{response_prefix}:{request_id}"
        response_bytes = msgpack.packb(response_data, use_bin_type=True)
        await server.redis_client.lpush(individual_response_list, response_bytes)
        # Set TTL for response list
        await server.redis_client.expire(individual_response_list, response_ttl)
        logger.warning(f"Request {request_id} failed: {e}")
        
    except Exception as e:
        tb = traceback.format_exc()
        # Send error response
        response_data = {
            'metadata': {
                'request_id': request_id if request_id else 'unknown',
                'status': 'error',
                'error': str(e),
                'error_type': type(e).__name__,
                'server_pid': os.getpid(),
                'server_code_marker': SERVER_CODE_MARKER,
                'traceback': tb,
            }
        }
        if request_id:
            individual_response_list = f"{response_prefix}:{request_id}"
            response_bytes = msgpack.packb(response_data, use_bin_type=True)
            await server.redis_client.lpush(individual_response_list, response_bytes)
            # Set TTL for response list
            await server.redis_client.expire(individual_response_list, response_ttl)
        logger.error(
            "Error processing request %s: type=%s pid=%s marker=%s error=%s\n%s",
            request_id,
            type(e).__name__,
            os.getpid(),
            SERVER_CODE_MARKER,
            e,
            tb,
        )


async def run_quotes_service(
    redis_params: Dict,
    clickhouse_params: Dict,
    request_list: str = 'quotes:requests',
    response_prefix: str = 'quotes:responses',
    timeout: int = 0,
    response_ttl: int = 300,
    stop_event: Optional[multiprocessing.Event] = None,
    ready_event: Optional[multiprocessing.Event] = None
):
    """
    Run quotes service that processes requests via Redis lists (LPUSH/BRPOP).
    
    The service listens to request_list for quote requests using BRPOP and pushes
    responses to individual response lists using LPUSH.
    Each response goes to a separate list: {response_prefix}:{request_id}
    
    Request format (MessagePack):
    {
        "request_id": "unique-request-id",
        "source": "binance",
        "symbol": "btc/usdt",
        "timeframe": "1d",
        "history_start": "2024-01-01T00:00:00",
        "history_end": "2024-01-31T23:59:59"  // optional
    }
    
    Response format (MessagePack):
    {
        "request_id": "unique-request-id",
        "status": "success" | "error",
        "data": {...}  // if success
        "error": "error message"  // if error
    }
    
    Args:
        redis_params: Dictionary with Redis connection parameters (host, port, db, password) - REQUIRED
        clickhouse_params: Dictionary with ClickHouse connection parameters (host, port, username, password, database) - REQUIRED
        request_list: Redis list name for incoming requests
        response_prefix: Prefix for response list names (each request gets its own list)
        timeout: BRPOP timeout in seconds (0 = block indefinitely)
        response_ttl: TTL for response lists in seconds (default: 300 = 5 minutes)
        stop_event: Multiprocessing event to signal service stop
        ready_event: Multiprocessing event to signal service is ready
    
    Raises:
        ValueError: If redis_params or clickhouse_params are not provided
    """
    if not redis_params:
        raise ValueError("redis_params must be provided and cannot be empty")
    if not clickhouse_params:
        raise ValueError("clickhouse_params must be provided and cannot be empty")
    
    server = QuotesServer(redis_params=redis_params, clickhouse_params=clickhouse_params)
    logger.info(
        "Quotes service booted: pid=%s marker=%s request_list=%s response_prefix=%s",
        os.getpid(),
        SERVER_CODE_MARKER,
        request_list,
        response_prefix,
    )
    
    # Clean Redis database from old test data
    patterns = [
        request_list,
        f"{response_prefix}:*",
        'quotes:*'
    ]
    
    for pattern in patterns:
        keys = await server.redis_client.keys(pattern)
        if keys:
            await server.redis_client.delete(*keys)
            logger.info(f"Cleaned {len(keys)} keys matching pattern: {pattern}")
    
    logger.info(f"Quotes service started. Listening on list: {request_list}")
    
    # Signal that service is ready to process requests
    if ready_event:
        ready_event.set()
    
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                # Blocking pop from request list (async I/O using asynchronous Redis client)
                # Use shorter timeout to check stop_event more frequently
                result = await server.redis_client.brpop(
                    request_list,
                    timeout=timeout if timeout > 0 else 1
                )
                
                if result is None:
                    # Timeout reached, check stop event and continue waiting
                    if stop_event and stop_event.is_set():
                        break
                    continue
                
                _, request_bytes = result
                
                try:
                    # Parse request using MessagePack
                    request_data = msgpack.unpackb(request_bytes, raw=False)
                    request_id = request_data.get('request_id')
                    
                    if not request_id:
                        logger.error("Request missing request_id, skipping")
                        continue
                    
                    # Start async processing (creates task for parallel processing)
                    asyncio.create_task(
                        process_request_async(server, request_data, request_id, response_prefix, response_ttl)
                    )
                    
                except Exception as e:
                    logger.error(f"Error parsing request: {e}", exc_info=True)
                    
            except asyncio.CancelledError:
                # Service is being cancelled (e.g., during shutdown)
                logger.info("Quotes service cancelled")
                break
            except Exception as e:
                # Catch any exceptions in the main loop to prevent service from crashing
                logger.error(f"Error in quotes service main loop: {e}", exc_info=True)
                # Wait a bit before retrying to avoid tight error loop
                await asyncio.sleep(1)
                
    except KeyboardInterrupt:
        logger.info("Quotes service stopped by keyboard interrupt")
    except asyncio.CancelledError:
        logger.info("Quotes service cancelled")
    except Exception as e:
        logger.error(f"Quotes service crashed with exception: {e}", exc_info=True)
        raise  # Re-raise to ensure process exits
    finally:
        if server.subscription_manager is not None:
            try:
                await server.subscription_manager.shutdown_all()
            except Exception as exc:
                logger.error("Error during subscription manager shutdown: %s", exc)
        if stop_event:
            stop_event.clear()
        logger.info("Quotes service finished")
        if ready_event:
            ready_event.clear()


def _quotes_service_worker(
    redis_params: Dict,
    clickhouse_params: Dict,
    request_list: str,
    response_prefix: str,
    timeout: int,
    response_ttl: int,
    stop_event: multiprocessing.Event,
    ready_event: multiprocessing.Event
):
    """
    Worker function for quotes service process.
    This function must be at module level to be picklable by multiprocessing.
    """
    try:
        asyncio.run(run_quotes_service(
            redis_params=redis_params,
            clickhouse_params=clickhouse_params,
            request_list=request_list,
            response_prefix=response_prefix,
            timeout=timeout,
            response_ttl=response_ttl,
            stop_event=stop_event,
            ready_event=ready_event
        ))
    except Exception as e:
        logger.critical(f"Quotes service process crashed: {e}", exc_info=True)


def start_quotes_service(
    redis_params: Dict,
    clickhouse_params: Dict,
    request_list: str = 'quotes:requests',
    response_prefix: str = 'quotes:responses',
    timeout: int = 0,
    response_ttl: int = 300,
    wait_ready: bool = True,
    ready_timeout: float = 30.0
) -> bool:
    """
    Start quotes service in a separate process.
    
    Args:
        redis_params: Dictionary with Redis connection parameters (host, port, db, password) - REQUIRED
        clickhouse_params: Dictionary with ClickHouse connection parameters (host, port, username, password, database) - REQUIRED
        request_list: Redis list name for incoming requests
        response_prefix: Prefix for response list names
        timeout: BRPOP timeout in seconds
        response_ttl: TTL for response lists in seconds
        wait_ready: If True, wait for service to be ready before returning
        ready_timeout: Maximum time to wait for service to be ready (seconds)
    
    Returns:
        True if service started successfully, False if already running
    
    Raises:
        ValueError: If redis_params or clickhouse_params are not provided
    """
    if not redis_params:
        raise ValueError("redis_params must be provided and cannot be empty")
    if not clickhouse_params:
        raise ValueError("clickhouse_params must be provided and cannot be empty")
    
    global _service_process, _stop_event, _ready_event
    
    if _service_process is not None and _service_process.is_alive():
        logger.warning("Quotes service is already running")
        return False

    _terminate_stale_quotes_service(redis_params)
    
    _stop_event = multiprocessing.Event()
    _ready_event = multiprocessing.Event()

    _service_process = multiprocessing.Process(
        target=_quotes_service_worker,
        args=(
            redis_params,
            clickhouse_params,
            request_list,
            response_prefix,
            timeout,
            response_ttl,
            _stop_event,
            _ready_event
        ),
        daemon=False
    )
    _service_process.start()
    logger.info("Quotes service process started")
    if _service_process.pid is not None:
        _store_service_pid(redis_params, _service_process.pid)
    
    # Wait for service to be ready if requested
    if wait_ready:
        if _ready_event.wait(timeout=ready_timeout):
            logger.info("Quotes service is ready to process requests")
        else:
            logger.warning(f"Quotes service did not become ready within {ready_timeout} seconds")
            # Don't return False here - service might still start, just log warning
    
    return True


def is_quotes_service_running() -> bool:
    """Return True when the tracked QuotesServer process is alive."""
    global _service_process

    return _service_process is not None and _service_process.is_alive()


def stop_quotes_service(timeout: float = 5.0) -> bool:
    """
    Stop quotes service.
    
    Args:
        timeout: Maximum time to wait for service to stop (seconds)
    
    Returns:
        True if service stopped successfully, False otherwise
    """
    global _service_process, _stop_event, _ready_event

    tracked_pid = _service_process.pid if _service_process is not None else None

    if _service_process is None or not _service_process.is_alive():
        logger.warning("Quotes service is not running")
        return False
    
    logger.info("Stopping quotes service...")
    if _stop_event is not None:
        _stop_event.set()
    
    _service_process.join(timeout=timeout)
    
    if _service_process.is_alive():
        logger.error(f"Quotes service did not stop within {timeout} seconds, terminating...")
        _service_process.terminate()
        _service_process.join(timeout=2.0)
        if _service_process.is_alive():
            logger.error("Quotes service did not terminate, killing...")
            _service_process.kill()
            _service_process.join()
    
    _service_process = None
    _stop_event = None
    _ready_event = None

    # Best-effort cleanup of the tracked PID after graceful or forced stop.
    try:
        _clear_stored_service_pid(get_runtime_redis_params(), expected_pid=tracked_pid)
    except Exception as exc:
        logger.warning("Failed to clear stored QuotesServer PID after stop: %s", exc)

    logger.info("Quotes service stopped")
    return True

    