"""
Class for writing and reading backtesting results to/from Redis.
Uses Sorted Set to store trades and deals.
"""
from typing import Optional, Dict
import weakref
import numpy as np
from app.services.tasks.tasks import Task
from app.services.tasks.broker import Broker, OrderSide
from app.core.logger import get_logger
from app.core.datetime_utils import datetime64_to_iso

logger = get_logger(__name__)


class BackTestingResults:
    """
    Class for writing and reading backtesting results to/from Redis.
    Uses Sorted Set (ZADD) to store trades and deals.
    """
    
    def __init__(self, task: Task):
        """
        Constructor.
        
        Args:
            task: Task instance (must have get_result_key() and get_redis_client() methods)
        """
        self.task = task
        self._redis_client = None
        self._broker_ref: Optional[weakref.ref] = None
        self._trades_start_index: int = 0
    
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
    
    def reset(self, broker: Broker) -> None:
        """
        Reset and initialize results storage.
        Stores weak reference to broker and remembers initial trades list size.
        
        Args:
            broker: Broker instance to track
            
        Raises:
            RuntimeError: If reset operation fails
        """
        try:
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
            logger.error(f"Failed to reset backtesting results: {str(e)}")
            raise RuntimeError(f"Failed to reset backtesting results: {str(e)}") from e
    
    def put_result(self) -> None:
        """
        Save new trades and deals to Redis.
        Checks trades list size, saves new trades, collects deal_id, saves deals.
        
        Raises:
            RuntimeError: If save operation fails
        """
        try:
            # Get broker from weak reference
            broker = self._broker_ref() if self._broker_ref else None
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
                
                # Format member: trade_id:deal_id:order_id:time_iso:side:price:quantity:fee:sum
                member = f"{trade.trade_id}:{trade.deal_id}:{trade.order_id}:{time_iso}:{side_str}:{trade.price}:{trade.quantity}:{trade.fee}:{trade.sum}"
                
                # Use trade_id as score
                score = trade.trade_id
                trades_to_save[member] = score
            
            # Save all trades to single key
            if trades_to_save:
                client.zadd(trades_key, trades_to_save)
            
            # Update trades start index
            self._trades_start_index = current_trades_size
            
            # Save deals for collected deal_id
            if deal_ids:
                deals_key = f"{result_key_prefix}:{result_id}:deals"
                deals_to_save = {}
                
                for deal in broker.deals:
                    if deal.deal_id in deal_ids:
                        # Format member: deal_id:avg_buy_price:avg_sell_price:quantity:fee:profit:is_closed
                        member = (
                            f"{deal.deal_id}:"
                            f"{self._format_value(deal.avg_buy_price)}:"
                            f"{self._format_value(deal.avg_sell_price)}:"
                            f"{deal.quantity}:"
                            f"{deal.fee}:"
                            f"{self._format_value(deal.profit)}:"
                            f"{self._format_value(deal.is_closed)}"
                        )
                        
                        # Use deal_id as score
                        score = deal.deal_id
                        deals_to_save[member] = score
                
                if deals_to_save:
                    client.zadd(deals_key, deals_to_save)
                    logger.debug(f"Saved {len(deals_to_save)} deals to {deals_key}")
            
            logger.debug(f"Saved {len(new_trades)} new trades")
        except Exception as e:
            logger.error(f"Failed to save results: {str(e)}")
            raise RuntimeError(f"Failed to save results: {str(e)}") from e
    
    def get_results(
        self, 
        result_id: str,
        time_begin: Optional[np.datetime64] = None, 
        time_end: Optional[np.datetime64] = None
    ) -> Dict:
        """
        Get results for the specified time interval.
        Currently a stub - returns empty dictionary.
        
        Args:
            result_id: Result ID
            time_begin: Interval start (optional)
            time_end: Interval end (optional)
            
        Returns:
            Dictionary with results (currently empty)
        """
        # Stub
        return {}

