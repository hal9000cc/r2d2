from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from typing import Dict, Any, List, Optional, cast
from collections import defaultdict
from pydantic import BaseModel
import asyncio
import json
from datetime import datetime, timezone
import redis
import redis.asyncio as redis_async
from app.services.tasks.tasks import BacktestingTaskList, TradingTaskList
from app.services.tasks.task_results import TaskResults
from app.services.strategies import load_strategy
from app.services.strategies.exceptions import R2D2StrategyFileError, R2D2StrategyNotFoundError
from app.core.config import (
    redis_params,
    SUPERVISOR_ERRORS_KEY,
    SUPERVISOR_ERRORS_KEY_PREFIX,
    SUPERVISOR_GLOBAL_CHANNEL,
)
from app.core.datetime_utils import parse_utc_datetime64
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


class StopRequest(BaseModel):
    close_deals_on_stop: bool = False


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


@router.post("/tasks/{task_id}/start", response_model=Dict[str, Any])
async def start_trading_task(task_id: int):
    """
    Start a live trading task.

    Sets isRunning=True and generates a result_id.
    The actual trading process is started by an external supervisor (not this endpoint).

    Validates required fields: strategy_snapshot, source, symbol, timeframe,
    precision_amount, precision_price.

    Args:
        task_id: Trading task ID

    Returns:
        Dictionary with success flag, task_id, and result_id
    """
    task = trading_task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Trading task {task_id} not found")

    if task.isRunning:
        raise HTTPException(status_code=409, detail="Task is already running")

    if not task.strategy_snapshot:
        raise HTTPException(status_code=400, detail="Task has no strategy_snapshot. Clone from a backtesting task first.")
    if not task.source:
        raise HTTPException(status_code=400, detail="Task source is required")
    if not task.symbol:
        raise HTTPException(status_code=400, detail="Task symbol is required")
    if not task.timeframe:
        raise HTTPException(status_code=400, detail="Task timeframe is required")
    if task.precision_amount == 0.0:
        raise HTTPException(status_code=400, detail="Precision Amount must be greater than 0")
    if task.precision_price == 0.0:
        raise HTTPException(status_code=400, detail="Precision Price must be greater than 0")

    task.result_id = "0"
    task.isRunning = True
    task.save()

    logger.info(f"Trading task {task_id} start requested: isRunning=True")
    return {
        "success": True,
        "task_id": task_id,
        "result_id": "0",
    }


@router.post("/tasks/{task_id}/stop", response_model=Dict[str, Any])
async def stop_trading_task(task_id: int, body: StopRequest = StopRequest()):
    """
    Stop a live trading task.

    Sets isRunning=False. If close_deals_on_stop is True, the trading process
    will close all open deals before exiting (checked by BrokerLive via _is_stopped()).

    Args:
        task_id: Trading task ID
        body: Optional JSON body with close_deals_on_stop (default: False)

    Returns:
        Dictionary with success flag, task_id, and message
    """
    task = trading_task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Trading task {task_id} not found")

    task.close_deals_on_stop = body.close_deals_on_stop
    task.isRunning = False
    task.save()

    logger.info(
        f"Trading task {task_id} stop requested: isRunning=False, "
        f"close_deals_on_stop={body.close_deals_on_stop}"
    )
    return {
        "success": True,
        "task_id": task_id,
        "message": "Stop request received",
        "close_deals_on_stop": body.close_deals_on_stop,
    }


@router.get("/tasks/{task_id}/results/{result_id}", response_model=Dict[str, Any])
async def get_trading_results(
    task_id: int,
    result_id: str,
    time_begin: Optional[str] = Query(None, description="Start time for filtering (ISO format)"),
    min_error_id: int = Query(0, description="Minimum error id for incremental error loading"),
):
    """
    Get live trading results (trades, deals, orders, stats, errors) for a task.

    Args:
        task_id: Trading task ID
        result_id: Result ID (UUID) associated with this trading run
        time_begin: Optional ISO datetime string for filtering from this time onwards
        min_error_id: Minimum error id to load (0 = all errors, use last known id for incremental)

    Returns:
        Dictionary with success flag and data (trades, deals, orders, optional stats, errors)
    """
    task = trading_task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Trading task {task_id} not found")

    time_begin_dt64 = None
    if time_begin is not None:
        try:
            time_begin_dt64 = parse_utc_datetime64(time_begin)
        except Exception as e:
            return {
                "success": False,
                "error_message": f"Invalid time_begin format: {str(e)}",
            }

    try:
        results = TaskResults(task, broker=None)
        data = results.get_results(result_id, time_begin_dt64, min_error_id=min_error_id)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(
            f"Error getting trading results for task {task_id}, result_id {result_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "error_message": f"Failed to get results: {str(e)}",
        }


