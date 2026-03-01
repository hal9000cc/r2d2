"""
Class for writing and reading backtesting results to/from Redis.
Uses Sorted Set to store trades and deals.
"""
from typing import Optional, Dict, Any, Tuple, List, TYPE_CHECKING
import json
import weakref
import numpy as np
import msgpack
import redis
from app.services.tasks.tasks import Task
from app.core.logger import get_logger
from app.core.datetime_utils import datetime64_to_iso

if TYPE_CHECKING:
    from app.services.tasks.broker import Broker
    from app.services.tasks.broker_backtesting import UsedIndicatorDescription

logger = get_logger(__name__)


class TaskResults:
    """
    Class for writing and reading backtesting results to/from Redis.
    Uses Sorted Set (ZADD) to store trades and deals.
    """
    
    def __init__(self, task: Task, broker: Optional['Broker'] = None, ta_proxies: Optional[Dict[str, Any]] = None):
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
        self._broker_ref: Optional[weakref.ReferenceType['Broker']] = None
        self._trades_start_index: int = 0
        self._last_orders_save_time: Optional[np.datetime64] = None
        self.ta_proxies: Optional[Dict[str, Any]] = ta_proxies
        self._sent_indicator_keys: set = set()
        
        try:
            if broker is not None:
                self._broker_ref = weakref.ref(broker)
                self._trades_start_index = len(broker.trades)
                
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
        redis_params = self.task.get_redis_params()
        
        return redis.Redis(
            host=redis_params['host'],
            port=redis_params['port'],
            db=redis_params['db'],
            password=redis_params.get('password'),
            decode_responses=False
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
        dt = dt64.astype('datetime64[s]').astype(int)
        from datetime import datetime, timezone
        return datetime.fromtimestamp(dt, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    
    def _serialize_cache_key(self, cache_key: Tuple) -> str:
        """
        Serialize cache key (tuple) to JSON string for use in Redis key.
        
        Args:
            cache_key: Tuple (name, actual_symbol, actual_tf, tuple(sorted(kwargs.items())))
            
        Returns:
            str: JSON-serialized string representation of the cache key
        """
        assert len(cache_key) == 4, f"Expected cache_key with 4 elements, got {len(cache_key)}: {cache_key}"
        name, actual_symbol, actual_tf, kwargs_tuple = cache_key
        kwargs_dict = dict(kwargs_tuple)
        timeframe_str = str(actual_tf)
        return json.dumps([name, actual_symbol, timeframe_str, kwargs_dict], sort_keys=True)
    
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
        Serialize indicator values from IndicatorResult to bytes with metadata.
        Similar to how quotes are serialized in quotes/server.py.
        
        Args:
            indicator_desc: UsedIndicatorDescription object with IndicatorResult values and series_info
            
        Returns:
            bytes: msgpack-serialized data with metadata and binary arrays
            
        Raises:
            ValueError: If series_info is empty or number of arrays doesn't match series_info length
        """
        values = indicator_desc.values
        series_info = indicator_desc.series_info
        
        # Check that series_info is not empty
        if not series_info:
            raise ValueError("series_info cannot be empty")
        
        # Extract arrays from IndicatorResult using series_info
        arrays_metadata = []
        arrays_binary = []
        
        for info in series_info:
            series_name = info['name']
            # Extract array from IndicatorResult (KeyError will propagate if not found)
            arr = values[series_name]
            # Assert that extracted value is a numpy array
            assert isinstance(arr, np.ndarray), f"Expected numpy array for series '{series_name}', got {type(arr)}"
            
            arrays_metadata.append({
                'dtype': str(arr.dtype),
                'shape': list(arr.shape)
            })
            arrays_binary.append(arr.tobytes())
        
        # Verify that number of arrays matches series_info length
        if len(arrays_metadata) != len(series_info):
            raise ValueError(
                f"Number of extracted arrays ({len(arrays_metadata)}) "
                f"does not match series_info length ({len(series_info)})"
            )
        
        # Always serialize as tuple (is_tuple=True)
        response_data = {
            'metadata': {
                'is_tuple': True,
                'arrays': arrays_metadata,
                'series_info': series_info,
                'paneTitle': indicator_desc.paneTitle
            },
            'binary_data': {
                'arrays': arrays_binary
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
        current_trades_size = len(broker.trades)
        new_trades = broker.trades[self._trades_start_index:current_trades_size]
        
        if not new_trades:
            return None
        
        deal_ids = set(trade.deal_id for trade in new_trades)
        
        trades_key = f"{result_key_prefix}:{result_id}:trades"
        trades_to_save = {}
        
        for trade in new_trades:
            time_iso = datetime64_to_iso(trade.time)
            side_str = trade.side.value
            
            member = f"{trade.trade_id}|{trade.deal_id}|{trade.order_id}|{time_iso}|{side_str}|{trade.price}|{trade.quantity}|{trade.fee}|{trade.sum}"
            
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
                    date_open_iso = datetime64_to_iso(deal.date_open) if deal.date_open is not None else ""
                    date_close_iso = datetime64_to_iso(deal.date_close) if deal.date_close is not None else ""
                    
                    member = (
                        f"{deal.deal_id}|"
                        f"{deal.type.value if deal.type else ''}|"
                        f"{self._format_value(deal.avg_buy_price)}|"
                        f"{self._format_value(deal.avg_sell_price)}|"
                        f"{deal.quantity}|"
                        f"{deal.fee}|"
                        f"{self._format_value(deal.profit)}|"
                        f"{self._format_value(deal.is_closed)}|"
                        f"{deal.close_type.value if deal.close_type else 0}|"
                        f"{date_open_iso}|"
                        f"{date_close_iso}"
                    )
                    
                    score = int(deal.deal_id)
                    deals_to_save[member] = score
        
        return (deals_key, deals_to_save)
    
    def _prepare_orders_data(self, broker, result_key_prefix: str, result_id: str):
        """
        Prepare orders data for saving to Redis.
        Filters orders by modify_time >= _last_orders_save_time.
        
        Args:
            broker: Broker instance (must be BrokerBacktesting with orders attribute)
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            
        Returns:
            tuple: (orders_hash_key, orders_index_key, orders_hash_data, orders_index_data)
                  Returns None if no orders to save
        """
        if not hasattr(broker, 'orders'):
            return None
        
        all_orders = broker.orders
        
        if self._last_orders_save_time is None:
            orders_to_save = all_orders
        else:
            orders_to_save = [
                order for order in all_orders
                if order.modify_time >= self._last_orders_save_time
            ]
        
        if not orders_to_save:
            return None
        
        orders_hash_key = f"{result_key_prefix}:{result_id}:orders"
        orders_index_key = f"{result_key_prefix}:{result_id}:orders_index"
        orders_hash_data = {}
        orders_index_data = {}
        
        for order in orders_to_save:
            order_id_str = str(order.order_id)
            create_time_iso = datetime64_to_iso(order.create_time)
            modify_time_iso = datetime64_to_iso(order.modify_time)
            side_str = order.side.value
            order_type_str = order.order_type.value
            trigger_price_str = self._format_value(order.trigger_price)
            
            order_group_value = order.order_group.value if order.order_group else 0
            fraction_str = self._format_value(order.fraction)
            exchange_order_id_str = self._format_value(order.exchange_order_id)
            
            member = (
                f"{order.order_id}|"
                f"{self._format_value(order.deal_id)}|"
                f"{create_time_iso}|"
                f"{modify_time_iso}|"
                f"{side_str}|"
                f"{order_type_str}|"
                f"{order.price}|"
                f"{order.volume}|"
                f"{order.filled_volume}|"
                f"{order.status.value}|"
                f"{trigger_price_str}|"
                f"{order_group_value}|"
                f"{fraction_str}|"
                f"{exchange_order_id_str}"
            )
            
            orders_hash_data[order_id_str] = member
            
            score = int(order.modify_time.astype('datetime64[ms]').astype(int))
            orders_index_data[order_id_str] = score
        
        return (orders_hash_key, orders_index_key, orders_hash_data, orders_index_data)
    
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
            broker.stats.calc_stat()
            
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
                'avg_profit_per_winning_deal': broker.stats.avg_profit_per_winning_deal,
                'avg_loss_per_losing_deal': broker.stats.avg_loss_per_losing_deal,
                'profit_long': broker.stats.profit_long,
                'profit_short': broker.stats.profit_short,
                'fee_taker': broker.stats.fee_taker,
                'fee_maker': broker.stats.fee_maker,
                'slippage': broker.stats.slippage,
                'price_step': broker.stats.price_step,
                'source': broker.stats.source,
                'symbol': broker.stats.symbol,
                'timeframe': broker.stats.timeframe,
                'date_start': broker.stats.date_start,
                'date_end': broker.stats.date_end,
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
        
        first_proxy = next(iter(self.ta_proxies.values()))
        if not hasattr(first_proxy, 'quotes_provider') or first_proxy.quotes_provider is None:
            return False
        
        time_array = first_proxy.quotes_provider.primary.time
        
        client_binary = self._get_redis_client_binary()
        time_key = f"{result_key_prefix}:{result_id}:time"
        
        if client_binary.exists(time_key.encode('utf-8')):
            return False
        
        time_bytes = self._serialize_array(time_array)
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
        
        client = self._get_redis_client_binary()
        indicators_key_prefix = f"{result_key_prefix}:{result_id}:indicators"
        
        current_cache_keys = set()
        for proxy_name, proxy in self.ta_proxies.items():
            if hasattr(proxy, 'cache') and proxy.cache:
                for cache_key in proxy.cache.keys():
                    composite_key = (proxy_name, cache_key)
                    current_cache_keys.add(composite_key)
        
        new_indicator_keys = current_cache_keys - self._sent_indicator_keys
        
        if not new_indicator_keys:
            return saved_indicator_keys
        
        indicators_pipeline = client.pipeline()
        
        for composite_key in new_indicator_keys:
            proxy_name, cache_key = composite_key
            proxy = self.ta_proxies[proxy_name]
            
            indicator_desc = proxy.cache[cache_key]
            
            if not indicator_desc.visible:
                continue
            
            serialized_cache_key = self._serialize_cache_key(cache_key)
            indicator_bytes = self._serialize_indicator_values(indicator_desc)
            indicator_redis_key = f"{indicators_key_prefix}:{proxy_name}:{serialized_cache_key}"
            
            indicators_pipeline.set(indicator_redis_key, indicator_bytes)
            saved_indicator_keys.add(composite_key)
        
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
            broker = self._broker_ref()
            if broker is None:
                raise RuntimeError("Broker reference is no longer valid")
            
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            result_id = broker.result_id
            
            trades_data = self._prepare_trades_data(broker, result_key_prefix, result_id)
            trades_key = None
            trades_to_save = {}
            new_trades = []
            deal_ids = set()
            current_trades_size = self._trades_start_index
            
            if trades_data is not None:
                trades_key, trades_to_save, new_trades, deal_ids, current_trades_size = trades_data
            
            deals_key, deals_to_save = self._prepare_deals_data(broker, result_key_prefix, result_id, deal_ids)
            
            orders_data = self._prepare_orders_data(broker, result_key_prefix, result_id)
            orders_hash_key = None
            orders_index_key = None
            orders_hash_data = {}
            orders_index_data = {}
            
            if orders_data is not None:
                orders_hash_key, orders_index_key, orders_hash_data, orders_index_data = orders_data
            
            stats_key, stats_json = self._prepare_stats_data(broker, result_key_prefix, result_id, is_finish)
            
            pipeline = client.pipeline()
            
            if trades_to_save:
                pipeline.zadd(trades_key, trades_to_save)
            
            if deals_to_save:
                pipeline.zadd(deals_key, deals_to_save)
            
            if orders_hash_data:
                pipeline.hset(orders_hash_key, mapping=orders_hash_data)
            if orders_index_data:
                pipeline.zadd(orders_index_key, orders_index_data)
            
            if stats_json:
                pipeline.set(stats_key, stats_json)
            
            pipeline.execute()
            
            if trades_data is not None:
                self._trades_start_index = current_trades_size
            
            if orders_data is not None and hasattr(broker, 'current_time') and broker.current_time is not None:
                self._last_orders_save_time = broker.current_time
            
            self._save_quotes_time(result_key_prefix, result_id)
            
            saved_indicator_keys = self._save_indicators(result_key_prefix, result_id)
            
            if saved_indicator_keys:
                self._sent_indicator_keys.update(saved_indicator_keys)
            
            if trades_to_save:
                logger.debug(f"Saved {len(new_trades)} new trades")
            if deals_to_save:
                logger.debug(f"Saved {len(deals_to_save)} deals to {deals_key}")
            if orders_hash_data:
                logger.debug(f"Saved {len(orders_hash_data)} orders to {orders_hash_key}")
            if stats_json:
                logger.debug(f"Saved statistics to {stats_key}")
            if saved_indicator_keys:
                logger.debug(f"Saved {len(saved_indicator_keys)} new indicators to Redis")
        except Exception as e:
            logger.error(f"Failed to save results: {str(e)}")
            raise RuntimeError(f"Failed to save results: {str(e)}") from e
    
    def _load_trades(self, client, result_key_prefix: str, result_id: str, time_begin_score: int) -> Tuple[List[Dict], set]:
        """
        Load trades from Redis with time >= time_begin.
        
        Args:
            client: Redis client
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            time_begin_score: Time begin as numeric score (milliseconds)
            
        Returns:
            Tuple of (trades list, set of deal_ids)
        """
        trades_key = f"{result_key_prefix}:{result_id}:trades"
        trades_data = client.zrangebyscore(trades_key, time_begin_score, '+inf', withscores=False)
        
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
            
        return trades, deal_ids
    
    def _load_deals(self, client, result_key_prefix: str, result_id: str, deal_ids: set) -> List[Dict]:
        """
        Load deals from Redis by deal_ids.
        
        Args:
            client: Redis client
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            deal_ids: Set of deal IDs to load
            
        Returns:
            List of deal dictionaries
        """
        deals = []
        if not deal_ids:
            return deals
        
        deals_key = f"{result_key_prefix}:{result_id}:deals"
        pipeline = client.pipeline()
        
        for deal_id in deal_ids:
            deal_id_int = int(deal_id)
            pipeline.zrangebyscore(deals_key, deal_id_int, deal_id_int, withscores=False)
        
        deals_data_list = pipeline.execute()
        
        for deals_data in deals_data_list:
            if deals_data:
                member = deals_data[0]
                parts = member.split('|')
                
                assert len(parts) == 11, f"Expected 11 parts in deal data, got {len(parts)}: {member[:100]}"
                
                deal_dict = {
                    'deal_id': parts[0],
                    'type': parts[1] if parts[1] else None,
                    'avg_buy_price': parts[2] if parts[2] else None,
                    'avg_sell_price': parts[3] if parts[3] else None,
                    'quantity': parts[4],
                    'fee': parts[5],
                    'profit': parts[6] if parts[6] else None,
                    'is_closed': parts[7] == '1' if parts[7] else False,
                    'close_type': int(parts[8]) if parts[8] else 0,
                    'date_open': parts[9] if parts[9] else None,
                    'date_close': parts[10] if parts[10] else None
                }
                deals.append(deal_dict)
            
        return deals
    
    def _load_orders(self, client, result_key_prefix: str, result_id: str, time_begin_score: int) -> List[Dict]:
        """
        Load orders from Redis with modify_time >= time_begin.
        
        Args:
            client: Redis client
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            time_begin_score: Time begin as numeric score (milliseconds)
            
        Returns:
            List of order dictionaries
        """
        orders = []
        orders_index_key = f"{result_key_prefix}:{result_id}:orders_index"
        orders_hash_key = f"{result_key_prefix}:{result_id}:orders"
        
        try:
            order_ids = client.zrangebyscore(orders_index_key, time_begin_score, '+inf', withscores=False)
            
            if order_ids:
                orders_data = client.hmget(orders_hash_key, order_ids)
                
                for order_member in orders_data:
                    if order_member:
                        parts = order_member.split('|')
                        
                        assert len(parts) == 14, f"Expected 14 parts in order data, got {len(parts)}: {order_member[:100]}"
                        
                        order_group = int(parts[11]) if parts[11] else 0
                        fraction = float(parts[12]) if parts[12] else None
                        exchange_order_id = parts[13] if parts[13] else None
                        
                        order_dict = {
                            'order_id': parts[0],
                            'deal_id': parts[1] if parts[1] else None,
                            'create_time': parts[2],
                            'modify_time': parts[3],
                            'side': parts[4],
                            'order_type': parts[5],
                            'price': parts[6],
                            'volume': parts[7],
                            'filled_volume': parts[8],
                            'status': int(parts[9]) if parts[9] else 0,
                            'trigger_price': parts[10] if parts[10] else None,
                            'order_group': order_group,
                            'fraction': fraction,
                            'exchange_order_id': exchange_order_id
                        }
                        orders.append(order_dict)
        except Exception as e:
            logger.warning(f"Failed to load orders from {orders_index_key}: {e}")
        
        return orders
    
    def _load_stats(self, client, result_key_prefix: str, result_id: str) -> Optional[Dict]:
        """
        Load statistics from Redis.
        
        Args:
            client: Redis client
            result_key_prefix: Redis key prefix for results
            result_id: Result ID
            
        Returns:
            Statistics dictionary or None
        """
        stats_key = f"{result_key_prefix}:{result_id}:stats"
        try:
            stats_data = client.get(stats_key)
            if stats_data:
                return json.loads(stats_data)
        except Exception as e:
            logger.warning(f"Failed to load statistics from {stats_key}: {e}")
            
        return None
    
    def get_results(
        self, 
        result_id: str,
        time_begin: Optional[np.datetime64] = None
    ) -> Dict:
        """
        Get results for the specified time interval.
        Returns all trades with time >= time_begin, corresponding deals, and orders with modify_time >= time_begin.
        
        Args:
            result_id: Result ID
            time_begin: Interval start (default: 1900-01-01)
            
        Returns:
            Dictionary with "trades", "deals", and "orders" lists
        """
        if time_begin is None:
            time_begin = np.datetime64('1900-01-01T00:00:00', 'ns')
        
        try:
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            
            time_begin_score = int(time_begin.astype('datetime64[ms]').astype(int))
            
            trades, deal_ids = self._load_trades(client, result_key_prefix, result_id, time_begin_score)
            deals = self._load_deals(client, result_key_prefix, result_id, deal_ids)
            orders = self._load_orders(client, result_key_prefix, result_id, time_begin_score)
            stats = self._load_stats(client, result_key_prefix, result_id)
            
            result = {
                'trades': trades,
                'deals': deals,
                'orders': orders
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
                names = [info.get('name', f'series{i}') for i, info in enumerate(series_info)] if series_info else [f'series{i}' for i in range(len(reconstructed_arrays))]
                while len(names) < len(reconstructed_arrays):
                    names.append(f'series{len(names)}')
                values = {name: arr.tolist() for name, arr in zip(names, reconstructed_arrays)}
        else:
            dtype = np.dtype(metadata['dtype'])
            shape = tuple(metadata['shape'])
            arr_bytes = binary_data.get('array')
            arr = np.frombuffer(arr_bytes, dtype=dtype).reshape(shape)
            values = arr.tolist()
        
        result_metadata = {
            'is_tuple': is_tuple,
            'series_info': series_info
        }
        
        # Preserve paneTitle from original metadata
        if 'paneTitle' in metadata:
            result_metadata['paneTitle'] = metadata['paneTitle']
        
        return {
            'metadata': result_metadata,
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
        start_idx = np.searchsorted(time_array, date_start, side='left')
        end_idx = np.searchsorted(time_array, date_end, side='right')
        
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
        
        indicator_keys = []
        redis_keys_to_fetch = []
        
        for redis_key in all_redis_keys:
            prefix_to_remove = f"{indicators_key_prefix}:"
            if not redis_key.startswith(prefix_to_remove):
                continue
            
            indicator_key = redis_key[len(prefix_to_remove):]
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
        parts = indicator_key.split(':', 1)
        assert len(parts) == 2, f"Invalid indicator key format: {indicator_key}"
        
        proxy_name = parts[0]
        serialized_cache_key = parts[1]
        
        cache_key_data = json.loads(serialized_cache_key)
        assert isinstance(cache_key_data, list), f"Invalid cache key format: {serialized_cache_key}"
        assert len(cache_key_data) == 4, f"Expected cache key with 4 elements, got {len(cache_key_data)}: {serialized_cache_key}"
        
        indicator_name = cache_key_data[0]
        actual_symbol = cache_key_data[1]
        timeframe_str = cache_key_data[2]
        parameters = cache_key_data[3]
        
        # Note: actual_symbol and timeframe_str are ignored as they are always primary
        # for visible indicators (cross-timeframe/cross-symbol indicators are not saved)
        
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
            if isinstance(val, np.integer):
                return int(val)
            elif isinstance(val, np.floating):
                val_float = float(val)
                if np.isnan(val_float):
                    return None
                return val_float
            elif isinstance(val, (int, float)):
                if isinstance(val, float) and (val != val):
                    return None
                return val
            else:
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
            filtered_values = {}
            for series_name, values_list in values.items():
                if len(values_list) > 0:
                    arr_start = min(start_idx, len(values_list))
                    arr_end = min(end_idx, len(values_list))
                    if arr_start < arr_end:
                        sliced = values_list[arr_start:arr_end+1]
                        filtered_values[series_name] = [convert_value(val) for val in sliced]
                    else:
                        filtered_values[series_name] = []
                else:
                    filtered_values[series_name] = []
            return filtered_values
        else:
            if len(values) > 0:
                arr_start = min(start_idx, len(values))
                arr_end = min(end_idx, len(values))
                if arr_start < arr_end:
                    sliced = values[arr_start:arr_end+1]
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
        date_end_iso: str,
        paneTitle: str
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
            paneTitle: Formatted pane title
            
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
            'date_end': date_end_iso,
            'paneTitle': paneTitle
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
            result_key_prefix = self.task.get_result_key()
            time_array = self._load_quotes_time(result_key_prefix, result_id)
            
            if time_array is None or len(time_array) == 0:
                logger.warning(f"No quotes time series found for result_id {result_id}")
                return {}
            
            start_idx, end_idx = self._get_indicator_slice_indices(time_array, date_start, date_end)
            start_idx = int(start_idx)
            end_idx = int(end_idx)
            
            if start_idx > end_idx:
                logger.info(f"Requested date range {date_start} - {date_end} is outside quotes time range. Returning empty indicators.")
                return {}
            
            indicator_keys, redis_keys_to_fetch = self._get_indicator_keys_from_redis(result_key_prefix, result_id)
            
            if not indicator_keys:
                return {}
            
            indicator_data_list = self._fetch_indicator_data_from_redis(redis_keys_to_fetch)
            
            date_start_iso = datetime64_to_iso(date_start)
            date_end_iso = datetime64_to_iso(date_end)
            
            time_range = time_array[start_idx:end_idx+1]
            time_range_iso = [str(datetime64_to_iso(t)) for t in time_range]
            
            result = {}
            indicators_processed = 0
            
            for indicator_key, indicator_bytes in zip(indicator_keys, indicator_data_list):
                if indicator_bytes is None:
                    logger.warning(f"Indicator key {indicator_key} not found in Redis")
                    continue
                
                try:
                    deserialized = self._deserialize_indicator_values(indicator_bytes)
                    
                    try:
                        proxy_name, indicator_name, parameters = self._parse_indicator_key(indicator_key)
                        parameters = self._convert_dict_numpy_types(parameters)
                    except (ValueError, json.JSONDecodeError) as e:
                        logger.warning(f"Failed to parse indicator key {indicator_key}: {e}")
                        continue
                    
                    is_tuple = bool(deserialized['metadata']['is_tuple'])
                    
                    filtered_values = self._filter_indicator_values_by_range(
                        deserialized['values'],
                        is_tuple,
                        start_idx,
                        end_idx
                    )
                    
                    series_info = self._convert_dict_numpy_types(deserialized['metadata']['series_info'])
                    pane_title = deserialized['metadata']['paneTitle']
                    
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
                        date_end_iso=date_end_iso,
                        paneTitle=pane_title
                    )
                    
                    entry = self._convert_dict_numpy_types(entry)
                    
                    result[indicator_key] = entry
                    indicators_processed += 1
                except Exception as e:
                    logger.error(f"Failed to deserialize indicator {indicator_key}: {e}", exc_info=True)
                    raise RuntimeError(f"Failed to deserialize indicator {indicator_key}: {str(e)}") from e
            
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
            
            indicator_keys, redis_keys_to_fetch = self._get_indicator_keys_from_redis(result_key_prefix, result_id)
            
            if not indicator_keys:
                return []
            
            indicator_data_list = self._fetch_indicator_data_from_redis(redis_keys_to_fetch)
            
            result = []
            
            for indicator_key, indicator_bytes in zip(indicator_keys, indicator_data_list):
                if indicator_bytes is None:
                    logger.warning(f"Indicator key {indicator_key} not found in Redis")
                    continue
                
                try:
                    response_data = msgpack.unpackb(indicator_bytes, raw=False)
                    metadata = response_data.get('metadata', {})
                    
                    try:
                        proxy_name, indicator_name, parameters = self._parse_indicator_key(indicator_key)
                        parameters = self._convert_dict_numpy_types(parameters)
                    except (ValueError, json.JSONDecodeError) as e:
                        logger.warning(f"Failed to parse indicator key {indicator_key}: {e}")
                        continue
                    
                    is_tuple = bool(metadata.get('is_tuple', False))
                    series_info = metadata.get('series_info', [])
                    series_info = self._convert_dict_numpy_types(series_info)
                    pane_title = metadata['paneTitle']
                    
                    entry = {
                        'key': indicator_key,
                        'proxy_name': proxy_name,
                        'indicator_name': indicator_name,
                        'parameters': parameters,
                        'is_tuple': is_tuple,
                        'series_info': series_info,
                        'paneTitle': pane_title
                    }
                    
                    entry = self._convert_dict_numpy_types(entry)
                    
                    result.append(entry)
                except Exception as e:
                    logger.error(f"Failed to extract metadata from indicator {indicator_key}: {e}", exc_info=True)
                    continue
            
            converted_result = self._convert_dict_numpy_types(result)
            
            return converted_result
            
        except Exception as e:
            logger.error(f"Failed to get indicator keys: {str(e)}")
            raise RuntimeError(f"Failed to get indicator keys: {str(e)}") from e

