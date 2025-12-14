"""
Task management with Redis storage.
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Type, TYPE_CHECKING
from pydantic import Field
from app.core.objects2redis import Objects2Redis, Objects2RedisList
from app.core.logger import get_logger

if TYPE_CHECKING:
    import redis

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
    dateStart: str = Field(
        default_factory=lambda: (datetime.now() + timedelta(days=-30)).isoformat()
    )
    dateEnd: str = Field(
        default_factory=lambda: (datetime.now() + timedelta(days=-1)).isoformat()
    )
    parameters: Dict[str, Any] = Field(default_factory=dict)
    
    def get_key(self) -> str:
        """
        Returns secondary key for the task (file_name - relative path).
        Used for indexing and searching tasks by strategy file.
        """
        return self.file_name if self.file_name else ""
    
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
