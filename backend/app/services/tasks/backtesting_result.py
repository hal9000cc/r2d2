"""
Class for writing and reading backtesting results to/from Redis.
Uses Sorted Set to store trades and deals.
"""
from typing import Optional, Dict, Any, Tuple, Union, List, TYPE_CHECKING
import json
import weakref
import numpy as np
import msgpack
import redis
from app.services.tasks.tasks import Task
from app.services.tasks.broker import Broker, OrderSide, DealType
from app.core.logger import get_logger
from app.core.datetime_utils import datetime64_to_iso

if TYPE_CHECKING:
    from app.services.tasks.broker_backtesting import UsedIndicatorDescription

logger = get_logger(__name__)


class BackTestingResults:
    """
    Class for writing and reading backtesting results to/from Redis.
    Uses Sorted Set (ZADD) to store trades and deals.
    """
    
    def __init__(self, task: Task, broker: Optional[Broker] = None, ta_proxies: Optional[Dict[str, Any]] = None):
        """
        Constructor.
        
        Args:
            task: Task instance (must have get_result_key() and get_redis_client() methods)
            broker: Optional Broker instance to track. If provided, initializes for writing results.
                   If None, instance is used only for reading results.
            ta_proxies: Optional dictionary of TA proxies (e.g., {'talib': ta_proxy_talib(...)}).
                       Used to access indicator cache for frontend display.
            
        Raises:
            RuntimeError: If initialization fails
        """
        self.task = task
        self._redis_client = None
        self._broker_ref: Optional[weakref.ReferenceType[Broker]] = None
        self._trades_start_index: int = 0
        self.ta_proxies: Optional[Dict[str, Any]] = ta_proxies  # Store TA proxies for access to indicator cache
        self._sent_indicator_keys: set = set()  # Track which indicator keys have been sent to Redis
        
        try:
            if broker is not None:
                # Store weak reference to broker
                self._broker_ref = weakref.ref(broker)
                
                # Remember initial trades list size (should be 0)
                self._trades_start_index = len(broker.trades)
                
                # Clear existing results
                client = self._get_redis_client()
                result_key_prefix = self.task.get_result_key()
                pattern = f"{result_key_prefix}:*"
                
                keys = client.keys(pattern)
                if keys:
                    deleted = client.delete(*keys)
                    logger.debug(f"Reset backtesting results: deleted {deleted} keys matching pattern {pattern}")
        except Exception as e:
            logger.error(f"Failed to initialize backtesting results: {str(e)}")
            raise RuntimeError(f"Failed to initialize backtesting results: {str(e)}") from e
    
    def _get_redis_client(self):
        """
        Get Redis client.
        
        Returns:
            redis.Redis: Redis client instance
            
        Raises:
            RuntimeError: If task is not associated with a list or cannot get Redis client
        """
        if self._redis_client is None:
            self._redis_client = self.task.get_redis_client()
        return self._redis_client
    
    def _get_redis_client_binary(self):
        """
        Get Redis client configured for binary data (decode_responses=False).
        Used for reading binary data like indicator values (msgpack).
        
        Returns:
            redis.Redis: Redis client instance with decode_responses=False
            
        Raises:
            RuntimeError: If task is not associated with a list or cannot get Redis client
        """
        # Get Redis params from task
        redis_params = self.task.get_redis_params()
        
        # Create new client with decode_responses=False for binary data
        return redis.Redis(
            host=redis_params['host'],
            port=redis_params['port'],
            db=redis_params['db'],
            password=redis_params.get('password'),
            decode_responses=False  # Keep binary for msgpack data
        )
    
    def _format_value(self, value) -> str:
        """
        Format value for serialization.
        None -> empty string, bool -> 1/0, else -> str(value)
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)
    
    def _datetime64_to_iso(self, dt64: np.datetime64) -> str:
        """
        Convert np.datetime64 to ISO string.
        
        Args:
            dt64: numpy datetime64 object
            
        Returns:
            str: ISO format string (YYYY-MM-DDTHH:MM:SS)
        """
        # Convert to datetime and format
        dt = dt64.astype('datetime64[s]').astype(int)
        from datetime import datetime, timezone
        return datetime.fromtimestamp(dt, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    
    def _serialize_cache_key(self, cache_key: Tuple) -> str:
        """
        Serialize cache key (tuple) to JSON string for use in Redis key.
        
        Args:
            cache_key: Tuple (name, tuple(sorted(kwargs.items())))
            
        Returns:
            str: JSON-serialized string representation of the cache key
        """
        # cache_key is (name, tuple(sorted(kwargs.items())))
        # Convert to JSON-serializable format: [name, dict(kwargs)]
        name, kwargs_tuple = cache_key
        kwargs_dict = dict(kwargs_tuple)
        return json.dumps([name, kwargs_dict], sort_keys=True)
    
    def _serialize_array(self, arr: np.ndarray) -> bytes:
        """
        Serialize a single numpy array to bytes using msgpack.
        
        Args:
            arr: numpy array to serialize
            
        Returns:
            bytes: msgpack-serialized data with metadata and binary array
        """
        response_data = {
            'metadata': {
                'dtype': str(arr.dtype),
                'shape': list(arr.shape)
            },
            'binary_data': {
                'array': arr.tobytes()
            }
        }
        return msgpack.packb(response_data, use_bin_type=True)
    
    def _deserialize_array(self, arr_bytes: bytes) -> np.ndarray:
        """
        Deserialize a single numpy array from bytes (msgpack).
        
        Args:
            arr_bytes: msgpack-serialized array data
            
        Returns:
            numpy array
        """
        response_data = msgpack.unpackb(arr_bytes, raw=False)
        metadata = response_data.get('metadata', {})
        binary_data = response_data.get('binary_data', {})
        
        dtype = np.dtype(metadata['dtype'])
        shape = tuple(metadata['shape'])
        arr_bytes_data = binary_data.get('array')
        arr = np.frombuffer(arr_bytes_data, dtype=dtype).reshape(shape)
        
        return arr
    
    def _serialize_indicator_values(self, indicator_desc: 'UsedIndicatorDescription') -> bytes:
        """
        Serialize indicator values (numpy array or tuple of arrays) to bytes with metadata.
        Similar to how quotes are serialized in quotes/server.py.
        
        Args:
            indicator_desc: UsedIndicatorDescription object with values and series_info
            
        Returns:
            bytes: msgpack-serialized data with metadata and binary arrays
        """
        values = indicator_desc.values
        series_info = indicator_desc.series_info
        
        if isinstance(values, tuple):
            # Multiple arrays
            arrays_metadata = []
            arrays_binary = []
            for arr in values:
                arrays_metadata.append({
                    'dtype': str(arr.dtype),
                    'shape': list(arr.shape)
                })
                arrays_binary.append(arr.tobytes())
            
            response_data = {
                'metadata': {
                    'is_tuple': True,
                    'arrays': arrays_metadata,
                    'series_info': series_info
                },
                'binary_data': {
                    'arrays': arrays_binary
                }
            }
        else:
            # Single array - build response with series_info
            response_data = {
                'metadata': {
                    'is_tuple': False,
                    'dtype': str(values.dtype),
                    'shape': list(values.shape),
                    'series_info': series_info
                },
                'binary_data': {
                    'array': values.tobytes()
                }
            }
            
        return msgpack.packb(response_data, use_bin_type=True)
    
    
    def _prepare_trades_data(self, broker, result_key_prefix: str, result_id: str):
        """
        Prepare trades data for saving to Redis.
        
        Args:
            broker: Broker instance
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            
        Returns:
            tuple: (trades_key, trades_to_save, new_trades, deal_ids, current_trades_size)
                  Returns None if no new trades
        """
        # Get new trades (from remembered index to current size)
        current_trades_size = len(broker.trades)
        new_trades = broker.trades[self._trades_start_index:current_trades_size]
        
        if not new_trades:
            return None
        
        # Collect unique deal_id from new trades
        deal_ids = set(trade.deal_id for trade in new_trades)
        
        # Prepare trades data for Redis
        trades_key = f"{result_key_prefix}:{result_id}:trades"
        trades_to_save = {}
        
        for trade in new_trades:
            time_iso = datetime64_to_iso(trade.time)
            side_str = trade.side.value  # "buy" or "sell"
            
            # Format member: trade_id|deal_id|order_id|time_iso|side|price|quantity|fee|sum
            member = f"{trade.trade_id}|{trade.deal_id}|{trade.order_id}|{time_iso}|{side_str}|{trade.price}|{trade.quantity}|{trade.fee}|{trade.sum}"
            
            # Use time as score (numeric representation in milliseconds)
            # Convert numpy int64 to Python int for Redis compatibility
            score = int(trade.time.astype('datetime64[ms]').astype(int))
            trades_to_save[member] = score
        
        return (trades_key, trades_to_save, new_trades, deal_ids, current_trades_size)
    
    def _prepare_deals_data(self, broker, result_key_prefix: str, result_id: str, deal_ids: set):
        """
        Prepare deals data for saving to Redis.
        
        Args:
            broker: Broker instance
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            deal_ids: Set of deal IDs to save
            
        Returns:
            tuple: (deals_key, deals_to_save)
        """
        deals_key = f"{result_key_prefix}:{result_id}:deals"
        deals_to_save = {}
        
        if deal_ids:
            for deal in broker.deals:
                if deal.deal_id in deal_ids:
                    # Format member: deal_id|type|avg_buy_price|avg_sell_price|quantity|fee|profit|is_closed
                    member = (
                        f"{deal.deal_id}|"
                        f"{deal.type.value if deal.type else ''}|"
                        f"{self._format_value(deal.avg_buy_price)}|"
                        f"{self._format_value(deal.avg_sell_price)}|"
                        f"{deal.quantity}|"
                        f"{deal.fee}|"
                        f"{self._format_value(deal.profit)}|"
                        f"{self._format_value(deal.is_closed)}"
                    )
                    
                    # Use deal_id as score (convert to int if needed)
                    score = int(deal.deal_id)
                    deals_to_save[member] = score
        
        return (deals_key, deals_to_save)
    
    def _prepare_stats_data(self, broker, result_key_prefix: str, result_id: str, is_finish: bool):
        """
        Prepare statistics data for saving to Redis.
        
        Args:
            broker: Broker instance
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            is_finish: Whether this is the final save
            
        Returns:
            tuple: (stats_key, stats_json) or (stats_key, None) if no stats
        """
        stats_key = f"{result_key_prefix}:{result_id}:stats"
        stats_json = None
        
        if broker.stats:
            # Calculate additional statistics before saving
            broker.stats.calc_stat()
            
            # Create stats dict excluding internal fields
            stats_dict = {
                'initial_equity_usd': broker.stats.initial_equity_usd,
                'total_trades': broker.stats.total_trades,
                'buy_trades': broker.stats.buy_trades,
                'sell_trades': broker.stats.sell_trades,
                'max_market_volume': broker.stats.max_market_volume,
                'total_fees': broker.stats.total_fees,
                'profit': broker.stats.profit,
                'drawdown_max': broker.stats.drawdown_max,
                'total_deals': broker.stats.total_deals,
                'long_deals': broker.stats.long_deals,
                'short_deals': broker.stats.short_deals,
                'profit_deals': broker.stats.profit_deals,
                'loss_deals': broker.stats.loss_deals,
                'profit_per_deal': broker.stats.profit_per_deal,
                'profit_gross': broker.stats.profit_gross,
                'profit_long': broker.stats.profit_long,
                'profit_short': broker.stats.profit_short,
                'completed': is_finish,
            }
            stats_json = json.dumps(stats_dict)
        
        return (stats_key, stats_json)
    
    def _save_quotes_time(self, result_key_prefix: str, result_id: str):
        """
        Save quotes time series to Redis (only on first call).
        Uses msgpack format similar to indicators.
        
        Args:
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            
        Returns:
            bool: True if saved (first time), False if already exists
        """
        if not self.ta_proxies:
            return False
        
        # Get first proxy to access quotes_data
        first_proxy = next(iter(self.ta_proxies.values()))
        if not hasattr(first_proxy, 'quotes_data') or 'time' not in first_proxy.quotes_data:
            return False
        
        time_array = first_proxy.quotes_data['time']
        
        # Serialize time array using msgpack (same format as indicators)
        client_binary = self._get_redis_client_binary()
        time_key = f"{result_key_prefix}:{result_id}:time"
        
        # Check if already saved (using binary client for consistency)
        if client_binary.exists(time_key.encode('utf-8')):
            return False  # Already saved
        
        # Serialize time array
        time_bytes = self._serialize_array(time_array)
        
        # Save to Redis
        client_binary.set(time_key.encode('utf-8'), time_bytes)
        
        logger.debug(f"Saved quotes time series to {time_key}")
        return True
    
    def _save_indicators(self, result_key_prefix: str, result_id: str):
        """
        Save new indicators from TA proxies cache to Redis using separate pipeline.
        
        Args:
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            
        Returns:
            set: Set of composite keys (proxy_name, cache_key) that were actually saved
        """
        saved_indicator_keys = set()
        
        if not self.ta_proxies:
            return saved_indicator_keys
        
        # Use binary client for saving indicator data (msgpack)
        client = self._get_redis_client_binary()
        indicators_key_prefix = f"{result_key_prefix}:{result_id}:indicators"
        
        # Collect all current cache keys from all proxies
        current_cache_keys = set()
        for proxy_name, proxy in self.ta_proxies.items():
            if hasattr(proxy, 'cache') and proxy.cache:
                for cache_key in proxy.cache.keys():
                    # Create composite key: (proxy_name, cache_key)
                    composite_key = (proxy_name, cache_key)
                    current_cache_keys.add(composite_key)
        
        # Find new keys using set difference
        new_indicator_keys = current_cache_keys - self._sent_indicator_keys
        
        if not new_indicator_keys:
            return saved_indicator_keys
        
        # Create separate pipeline for indicators
        indicators_pipeline = client.pipeline()
        
        # Process and save new indicators
        for composite_key in new_indicator_keys:
            proxy_name, cache_key = composite_key
            proxy = self.ta_proxies[proxy_name]
            
            # Get indicator description from cache
            indicator_desc = proxy.cache[cache_key]
            
            # Skip if not visible
            if not indicator_desc.visible:
                continue
            
            # Serialize cache key for Redis key
            serialized_cache_key = self._serialize_cache_key(cache_key)
            
            # Serialize indicator values
            indicator_bytes = self._serialize_indicator_values(indicator_desc)
            
            # Create Redis key: {prefix}:{result_id}:indicators:{proxy_name}:{serialized_cache_key}
            indicator_redis_key = f"{indicators_key_prefix}:{proxy_name}:{serialized_cache_key}"
            
            # Add to pipeline
            indicators_pipeline.set(indicator_redis_key, indicator_bytes)
            
            # Mark as saved
            saved_indicator_keys.add(composite_key)
        
        # Execute indicators pipeline if there are any indicators to save
        if saved_indicator_keys:
            indicators_pipeline.execute()
        
        return saved_indicator_keys
    
    def put_result(self, is_finish: bool = False) -> None:
        """
        Save new trades and deals to Redis.
        Checks trades list size, saves new trades, collects deal_id, saves deals.
        
        Args:
            is_finish: If True, marks the backtesting result as completed. Default: False.
        
        Raises:
            RuntimeError: If broker was not provided during initialization or save operation fails
        """
        if self._broker_ref is None:
            raise RuntimeError("Cannot save results: broker was not provided during initialization")
        
        try:
            # Get broker from weak reference
            broker = self._broker_ref()
            if broker is None:
                raise RuntimeError("Broker reference is no longer valid")
            
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            result_id = broker.result_id
            
            # Prepare trades data
            trades_data = self._prepare_trades_data(broker, result_key_prefix, result_id)
            if trades_data is None:
                return  # No new trades
            
            trades_key, trades_to_save, new_trades, deal_ids, current_trades_size = trades_data
            
            # Prepare deals data
            deals_key, deals_to_save = self._prepare_deals_data(broker, result_key_prefix, result_id, deal_ids)
            
            # Prepare statistics data
            stats_key, stats_json = self._prepare_stats_data(broker, result_key_prefix, result_id, is_finish)
            
            # Use pipeline to execute all write operations in one batch
            pipeline = client.pipeline()
            
            # Add trades to pipeline
            if trades_to_save:
                pipeline.zadd(trades_key, trades_to_save)
            
            # Add deals to pipeline
            if deals_to_save:
                pipeline.zadd(deals_key, deals_to_save)
            
            # Add statistics to pipeline
            if stats_json:
                pipeline.set(stats_key, stats_json)
            
            # Execute main pipeline (trades, deals, stats)
            pipeline.execute()
            
            # Update trades start index only after successful save
            self._trades_start_index = current_trades_size
            
            # Save quotes time series (only on first call)
            self._save_quotes_time(result_key_prefix, result_id)
            
            # Save indicators in separate pipeline
            saved_indicator_keys = self._save_indicators(result_key_prefix, result_id)
            
            # Update sent indicator keys only after successful save (only visible ones)
            if saved_indicator_keys:
                self._sent_indicator_keys.update(saved_indicator_keys)
            
            # Log operations
            if trades_to_save:
                logger.debug(f"Saved {len(new_trades)} new trades")
            if deals_to_save:
                logger.debug(f"Saved {len(deals_to_save)} deals to {deals_key}")
            if stats_json:
                logger.debug(f"Saved statistics to {stats_key}")
            if saved_indicator_keys:
                logger.debug(f"Saved {len(saved_indicator_keys)} new indicators to Redis")
        except Exception as e:
            logger.error(f"Failed to save results: {str(e)}")
            raise RuntimeError(f"Failed to save results: {str(e)}") from e
    
    def get_results(
        self, 
        result_id: str,
        time_begin: Optional[np.datetime64] = None
    ) -> Dict:
        """
        Get results for the specified time interval.
        Returns all trades with time >= time_begin and corresponding deals.
        
        Args:
            result_id: Result ID
            time_begin: Interval start (default: 1900-01-01)
            
        Returns:
            Dictionary with "trades" and "deals" lists
        """
        if time_begin is None:
            time_begin = np.datetime64('1900-01-01T00:00:00', 'ns')
        
        try:
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            
            # Convert time_begin to numeric score (milliseconds)
            # Convert numpy int64 to Python int for Redis compatibility
            time_begin_score = int(time_begin.astype('datetime64[ms]').astype(int))
            
            # Get trades with time >= time_begin
            trades_key = f"{result_key_prefix}:{result_id}:trades"
            trades_data = client.zrangebyscore(trades_key, time_begin_score, '+inf', withscores=False)
            
            # Parse trades and collect deal_id
            trades = []
            deal_ids = set()
            
            for member in trades_data:
                parts = member.split('|')
                
                if len(parts) >= 9:
                    trade_dict = {
                        'trade_id': parts[0],
                        'deal_id': parts[1],
                        'order_id': parts[2],
                        'time': parts[3],
                        'side': parts[4],
                        'price': parts[5],
                        'quantity': parts[6],
                        'fee': parts[7],
                        'sum': parts[8]
                    }
                    trades.append(trade_dict)
                    deal_ids.add(int(parts[1]))
            
            # Get deals using PIPELINE
            deals = []
            if deal_ids:
                deals_key = f"{result_key_prefix}:{result_id}:deals"
                pipeline = client.pipeline()
                
                # Add ZRANGEBYSCORE commands for each deal_id
                # Convert deal_id to int if needed (deal_ids come from parsed strings)
                for deal_id in deal_ids:
                    deal_id_int = int(deal_id)
                    pipeline.zrangebyscore(deals_key, deal_id_int, deal_id_int, withscores=False)
                
                # Execute pipeline
                deals_data_list = pipeline.execute()
                
                # Parse deals
                for deals_data in deals_data_list:
                    if deals_data:
                        member = deals_data[0]
                        parts = member.split('|')
                        
                        if len(parts) >= 8:
                            deal_dict = {
                                'deal_id': parts[0],
                                'type': parts[1] if parts[1] else None,
                                'avg_buy_price': parts[2] if parts[2] else None,
                                'avg_sell_price': parts[3] if parts[3] else None,
                                'quantity': parts[4],
                                'fee': parts[5],
                                'profit': parts[6] if parts[6] else None,
                                'is_closed': parts[7] == '1' if parts[7] else False
                            }
                            deals.append(deal_dict)
            
            # Get statistics
            stats_key = f"{result_key_prefix}:{result_id}:stats"
            stats = None
            try:
                stats_data = client.get(stats_key)
                if stats_data:
                    stats = json.loads(stats_data)
            except Exception as e:
                logger.warning(f"Failed to load statistics from {stats_key}: {e}")
            
            result = {
                'trades': trades,
                'deals': deals
            }
            
            if stats is not None:
                result['stats'] = stats
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get results: {str(e)}")
            raise RuntimeError(f"Failed to get results: {str(e)}") from e
    
    def _deserialize_indicator_values(self, indicator_bytes: bytes) -> Dict[str, Any]:
        """
        Deserialize indicator values from bytes (msgpack) to numpy arrays.
        Similar to how quotes are deserialized in quotes/client.py.
        
        Args:
            indicator_bytes: msgpack-serialized indicator data
            
        Returns:
            Dictionary with 'metadata' and 'values' (numpy arrays)
        """
        # Deserialize MessagePack response
        response_data = msgpack.unpackb(indicator_bytes, raw=False)
        
        metadata = response_data.get('metadata', {})
        binary_data = response_data.get('binary_data', {})
        
        is_tuple = metadata.get('is_tuple', False)
        series_info = metadata.get('series_info', [])
        
        if is_tuple:
            # Multiple arrays
            arrays_metadata = metadata.get('arrays', [])
            arrays_binary = binary_data.get('arrays', [])
            
            if len(arrays_metadata) != len(arrays_binary):
                raise ValueError(f"Mismatch between arrays metadata ({len(arrays_metadata)}) and binary data ({len(arrays_binary)})")
            
            # Reconstruct numpy arrays
            reconstructed_arrays = []
            for arr_meta, arr_bytes in zip(arrays_metadata, arrays_binary):
                dtype = np.dtype(arr_meta['dtype'])
                shape = tuple(arr_meta['shape'])
                arr = np.frombuffer(arr_bytes, dtype=dtype).reshape(shape)
                reconstructed_arrays.append(arr)
            
            # Use series_info to create dict with named keys
            if series_info and len(series_info) == len(reconstructed_arrays):
                values = {info['name']: arr.tolist() for info, arr in zip(series_info, reconstructed_arrays)}
            else:
                # Fallback: use generic names
                names = [info.get('name', f'series{i}') for i, info in enumerate(series_info)] if series_info else [f'series{i}' for i in range(len(reconstructed_arrays))]
                # Ensure we have enough names
                while len(names) < len(reconstructed_arrays):
                    names.append(f'series{len(names)}')
                values = {name: arr.tolist() for name, arr in zip(names, reconstructed_arrays)}
        else:
            # Single array
            dtype = np.dtype(metadata['dtype'])
            shape = tuple(metadata['shape'])
            arr_bytes = binary_data.get('array')
            arr = np.frombuffer(arr_bytes, dtype=dtype).reshape(shape)
            values = arr.tolist()
        
        return {
            'metadata': {
                'is_tuple': is_tuple,
                'series_info': series_info
            },
            'values': values
        }
    
    def _load_quotes_time(self, result_key_prefix: str, result_id: str) -> Optional[np.ndarray]:
        """
        Load quotes time series from Redis.
        
        Args:
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            
        Returns:
            numpy array with time series or None if not found
        """
        try:
            client_binary = self._get_redis_client_binary()
            time_key = f"{result_key_prefix}:{result_id}:time"
            
            time_bytes = client_binary.get(time_key.encode('utf-8'))
            
            if time_bytes is None:
                return None
            
            # Deserialize array
            deserialized = self._deserialize_array(time_bytes)
            
            return deserialized
        except Exception as e:
            logger.warning(f"Failed to load quotes time series: {e}")
            return None
    
    def _get_indicator_slice_indices(self, time_array: np.ndarray, date_start: np.datetime64, date_end: np.datetime64) -> tuple[int, int]:
        """
        Calculate slice indices for filtering indicators by date range.
        
        Args:
            time_array: Array of datetime64 timestamps
            date_start: Start date (datetime64) for filtering
            date_end: End date (datetime64) for filtering
            
        Returns:
            Tuple of (start_idx, end_idx) for slicing
        """
        # Find first index where time >= date_start
        start_idx = np.searchsorted(time_array, date_start, side='left')
        # Find last index where time <= date_end (inclusive)
        end_idx = np.searchsorted(time_array, date_end, side='right')
        
        # Clamp indices to array bounds
        start_idx = max(0, min(start_idx, len(time_array) - 1))
        end_idx = max(start_idx, min(end_idx, len(time_array)))
        
        return start_idx, end_idx
    
    def _get_indicator_keys_from_redis(self, result_key_prefix: str, result_id: str) -> tuple[list[str], list[str]]:
        """
        Get indicator keys from Redis and extract indicator key names.
        
        Args:
            result_key_prefix: Result key prefix
            result_id: Result ID
            
        Returns:
            Tuple of (indicator_keys, redis_keys_to_fetch)
            indicator_keys: List of indicator key names (e.g., "talib:[\"SMA\",{\"timeperiod\":50}]")
            redis_keys_to_fetch: List of full Redis keys to fetch
        """
        client = self._get_redis_client()
        indicators_key_prefix = f"{result_key_prefix}:{result_id}:indicators"
        
        # Get all indicator keys from Redis
        pattern = f"{indicators_key_prefix}:*"
        all_redis_keys = client.keys(pattern)
        
        if not all_redis_keys:
            return [], []
        
        # Extract indicator keys (remove prefix to get {proxy_name}:{serialized_cache_key})
        indicator_keys = []
        redis_keys_to_fetch = []
        
        for redis_key in all_redis_keys:
            # Extract indicator key: remove prefix "{prefix}:{result_id}:indicators:"
            prefix_to_remove = f"{indicators_key_prefix}:"
            if not redis_key.startswith(prefix_to_remove):
                continue
            
            indicator_key = redis_key[len(prefix_to_remove):]  # {proxy_name}:{serialized_cache_key}
            indicator_keys.append(indicator_key)
            redis_keys_to_fetch.append(redis_key)
        
        return indicator_keys, redis_keys_to_fetch
    
    def _fetch_indicator_data_from_redis(self, redis_keys_to_fetch: list[str]) -> list[bytes]:
        """
        Fetch indicator data from Redis using pipeline.
        
        Args:
            redis_keys_to_fetch: List of Redis keys to fetch
            
        Returns:
            List of indicator data bytes (or None if key not found)
        """
        client_binary = self._get_redis_client_binary()
        pipeline = client_binary.pipeline()
        for redis_key in redis_keys_to_fetch:
            pipeline.get(redis_key)
        return pipeline.execute()
    
    def _parse_indicator_key(self, indicator_key: str) -> tuple[str, str, dict]:
        """
        Parse indicator key to extract proxy_name, indicator_name, and parameters.
        
        Args:
            indicator_key: Indicator key in format "{proxy_name}:{serialized_cache_key}"
            
        Returns:
            Tuple of (proxy_name, indicator_name, parameters)
            
        Raises:
            ValueError: If key format is invalid
        """
        # Parse indicator key to extract proxy_name and cache_key
        parts = indicator_key.split(':', 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid indicator key format: {indicator_key}")
        
        proxy_name = parts[0]
        serialized_cache_key = parts[1]
        
        # Parse cache_key JSON to get indicator_name and parameters
        cache_key_data = json.loads(serialized_cache_key)
        if not isinstance(cache_key_data, list) or len(cache_key_data) != 2:
            raise ValueError(f"Invalid cache key format: {serialized_cache_key}")
        
        indicator_name = cache_key_data[0]
        parameters = cache_key_data[1]
        
        return proxy_name, indicator_name, parameters
    
    def _convert_dict_numpy_types(self, obj: Any) -> Any:
        """
        Recursively convert numpy types in a dictionary to Python types.
        Similar to how quotes are converted in get_quotes endpoint.
        """
        if isinstance(obj, dict):
            return {key: self._convert_dict_numpy_types(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_dict_numpy_types(item) for item in obj]
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            val_float = float(obj)
            if np.isnan(val_float):
                return None
            return val_float
        elif isinstance(obj, (int, float)):
            if isinstance(obj, float) and (obj != obj):
                return None
            return obj
        else:
            try:
                if hasattr(obj, 'item'):
                    val_item = obj.item()
                    if isinstance(val_item, float) and (val_item != val_item):
                        return None
                    return val_item
                return obj
            except (AttributeError, ValueError, TypeError):
                return obj
    
    def _filter_indicator_values_by_range(self, values: Any, is_tuple: bool, start_idx: int, end_idx: int) -> Any:
        """
        Filter indicator values by date range indices.
        
        Args:
            values: Indicator values (dict for multi-series, list for single series)
            is_tuple: Whether indicator has multiple series
            start_idx: Start index for slicing
            end_idx: End index for slicing (inclusive)
            
        Returns:
            Filtered values (same structure as input, with numpy types converted to Python types)
        """
        def convert_value(val):
            """
            Convert a single value from numpy type to Python type.
            Similar to how quotes are converted in get_quotes endpoint (float(open_array[i])).
            """
            if val is None:
                return None
            # Check for numpy types first
            if isinstance(val, np.integer):
                return int(val)
            elif isinstance(val, np.floating):
                val_float = float(val)
                # Convert NaN to None for JSON compatibility
                if np.isnan(val_float):
                    return None
                return val_float
            elif isinstance(val, (int, float)):
                # Check if float is NaN
                if isinstance(val, float) and (val != val):
                    return None
                return val
            else:
                # Fallback: try to convert numpy scalar
                try:
                    if hasattr(val, 'item'):
                        val_item = val.item()
                        if isinstance(val_item, float) and (val_item != val_item):
                            return None
                        return val_item
                    return val
                except (AttributeError, ValueError, TypeError):
                    return val
        
        if is_tuple:
            # Multiple series (dict with series names as keys, values are lists)
            filtered_values = {}
            for series_name, values_list in values.items():
                if len(values_list) > 0:
                    # Clamp indices to array bounds
                    arr_start = min(start_idx, len(values_list))
                    arr_end = min(end_idx, len(values_list))
                    if arr_start < arr_end:
                        # Slice list (inclusive end: end_idx+1)
                        sliced = values_list[arr_start:arr_end+1]
                        # Convert each value explicitly, like in get_quotes: float(open_array[i])
                        filtered_values[series_name] = [convert_value(val) for val in sliced]
                    else:
                        filtered_values[series_name] = []
                else:
                    filtered_values[series_name] = []
            return filtered_values
        else:
            # Single series (list)
            if len(values) > 0:
                # Clamp indices to array bounds
                arr_start = min(start_idx, len(values))
                arr_end = min(end_idx, len(values))
                if arr_start < arr_end:
                    # Slice list (inclusive end: end_idx+1)
                    sliced = values[arr_start:arr_end+1]
                    # Convert each value explicitly, like in get_quotes: float(open_array[i])
                    return [convert_value(val) for val in sliced]
                else:
                    return []
            else:
                return []
    
    def _build_indicator_result_entry(
        self,
        indicator_key: str,
        proxy_name: str,
        indicator_name: str,
        parameters: dict,
        is_tuple: bool,
        series_info: list,
        filtered_values: Any,
        time_range_iso: list[str],
        date_start_iso: str,
        date_end_iso: str
    ) -> dict[str, Any]:
        """
        Build result entry for a single indicator.
        
        Args:
            indicator_key: Indicator key
            proxy_name: Proxy name
            indicator_name: Indicator name
            parameters: Indicator parameters
            is_tuple: Whether indicator has multiple series
            series_info: Series information
            filtered_values: Filtered indicator values
            time_range_iso: Time range as ISO strings
            date_start_iso: Start date as ISO string
            date_end_iso: End date as ISO string
            
        Returns:
            Dictionary with indicator data
        """
        return {
            'proxy_name': proxy_name,
            'indicator_name': indicator_name,
            'parameters': parameters,
            'is_tuple': is_tuple,
            'series_info': series_info,
            'values': filtered_values,
            'time': time_range_iso,
            'date_start': date_start_iso,
            'date_end': date_end_iso
        }
    
    def get_indicators(self, result_id: str, date_start: np.datetime64, date_end: np.datetime64) -> Dict[str, Dict[str, Any]]:
        """
        Get all indicators from Redis filtered by date range.
        
        Args:
            result_id: Result ID
            date_start: Start date (datetime64) for filtering
            date_end: End date (datetime64) for filtering
            
        Returns:
            Dictionary mapping indicator key to indicator data:
            {
                "talib:[\"SMA\",{\"timeperiod\":50}]": {
                    "proxy_name": "talib",
                    "indicator_name": "SMA",
                    "parameters": {"timeperiod": 50},
                    "is_tuple": false,
                    "series_info": [{"name": "SMA", "is_price": true}],
                    "values": [1.0, 2.0, ...],  # filtered by date range
                    "date_start": "ISO string",
                    "date_end": "ISO string"
                },
                ...
            }
            
        Raises:
            RuntimeError: If operation fails
        """
        try:
            # Load quotes time series to determine indices
            result_key_prefix = self.task.get_result_key()
            time_array = self._load_quotes_time(result_key_prefix, result_id)
            
            if time_array is None or len(time_array) == 0:
                logger.warning(f"No quotes time series found for result_id {result_id}")
                return {}
            
            # Calculate slice indices for date range
            start_idx, end_idx = self._get_indicator_slice_indices(time_array, date_start, date_end)
            # Ensure indices are Python int, not numpy int
            start_idx = int(start_idx)
            end_idx = int(end_idx)
            
            if start_idx > end_idx:
                logger.info(f"Requested date range {date_start} - {date_end} is outside quotes time range. Returning empty indicators.")
                return {}
            
            # Get indicator keys from Redis
            indicator_keys, redis_keys_to_fetch = self._get_indicator_keys_from_redis(result_key_prefix, result_id)
            
            if not indicator_keys:
                return {}
            
            # Fetch indicator data from Redis
            indicator_data_list = self._fetch_indicator_data_from_redis(redis_keys_to_fetch)
            
            # Convert dates to ISO strings for metadata
            date_start_iso = datetime64_to_iso(date_start)
            date_end_iso = datetime64_to_iso(date_end)
            
            # Extract time range for indicators (matching the filtered values)
            time_range = time_array[start_idx:end_idx+1]
            # Convert datetime64 to ISO strings (ensure Python strings, not numpy types)
            time_range_iso = [str(datetime64_to_iso(t)) for t in time_range]
            
            # Process and deserialize indicators
            result = {}
            indicators_processed = 0
            
            for indicator_key, indicator_bytes in zip(indicator_keys, indicator_data_list):
                if indicator_bytes is None:
                    logger.warning(f"Indicator key {indicator_key} not found in Redis")
                    continue
                
                try:
                    # Deserialize indicator
                    deserialized = self._deserialize_indicator_values(indicator_bytes)
                    
                    # Parse indicator key
                    try:
                        proxy_name, indicator_name, parameters = self._parse_indicator_key(indicator_key)
                        # Convert numpy types in parameters to Python types (like in get_quotes)
                        parameters = self._convert_dict_numpy_types(parameters)
                    except (ValueError, json.JSONDecodeError) as e:
                        logger.warning(f"Failed to parse indicator key {indicator_key}: {e}")
                        continue
                    
                    # Filter values by date range
                    # Ensure is_tuple is Python bool, not numpy bool
                    is_tuple = bool(deserialized['metadata']['is_tuple'])
                    
                    filtered_values = self._filter_indicator_values_by_range(
                        deserialized['values'],
                        is_tuple,
                        start_idx,
                        end_idx
                    )
                    
                    # Convert series_info numpy types to Python types
                    series_info = self._convert_dict_numpy_types(deserialized['metadata']['series_info'])
                    
                    # Build result entry
                    entry = self._build_indicator_result_entry(
                        indicator_key=indicator_key,
                        proxy_name=proxy_name,
                        indicator_name=indicator_name,
                        parameters=parameters,
                        is_tuple=is_tuple,
                        series_info=series_info,
                        filtered_values=filtered_values,
                        time_range_iso=time_range_iso,
                        date_start_iso=date_start_iso,
                        date_end_iso=date_end_iso
                    )
                    
                    # Convert entry to ensure all numpy types are converted
                    entry = self._convert_dict_numpy_types(entry)
                    
                    result[indicator_key] = entry
                    indicators_processed += 1
                except Exception as e:
                    logger.error(f"Failed to deserialize indicator {indicator_key}: {e}", exc_info=True)
                    raise RuntimeError(f"Failed to deserialize indicator {indicator_key}: {str(e)}") from e
            
            # Convert all numpy types in the entire result structure before returning
            # This ensures JSON serialization will work (like in get_quotes)
            converted_result = self._convert_dict_numpy_types(result)
            
            return converted_result
            
        except Exception as e:
            logger.error(f"Failed to get indicators: {str(e)}")
            raise RuntimeError(f"Failed to get indicators: {str(e)}") from e

    def get_indicators_key(self, result_id: str) -> list[Dict[str, Any]]:
        """
        Get indicator keys and metadata (without values) from Redis.
        This is a lightweight method that returns only keys and metadata,
        without loading and processing indicator values.
        
        Args:
            result_id: Result ID
            
        Returns:
            List of indicator objects with key and metadata:
            [
                {
                    "key": "talib:[\"SMA\",{\"timeperiod\":50}]",
                    "proxy_name": "talib",
                    "indicator_name": "SMA",
                    "parameters": {"timeperiod": 50},
                    "is_tuple": false,
                    "series_info": [{"name": "SMA", "is_price": true}]
                },
                ...
            ]
            
        Raises:
            RuntimeError: If operation fails
        """
        try:
            result_key_prefix = self.task.get_result_key()
            
            # Get indicator keys from Redis
            indicator_keys, redis_keys_to_fetch = self._get_indicator_keys_from_redis(result_key_prefix, result_id)
            
            if not indicator_keys:
                return []
            
            # Fetch indicator data from Redis (we need metadata, but won't process values)
            indicator_data_list = self._fetch_indicator_data_from_redis(redis_keys_to_fetch)
            
            # Process indicators to extract metadata only
            result = []
            
            for indicator_key, indicator_bytes in zip(indicator_keys, indicator_data_list):
                if indicator_bytes is None:
                    logger.warning(f"Indicator key {indicator_key} not found in Redis")
                    continue
                
                try:
                    # Deserialize only metadata (not values)
                    # We unpack msgpack but only use metadata part
                    response_data = msgpack.unpackb(indicator_bytes, raw=False)
                    metadata = response_data.get('metadata', {})
                    
                    # Parse indicator key
                    try:
                        proxy_name, indicator_name, parameters = self._parse_indicator_key(indicator_key)
                        # Convert numpy types in parameters to Python types
                        parameters = self._convert_dict_numpy_types(parameters)
                    except (ValueError, json.JSONDecodeError) as e:
                        logger.warning(f"Failed to parse indicator key {indicator_key}: {e}")
                        continue
                    
                    # Extract metadata fields
                    is_tuple = bool(metadata.get('is_tuple', False))
                    series_info = metadata.get('series_info', [])
                    # Convert series_info numpy types to Python types
                    series_info = self._convert_dict_numpy_types(series_info)
                    
                    # Build result entry
                    entry = {
                        'key': indicator_key,
                        'proxy_name': proxy_name,
                        'indicator_name': indicator_name,
                        'parameters': parameters,
                        'is_tuple': is_tuple,
                        'series_info': series_info
                    }
                    
                    # Convert all numpy types in entry
                    entry = self._convert_dict_numpy_types(entry)
                    
                    result.append(entry)
                except Exception as e:
                    logger.error(f"Failed to extract metadata from indicator {indicator_key}: {e}", exc_info=True)
                    # Continue with other indicators instead of failing completely
                    continue
            
            # Convert all numpy types in the entire result structure before returning
            converted_result = self._convert_dict_numpy_types(result)
            
            return converted_result
            
        except Exception as e:
            logger.error(f"Failed to get indicator keys: {str(e)}")
            raise RuntimeError(f"Failed to get indicator keys: {str(e)}") from e