@router.get("/supervisor-errors", response_model=Dict[str, Any])
async def get_all_supervisor_errors():
    """
    Get supervisor errors from all trading tasks combined.

    Scans all Redis keys matching trading_tasks:supervisor_errors:*,
    reads their contents, adds task_id to each entry, and returns
    results sorted by timestamp ascending.

    Returns:
        Dictionary with success flag and data (list of error objects with id and task_id)
    """
    try:
        redis_params_dict = trading_task_list.get_redis_params()
        r = redis.Redis(
            host=redis_params_dict["host"],
            port=redis_params_dict["port"],
            db=redis_params_dict["db"],
            password=redis_params_dict.get("password"),
            decode_responses=True,
            socket_connect_timeout=5,
        )

        pattern = f"{SUPERVISOR_ERRORS_KEY_PREFIX}*"
        keys = cast(List[str], r.keys(pattern))

        errors = []
        for key in keys:
            try:
                task_id = int(key[len(SUPERVISOR_ERRORS_KEY_PREFIX):])
            except (ValueError, IndexError):
                continue

            raw_list = cast(List[str], r.lrange(key, 0, -1))
            for raw in raw_list:
                try:
                    entry = json.loads(raw)
                    entry["task_id"] = task_id
                    errors.append(entry)
                except Exception:
                    logger.warning(f"Skipping malformed supervisor error entry for key {key}: {raw[:120]}")

        r.close()

        # Sort by timestamp, then assign sequential id
        errors.sort(key=lambda e: e.get("timestamp", ""))
        for i, entry in enumerate(errors, start=1):
            entry["id"] = i

        return {"success": True, "data": errors}
    except Exception as e:
        logger.error(f"Error reading all supervisor errors: {e}", exc_info=True)
        return {"success": False, "error_message": f"Failed to get supervisor errors: {str(e)}"}


@router.delete("/supervisor-errors", response_model=Dict[str, Any])
async def clear_all_supervisor_errors():
    """
    Delete all persisted supervisor errors for all trading tasks.

    Scans all Redis keys matching trading_tasks:supervisor_errors:* and deletes them.

    Returns:
        Dictionary with success flag and deleted keys count
    """
    try:
        redis_params_dict = trading_task_list.get_redis_params()
        r = redis.Redis(
            host=redis_params_dict["host"],
            port=redis_params_dict["port"],
            db=redis_params_dict["db"],
            password=redis_params_dict.get("password"),
            decode_responses=True,
            socket_connect_timeout=5,
        )

        pattern = f"{SUPERVISOR_ERRORS_KEY_PREFIX}*"
        keys = cast(List[str], r.keys(pattern))
        deleted_count = r.delete(*keys) if keys else 0
        r.close()

        logger.info(f"Cleared all supervisor errors: deleted {deleted_count} Redis keys")
        return {"success": True, "deleted_count": deleted_count}
    except Exception as e:
        logger.error(f"Error clearing all supervisor errors: {e}", exc_info=True)
        return {"success": False, "error_message": f"Failed to clear supervisor errors: {str(e)}"}


@router.get("/tasks/{task_id}/supervisor-errors", response_model=Dict[str, Any])
async def get_supervisor_errors(task_id: int):
    """
    Get supervisor-level errors for a trading task.

    These are errors written by the supervisor process (crash detection,
    force kill, instance protection) — not by the trading strategy itself.

    Stored as a JSON list at trading_tasks:supervisor_errors:{task_id}.
    Sequential id is added on the fly (1-based).

    Args:
        task_id: Trading task ID

    Returns:
        Dictionary with success flag and data (list of error objects with id)
    """
    task = trading_task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Trading task {task_id} not found")

    key = SUPERVISOR_ERRORS_KEY.format(task_id=task_id)
    try:
        redis_params_dict = trading_task_list.get_redis_params()
        r = redis.Redis(
            host=redis_params_dict["host"],
            port=redis_params_dict["port"],
            db=redis_params_dict["db"],
            password=redis_params_dict.get("password"),
            decode_responses=True,
            socket_connect_timeout=5,
        )
        raw_list = cast(List[str], r.lrange(key, 0, -1))
        r.close()

        errors = []
        for i, raw in enumerate(raw_list, start=1):
            try:
                entry = json.loads(raw)
                entry["id"] = i
                errors.append(entry)
            except Exception:
                logger.warning(f"Skipping malformed supervisor error entry for task {task_id}: {raw[:120]}")

        return {"success": True, "data": errors}
    except Exception as e:
        logger.error(f"Error reading supervisor errors for task {task_id}: {e}", exc_info=True)
        return {"success": False, "error_message": f"Failed to get supervisor errors: {str(e)}"}


@router.get("/tasks/{task_id}/results/{result_id}/errors", response_model=Dict[str, Any])
async def get_trading_errors(
    task_id: int,
    result_id: str,
    min_id: int = Query(0, description="Minimum error id (0 = all errors)"),
    deal_id: Optional[int] = Query(None, description="Filter by deal id"),
):
    """
    Get errors from the error registry for a live trading run.

    Args:
        task_id: Trading task ID
        result_id: Result ID (UUID) associated with this trading run
        min_id: Minimum error id to load (0 = all, use last known id for incremental)
        deal_id: Optional deal id to filter errors by

    Returns:
        Dictionary with success flag and data (list of error objects)
    """
    task = trading_task_list.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Trading task {task_id} not found")

    try:
        results = TaskResults(task, broker=None)
        errors = results.get_errors(result_id, min_id=min_id, deal_id=deal_id)
        return {"success": True, "data": errors}
    except Exception as e:
        logger.error(
            f"Error getting trading errors for task {task_id}, result_id {result_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "error_message": f"Failed to get errors: {str(e)}",
        }


