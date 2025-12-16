"""
Abstract classes for objects stored in Redis with Pydantic models.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, TypeVar, Generic, Type, TYPE_CHECKING
from datetime import datetime, timezone
import redis
import json
from pydantic import BaseModel, PrivateAttr
from app.core.logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    pass

T = TypeVar('T', bound='Objects2Redis')


class Objects2Redis(BaseModel, ABC):
    """
    Abstract base class for objects stored in Redis.
    Inherits from Pydantic BaseModel for validation and serialization.
    """
    
    id: int  # Unique primary key
    _list: 'Objects2RedisList' = PrivateAttr(default=None)  # Reference to list
    
    model_config = {
        'arbitrary_types_allowed': True
    }
    
    @abstractmethod
    def get_key(self) -> str:
        """
        Returns secondary key for the object (used for searching).
        
        Example:
            - "AAPL:1D"
            - "strategy_ma_cross"
            - "binance:BTCUSDT"
            
        Returns:
            str: Secondary key for the object
        """
        pass
    
    def save(self) -> 'Objects2Redis':
        """
        Saves the object through the list.
        
        Returns:
            Self for method chaining
        """
        return self._list.save(self)


class Objects2RedisList(ABC, Generic[T]):
    """
    Abstract base class for managing a list of objects in Redis.
    """
    
    def __init__(self, redis_params: Optional[Dict] = None):
        """
        Initialize the list with Redis connection parameters.
        
        Args:
            redis_params: Dictionary with Redis connection parameters
                - host: str (default: 'localhost')
                - port: int (default: 6379)
                - db: int (default: 0)
                - password: Optional[str] (default: None)
        """
        if redis_params is not None:
            self.redis_host = redis_params.get('host', 'localhost')
            self.redis_port = redis_params.get('port', 6379)
            self.redis_db = redis_params.get('db', 0)
            self.redis_password = redis_params.get('password', None)
            
            # Key for next_id counter
            self.next_id_key = f"{self.list_key()}:next_id"
            self._is_initialized = True
        else:
            self._is_initialized = False
    
    def get_redis_params(self) -> Dict:
        """
        Returns Redis connection parameters used by this list.
        """
        self._check_initialized()
        return {
            "host": self.redis_host,
            "port": self.redis_port,
            "db": self.redis_db,
            "password": self.redis_password,
        }
    
    def _check_initialized(self):
        """Check if the list is initialized, raise error if not"""
        if not getattr(self, '_is_initialized', False):
            raise RuntimeError(
                f"{self.__class__.__name__} not initialized. "
                f"Must be initialized with redis_params first (usually in startup.py)."
            )
    
    @abstractmethod
    def list_key(self) -> str:
        """
        Returns the prefix for keys in Redis.
        
        Example:
            - "tasks"
            - "strategies"
            - "orders"
            
        Returns:
            str: Prefix for Redis keys (without trailing colon)
        """
        pass
    
    @abstractmethod
    def object_class(self) -> Type[T]:
        """
        Returns the class of objects managed by this list.
        
        Example:
            return Strategy
            return Task
            
        Returns:
            Type[T]: Class of the object
        """
        pass
    
    def _get_redis_client(self) -> redis.Redis:
        """
        Get Redis client connection.
        
        Returns:
            redis.Redis: Redis client instance
        """
        return redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            db=self.redis_db,
            password=self.redis_password,
            decode_responses=True
        )
    
    def _get_object_key(self, obj_id: int) -> str:
        """
        Forms full Redis key for an object.
        
        Args:
            obj_id: Object ID
            
        Returns:
            str: Full Redis key like "tasks:obj:1" or "strategies:obj:42"
        """
        return f"{self.list_key()}:obj:{obj_id}"
    
    def _get_index_key(self, key: str) -> str:
        """
        Forms Redis key for reverse index (key -> id).
        
        Args:
            key: Secondary key from object.get_key()
            
        Returns:
            str: Index key like "tasks:index:AAPL:1D"
        """
        return f"{self.list_key()}:index:{key}"
    
    def save(self, obj: T) -> T:
        """
        Saves object to Redis with reverse index by key.
        Key must be unique - raises ValueError if duplicate key exists.
        
        Key: {list_key}:{obj.id}
        Value: JSON via obj.model_dump()
        Index: {list_key}:index:{obj.get_key()} -> obj.id
        
        Args:
            obj: Object to save
            
        Returns:
            The saved object
            
        Raises:
            ValueError: If key is not unique
            RuntimeError: If save operation fails
        """
        self._check_initialized()
        client = self._get_redis_client()
        obj_key = self._get_object_key(obj.id)
        
        try:
            # Get current key value
            new_key = obj.get_key()
            
            # Load old object to check if key changed
            old_obj = self.load(obj.id)
            old_key = old_obj.get_key() if old_obj else None
            
            # Check key uniqueness if key is set and changed
            if new_key:
                if old_key != new_key:
                    # Key changed or new object - check uniqueness
                    index_key = self._get_index_key(new_key)
                    existing_id_str = client.get(index_key)
                    
                    if existing_id_str:
                        existing_id = int(existing_id_str)
                        # Check if it's not the same object
                        if existing_id != obj.id:
                            raise ValueError(
                                f"Key '{new_key}' already exists for object with id {existing_id}"
                            )
                
                # Delete old index if key changed
                if old_key and old_key != new_key:
                    old_index_key = self._get_index_key(old_key)
                    client.delete(old_index_key)
                    logger.debug(f"Deleted old index for key '{old_key}'")
            
            # Serialize and save object
            obj_dict = obj.model_dump()
            obj_json = json.dumps(obj_dict, ensure_ascii=False)
            client.set(obj_key, obj_json)
            
            # Create/update index if key is set
            if new_key:
                index_key = self._get_index_key(new_key)
                client.set(index_key, str(obj.id))
                logger.debug(f"Created index for key '{new_key}' -> id {obj.id}")
            
            logger.debug(f"Saved object with id {obj.id} to key {obj_key}")
            return obj
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to save object {obj.id}: {str(e)}")
            raise RuntimeError(f"Failed to save object {obj.id}: {str(e)}") from e
    
    def load(self, obj_id: int) -> Optional[T]:
        """
        Loads object by id from Redis.
        
        Args:
            obj_id: Object ID
            
        Returns:
            Object instance or None if not found
            
        Raises:
            RuntimeError: If load operation fails
        """
        self._check_initialized()
        client = self._get_redis_client()
        key = self._get_object_key(obj_id)
        
        try:
            obj_json = client.get(key)
            if not obj_json:
                return None
            
            # Deserialize via pydantic
            obj_dict = json.loads(obj_json)
            obj = self.object_class().model_validate(obj_dict)
            obj._list = self  # Set reference to list
            logger.debug(f"Loaded object with id {obj_id} from key {key}")
            return obj
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode object {obj_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Failed to load object {obj_id}: {str(e)}")
            raise RuntimeError(f"Failed to load object {obj_id}: {str(e)}") from e
    
    def load_by_key(self, key: str) -> Optional[T]:
        """
        Loads object by secondary key from Redis.
        Uses reverse index to find object id.
        
        Args:
            key: Secondary key from object.get_key()
            
        Returns:
            Object instance or None if not found
            
        Raises:
            RuntimeError: If load operation fails
        """
        self._check_initialized()
        client = self._get_redis_client()
        index_key = self._get_index_key(key)
        
        try:
            # Get id from reverse index
            obj_id_str = client.get(index_key)
            if not obj_id_str:
                logger.debug(f"No object found for key '{key}'")
                return None
            
            # Load object by id
            obj_id = int(obj_id_str)
            logger.debug(f"Found object id {obj_id} for key '{key}'")
            return self.load(obj_id)
        except Exception as e:
            logger.error(f"Failed to load object by key '{key}': {str(e)}")
            raise RuntimeError(f"Failed to load object by key '{key}': {str(e)}") from e
    
    def new(self) -> T:
        """
        Creates new object with unique id.
        The key is unknown yet, will be created on first save().
        
        Returns:
            New object instance
            
        Raises:
            RuntimeError: If creation fails
        """
        self._check_initialized()
        client = self._get_redis_client()
        
        try:
            new_id = client.incr(self.next_id_key)
            
            # Create new object with unique id
            obj = self.object_class()(id=new_id)
            obj._list = self  # Set reference to list
            logger.debug(f"Created new object with id {new_id}")
            return obj
        except Exception as e:
            logger.error(f"Failed to create new object: {str(e)}")
            raise RuntimeError(f"Failed to create new object: {str(e)}") from e
    
    def list(self) -> List[T]:
        """
        Returns list of all objects.
        
        Returns:
            List of object instances
            
        Raises:
            RuntimeError: If list operation fails
        """
        self._check_initialized()
        client = self._get_redis_client()
        pattern = f"{self.list_key()}:obj:*"
        
        try:
            # Get all object keys
            keys = client.keys(pattern)
            
            objects = []
            for key in keys:
                obj_json = client.get(key)
                if obj_json:
                    try:
                        obj_dict = json.loads(obj_json)
                        obj = self.object_class().model_validate(obj_dict)
                        obj._list = self
                        objects.append(obj)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode object from key {key}")
                        continue
            
            logger.debug(f"Listed {len(objects)} objects")
            return objects
        except Exception as e:
            logger.error(f"Failed to list objects: {str(e)}")
            raise RuntimeError(f"Failed to list objects: {str(e)}") from e
    
    def delete(self, obj_id: int) -> None:
        """
        Deletes object from Redis along with its reverse index.
        
        Args:
            obj_id: Object ID
            
        Raises:
            KeyError: If object not found
            RuntimeError: If delete operation fails
        """
        self._check_initialized()
        client = self._get_redis_client()
        key = self._get_object_key(obj_id)
        
        try:
            # Check existence
            if not client.exists(key):
                raise KeyError(f"Object with ID {obj_id} not found")
            
            # Load object to get key for deleting index
            obj = self.load(obj_id)
            if obj:
                obj_key = obj.get_key()
                if obj_key:
                    index_key = self._get_index_key(obj_key)
                    client.delete(index_key)
                    logger.debug(f"Deleted index for key '{obj_key}'")
            
            # Delete the object itself
            client.delete(key)
            logger.debug(f"Deleted object with id {obj_id}")
        except KeyError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete object {obj_id}: {str(e)}")
            raise RuntimeError(f"Failed to delete object {obj_id}: {str(e)}") from e
    
    def startup(self):
        """
        Initialize list and test Redis connection.
        Optional method to verify connection on startup.
        """
        try:
            client = self._get_redis_client()
            client.ping()
            logger.info(f"{self.list_key()} list initialized with Redis connection")
        except Exception as e:
            logger.critical(f"Failed to initialize {self.list_key()} list: {str(e)}")
            raise RuntimeError(f"Failed to initialize list: {str(e)}") from e
    
    def shutdown(self):
        """
        Shutdown list.
        Redis connection will be closed automatically when client goes out of scope.
        """
        logger.info(f"{self.list_key()} list shutdown")
    
    def send_message(self, obj_id: int, level: str, message: str) -> None:
        """
        Send message to Redis pub/sub channel for the object.
        
        Channel name format: {list_key()}:messages:{obj_id}
        Message format: JSON with timestamp, level, and message.
        
        Args:
            obj_id: Object ID
            level: Message level (info, warning, error, success, debug)
            message: Message text
            
        Raises:
            RuntimeError: If list is not initialized or publish fails
        """
        self._check_initialized()
        
        # Validate level
        valid_levels = ['info', 'warning', 'error', 'success', 'debug']
        if level not in valid_levels:
            raise ValueError(f"Invalid message level '{level}'. Must be one of: {', '.join(valid_levels)}")
        
        # Form channel name
        channel = f"{self.list_key()}:messages:{obj_id}"
        
        # Create message payload with timestamp
        message_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message
        }
        
        # Serialize to JSON
        message_json = json.dumps(message_data, ensure_ascii=False)
        
        try:
            client = self._get_redis_client()
            # Publish to Redis pub/sub channel
            subscribers = client.publish(channel, message_json)
            logger.debug(f"Published message to channel {channel} (subscribers: {subscribers})")
        except Exception as e:
            logger.error(f"Failed to publish message to channel {channel}: {str(e)}")
            raise RuntimeError(f"Failed to publish message to channel {channel}: {str(e)}") from e

