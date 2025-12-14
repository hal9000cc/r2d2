"""
Universal manager for uploading changing data to Redis.
Handles incremental updates for growing lists and full updates for simple properties.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum
import redis
import json
import numpy as np
from pydantic import BaseModel
from app.core.logger import get_logger

logger = get_logger(__name__)


class GrowingData2Redis:
    """
    Universal manager for uploading changing data to Redis.
    
    Tracks changes in object properties:
    - Simple properties: always uploaded with current value
    - List properties: only new elements are uploaded incrementally
    
    Data is stored in Redis List as JSON packets with type markers:
    - "start": initialization marker
    - "data": data packet with changes
    - "end": completion marker
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        redis_key: str,
        source_object: Any,
        property_names: List[str]
    ):
        """
        Initialize GrowingData2Redis.
        
        Args:
            redis_client: Redis client instance
            redis_key: Key for Redis List where data will be stored
            source_object: Object containing data to upload (e.g., Strategy instance)
            property_names: List of property names to track and upload
        """
        self.redis_client = redis_client
        self.redis_key = redis_key
        self.source_object = source_object
        self.property_names = property_names
        
        # Internal state (set in reset())
        self._list_sizes: Dict[str, int] = {}  # property_name -> current size
        self._simple_properties: List[str] = []  # properties that are not lists
        
        self._initialized = False
    
    def _serialize_value(self, value: Any) -> Any:
        """
        Serialize value to JSON-serializable format.
        
        Handles:
        - Pydantic BaseModel: uses model_dump()
        - Enum: uses value
        - numpy types: converts to Python types
        - datetime/numpy datetime64: converts to ISO string
        - Regular objects: attempts to serialize __dict__
        - Basic types: passes through
        
        Args:
            value: Value to serialize
            
        Returns:
            JSON-serializable value
        """
        if value is None:
            return None
        
        # Pydantic BaseModel
        if isinstance(value, BaseModel):
            return value.model_dump()
        
        # Enum
        if isinstance(value, Enum):
            return value.value
        
        # numpy datetime64
        if isinstance(value, np.datetime64):
            return str(value)
        
        # numpy scalar types
        if isinstance(value, (np.integer, np.floating)):
            return float(value) if isinstance(value, np.floating) else int(value)
        
        # numpy array (convert to list)
        if isinstance(value, np.ndarray):
            return value.tolist()
        
        # datetime
        if isinstance(value, datetime):
            return value.isoformat()
        
        # Basic types
        if isinstance(value, (str, int, float, bool)):
            return value
        
        # List - recursively serialize elements
        if isinstance(value, (list, tuple)):
            return [self._serialize_value(item) for item in value]
        
        # Dict - recursively serialize values
        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        
        # Regular object - try to serialize __dict__
        if hasattr(value, '__dict__'):
            try:
                obj_dict = {}
                for key, val in value.__dict__.items():
                    # Skip private attributes
                    if not key.startswith('_'):
                        obj_dict[key] = self._serialize_value(val)
                return obj_dict
            except Exception as e:
                logger.error(f"Failed to serialize object {type(value).__name__}: {e}")
                return str(value)
        
        # Fallback: convert to string
        return str(value)
    
    def _send_packet(self, packet_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Send packet to Redis List.
        
        Args:
            packet_type: Type of packet ("start", "data", or "end")
            data: Optional data dictionary (for "data" type)
        """
        packet = {
            "type": packet_type,
            "timestamp": datetime.now().isoformat()
        }
        
        if data is not None:
            packet["data"] = data
        
        try:
            packet_json = json.dumps(packet, ensure_ascii=False)
            self.redis_client.lpush(self.redis_key, packet_json)
            logger.debug(f"Sent {packet_type} packet to {self.redis_key}")
        except Exception as e:
            logger.error(f"Failed to send {packet_type} packet to Redis: {e}")
            raise
    
    def reset(self) -> None:
        """
        Initialize tracking state.
        
        Analyzes properties:
        - Identifies which properties are lists (for incremental updates)
        - Identifies which properties are simple (for full updates)
        - Records initial list sizes
        
        Sends "start" marker to Redis.
        """
        self._list_sizes = {}
        self._simple_properties = []
        
        for prop_name in self.property_names:
            try:
                value = getattr(self.source_object, prop_name)
                
                # Check if it's a list or tuple
                if isinstance(value, (list, tuple)):
                    self._list_sizes[prop_name] = len(value)
                    logger.debug(f"Property '{prop_name}' is a list with size {len(value)}")
                else:
                    self._simple_properties.append(prop_name)
                    logger.debug(f"Property '{prop_name}' is a simple property")
            except AttributeError:
                logger.error(f"Property '{prop_name}' not found in source object, skipping")
            except Exception as e:
                logger.error(f"Error analyzing property '{prop_name}': {e}, skipping")
        
        # Send start marker
        self._send_packet("start")
        self._initialized = True
        
        logger.info(f"Reset completed: {len(self._simple_properties)} simple properties, "
                   f"{len(self._list_sizes)} list properties")
    
    def send_changes(self) -> None:
        """
        Send changes to Redis.
        
        For simple properties: always uploads current value.
        For list properties: uploads only new elements (added since last check).
        
        Sends "data" packet to Redis.
        """
        if not self._initialized:
            raise RuntimeError("reset() must be called before send_changes()")
        
        data = {}
        
        # Process simple properties (always upload)
        for prop_name in self._simple_properties:
            try:
                value = getattr(self.source_object, prop_name)
                serialized_value = self._serialize_value(value)
                data[prop_name] = serialized_value
            except AttributeError:
                logger.warning(f"Property '{prop_name}' not found, skipping")
            except Exception as e:
                logger.warning(f"Error serializing property '{prop_name}': {e}, skipping")
        
        # Process list properties (only new elements)
        for prop_name, last_size in self._list_sizes.items():
            try:
                current_list = getattr(self.source_object, prop_name)
                
                if not isinstance(current_list, (list, tuple)):
                    logger.warning(f"Property '{prop_name}' is no longer a list, skipping")
                    continue
                
                current_size = len(current_list)
                
                # Check if there are new elements
                if current_size > last_size:
                    new_elements = current_list[last_size:]
                    serialized_elements = [self._serialize_value(item) for item in new_elements]
                    data[f"{prop_name}_new"] = serialized_elements
                    
                    # Update stored size
                    self._list_sizes[prop_name] = current_size
                    
                    logger.debug(f"Property '{prop_name}': added {len(new_elements)} new elements")
                elif current_size < last_size:
                    logger.warning(f"Property '{prop_name}': list size decreased from {last_size} to {current_size}, "
                                 f"this is unexpected for growing lists")
                    # Update size anyway
                    self._list_sizes[prop_name] = current_size
            except AttributeError:
                logger.error(f"Property '{prop_name}' not found, skipping")
            except Exception as e:
                logger.error(f"Error processing list property '{prop_name}': {e}, skipping")
        
        # Send data packet if there's any data
        if data:
            self._send_packet("data", data)
        else:
            logger.debug("No changes to send")
    
    def finish(self) -> None:
        """
        Finalize upload process.
        
        Updates list sizes to final values and sends "end" marker to Redis.
        """
        if not self._initialized:
            raise RuntimeError("reset() must be called before finish()")
        
        # Update final list sizes
        for prop_name in list(self._list_sizes.keys()):
            try:
                current_list = getattr(self.source_object, prop_name)
                if isinstance(current_list, (list, tuple)):
                    self._list_sizes[prop_name] = len(current_list)
            except (AttributeError, Exception) as e:
                logger.error(f"Error updating final size for '{prop_name}': {e}")
        
        # Send end marker
        self._send_packet("end")
        
        logger.info(f"Finish completed. Final list sizes: {self._list_sizes}")