@router.websocket("/tasks/{task_id}/messages")
async def trading_task_messages_websocket(websocket: WebSocket, task_id: int):
    """
    WebSocket endpoint for streaming live trading task messages to frontend.

    Subscribes to Redis pub/sub channel: trading_tasks:messages:{task_id}
    and forwards messages to the frontend.

    Args:
        websocket: WebSocket connection
        task_id: Trading task ID
    """
    await websocket.accept()

    redis_params_dict = trading_task_list.get_redis_params()

    redis_client = None
    pubsub = None

    try:
        redis_client = redis_async.Redis(
            host=redis_params_dict["host"],
            port=redis_params_dict["port"],
            db=redis_params_dict["db"],
            password=redis_params_dict.get("password"),
            decode_responses=True,
        )

        channel = f"trading_tasks:messages:{task_id}"
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)

        logger.info(f"Subscribed to trading messages channel {channel} for task {task_id}")

        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0
                )

                if message is not None:
                    try:
                        message_data = json.loads(message["data"])
                        await websocket.send_json(message_data)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Received non-JSON message from channel {channel}: {message['data']}"
                        )
                    except (WebSocketDisconnect, ConnectionError) as e:
                        logger.debug(f"WebSocket disconnected while sending for task {task_id}: {e}")
                        break
                    except Exception as e:
                        error_str = str(e).lower()
                        if any(code in error_str for code in ("1001", "1005", "1012", "going away", "no status received", "service restart")):
                            logger.debug(f"WebSocket closed for task {task_id}: {e}")
                            break
                        logger.error(f"Error processing message from channel {channel}: {e}")

            except asyncio.CancelledError:
                logger.debug(f"WebSocket cancelled for trading task {task_id}")
                break
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in trading messages stream for task {task_id}: {e}", exc_info=True)
                try:
                    await websocket.send_json({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "level": "error",
                        "message": f"Error in messages stream: {str(e)}",
                    })
                except Exception:
                    pass
                break

    except asyncio.CancelledError:
        logger.debug(f"WebSocket cancelled for trading task {task_id}")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Error setting up trading messages stream for task {task_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "error",
                "message": f"Error setting up messages stream: {str(e)}",
            })
        except Exception:
            pass
    finally:
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception as e:
                logger.warning(f"Error closing pubsub for trading task {task_id}: {e}")

        if redis_client:
            try:
                await redis_client.close()
            except Exception as e:
                logger.warning(f"Error closing Redis client for trading task {task_id}: {e}")

        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/supervisor/messages")
async def supervisor_messages_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for streaming global supervisor messages to frontend.

    Subscribes to Redis pub/sub channel: supervisor:messages
    and forwards all supervisor events to the frontend.
    This channel receives messages from all trading tasks combined.

    Message format: {timestamp, level, category, message, task_id}
    """
    await websocket.accept()

    redis_params_dict = trading_task_list.get_redis_params()

    redis_client = None
    pubsub = None

    try:
        redis_client = redis_async.Redis(
            host=redis_params_dict["host"],
            port=redis_params_dict["port"],
            db=redis_params_dict["db"],
            password=redis_params_dict.get("password"),
            decode_responses=True,
        )

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(SUPERVISOR_GLOBAL_CHANNEL)

        logger.info(f"Subscribed to global supervisor channel {SUPERVISOR_GLOBAL_CHANNEL}")

        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0
                )

                if message is not None:
                    try:
                        message_data = json.loads(message["data"])
                        await websocket.send_json(message_data)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Received non-JSON message from supervisor channel: {message['data']}"
                        )
                    except (WebSocketDisconnect, ConnectionError) as e:
                        logger.debug(f"Supervisor WebSocket disconnected: {e}")
                        break
                    except Exception as e:
                        error_str = str(e).lower()
                        if any(code in error_str for code in ("1001", "1005", "1012", "going away", "no status received", "service restart")):
                            logger.debug(f"Supervisor WebSocket closed: {e}")
                            break
                        logger.error(f"Error processing supervisor message: {e}")

            except asyncio.CancelledError:
                logger.debug("Supervisor WebSocket cancelled")
                break
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in supervisor messages stream: {e}", exc_info=True)
                break

    except asyncio.CancelledError:
        logger.debug("Supervisor WebSocket cancelled")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Error setting up supervisor messages stream: {e}", exc_info=True)
    finally:
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception as e:
                logger.warning(f"Error closing pubsub for supervisor channel: {e}")

        if redis_client:
            try:
                await redis_client.close()
            except Exception as e:
                logger.warning(f"Error closing Redis client for supervisor channel: {e}")

        try:
            await websocket.close()
        except Exception:
            pass
