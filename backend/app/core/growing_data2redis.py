"""
Universal manager for uploading changing data to Redis.
Handles incremental updates for growing lists and full updates for simple properties.
"""
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from enum import Enum
import redis
import redis.asyncio as redis_async
import json
import numpy as np
from pydantic import BaseModel
from app.core.logger import get_logger

logger = get_logger(__name__)


class PacketType(str, Enum):
    """String enum for packet types stored in Redis."""
    START = "start"
    DATA = "data"
    END = "end"
    ERROR = "error"
    CANCEL = "cancel"


class GrowingData2Redis:
    """
    Universal manager for uploading changing data to Redis.
    
    Tracks changes in object properties:
    - Simple properties: always uploaded with current value
    - List properties: only new elements are uploaded incrementally
    
    Data is stored in Redis Stream as JSON packets with type markers:
    - "start": initialization marker
    - "data": data packet with changes
    - "end": completion marker
    """
    
    def __init__(
        self,
        redis_params: Dict,
        redis_key: str,
        source_object: Optional[Any] = None,
        property_names: Optional[List[str]] = None,
        id_result: Optional[str] = None
    ):
        """
        Initialize GrowingData2Redis.
        
        Args:
            redis_params: Redis connection parameters dict
                - host: str
                - port: int
                - db: int
                - password: Optional[str]
            redis_key: Key for Redis Stream where data will be stored
            source_object: Optional object containing data to upload (e.g., Strategy instance).
                           If None, the instance works in read-only mode (for receiving packets).
            property_names: Optional list of property names to track and upload.
                            Required for write mode, ignored in read-only mode.
            id_result: Optional unique ID for this backtesting run (GUID). If provided, will be included in all packets.
        """
        self.redis_key = redis_key
        self.source_object = source_object
        self.property_names = property_names
        
        # Determine mode: write mode if source_object is provided
        self._write_mode = self.source_object is not None
        
        # In write mode, property_names and id_result are required
        if self._write_mode:
            if self.property_names is None:
                raise ValueError("property_names is required in write mode (when source_object is provided)")
            if not id_result:
                raise ValueError("id_result is required in write mode (when source_object is provided)")
        
        self.id_result = id_result

        # Internal state (set in reset() for write mode)
        self._list_sizes: Dict[str, int] = {}  # property_name -> current size
        self._simple_properties: List[str] = []  # properties that are not lists

        self._initialized = False

        # Write mode: use synchronous Redis client; read mode: use asynchronous client
        if self._write_mode:
            self.redis_client = redis.Redis(
                host=redis_params["host"],
                port=redis_params["port"],
                db=redis_params["db"],
                password=redis_params.get("password"),
                decode_responses=True,
            )
            self.redis_client_async = None
        else:
            self.redis_client = None
            self.redis_client_async = redis_async.Redis(
                host=redis_params["host"],
                port=redis_params["port"],
                db=redis_params["db"],
                password=redis_params.get("password"),
                decode_responses=True,
            )
    
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
    
    def _send_packet(self, packet_type: PacketType, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Send packet to Redis Stream using XADD.
        
        Args:
            packet_type: Type of packet (PacketType.START, PacketType.DATA, PacketType.END, PacketType.ERROR, PacketType.CANCEL)
            data: Optional data dictionary (for "data" type)
        """
        # Store only type and data in the stream entry.
        # Data is JSON-encoded to keep the stream schema simple (string fields).
        fields: Dict[str, Any] = {"type": packet_type.value}
        
        # Prepare data dict, adding id_result (always present in write mode)
        packet_data = data or {}
        packet_data["id_result"] = self.id_result
        
        fields["data"] = json.dumps(packet_data)
        
        try:
            message_id = self.redis_client.xadd(self.redis_key, fields, id="*")
            logger.debug(f"Sent {packet_type} packet to stream {self.redis_key} with id {message_id}")
        except Exception as e:
            logger.error(f"Failed to send {packet_type} packet to Redis stream: {e}")
            raise

    def send_error_packet(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Try to send an error packet with diagnostics to Redis.
        Does not raise if sending the error packet itself fails.
        """
        data: Dict[str, Any] = {"message": message}
        if context:
            data["context"] = context
        try:
            self._send_packet(PacketType.ERROR, data)
        except Exception as e:
            # Avoid masking original errors with secondary failures
            logger.error(f"Failed to send error packet to Redis: {e}")
    
    def send_cancel_packet(self, message: str) -> None:
        """
        Send a cancel packet to Redis.
        Used when backtesting is stopped by user request.
        Does not raise if sending the cancel packet itself fails.
        """
        data: Dict[str, Any] = {"message": message}
        try:
            self._send_packet(PacketType.CANCEL, data)
        except Exception as e:
            # Avoid masking original errors with secondary failures
            logger.error(f"Failed to send cancel packet to Redis: {e}")
    
    def reset(self) -> None:
        """
        Initialize tracking state (write mode).
        
        Analyzes properties:
        - Identifies which properties are lists (for incremental updates)
        - Identifies which properties are simple (for full updates)
        - Records initial list sizes
        
        And sends "start" marker.
        """
        if not self._write_mode:
            msg = (
                "reset() is only available in write mode "
                "(source_object and property_names must be provided)"
            )
            self.send_error_packet(msg, {"redis_key": self.redis_key})
            raise RuntimeError(msg)
        
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
        self._send_packet(PacketType.START)
        self._initialized = True
        
        logger.info(f"Reset completed: {len(self._simple_properties)} simple properties, "
                   f"{len(self._list_sizes)} list properties")
    
    def send_changes(self) -> None:
        """
        Send changes to Redis (write mode).
        
        For simple properties: always uploads current value.
        For list properties: uploads only new elements (added since last check).
        
        Sends "data" packet to Redis.
        """
        if not self._initialized:
            msg = "reset() must be called before send_changes()"
            self.send_error_packet(msg, {"redis_key": self.redis_key})
            raise RuntimeError(msg)
        
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
            self._send_packet(PacketType.DATA, data)
        else:
            logger.debug("No changes to send")
    
    def finish(self) -> None:
        """
        Finalize upload process (write mode).
        
        Updates list sizes to final values and sends "end" marker to Redis.
        """
        if not self._initialized:
            msg = "reset() must be called before finish()"
            self.send_error_packet(msg, {"redis_key": self.redis_key})
            raise RuntimeError(msg)
        
        # Update final list sizes
        for prop_name in list(self._list_sizes.keys()):
            try:
                current_list = getattr(self.source_object, prop_name)
                if isinstance(current_list, (list, tuple)):
                    self._list_sizes[prop_name] = len(current_list)
            except (AttributeError, Exception) as e:
                msg = f"Error updating final size for '{prop_name}': {e}"
                logger.error(msg)
                self.send_error_packet(msg, {"redis_key": self.redis_key, "property": prop_name})
        
        # Send end marker
        self._send_packet(PacketType.END)
        
        logger.info(f"Finish completed. Final list sizes: {self._list_sizes}")
        logger.info(f"Finish completed. Final list sizes: {self._list_sizes}")

    # ==== Stream read helpers (read mode, asynchronous) ====
    
    async def read_stream_from_async(
        self,
        last_id: str,
        block_ms: int,
        count: int = 1,
    ) -> Optional[List[Tuple[str, Dict[str, Any]]]]:
        """
        Read entries from the Redis Stream starting after last_id.
        This method is async and uses an asynchronous Redis client.

        Args:
            last_id: Last seen message ID (e.g. "0-0" for from beginning).
            block_ms: Block time in milliseconds (0 for non-blocking).
            count: Maximum number of entries to return per call.

        Returns:
            List of (message_id, packet_dict) or None if timeout / no data.
            packet_dict has keys: "type" (str) and optional "data" (dict).
        """
        streams = {self.redis_key: last_id}
        try:
            if self.redis_client_async is None:
                raise RuntimeError("read_stream_from_async can only be used in read mode (async client not initialized)")
            results = await self.redis_client_async.xread(
                streams=streams,
                count=count,
                block=block_ms if block_ms > 0 else None,
            )
            if not results:
                return None

            # xread returns list of (stream, [ (id, fields), ... ])
            _, entries = results[0]
            parsed: List[Tuple[str, Dict[str, Any]]] = []
            for message_id, fields in entries:
                raw_type = fields.get("type")
                raw_data = fields.get("data")
                packet: Dict[str, Any] = {"type": raw_type}
                if raw_data is not None:
                    try:
                        packet["data"] = json.loads(raw_data)
                    except json.JSONDecodeError:
                        # If data is not valid JSON, pass it as-is for diagnostics
                        packet["data"] = {"raw": raw_data}
                parsed.append((message_id, packet))
            return parsed
        except Exception as e:
            msg = f"Failed to read from Redis stream {self.redis_key}: {e}"
            logger.error(msg)
            self.send_error_packet(msg, {"redis_key": self.redis_key})
            raise

    async def trim_stream_min_id_async(self, min_id: str) -> None:
        """
        Trim Redis Stream so that entries with ID < min_id are removed.
        Keeps min_id and all newer entries.
        This method is async and uses an asynchronous Redis client.
        """
        try:
            # XTRIM <key> MINID <min_id>
            if self.redis_client_async is None:
                raise RuntimeError("trim_stream_min_id_async can only be used in read mode (async client not initialized)")
            await self.redis_client_async.xtrim(self.redis_key, minid=min_id)
            logger.debug(f"Trimmed Redis stream {self.redis_key} to MINID {min_id}")
        except Exception as e:
            msg = f"Failed to trim Redis stream {self.redis_key} to MINID {min_id}: {e}"
            logger.error(msg)
            self.send_error_packet(msg, {"redis_key": self.redis_key, "min_id": min_id})
