from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import importlib.util
import sys
import asyncio
from multiprocessing import Process
from app.services.tasks.tasks import BacktestingTaskList, Task
from app.services.tasks.strategy import StrategyBacktest
from app.services.strategies import validate_relative_path, load_strategy
from app.services.strategies.exceptions import StrategyFileError, StrategyNotFoundError
from app.services.quotes.client import Client
from app.core.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
from app.core.logger import get_logger, setup_logging
from app.core.growing_data2redis import GrowingData2Redis, PacketType

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
        Strategy class that inherits from StrategyBacktest
        
    Raises:
        StrategyNotFoundError: If strategy file not found
        HTTPException: If strategy class cannot be loaded
    """
    # Load strategy file
    try:
        strategy_name, _, strategy_text = load_strategy(file_path)
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StrategyFileError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Create a unique module name
    module_name = f"strategy_backtest_{strategy_name.replace('/', '_').replace('.', '_')}"
    
    # Remove module from cache if it exists
    if module_name in sys.modules:
        del sys.modules[module_name]
    
    # Compile and load the module
    try:
        spec = importlib.util.spec_from_loader(module_name, loader=None)
        if spec is None:
            raise HTTPException(status_code=500, detail="Failed to create module spec")
        
        module = importlib.util.module_from_spec(spec)
        exec(strategy_text, module.__dict__)
        sys.modules[module_name] = module
    except SyntaxError as e:
        error_msg = f"Syntax error in strategy code: {e.msg}"
        if e.lineno:
            error_msg += f" at line {e.lineno}"
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load strategy module: {str(e)}")
    
    # Find the strategy class (should inherit from StrategyBacktest)
    strategy_class = None
    for attr_name in dir(module):
        try:
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and 
                issubclass(attr, StrategyBacktest) and 
                attr != StrategyBacktest):
                strategy_class = attr
                break
        except Exception:
            continue
    
    if strategy_class is None:
        raise HTTPException(
            status_code=400,
            detail="Strategy class not found: no class inheriting from StrategyBacktest found in the code"
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
    
    # Start worker in separate process
    process = Process(target=worker_backtesting_task, args=(task_id,))
    process.start()
    logger.info(f"Started backtesting worker process for task {task_id} (PID: {process.pid})")


def worker_backtesting_task(task_id: int) -> None:
    """
    Worker function that runs in a separate process.
    Handles task status updates and calls process_backtesting_task.
    
    Args:
        task_id: Task ID to run backtesting for
    """
    try:
        # Initialize logging in this process
        setup_logging()
        
        # Ensure BacktestingTaskList and Quotes Client are initialized in this process
        redis_params = {
            "host": REDIS_HOST,
            "port": REDIS_PORT,
            "db": REDIS_DB,
            "password": REDIS_PASSWORD,
        }
        BacktestingTaskList(redis_params=redis_params)
        Client(redis_params=redis_params)

        task = task_list.load(task_id)
        if task is None:
            logger.error(f"Task {task_id} not found in worker process")
            return
            
        task.isRunning = True
        task.save()
        logger.info(f"Starting background backtesting for task {task_id}")
        process_backtesting_task(task)
    except Exception as e:
        logger.error(f"Error running backtesting for task {task_id}: {str(e)}", exc_info=True)
    finally:
        # Reload task to get latest state
        task = task_list.load(task_id)
        if task is not None:
            task.isRunning = False
            task.save()
            logger.info(f"Task {task_id} status updated: isRunning=False")
    
    
def process_backtesting_task(task: Task) -> None:
    """
    Background procedure for running backtesting task.
    This function is designed to run in a separate process.
    
    Args:
        task: Task instance to run backtesting for
        
    This function runs synchronously in a separate process and does not return any value.
    Task status is updated in Redis (isRunning flag).
    """
    try:
        # Load strategy class
        # Note: load_strategy_class may raise HTTPException, which we catch as Exception
        strategy_class = load_strategy_class(task.file_name)
        
        # Create strategy instance
        strategy = strategy_class(task)
        
        # Run backtesting
        strategy.run()
        
        logger.info(f"Background backtesting completed successfully for task {task.id}")
        
    except HTTPException as e:
        # HTTPException is raised by load_strategy_class, log it as error
        logger.error(f"Error loading strategy for task {task.id}: {e.detail}")
    except Exception as e:
        logger.error(f"Error running background backtesting for task {task.id}: {str(e)}", exc_info=True)


@router.websocket("/tasks/{task_id}/results")
async def backtesting_results_websocket(websocket: WebSocket, task_id: int):
    """
    WebSocket endpoint for streaming backtesting results from Redis to frontend.
    
    Protocol:
    1. Reads Redis Stream from the beginning until the first START packet (type == "start").
       These initial packets are not sent to the frontend.
    2. Trims the stream so that all entries before START are removed (START remains).
    3. Starting from START, forwards all packets to the frontend:
       - "start": marks the beginning of results stream
       - "data": incremental data packets (including progress 0-100 in packet.data.progress)
       - "end": normal completion, forwarded and then coroutine terminates
       - "error": error packet, forwarded and then coroutine terminates
       Any other packet type is treated as error: logged, converted to "error" packet and sent, then coroutine terminates.
    """
    await websocket.accept()

    # Load task to resolve Redis key
    task = task_list.load(task_id)
    if task is None:
        await websocket.send_json({
            "type": PacketType.ERROR.value,
            "data": {"message": "Task not found"}
        })
        await websocket.close()
        return

    # Get Redis key for this task's results
    try:
        redis_key = task.get_result_key()
    except Exception as e:
        logger.error(f"Failed to get result key for task {task_id}: {e}", exc_info=True)
        await websocket.send_json({
            "type": PacketType.ERROR.value,
            "data": {"message": "Failed to get result key for task"}
        })
        await websocket.close()
        return

    # Initialize GrowingData2Redis in read mode
    try:
        redis_client = task_list._get_redis_client()
        reader = GrowingData2Redis(redis_client=redis_client, redis_key=redis_key)
    except Exception as e:
        logger.error(f"Failed to initialize GrowingData2Redis for task {task_id}: {e}", exc_info=True)
        await websocket.send_json({
            "type": PacketType.ERROR.value,
            "data": {"message": "Failed to initialize results reader"}
        })
        await websocket.close()
        return

    # Start by reading from the beginning to find START packet
    # After START, we'll continue reading entries after START sequentially
    last_id = "0-0"
    start_found = False

    try:
        while True:
            # Read from Redis stream; block up to 1 second for new data
            # Read one entry at a time to ensure strict ordering and immediate forwarding
            # Wrap synchronous Redis call in executor to avoid blocking event loop
            entries = await asyncio.to_thread(reader.read_stream_from, last_id=last_id, block_ms=1000, count=1)
            if not entries:
                continue

            # Process single entry (count=1 ensures only one entry)
            message_id, packet = entries[0]
            packet_type = packet.get("type")
            
            # Update last_id immediately to ensure sequential reading
            # Always update last_id to the current message_id to read next entry sequentially
            last_id = message_id

            # Ensure packet_type is a plain string
            if isinstance(packet_type, bytes):
                packet_type = packet_type.decode("utf-8")

            # Phase 1: search for first START packet, do not forward anything before it
            if not start_found:
                if packet_type == PacketType.START.value:
                    start_found = True
                    # Trim all entries before START (keep START)
                    # Wrap synchronous Redis call in executor to avoid blocking event loop
                    try:
                        await asyncio.to_thread(reader.trim_stream_min_id, message_id)
                    except Exception as e:
                        logger.error(
                            f"Failed to trim Redis stream {redis_key} to START id {message_id}: {e}",
                            exc_info=True
                        )
                    # Forward START packet to frontend
                    try:
                        await websocket.send_json(packet)
                    except Exception as send_err:
                        logger.info(
                            f"WebSocket closed while sending START packet for task {task_id}: {send_err}"
                        )
                        return
                    # After START, continue reading entries after START (use START's message_id as last_id)
                    # This ensures we read all DATA packets that come after START, even if they're already in the stream
                    # We read them one by one (count=1) and update last_id after each read
                    last_id = message_id
                    # Continue to next iteration to read next packet after START
                    continue
                # Skip all packets before START
                continue

            # Phase 2: after START, forward all packets according to rules
            if packet_type == PacketType.DATA.value:
                try:
                    await websocket.send_json(packet)
                except Exception as send_err:
                    logger.info(
                        f"WebSocket closed while sending DATA packet for task {task_id}: {send_err}"
                    )
                    return
                continue

            if packet_type == PacketType.END.value:
                try:
                    await websocket.send_json(packet)
                except Exception as send_err:
                    logger.info(
                        f"WebSocket closed while sending END packet for task {task_id}: {send_err}"
                    )
                return

            if packet_type == PacketType.ERROR.value:
                try:
                    await websocket.send_json(packet)
                except Exception as send_err:
                    logger.info(
                        f"WebSocket closed while sending ERROR packet for task {task_id}: {send_err}"
                    )
                return

            # Unexpected packet type
            logger.error(
                f"Unexpected packet type '{packet_type}' in results stream for task {task_id}"
            )
            error_packet = {
                "type": PacketType.ERROR.value,
                "data": {
                    "message": f"Unexpected packet type '{packet_type}' in results stream"
                },
            }
            try:
                await websocket.send_json(error_packet)
            except Exception as send_err:
                logger.info(
                    f"WebSocket closed while sending unexpected-type ERROR packet for task {task_id}: {send_err}"
                )
            return

    except WebSocketDisconnect:
        logger.info(f"Backtesting results WebSocket disconnected for task {task_id}")
    except Exception as e:
        # Generic error while reading from Redis or processing packets.
        # Do not attempt to send or close if connection is already broken.
        logger.error(
            f"Error while streaming backtesting results for task {task_id}: {e}",
            exc_info=True,
        )


