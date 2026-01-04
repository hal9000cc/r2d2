"""
Task management with Redis storage.
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Type
from pydantic import Field
from app.core.objects2redis import Objects2Redis, Objects2RedisList, MessageType
from app.core.logger import get_logger

logger = get_logger(__name__)


class Task(Objects2Redis):
    """
    Task class representing a strategy task.
    Inherits from Objects2Redis for Redis storage with Pydantic validation.
    """
    
    file_name: str = ""  # Relative path to strategy file (from STRATEGIES_DIR, with .py extension)
    name: str = ""  # Strategy name (can be arbitrary, not necessarily related to file path)
    source: str = ""
    symbol: str = ""
    timeframe: str = ""
    isRunning: bool = False
    result_id: str = ""  # Unique ID for this backtesting run (GUID), used to detect duplicate workers
    dateStart: str = Field(
        default_factory=lambda: (datetime.now() + timedelta(days=-30)).isoformat()
    )
    dateEnd: str = Field(
        default_factory=lambda: (datetime.now() + timedelta(days=-1)).isoformat()
    )
    fee_taker: float = 0.0  # Taker fee rate (as fraction, e.g., 0.001 for 0.1%)
    fee_maker: float = 0.0  # Maker fee rate (as fraction, e.g., 0.001 for 0.1%)
    price_step: float = 0.0  # Minimum price step for the symbol (e.g., 0.1, 0.001)
    slippage_in_steps: float = 1.0  # Slippage in price steps (e.g., 1.0 means 1 step)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    
    def get_key(self) -> str:
        """
        Returns secondary key for the task (file_name - relative path).
        Used for indexing and searching tasks by strategy file.
        """
        return self.file_name if self.file_name else ""
    
    def load(self) -> Optional['Task']:
        """
        Reload task from Redis to get current state.
        Proxies to the associated list's load method.
        
        Returns:
            Task instance with current state from Redis, or None if not found
            
        Raises:
            RuntimeError: If task is not associated with a list
        """
        if self._list is None:
            raise RuntimeError("Task is not associated with a list. Cannot load from Redis.")
            
        return self._list.load(self.id)
    
    def get_redis_client(self):
        """
        Get Redis client from the associated list.
        
        Returns:
            redis.Redis: Redis client instance
            
        Raises:
            RuntimeError: If task is not associated with a list
        """
        if self._list is None:
            raise RuntimeError("Task is not associated with a list. Cannot get Redis client.")
        return self._list._get_redis_client()

    def get_redis_params(self) -> Optional[dict]:
        """
        Get Redis connection parameters from the associated list.
        
        Returns:
            dict | None: Redis connection parameters (host, port, db, password) or None
                         if the task is not associated with a list.
        """
        # For standalone tasks (e.g., unit tests) we allow missing list and simply
        # disable Redis-based features by returning None.
        if self._list is None:
            return None
        if not hasattr(self._list, "get_redis_params"):
            return None
        return self._list.get_redis_params()

    def get_result_key(self) -> str:
        """
        Get Redis key for backtesting results associated with this task.
        Delegates to the associated task list.
        """
        if self._list is None:
            raise RuntimeError("Task is not associated with a list. Cannot get result key.")
        if not hasattr(self._list, "get_result_key"):
            raise RuntimeError("Associated task list does not support result keys.")
        return self._list.get_result_key(self.id)

    def clear_result(self) -> None:
        """
        Clear backtesting results associated with this task in Redis.
        Delegates to the associated task list.
        """
        if self._list is None:
            raise RuntimeError("Task is not associated with a list. Cannot clear result.")
        if not hasattr(self._list, "clear_result"):
            raise RuntimeError("Associated task list does not support clearing results.")
            
        self._list.clear_result(self.id)
    
    def send_message(self, type: MessageType, data: Dict) -> None:
        """
        Send message to Redis pub/sub channel for this task.
        
        Args:
            type: Message type (MessageType.MESSAGE or MessageType.EVENT)
            data: Dictionary with message data. Structure depends on type:
                - For MessageType.MESSAGE: must contain 'level' (str) and 'message' (str)
                - For MessageType.EVENT: must contain 'event' (str)
            
        Raises:
            ValueError: If data structure is invalid for the given type
            RuntimeError: If task is not associated with a list or publish fails
        """
        if self._list is None:
            raise RuntimeError("Task is not associated with a list. Cannot send message.")
        self._list.send_message(self.id, type, data)
    
    def message(self, message: str, level: str = "info") -> None:
        """
        Send message to user via Redis pub/sub channel.
        Convenience method that wraps send_message for user messages.
        
        Args:
            message: Message text to display to user
            level: Message level (optional, default: "info")
                  Valid levels: info, warning, error, success, debug
            
        Raises:
            RuntimeError: If task is not associated with a list or publish fails
        """
        self.send_message(MessageType.MESSAGE, {"level": level, "message": message})
    
    def backtesting_error(self, message: str) -> None:
        """
        Send backtesting error notification. Sends two messages:
        1. Event message with event='backtesting_error' for frontend to react (disable start button, etc.)
        2. Message with error level to display to user.
        
        Args:
            message: Error message text to display to user
            
        Raises:
            RuntimeError: If task is not associated with a list or publish fails
        """
        if self._list is None:
            raise RuntimeError("Task is not associated with a list. Cannot send message.")
        # Send event notification
        self._list.send_message(self.id, MessageType.EVENT, {"event": "backtesting_error"})
        # Send error message to user
        self._list.send_message(self.id, MessageType.MESSAGE, {"level": "error", "message": message})


class TaskList(Objects2RedisList[Task]):
    """
    Singleton class for managing tasks in Redis.
    Inherits from Objects2RedisList.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(TaskList, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, redis_params: Optional[dict] = None):
        if not TaskList._initialized:
            if redis_params is None:
                raise ValueError("TaskList must be initialized with redis_params on first call")
            super().__init__(redis_params)
            TaskList._initialized = True
    
    def list_key(self) -> str:
        """Returns the prefix for task keys in Redis"""
        return "tasks"
    
    def object_class(self) -> Type[Task]:
        """Returns the Task class"""
        return Task


