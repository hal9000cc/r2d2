from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import importlib.util
import sys
import uuid
import json
import asyncio
from datetime import datetime, timezone
from multiprocessing import Process
import redis.asyncio as redis_async
from app.services.tasks.tasks import BacktestingTaskList, Task
from app.services.tasks.strategy import Strategy
from app.services.tasks.broker import Broker
from app.services.strategies import validate_relative_path, load_strategy
from app.services.strategies.exceptions import StrategyFileError, StrategyNotFoundError
from app.services.quotes.client import QuotesClient
from app.core.config import redis_params
from app.core.logger import get_logger, setup_logging
from app.core.objects2redis import MessageType
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/backtesting", tags=["backtesting"])

# Get singleton instance (initialized in startup.py)
task_list = BacktestingTaskList()


@router.get("/tasks", response_model=List[Dict[str, Any]])
async def get_backtesting_tasks():
    """
    Get list of all backtesting tasks from Redis
    
    Returns:
        List of backtesting task dictionaries (with relative paths in file_name)
    """
    tasks = task_list.list()
    result = []
    for task in tasks:
        task_dict = task.model_dump()
        result.append(task_dict)
    return result


@router.get("/tasks/{task_id}", response_model=Dict[str, Any])
async def get_backtesting_task(task_id: int):
    """
    Get single backtesting task by ID
    If task_id is 0, returns empty task with new ID
    
    Args:
        task_id: Task ID
        
    Returns:
        Task dictionary (with relative path in file_name)
    """
    # If task_id == 0, return empty task with new ID
    if task_id == 0:
        task = task_list.new()
        task_dict = task.model_dump()
        return task_dict
    
    task = task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_dict = task.model_dump()
    return task_dict


@router.post("/tasks", response_model=Dict[str, Any])
async def create_backtesting_task(task_data: Dict[str, Any]):
    """
    Create new backtesting task
    
    Args:
        task_data: Task data dictionary (with relative path in file_name)
    
    Returns:
        Created task dictionary (with relative path in file_name)
        
    Raises:
        HTTPException: If task with same file_name already exists or path is invalid
    """
    # Validate relative path if provided
    relative_file_name = task_data.get('file_name', '')
    if relative_file_name:
        try:
            validate_relative_path(relative_file_name)
        except StrategyFileError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Check if task with same file_name already exists
        existing_task = task_list.load_by_key(relative_file_name)
        if existing_task is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Task with file_name '{relative_file_name}' already exists. Please use a different strategy file or update the existing task."
            )
    
    # Create new task
    task = task_list.new()
    
    # Update fields from request data
    for key, value in task_data.items():
        if hasattr(task, key) and key != 'id':
            setattr(task, key, value)
    
    # Save task
    saved_task = task.save()
    
    task_dict = saved_task.model_dump()
    return task_dict


@router.put("/tasks/{task_id}", response_model=Dict[str, Any])
async def update_backtesting_task(task_id: int, task_data: Dict[str, Any]):
    """
    Update backtesting task
    
    Args:
        task_id: Task ID
        task_data: Task data dictionary (with relative path in file_name)
        
    Returns:
        Updated task dictionary (with relative path in file_name)
        
    Raises:
        HTTPException: If path is invalid
    """
    # Ensure id matches
    task_data["id"] = task_id
    
    # Validate relative path if provided
    relative_file_name = task_data.get('file_name', '')
    if relative_file_name:
        try:
            validate_relative_path(relative_file_name)
        except StrategyFileError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    # Convert dict to Task object using Pydantic
    task = Task.model_validate(task_data)
    task._list = task_list  # Set reference to list
    
    # save() will add or update the task
    updated_task = task.save()
    
    task_dict = updated_task.model_dump()
    return task_dict


