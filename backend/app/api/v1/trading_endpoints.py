from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from collections import defaultdict
from app.services.tasks.tasks import BacktestingTaskList, TradingTaskList
from app.services.strategies import load_strategy
from app.services.strategies.exceptions import R2D2StrategyFileError, R2D2StrategyNotFoundError
from app.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/trading", tags=["trading"])

backtesting_task_list = BacktestingTaskList()
trading_task_list = TradingTaskList()

CLONE_FIELDS = [
    "name", "source", "symbol", "timeframe",
    "fee_taker", "fee_maker", "price_step",
    "precision_amount", "precision_price",
    "parameters", "history_size",
]


@router.get("/tasks", response_model=Dict[str, Any])
async def get_trading_tasks():
    """
    Get all trading tasks grouped by group_id.
    
    Returns dict with:
    - tasks: flat list of all trading tasks
    - groups: dict mapping group_id -> {name, count} for groups with >1 task
    """
    tasks = trading_task_list.list()
    task_dicts = [t.model_dump(exclude_unset=False) for t in tasks]

    group_counts: Dict[int, int] = defaultdict(int)
    for t in tasks:
        if t.group_id > 0:
            group_counts[t.group_id] += 1

    groups: Dict[str, Dict[str, Any]] = {}
    for gid, count in group_counts.items():
        if count > 1:
            source = backtesting_task_list.load(gid)
            groups[str(gid)] = {
                "name": source.name if source else f"Task #{gid}",
                "count": count,
            }

    return {"tasks": task_dicts, "groups": groups}


@router.delete("/tasks/{task_id}")
async def delete_trading_task(task_id: int):
    """
    Delete a trading task. Cannot delete a running task.
    """
    task = trading_task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Trading task {task_id} not found")

    if task.isRunning:
        raise HTTPException(status_code=400, detail="Cannot delete a running task. Stop it first.")

    trading_task_list.clear_result(task_id)
    trading_task_list.delete(task_id)
    logger.info(f"Deleted trading task {task_id}")
    return {"ok": True}


@router.post("/tasks/clone/{backtesting_task_id}", response_model=Dict[str, Any])
async def clone_to_trading(backtesting_task_id: int):
    """
    Clone a backtesting task into a new trading task.
    
    Copies task parameters, reads strategy source code from file
    and stores it as strategy_snapshot.
    
    Args:
        backtesting_task_id: ID of the backtesting task to clone
        
    Returns:
        Created trading task dictionary
    """
    source_task = backtesting_task_list.load(backtesting_task_id)
    if source_task is None:
        raise HTTPException(status_code=404, detail=f"Backtesting task {backtesting_task_id} not found")

    if not source_task.file_name:
        raise HTTPException(status_code=400, detail="Backtesting task has no strategy file")

    try:
        _, _, strategy_code = load_strategy(source_task.file_name)
    except R2D2StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except R2D2StrategyFileError as e:
        raise HTTPException(status_code=500, detail=str(e))

    trading_task = trading_task_list.new()
    trading_task.group_id = backtesting_task_id
    trading_task.strategy_snapshot = strategy_code

    for field in CLONE_FIELDS:
        setattr(trading_task, field, getattr(source_task, field))

    trading_task.dateStart = ""
    trading_task.dateEnd = ""
    trading_task.isRunning = False
    trading_task.result_id = ""

    saved = trading_task.save()
    logger.info(
        f"Created trading task {saved.id} from backtesting task {backtesting_task_id} "
        f"(strategy: {source_task.name})"
    )
    return saved.model_dump(exclude_unset=False)