class BacktestingTaskList(Objects2RedisList[Task]):
    """
    Singleton class for managing backtesting tasks in Redis.
    Inherits from Objects2RedisList.
    Uses the same Task class but with different Redis key prefix.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(BacktestingTaskList, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, redis_params: Optional[dict] = None):
        # If already initialized, just return (allow multiple calls without params)
        if BacktestingTaskList._initialized:
            return
            
        # First initialization requires redis_params
        if redis_params is not None:
            super().__init__(redis_params)
            BacktestingTaskList._initialized = True
    
    def list_key(self) -> str:
        """Returns the prefix for backtesting task keys in Redis"""
        return "backtesting_tasks"
    
    def object_class(self) -> Type[Task]:
        """Returns the Task class"""
        return Task

    # --- Backtesting results helpers ---

    def get_result_key(self, task_id: int) -> str:
        """
        Get Redis key for backtesting results stream for a given task.
        """
        return f"{self.list_key()}:result:{task_id}"

    def clear_result(self, task_id: int) -> None:
        """
        Clear Redis stream with backtesting results for the given task.

        Raises:
            RuntimeError: On any Redis error during deletion.
        """
        key = self.get_result_key(task_id)
        redis_client = self._get_redis_client()
        try:
            deleted = redis_client.delete(key)
            logger.debug(f"Cleared backtesting result stream at key {key}, deleted={deleted}")
        except Exception as e:
            msg = f"Failed to clear backtesting result stream for task {task_id} at key {key}: {e}"
            logger.error(msg)
            raise RuntimeError(msg)