@router.delete("/tasks/{task_id}")
async def delete_backtesting_task(task_id: int):
    """
    Delete backtesting task
    
    Args:
        task_id: Task ID
        
    Returns:
        Success message
    """
    try:
        task_list.delete(task_id)
        return {"success": True, "message": f"Task {task_id} deleted"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


def load_strategy_class(file_path: str):
    """
    Load strategy class from file path dynamically.
    
    Args:
        file_path: Relative path to strategy file (from STRATEGIES_DIR, with .py extension)
        
    Returns:
        Strategy class that inherits from Strategy
        
    Raises:
        StrategyNotFoundError: If strategy file not found
        StrategyFileError: If strategy file is invalid
        ValueError: If strategy class cannot be loaded (syntax error, class not found, etc.)
        RuntimeError: If module loading fails
    """
    # Load strategy file
    try:
        strategy_name, _, strategy_text = load_strategy(file_path)
    except (StrategyNotFoundError, StrategyFileError):
        # Re-raise as-is (these are already proper exceptions)
        raise
    
    # Create a unique module name
    module_name = f"strategy_backtest_{strategy_name.replace('/', '_').replace('.', '_')}"
    
    # Remove module from cache if it exists
    if module_name in sys.modules:
        del sys.modules[module_name]
    
    # Compile and load the module
    try:
        spec = importlib.util.spec_from_loader(module_name, loader=None)
        if spec is None:
            raise RuntimeError("Failed to create module spec")
        
        module = importlib.util.module_from_spec(spec)
        exec(strategy_text, module.__dict__)
        sys.modules[module_name] = module
    except SyntaxError as e:
        error_msg = f"Syntax error in strategy code: {e.msg}"
        if e.lineno:
            error_msg += f" at line {e.lineno}"
        raise ValueError(error_msg) from e
    except Exception as e:
        raise RuntimeError(f"Failed to load strategy module: {str(e)}") from e
    
    # Find the strategy class (should inherit from Strategy)
    strategy_class = None
    for attr_name in dir(module):
        try:
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and 
                issubclass(attr, Strategy) and 
                attr != Strategy):
                strategy_class = attr
                break
        except Exception:
            continue
    
    if strategy_class is None:
        raise ValueError(
            "Strategy class not found: no class inheriting from Strategy found in the code"
        )
    
    return strategy_class


def serialize_deal(deal) -> Dict[str, Any]:
    """
    Serialize Deal object to dictionary for JSON response.
    
    Args:
        deal: Deal instance
        
    Returns:
        Dictionary representation of deal
    """
    # Handle OrderSide enum
    side_value = None
    if deal.side is not None:
        if hasattr(deal.side, 'value'):
            side_value = deal.side.value
        elif hasattr(deal.side, 'name'):
            side_value = deal.side.name
        else:
            side_value = str(deal.side)
    
    return {
        "side": side_value,
        "entry_time": str(deal.entry_time) if deal.entry_time is not None else None,
        "exit_time": str(deal.exit_time) if deal.exit_time is not None else None,
        "entry_price": float(deal.entry_price) if deal.entry_price is not None else None,
        "exit_price": float(deal.exit_price) if deal.exit_price is not None else None,
        "max_volume": float(deal.max_volume) if deal.max_volume is not None else None,
        "profit": float(deal.profit) if deal.profit is not None else None,
        "fees": float(deal.fees) if deal.fees is not None else None
    }


@router.post("/tasks/{task_id}/start", response_model=Dict[str, Any])
async def start_backtesting(task_id: int):
    """
    Start backtesting for a task in background worker.
    
    This endpoint:
    - Validates the task via start_backtesting_worker
    - Clears previous backtesting results in Redis
    - Starts a separate process to run backtesting
    - Does not wait for completion and does not return backtesting results
    
    Args:
        task_id: Task ID
        
    Returns:
        Dictionary with success flag and task_id
        
    Raises:
        HTTPException: If task validation fails or worker cannot be started
    """
    try:
        start_backtesting_worker(task_id)
        return {
            "success": True,
            "task_id": task_id,
        }
    except HTTPException:
        # Re-raise HTTP exceptions from worker validation
        raise
    except Exception as e:
        logger.error(f"Error starting backtesting worker for task {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error starting backtesting worker: {str(e)}")


@router.post("/tasks/{task_id}/stop", response_model=Dict[str, Any])
async def stop_backtesting(task_id: int):
    """
    Stop backtesting for a task.
    
    This endpoint:
    - Sets task.isRunning flag to False
    - TODO: In future, will signal the worker process to stop gracefully
    
    Args:
        task_id: Task ID
        
    Returns:
        Dictionary with success flag and task_id
        
    Raises:
        HTTPException: If task not found
    """
    # Load task
    task = task_list.load(task_id)
    if task is None:
        logger.error(f"Task {task_id} not found for stop request")
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Set isRunning to False
    task.isRunning = False
    task.save()
    logger.info(f"Task {task_id} stop requested: isRunning set to False")
    
    # TODO: Add mechanism to signal worker process to stop gracefully
    # For now, this is a stub that just sets the flag
    
    return {
        "success": True,
        "task_id": task_id,
        "message": "Stop request received"
    }


