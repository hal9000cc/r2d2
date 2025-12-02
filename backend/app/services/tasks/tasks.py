"""
Task management with Redis storage.
"""
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import redis
from app.core.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
from app.core.logger import get_logger

logger = get_logger(__name__)


class Task:
    """
    Task class representing an active strategy task.
    """
    
    def __init__(
        self,
        active_strategy_id: int,
        strategy_id: str = "",
        name: str = "",
        source: str = "",
        symbol: str = "",
        timeframe: str = "",
        isRunning: bool = False,
        isTrading: bool = False,
        dateStart: Optional[str] = None,
        dateEnd: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None
    ):
        self.active_strategy_id = active_strategy_id
        self.strategy_id = strategy_id
        self.name = name
        self.source = source
        self.symbol = symbol
        self.timeframe = timeframe
        self.isRunning = isRunning
        self.isTrading = isTrading
        self.dateStart = dateStart or (datetime.now() + timedelta(days=-30)).isoformat()
        self.dateEnd = dateEnd or (datetime.now() + timedelta(days=-1)).isoformat()
        self.parameters = parameters or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert task to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the task
        """
        return {
            "active_strategy_id": self.active_strategy_id,
            "strategy_id": self.strategy_id,
            "name": self.name,
            "source": self.source,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "isRunning": self.isRunning,
            "isTrading": self.isTrading,
            "dateStart": self.dateStart,
            "dateEnd": self.dateEnd,
            "parameters": self.parameters
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """
        Create Task instance from dictionary.
        
        Args:
            data: Dictionary with task data
            
        Returns:
            Task instance
        """
        return cls(
            active_strategy_id=data.get("active_strategy_id", 0),
            strategy_id=data.get("strategy_id", ""),
            name=data.get("name", ""),
            source=data.get("source", ""),
            symbol=data.get("symbol", ""),
            timeframe=data.get("timeframe", ""),
            isRunning=data.get("isRunning", False),
            isTrading=data.get("isTrading", False),
            dateStart=data.get("dateStart"),
            dateEnd=data.get("dateEnd"),
            parameters=data.get("parameters", {})
        )


class TaskList:
    """
    Singleton class for managing tasks in Redis.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(TaskList, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, redis_host: str = None, redis_port: int = None, redis_db: int = None, redis_password: str = None):
        if not TaskList._initialized:
            self.redis_host = redis_host or REDIS_HOST
            self.redis_port = redis_port or REDIS_PORT
            self.redis_db = redis_db or REDIS_DB
            self.redis_password = redis_password or REDIS_PASSWORD
            
            # Redis key prefixes
            self.task_key_prefix = "tasks:"
            self.next_id_key = "tasks:next_id"
            
            TaskList._initialized = True
    
    def _get_redis_client(self) -> redis.Redis:
        """
        Get Redis client connection.
        
        Returns:
            Redis client instance
        """
        return redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            db=self.redis_db,
            password=self.redis_password,
            decode_responses=True  # Decode responses to strings for JSON
        )
    
    def _get_task_key(self, task_id: int) -> str:
        """Get Redis key for a task."""
        return f"{self.task_key_prefix}{task_id}"
    
    def startup(self):
        """
        Initialize TaskList.
        Creates Redis connection (counter will be created automatically on first INCR).
        """
        try:
            # Test Redis connection
            client = self._get_redis_client()
            client.ping()
            logger.info("TaskList initialized with Redis connection")
        except Exception as e:
            logger.critical(f"Failed to initialize TaskList: {str(e)}")
            raise RuntimeError(f"Failed to initialize TaskList: {str(e)}") from e
    
    def shutdown(self):
        """
        Shutdown TaskList.
        Redis connection will be closed automatically when client goes out of scope.
        """
        logger.info("TaskList shutdown")
    
    def get_tasks(self) -> List[Task]:
        """
        Get list of all tasks from Redis.
        
        Returns:
            List of Task objects
        """
        client = self._get_redis_client()
        tasks = []
        
        try:
            # Get all task keys
            pattern = f"{self.task_key_prefix}*"
            # Exclude next_id key
            keys = [key for key in client.keys(pattern) if key != self.next_id_key]
            
            # Load all tasks
            for key in keys:
                task_json = client.get(key)
                if task_json:
                    try:
                        task_data = json.loads(task_json)
                        task = Task.from_dict(task_data)
                        tasks.append(task)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode task from key {key}")
                        continue
            
            return tasks
        except Exception as e:
            logger.error(f"Failed to get tasks: {str(e)}")
            raise RuntimeError(f"Failed to get tasks: {str(e)}") from e
    
    def get_task(self, task_id: int) -> Optional[Task]:
        """
        Get single task by ID from Redis.
        
        Args:
            task_id: Task ID
            
        Returns:
            Task object or None if not found
        """
        client = self._get_redis_client()
        key = self._get_task_key(task_id)
        
        try:
            task_json = client.get(key)
            if task_json:
                task_data = json.loads(task_json)
                return Task.from_dict(task_data)
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode task {task_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {str(e)}")
            raise RuntimeError(f"Failed to get task {task_id}: {str(e)}") from e
    
    def put_task(self, task: Task) -> Task:
        """
        Add or update task in Redis.
        
        Args:
            task: Task object
            
        Returns:
            Updated Task object
        """
        client = self._get_redis_client()
        task_id = task.active_strategy_id
        key = self._get_task_key(task_id)
        
        try:
            # Generate name if not set
            if not task.name:
                task.name = f'{task.strategy_id} ({task.source}:{task.symbol} {task.timeframe})'
            
            # Convert to dict and serialize to JSON
            task_dict = task.to_dict()
            task_json = json.dumps(task_dict, ensure_ascii=False)
            
            # Store in Redis
            client.set(key, task_json)
            
            return task
        except Exception as e:
            logger.error(f"Failed to put task {task_id}: {str(e)}")
            raise RuntimeError(f"Failed to put task {task_id}: {str(e)}") from e
    
    def delete_task(self, task_id: int) -> None:
        """
        Delete task from Redis.
        
        Args:
            task_id: Task ID
            
        Raises:
            KeyError: If task not found
        """
        client = self._get_redis_client()
        key = self._get_task_key(task_id)
        
        try:
            # Check if task exists
            if not client.exists(key):
                raise KeyError(f"Task with ID {task_id} not found")
            
            # Delete from Redis
            client.delete(key)
        except KeyError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {str(e)}")
            raise RuntimeError(f"Failed to delete task {task_id}: {str(e)}") from e
    
    def new_task_id(self) -> int:
        """
        Get new unique task ID using Redis INCR.
        
        Returns:
            New unique task ID
        """
        client = self._get_redis_client()
        
        try:
            # INCR creates key with value 1 if it doesn't exist
            new_id = client.incr(self.next_id_key)
            return new_id
        except Exception as e:
            logger.error(f"Failed to get new task ID: {str(e)}")
            raise RuntimeError(f"Failed to get new task ID: {str(e)}") from e
    
    def new_task(self) -> Task:
        """
        Create a new empty task with a new ID.
        
        Returns:
            New Task object
        """
        task_id = self.new_task_id()
        return Task(
            active_strategy_id=task_id,
            strategy_id="",
            name="",
            source="",
            symbol="",
            timeframe="",
            isRunning=False,
            isTrading=False,
            dateStart=(datetime.now() + timedelta(days=-30)).isoformat(),
            dateEnd=(datetime.now() + timedelta(days=-1)).isoformat(),
            parameters={}
        )
