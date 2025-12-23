"""
Class for writing and reading backtesting results to/from Redis.
Uses Sorted Set to store buy and sell operations.
"""
from typing import Optional, Dict
import numpy as np
from app.services.tasks.tasks import Task
from app.core.logger import get_logger

logger = get_logger(__name__)


class BackTestingResults:
    """
    Class for writing and reading backtesting results to/from Redis.
    Uses Sorted Set (ZADD) to store buy and sell operations.
    """
    
    def __init__(self, task: Task):
        """
        Constructor.
        
        Args:
            task: Task instance (must have get_result_key() and get_redis_client() methods)
        """
        self.task = task
        self._redis_client = None
    
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
    
    def _datetime64_to_timestamp(self, dt64: np.datetime64) -> int:
        """
        Convert np.datetime64 to Unix timestamp (seconds).
        
        Args:
            dt64: numpy datetime64 object
            
        Returns:
            int: Unix timestamp in seconds
        """
        # Convert to seconds and then to int
        return int(dt64.astype('datetime64[s]').astype(int))
    
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
    
    def reset(self) -> None:
        """
        Remove all results for the task.
        Deletes all keys matching pattern {task.get_result_key()}:*
        
        Raises:
            RuntimeError: If reset operation fails
        """
        try:
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            pattern = f"{result_key_prefix}:*"
            
            # Find all keys matching pattern
            keys = client.keys(pattern)
            
            if keys:
                # Delete all found keys
                deleted = client.delete(*keys)
                logger.debug(f"Reset backtesting results: deleted {deleted} keys matching pattern {pattern}")
            else:
                logger.debug(f"Reset backtesting results: no keys found matching pattern {pattern}")
        except Exception as e:
            logger.error(f"Failed to reset backtesting results: {str(e)}")
            raise RuntimeError(f"Failed to reset backtesting results: {str(e)}") from e
    
    def append_buy(
        self, 
        result_id: str,
        time: np.datetime64, 
        price: float, 
        volume: float, 
        fee: float, 
        deal_id: str
    ) -> None:
        """
        Append buy operation to Redis Sorted Set.
        
        Args:
            result_id: Result ID (usually task.result_id)
            time: Operation time (np.datetime64)
            price: Buy price
            volume: Buy volume
            fee: Fee
            deal_id: Deal ID (for linking operations)
            
        Raises:
            RuntimeError: If append operation fails
        """
        try:
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            key = f"{result_key_prefix}:{result_id}:buy"
            
            # Convert time to timestamp for score
            score = self._datetime64_to_timestamp(time)
            
            # Format member: time_iso:price:volume:fee:deal_id
            time_iso = self._datetime64_to_iso(time)
            member = f"{time_iso}:{price}:{volume}:{fee}:{deal_id}"
            
            # Add to Sorted Set
            client.zadd(key, {member: score})
            
            logger.debug(f"Appended buy operation to {key}: time={time_iso}, price={price}, volume={volume}, fee={fee}, deal_id={deal_id}")
        except Exception as e:
            logger.error(f"Failed to append buy operation: {str(e)}")
            raise RuntimeError(f"Failed to append buy operation: {str(e)}") from e
    
    def append_sell(
        self, 
        result_id: str,
        time: np.datetime64, 
        price: float, 
        volume: float, 
        fee: float, 
        deal_id: str
    ) -> None:
        """
        Append sell operation to Redis Sorted Set.
        
        Args:
            result_id: Result ID (usually task.result_id)
            time: Operation time (np.datetime64)
            price: Sell price
            volume: Sell volume
            fee: Fee
            deal_id: Deal ID (for linking operations)
            
        Raises:
            RuntimeError: If append operation fails
        """
        try:
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            key = f"{result_key_prefix}:{result_id}:sell"
            
            # Convert time to timestamp for score
            score = self._datetime64_to_timestamp(time)
            
            # Format member: time_iso:price:volume:fee:deal_id
            time_iso = self._datetime64_to_iso(time)
            member = f"{time_iso}:{price}:{volume}:{fee}:{deal_id}"
            
            # Add to Sorted Set
            client.zadd(key, {member: score})
            
            logger.debug(f"Appended sell operation to {key}: time={time_iso}, price={price}, volume={volume}, fee={fee}, deal_id={deal_id}")
        except Exception as e:
            logger.error(f"Failed to append sell operation: {str(e)}")
            raise RuntimeError(f"Failed to append sell operation: {str(e)}") from e
    
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