def start_backtesting_worker(task_id: int) -> None:
    """
    Start backtesting worker in a separate process.
    
    Args:
        task_id: Task ID to run backtesting for
        
    This function validates the task and starts a background process to run backtesting.
    """
    # Load task
    task = task_list.load(task_id)
    if task is None:
        logger.error(f"Task {task_id} not found for background execution")
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Check if task is already running
    if task.isRunning:
        logger.warning(f"Task {task_id} is already running, skipping")
        raise HTTPException(status_code=409, detail="Task is already running")
    
    # Validate required fields
    if not task.file_name:
        logger.error(f"Task {task_id} file_name is required")
        raise HTTPException(status_code=400, detail="Task file_name is required")
    if not task.source:
        logger.error(f"Task {task_id} source is required")
        raise HTTPException(status_code=400, detail="Task source is required")
    if not task.symbol:
        logger.error(f"Task {task_id} symbol is required")
        raise HTTPException(status_code=400, detail="Task symbol is required")
    if not task.timeframe:
        logger.error(f"Task {task_id} timeframe is required")
        raise HTTPException(status_code=400, detail="Task timeframe is required")
    if not task.dateStart:
        logger.error(f"Task {task_id} dateStart is required")
        raise HTTPException(status_code=400, detail="Task dateStart is required")
    if not task.dateEnd:
        logger.error(f"Task {task_id} dateEnd is required")
        raise HTTPException(status_code=400, detail="Task dateEnd is required")
    
    # Clear previous backtesting results for this task
    try:
        task.clear_result()
    except Exception as e:
        logger.error(f"Failed to clear previous backtesting results for task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear previous backtesting results")
    
    # Generate unique ID for this backtesting run
    result_id = str(uuid.uuid4())
    
    # Write result_id to task and save
    task.result_id = result_id
    task.save()
    logger.info(f"Generated result_id {result_id} for task {task_id}")
    
    # Start worker in separate process
    process = Process(target=worker_backtesting_task, args=(task_id, result_id))
    process.start()
    logger.info(f"Started backtesting worker process for task {task_id} (PID: {process.pid}) with result_id {result_id}")


def worker_backtesting_task(task_id: int, result_id: str) -> None:
    """
    Worker function that runs in a separate process.
    Handles task status updates and calls process_backtesting_task.
    
    Args:
        task_id: Task ID to run backtesting for
        result_id: Unique ID for this backtesting run (GUID)
    """
    try:
        # Initialize logging in this process
        setup_logging()
        
        # Ensure BacktestingTaskList and Quotes Client are initialized in this process
        BacktestingTaskList(redis_params=redis_params())
        QuotesClient(redis_params=redis_params())

        task = task_list.load(task_id)
        if task is None:
            logger.error(f"Task {task_id} not found in worker process")
            return
            
        task.isRunning = True
        task.save()
        logger.info(f"Starting background backtesting for task {task_id} with result_id {result_id}")
        process_backtesting_task(task, result_id)
    except Exception as e:
        logger.error(f"Error running backtesting for task {task_id}: {str(e)}", exc_info=True)
        task.backtesting_error(f"Error running backtesting: {str(e)}")
    finally:
        # Reload task to get latest state
        task = task_list.load(task_id)
        if task is not None:
            task.isRunning = False
            task.save()
            logger.info(f"Task {task_id} status updated: isRunning=False")
    
    
def process_backtesting_task(task: Task, result_id: str) -> None:
    """
    Background procedure for running backtesting task.
    This function is designed to run in a separate process.
    
    Args:
        task: Task instance to run backtesting for
        result_id: Unique ID for this backtesting run (GUID)
        
    This function runs synchronously in a separate process and does not return any value.
    Task status is updated in Redis (isRunning flag).
    
    Raises:
        Exception: Any exception that occurs during backtesting will be propagated
                  to worker_backtesting_task for handling.
    """
    # Load strategy class
    # Note: load_strategy_class may raise StrategyNotFoundError, StrategyFileError, ValueError, or RuntimeError
    # All exceptions will be caught in worker_backtesting_task and handled appropriately
    strategy_class = load_strategy_class(task.file_name)
    
    # Create strategy instance
    try:
        strategy = strategy_class()
    except TypeError as e:
        if "__init__()" in str(e) and "positional arguments" in str(e):
            error_msg = (
                f"Strategy class {strategy_class.__name__} constructor is outdated. "
                f"It must accept no parameters: def __init__(self)"
            )
            logger.error(f"{error_msg}. Error: {e}")
            raise ValueError(error_msg) from e
        raise
    
    message = f"Backtesting for task {task.id} started"
    task.message(message)
    logger.info(message)

    task.send_message(MessageType.EVENT, {"event": "backtesting_started"})
    
    # Create broker with strategy callbacks
    callbacks = Strategy.create_strategy_callbacks(strategy)
    broker = Broker(
        fee=0.001,
        task=task,
        result_id=result_id,
        callbacks_dict=callbacks,
        results_save_period=TRADE_RESULTS_SAVE_PERIOD
    )
    # Set broker reference in strategy
    strategy.broker = broker
    broker.run(task)
    
    task.send_message(MessageType.EVENT, {"event": "backtesting_completed"})
    
    message = f"Backtesting for task {task.id} completed successfully"
    task.message(message)
    logger.info(message)

