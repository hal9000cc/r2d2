from datetime import datetime, UTC
from typing import Optional, Dict, List, Tuple
import redis
import numpy as np
import msgpack
import logging
import threading
from pathlib import Path
import clickhouse_connect
import ccxt
import asyncio
from .timeframe import Timeframe
from .exceptions import R2D2QuotesException, R2D2QuotesExceptionDataNotReceived
from .constants import TIME_TYPE, TIME_TYPE_UNIT, TIME_UNITS_IN_ONE_SECOND

logger = logging.getLogger(__name__)

# Global variables for service management
_service_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None
_ready_event: Optional[threading.Event] = None


class QuotesServer:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(QuotesServer, cls).__new__(cls)
        return cls._instance

    def __init__(self, redis_params: Optional[Dict] = None, clickhouse_params: Optional[Dict] = None):
        if not QuotesServer._initialized:
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
            
            # Default ClickHouse parameters
            clickhouse_params = clickhouse_params or {}
            self.clickhouse_host = clickhouse_params.get('host', 'localhost')
            self.clickhouse_port = clickhouse_params.get('port', 8123)
            self.clickhouse_username = clickhouse_params.get('username', 'default')
            self.clickhouse_password = clickhouse_params.get('password', '')
            self.clickhouse_database = clickhouse_params.get('database', 'quotes')
            
            self.init_database()
            
            # Dictionary of locks for synchronizing requests by (source, symbol, timeframe)
            # Prevents parallel processing of requests for the same symbol and timeframe
            # Note: Locks are never removed from this dictionary to avoid race conditions
            self._request_locks: Dict[Tuple[str, str, str], asyncio.Lock] = {}
            self._locks_lock = asyncio.Lock()  # For thread-safe access to _request_locks
            
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
        
        return clickhouse_connect.get_client(**params)

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
        
        result = self.clickhouse_client.query(query)
        
        # Get all rows at once
        rows = result.result_rows
        
        # Check if we have any results
        if not rows:
            # Return empty arrays if no data
            return {
                'time': np.array([], dtype=TIME_TYPE),
                'open': np.array([], dtype=np.float64),
                'high': np.array([], dtype=np.float64),
                'low': np.array([], dtype=np.float64),
                'close': np.array([], dtype=np.float64),
                'volume': np.array([], dtype=np.float64)
            }
        
        # Convert rows to numpy arrays (more efficient than list comprehension)
        # Each row is: (time, open, high, low, close, volume)
        n_rows = len(rows)
        time_array = np.array([row[0] for row in rows], dtype=TIME_TYPE)
        open_array = np.array([row[1] for row in rows], dtype=np.float64)
        high_array = np.array([row[2] for row in rows], dtype=np.float64)
        low_array = np.array([row[3] for row in rows], dtype=np.float64)
        close_array = np.array([row[4] for row in rows], dtype=np.float64)
        volume_array = np.array([row[5] for row in rows], dtype=np.float64)
        
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

    async def get_quotes(self, source: str, symbol: str, timeframe: Timeframe, history_start: datetime, history_end: Optional[datetime] = None) -> Dict[str, np.ndarray]:
        """
        Get quotes data from database, filling gaps if needed.
        
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
        if history_end is None:
            history_end = datetime.now(UTC)
        
        # Step 1: Get history from database
        quotes_data = self.get_quotes_base(source, symbol, timeframe, history_start, history_end)
        
        # Step 2: Find gaps (find_gaps handles empty arrays internally)
        gaps = self.find_gaps(quotes_data['time'], timeframe, history_start, history_end)
        
        # Step 3: Fill gaps by calling fetch_bar_async for each gap
        if gaps:
            # Create exchange instance
            exchange_class = getattr(ccxt, source.lower())
            exchange = exchange_class()
            
            # Fill each gap sequentially
            for gap_start, gap_end in gaps:
                logger.info(f"Filling gap for {source}/{symbol}/{timeframe} from {gap_start} to {gap_end}")
                await self.fetch_bar_async(
                    exchange=exchange,
                    exchange_name=source,
                    symbol=symbol,
                    tf=timeframe,
                    time_start=gap_start,
                    time_end=gap_end,
                    max_bars=1000
                )
        
            quotes_data = self.get_quotes_base(source, symbol, timeframe, history_start, history_end)
            
        return quotes_data

    def save_bars(self, exchange_name: str, symbol: str, tf: Timeframe, bars: List[list], check_data: bool = True):
        """
        Save bars to ClickHouse database
        
        Args:
            exchange_name: Exchange name (e.g., 'binance')
            symbol: Trading symbol (e.g., 'BTC/USDT')
            tf: Timeframe object
            bars: List of bars, each bar is [timestamp, open, high, low, close, volume]
            check_data: If True, check for duplicates and gaps before saving
        """
        if not bars:
            return
        
        tf_str = str(tf)
        temp_table = 'temp_save_bars'
        
        try:
            # Create temporary table
            self.clickhouse_client.command(f"""
                CREATE TABLE IF NOT EXISTS {temp_table}
                (
                    source String,
                    symbol String,
                    timeframe String,
                    time DateTime64(3, 'UTC'),
                    open Float64,
                    high Float64,
                    low Float64,
                    close Float64,
                    volume Float64
                )
                ENGINE = Memory
            """)
            
            self.clickhouse_client.command(f"TRUNCATE TABLE {temp_table}")
            
            # Prepare data for insertion
            data = [
                [exchange_name, symbol, tf_str, datetime.fromtimestamp(bar[0] / 1000.0, UTC), bar[1], bar[2], bar[3], bar[4], bar[5]]
                for bar in bars
            ]
            
            self.clickhouse_client.insert(
                temp_table,
                data,
                column_names=['source', 'symbol', 'timeframe', 'time', 'open', 'high', 'low', 'close', 'volume']
            )
            
            # Check for duplicates and gaps if requested
            if check_data:

                query = f"""
                    SELECT 
                        (SELECT COUNT(*) FROM {temp_table} t
                         INNER JOIN quotes q ON t.source = q.source 
                             AND t.symbol = q.symbol 
                             AND t.timeframe = q.timeframe 
                             AND t.time = q.time) as duplicate_count,
                        (SELECT MAX(time) FROM quotes
                         WHERE source = '{exchange_name.replace("'", "''")}' 
                           AND symbol = '{symbol.replace("'", "''")}' 
                           AND timeframe = '{tf_str.replace("'", "''")}') as last_time
                """
                result = self.clickhouse_client.query(query)
                
                if result.result_rows:
                    duplicate_count = result.result_rows[0][0] or 0
                    last_time = result.result_rows[0][1]
                    
                    if last_time:
                        last_time = last_time.replace(tzinfo=UTC)
                    
                    if duplicate_count > 0:
                        raise ValueError(f"Found {duplicate_count} duplicate bars for {exchange_name}/{symbol}/{tf_str}")
            
            # Insert from temp table to main table
            # Convert timestamp (milliseconds) to DateTime64 with UTC timezone
            self.clickhouse_client.command(f"""
                INSERT INTO quotes
                SELECT source, symbol, timeframe, time, open, high, low, close, volume
                FROM {temp_table}
            """)
            
            self.clickhouse_client.command(f"TRUNCATE TABLE {temp_table}")
            logger.info(f"Saved {len(bars)} bars to database ({exchange_name}/{symbol}/{tf_str})")
            
        except Exception as e:
            logger.error(f"Error saving bars to database: {e}", exc_info=True)
            raise

    async def fetch_bar_async(self, exchange: ccxt.Exchange, exchange_name: str, symbol: str, tf: Timeframe, time_start: datetime, time_end: Optional[datetime] = None, max_bars: int = 1000, retry_delay: int = 1) -> tuple:
        """
        Asynchronously fetch bars from exchange
        
        Args:
            exchange: CCXT exchange instance
            exchange_name: Name of the exchange (for logging)
            symbol: Trading pair symbol
            tf: Timeframe object
            time_start: Start time as datetime
            time_end: End time as datetime (optional, if None, fetch until no more data)
            realtime: If True, realtime mode - retry until we get a new bar
            max_bars: Maximum number of bars per request
            retry_delay: Delay in seconds before retry in realtime mode (default: 1)
            
        Returns:
            Tuple (exchange_name, symbol, tf, bars) where:
            - In historical mode: bars is empty list (bars are saved during fetch)
            - In realtime mode: bars contains only the last complete bar [timestamp, open, high, low, close, volume]
        """
        realtime = time_end is None
        if realtime:
            raise ValueError(f"Not released realtime mode for {exchange_name}/{symbol}/{tf_str}")

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
            bars_needed = int(time_diff_ms / timeframe_ms) + 2 # +2 because we need to fetch +1 bars more to be sure that we have the last complete bar
            request_limit = min(bars_needed, max_bars)
            
            try:
                bars = await asyncio.to_thread(
                    exchange.fetch_ohlcv,
                    symbol=symbol,
                    timeframe=tf_str,
                    since=current_since,
                    limit=request_limit
                )
            except Exception as e:
                logger.error(f"Error fetching bars from {exchange_name}/{symbol}/{tf_str}: {e}", exc_info=True)
                raise
            
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
    try:
        source = request_data.get('source')
        symbol = request_data.get('symbol')
        timeframe_str = request_data.get('timeframe')
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
            logger.debug(f"Processing request {request_id} for {source}:{symbol}:{timeframe_str} (locked)")
            
            # Get quotes data (async function)
            quotes_data = await server.get_quotes(source, symbol, timeframe, history_start, history_end)
            
            # Prepare response with binary data
            response_data = {
                'metadata': {
                    'request_id': request_id,
                    'status': 'success',
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
            await asyncio.to_thread(server.redis_client.lpush, individual_response_list, response_bytes)
            
            # Set TTL for response list (async I/O)
            await asyncio.to_thread(server.redis_client.expire, individual_response_list, response_ttl)
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
        await asyncio.to_thread(server.redis_client.lpush, individual_response_list, response_bytes)
        # Set TTL for response list
        await asyncio.to_thread(server.redis_client.expire, individual_response_list, response_ttl)
        logger.warning(f"Request {request_id} failed: {e}")
        
    except Exception as e:
        # Send error response
        response_data = {
            'metadata': {
                'request_id': request_id if request_id else 'unknown',
                'status': 'error',
                'error': str(e)
            }
        }
        if request_id:
            individual_response_list = f"{response_prefix}:{request_id}"
            response_bytes = msgpack.packb(response_data, use_bin_type=True)
            await asyncio.to_thread(server.redis_client.lpush, individual_response_list, response_bytes)
            # Set TTL for response list
            await asyncio.to_thread(server.redis_client.expire, individual_response_list, response_ttl)
        logger.error(f"Error processing request {request_id}: {e}", exc_info=True)


async def run_quotes_service(
    request_list: str = 'quotes:requests',
    response_prefix: str = 'quotes:responses',
    redis_params: Optional[Dict] = None,
    clickhouse_params: Optional[Dict] = None,
    timeout: int = 0,
    response_ttl: int = 300,
    stop_event: Optional[threading.Event] = None
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
        request_list: Redis list name for incoming requests
        response_prefix: Prefix for response list names (each request gets its own list)
        redis_params: Dictionary with Redis connection parameters (host, port, db, password)
        clickhouse_params: Dictionary with ClickHouse connection parameters (host, port, username, password, database)
        timeout: BRPOP timeout in seconds (0 = block indefinitely)
        response_ttl: TTL for response lists in seconds (default: 300 = 5 minutes)
        stop_event: Threading event to signal service stop
    """
    server = QuotesServer(redis_params=redis_params, clickhouse_params=clickhouse_params)
    
    # Clean Redis database from old test data
    patterns = [
        request_list,
        f"{response_prefix}:*",
        'quotes:*'
    ]
    
    for pattern in patterns:
        keys = await asyncio.to_thread(server.redis_client.keys, pattern)
        if keys:
            await asyncio.to_thread(server.redis_client.delete, *keys)
            logger.info(f"Cleaned {len(keys)} keys matching pattern: {pattern}")
    
    logger.info(f"Quotes service started. Listening on list: {request_list}")
    
    # Signal that service is ready to process requests
    global _ready_event
    if _ready_event:
        _ready_event.set()
    
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                # Blocking pop from request list (async I/O)
                result = await asyncio.to_thread(
                    server.redis_client.brpop,
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
                    logger.debug(f"Started async processing for request {request_id}")
                    
                except Exception as e:
                    logger.error(f"Error parsing request: {e}", exc_info=True)
                    
            except Exception as e:
                # Catch any exceptions in the main loop to prevent service from crashing
                logger.error(f"Error in quotes service main loop: {e}", exc_info=True)
                # Wait a bit before retrying to avoid tight error loop
                await asyncio.sleep(1)
                
    except KeyboardInterrupt:
        logger.info("Quotes service stopped by keyboard interrupt")
    except Exception as e:
        logger.error(f"Quotes service crashed with exception: {e}", exc_info=True)
        raise  # Re-raise to ensure thread exits
    finally:
        if stop_event:
            stop_event.clear()
        logger.info("Quotes service finished")


def start_quotes_service(
    request_list: str = 'quotes:requests',
    response_prefix: str = 'quotes:responses',
    redis_params: Optional[Dict] = None,
    clickhouse_params: Optional[Dict] = None,
    timeout: int = 0,
    response_ttl: int = 300,
    wait_ready: bool = True,
    ready_timeout: float = 30.0
) -> bool:
    """
    Start quotes service in a separate thread.
    
    Args:
        request_list: Redis list name for incoming requests
        response_prefix: Prefix for response list names
        redis_params: Dictionary with Redis connection parameters (host, port, db, password)
        clickhouse_params: Dictionary with ClickHouse connection parameters (host, port, username, password, database)
        timeout: BRPOP timeout in seconds
        response_ttl: TTL for response lists in seconds
        wait_ready: If True, wait for service to be ready before returning
        ready_timeout: Maximum time to wait for service to be ready (seconds)
    
    Returns:
        True if service started successfully, False if already running
    """
    global _service_thread, _stop_event, _ready_event
    
    if _service_thread is not None and _service_thread.is_alive():
        logger.warning("Quotes service is already running")
        return False
    
    _stop_event = threading.Event()
    _ready_event = threading.Event()

    def service_wrapper():
        # Run async function in event loop
        try:
            asyncio.run(run_quotes_service(
                request_list=request_list,
                response_prefix=response_prefix,
                redis_params=redis_params,
                clickhouse_params=clickhouse_params,
                timeout=timeout,
                response_ttl=response_ttl,
                stop_event=_stop_event
            ))
        except Exception as e:
            logger.critical(f"Quotes service thread crashed: {e}", exc_info=True)
            # Thread will exit, but we log the error for debugging
    
    _service_thread = threading.Thread(target=service_wrapper, daemon=False)
    _service_thread.start()
    logger.info("Quotes service thread started")
    
    # Wait for service to be ready if requested
    if wait_ready:
        if _ready_event.wait(timeout=ready_timeout):
            logger.info("Quotes service is ready to process requests")
        else:
            logger.warning(f"Quotes service did not become ready within {ready_timeout} seconds")
            # Don't return False here - service might still start, just log warning
    
    return True


def stop_quotes_service(timeout: float = 5.0) -> bool:
    """
    Stop quotes service.
    
    Args:
        timeout: Maximum time to wait for service to stop (seconds)
    
    Returns:
        True if service stopped successfully, False otherwise
    """
    global _service_thread, _stop_event
    
    if _service_thread is None or not _service_thread.is_alive():
        logger.warning("Quotes service is not running")
        return False
    
    logger.info("Stopping quotes service...")
    _stop_event.set()
    
    _service_thread.join(timeout=timeout)
    
    if _service_thread.is_alive():
        logger.error(f"Quotes service did not stop within {timeout} seconds")
        return False
    
    _service_thread = None
    _stop_event = None
    _ready_event = None
    logger.info("Quotes service stopped")
    return True

    