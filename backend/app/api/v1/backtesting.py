from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import importlib.util
import sys
from multiprocessing import Process
from app.services.tasks.tasks import BacktestingTaskList, Task
from app.services.tasks.strategy import StrategyBacktest
from app.services.strategies import validate_relative_path, load_strategy
from app.services.strategies.exceptions import StrategyFileError, StrategyNotFoundError
from app.core.config import STRATEGIES_DIR
from app.core.logger import get_logger

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
    Start backtesting for a task.
    
    Args:
        task_id: Task ID
        
    Returns:
        Dictionary with backtesting results including deals, global_deal, and statistics
        
    Raises:
        HTTPException: If task not found, strategy file not found, or execution fails
    """
    # Load task
    task = task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Check if task is already running
    if task.isRunning:
        raise HTTPException(status_code=409, detail="Task is already running")
    
    # Validate required fields
    if not task.file_name:
        raise HTTPException(status_code=400, detail="Task file_name is required")
    if not task.source:
        raise HTTPException(status_code=400, detail="Task source is required")
    if not task.symbol:
        raise HTTPException(status_code=400, detail="Task symbol is required")
    if not task.timeframe:
        raise HTTPException(status_code=400, detail="Task timeframe is required")
    if not task.dateStart:
        raise HTTPException(status_code=400, detail="Task dateStart is required")
    if not task.dateEnd:
        raise HTTPException(status_code=400, detail="Task dateEnd is required")
    
    try:
        # Load strategy class
        strategy_class = load_strategy_class(task.file_name)
        
        # Create strategy instance
        strategy = strategy_class(task)
        
        # Run backtesting
        strategy.run()
        
        # Serialize results
        deals = [serialize_deal(deal) for deal in strategy.deals]
        global_deal = serialize_deal(strategy.global_deal)
        
        # Calculate statistics
        total_deals = len(deals)
        winning_deals = sum(1 for deal in deals if deal.get('profit', 0) > 0)
        losing_deals = sum(1 for deal in deals if deal.get('profit', 0) < 0)
        total_profit = sum(deal.get('profit', 0) for deal in deals)
        total_fees = sum(deal.get('fees', 0) for deal in deals)
        
        # Update task status
        task.isRunning = False
        task.save()
        
        return {
            "success": True,
            "task_id": task_id,
            "deals": deals,
            "global_deal": global_deal,
            "statistics": {
                "total_deals": total_deals,
                "winning_deals": winning_deals,
                "losing_deals": losing_deals,
                "total_profit": total_profit,
                "total_fees": total_fees,
                "win_rate": (winning_deals / total_deals * 100) if total_deals > 0 else 0,
                "final_balance": global_deal.get('balance', 0)
            }
        }
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error running backtesting for task {task_id}: {str(e)}", exc_info=True)
        # Update task status on error
        task.isRunning = False
        task.save()
        raise HTTPException(status_code=500, detail=f"Error running backtesting: {str(e)}")


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
    
    task.clear_results()
    
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