@router.websocket("/tasks/{task_id}/messages")
async def task_messages_websocket(websocket: WebSocket, task_id: int):
    """
    WebSocket endpoint for streaming task messages to frontend.
    
    Subscribes to Redis pub/sub channel: backtesting_tasks:messages:{task_id}
    and forwards messages to the frontend via WebSocket.
    
    Args:
        websocket: WebSocket connection
        task_id: Task ID
    """
    await websocket.accept()
    
    # Load task to get Redis params and validate task exists
    task = task_list.load(task_id)
    if task is None:
        # Send error messages via new message mechanism
        # Messages will be sent through Redis pub/sub and this WebSocket will forward them
        error_message = f"Task {task_id} not found"
        task_list.send_message(task_id, MessageType.EVENT, {"event": "backtesting_error"})
        task_list.send_message(task_id, MessageType.MESSAGE, {"level": "error", "message": error_message})
        # Continue - WebSocket will read and forward these messages from Redis pub/sub
    
    # Get Redis connection parameters
    redis_params_dict = task_list.get_redis_params()
    
    # Create async Redis client
    redis_client = None
    pubsub = None
    
    try:
        redis_client = redis_async.Redis(
            host=redis_params_dict["host"],
            port=redis_params_dict["port"],
            db=redis_params_dict["db"],
            password=redis_params_dict.get("password"),
            decode_responses=True
        )
        
        # Form channel name: backtesting_tasks:messages:{task_id}
        channel = f"backtesting_tasks:messages:{task_id}"
        
        # Create pubsub and subscribe to channel
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        
        logger.info(f"Subscribed to messages channel {channel} for task {task_id}")
        
        # Listen for messages from Redis pub/sub
        while True:
            try:
                # Get message from pubsub (with timeout to allow checking WebSocket state)
                message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0)
                
                if message is not None:
                    # Parse message data (should be JSON string)
                    try:
                        message_data = json.loads(message["data"])
                        # Forward message to WebSocket
                        await websocket.send_json(message_data)
                    except json.JSONDecodeError:
                        logger.warning(f"Received non-JSON message from channel {channel}: {message['data']}")
                    except (WebSocketDisconnect, ConnectionError) as e:
                        # Client disconnected - this is normal, exit loop
                        logger.debug(f"WebSocket disconnected while sending message for task {task_id}: {e}")
                        break
                    except Exception as e:
                        # Check if it's a WebSocket close error
                        # 1001 = "going away" (normal closure)
                        # 1005 = "no status received [internal]" (connection closed without close frame)
                        # 1012 = "service restart" (server restarting)
                        error_str = str(e).lower()
                        if "1001" in error_str or "going away" in error_str:
                            # Normal WebSocket closure, exit loop
                            logger.debug(f"WebSocket closed normally for task {task_id}: {e}")
                            break
                        elif "1005" in error_str or "no status received" in error_str:
                            # Connection closed without close frame - treat as normal closure
                            logger.debug(f"WebSocket closed without close frame for task {task_id}: {e}")
                            break
                        elif "1012" in error_str or "service restart" in error_str:
                            # Server restarting - treat as normal closure
                            logger.debug(f"WebSocket closed due to service restart for task {task_id}: {e}")
                            break
                        # Other errors - log and continue
                        logger.error(f"Error processing message from channel {channel}: {e}")
                
                # Check if WebSocket is still open (non-blocking)
                # If connection is closed, get_message will raise on next iteration
                
            except asyncio.CancelledError:
                # WebSocket is being cancelled (e.g., during shutdown)
                logger.debug(f"WebSocket cancelled for task {task_id}")
                break
            except asyncio.TimeoutError:
                # Timeout is normal, continue listening
                continue
            except WebSocketDisconnect:
                # Client disconnected normally
                break
            except Exception as e:
                logger.error(f"Error in messages stream for task {task_id}: {e}", exc_info=True)
                # Try to send error message
                try:
                    await websocket.send_json({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "level": "error",
                        "message": f"Error in messages stream: {str(e)}"
                    })
                except:
                    pass
                break
                
    except asyncio.CancelledError:
        # WebSocket is being cancelled (e.g., during shutdown)
        logger.debug(f"WebSocket cancelled for task {task_id}")
    except WebSocketDisconnect:
        # Client disconnected normally
        pass
    except Exception as e:
        logger.error(f"Error setting up messages stream for task {task_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "error",
                "message": f"Error setting up messages stream: {str(e)}"
            })
        except:
            pass
    finally:
        # Cleanup: unsubscribe and close connections
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception as e:
                logger.warning(f"Error closing pubsub for task {task_id}: {e}")
        
        if redis_client:
            try:
                await redis_client.close()
            except Exception as e:
                logger.warning(f"Error closing Redis client for task {task_id}: {e}")
        
        try:
            await websocket.close()
        except:
            pass
