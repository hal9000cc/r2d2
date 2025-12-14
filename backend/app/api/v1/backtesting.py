from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from app.services.tasks.backtesting_task import BacktestingTaskList, BacktestingTask

router = APIRouter(prefix="/api/v1/backtesting", tags=["backtesting"])

# Get singleton instance (initialized in startup.py)
task_list = BacktestingTaskList()


@router.get("/tasks", response_model=List[Dict[str, Any]])
async def get_backtesting_tasks():
    """
    Get list of all backtesting tasks from Redis
    
    Returns:
        List of backtesting task dictionaries
    """
    tasks = task_list.list()
    return [task.model_dump() for task in tasks]


@router.get("/tasks/{task_id}", response_model=Dict[str, Any])
async def get_backtesting_task(task_id: int):
    """
    Get single backtesting task by ID
    If task_id is 0, returns empty task with new ID
    
    Args:
        task_id: Task ID
        
    Returns:
        Task dictionary
    """
    # If task_id == 0, return empty task with new ID
    if task_id == 0:
        task = task_list.new()
        return task.model_dump()
    
    task = task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task.model_dump()


@router.post("/tasks", response_model=Dict[str, Any])
async def create_backtesting_task(task_data: Dict[str, Any]):
    """
    Create new backtesting task
    
    Args:
        task_data: Task data dictionary
        
    Returns:
        Created task dictionary
        
    Raises:
        HTTPException: If task with same strategy_id already exists
    """
    # Check if task with same strategy_id already exists
    strategy_id = task_data.get('strategy_id', '')
    if strategy_id:
        existing_task = task_list.load_by_key(strategy_id)
        if existing_task is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Task with strategy_id '{strategy_id}' already exists. Please use a different strategy name or update the existing task."
            )
    
    # Create new task
    task = task_list.new()
    
    # Update fields from request data
    for key, value in task_data.items():
        if hasattr(task, key) and key != 'id':
            setattr(task, key, value)
    
    # Save task
    saved_task = task.save()
    return saved_task.model_dump()


@router.put("/tasks/{task_id}", response_model=Dict[str, Any])
async def update_backtesting_task(task_id: int, task_data: Dict[str, Any]):
    """
    Update backtesting task
    
    Args:
        task_id: Task ID
        task_data: Task data dictionary
        
    Returns:
        Updated task dictionary
    """
    # Ensure id matches
    task_data["id"] = task_id
    
    # Convert dict to BacktestingTask object using Pydantic
    task = BacktestingTask.model_validate(task_data)
    task._list = task_list  # Set reference to list
    
    # save() will add or update the task
    updated_task = task.save()
    return updated_task.model_dump()


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


@router.get("/strategies", response_model=List[str])
async def get_backtesting_strategies():
    """
    Get list of unique strategy identifiers from all backtesting tasks
    
    Returns:
        List of unique strategy_id values
    """
    tasks = task_list.list()
    strategy_ids = set()
    for task in tasks:
        if task.strategy_id:
            strategy_ids.add(task.strategy_id)
    return sorted(list(strategy_ids))

