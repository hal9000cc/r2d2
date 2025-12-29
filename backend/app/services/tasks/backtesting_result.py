"""
Class for writing and reading backtesting results to/from Redis.
Uses Sorted Set to store trades and deals.
"""
from typing import Optional, Dict
import json
import weakref
import numpy as np
from app.services.tasks.tasks import Task
from app.services.tasks.broker import Broker, OrderSide, DealType
from app.core.logger import get_logger
from app.core.datetime_utils import datetime64_to_iso

logger = get_logger(__name__)


class BackTestingResults:
    """
    Class for writing and reading backtesting results to/from Redis.
    Uses Sorted Set (ZADD) to store trades and deals.
    """
    
    def __init__(self, task: Task, broker: Optional[Broker] = None):
        """
        Constructor.
        
        Args:
            task: Task instance (must have get_result_key() and get_redis_client() methods)
            broker: Optional Broker instance to track. If provided, initializes for writing results.
                   If None, instance is used only for reading results.
            
        Raises:
            RuntimeError: If initialization fails
        """
        self.task = task
        self._redis_client = None
        self._broker_ref: Optional[weakref.ReferenceType[Broker]] = None
        self._trades_start_index: int = 0
        
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
            
            # Get new trades (from remembered index to current size)
            current_trades_size = len(broker.trades)
            new_trades = broker.trades[self._trades_start_index:current_trades_size]
            
            if not new_trades:
                return
            
            # Collect unique deal_id from new trades
            deal_ids = set(trade.deal_id for trade in new_trades)
            
            # Save new trades to Redis (all trades in one key)
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
            
            # Prepare deals data
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
            
            # Prepare statistics data
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
            
            # Execute all operations in one batch
            pipeline.execute()
            
            # Update trades start index only after successful save
            self._trades_start_index = current_trades_size
            
            # Log operations
            if trades_to_save:
                logger.debug(f"Saved {len(new_trades)} new trades")
            if deals_to_save:
                logger.debug(f"Saved {len(deals_to_save)} deals to {deals_key}")
            if stats_json:
                logger.debug(f"Saved statistics to {stats_key}")
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

