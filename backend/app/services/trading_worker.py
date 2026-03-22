"""
Worker for live trading tasks.

Runs in a separate process launched by the supervisor.
Loads the strategy from task.strategy_snapshot, creates BrokerLive,
and runs the trading loop.
"""
import sys
import signal
import importlib.util
from pathlib import Path
from typing import Optional

from app.core.config import redis_params, STRATEGIES_DIR, reload_runtime_config
from app.core.logger import setup_logging, get_logger
from app.core.objects2redis import MessageType
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.services.tasks.tasks import TradingTaskList, Task
from app.services.tasks.strategy import Strategy
from app.services.tasks.broker_live import BrokerLive
from app.services.quotes.client import QuotesClient

logger = get_logger(__name__)

# Module-level singleton (initialized in worker process)
_trading_task_list: Optional[TradingTaskList] = None

TRADING_RESULT_ID = "0"


def _handle_sigterm(signum, frame) -> None:
    """Convert SIGTERM into graceful Python shutdown."""
    raise SystemExit(0)


def _get_task_list() -> TradingTaskList:
    global _trading_task_list
    if _trading_task_list is None:
        _trading_task_list = TradingTaskList()
    return _trading_task_list


def load_strategy_from_snapshot(snapshot_code: str) -> type:
    """
    Load strategy class from frozen source code stored in task.strategy_snapshot.

    Args:
        snapshot_code: Python source code of the strategy (from strategy_snapshot field)

    Returns:
        Strategy subclass

    Raises:
        ValueError: If strategy class not found or syntax error
        RuntimeError: If module loading fails
    """
    module_name = "trading_strategy_live"

    if module_name in sys.modules:
        del sys.modules[module_name]

    try:
        spec = importlib.util.spec_from_loader(module_name, loader=None)
        if spec is None:
            raise RuntimeError("Failed to create module spec for strategy snapshot")

        module = importlib.util.module_from_spec(spec)
        exec(snapshot_code, module.__dict__)
        sys.modules[module_name] = module
    except SyntaxError as e:
        msg = f"Syntax error in strategy snapshot: {e.msg}"
        if e.lineno:
            msg += f" at line {e.lineno}"
        raise ValueError(msg) from e
    except Exception as e:
        raise RuntimeError(f"Failed to load strategy from snapshot: {e}") from e

    strategy_class = None
    for attr_name in dir(module):
        try:
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Strategy) and attr is not Strategy:
                strategy_class = attr
                break
        except Exception:
            continue

    if strategy_class is None:
        raise ValueError(
            "Strategy class not found in snapshot: no class inheriting from Strategy"
        )

    return strategy_class


def process_trading_task(task: Task) -> None:
    """
    Core function that runs the trading loop for a task.

    Loads the strategy class from strategy_snapshot, creates BrokerLive,
    and calls broker.run(). Exceptions propagate to worker_trading_task.

    Args:
        task: TradingTask instance with strategy_snapshot set
    """
    if not task.strategy_snapshot:
        raise ValueError(f"Task {task.id} has no strategy_snapshot")

    strategy_class = load_strategy_from_snapshot(task.strategy_snapshot)

    try:
        strategy = strategy_class()
    except TypeError as e:
        if "__init__()" in str(e) and "positional arguments" in str(e):
            raise ValueError(
                f"Strategy {strategy_class.__name__} constructor must accept no parameters: def __init__(self)"
            ) from e
        raise

    # Set strategy file path to snapshot marker
    strategy.strategy_file = str(STRATEGIES_DIR / "snapshot")

    task_display_name = f"{task.name} (id={task.id})" if task.name else f"id={task.id}"

    task.message(f"Live trading task {task_display_name} starting", level="info")
    task.send_message(MessageType.EVENT, {"event": "trading_started", "result_id": TRADING_RESULT_ID})
    logger.info(f"Starting live trading for task {task.id}")

    callbacks = Strategy.create_strategy_callbacks(strategy)

    broker = BrokerLive(
        task=task,
        result_id=TRADING_RESULT_ID,
        callbacks_dict=callbacks,
        results_save_period=TRADE_RESULTS_SAVE_PERIOD,
    )
    strategy.broker = broker

    broker.run()

    task.message(f"Live trading task {task_display_name} completed", level="info")
    task.send_message(MessageType.EVENT, {"event": "trading_stopped", "result_id": TRADING_RESULT_ID})
    logger.info(f"Live trading task {task.id} completed normally")


def worker_trading_task(task_id: int) -> None:
    """
    Worker function for a live trading task. Runs in a separate process.

    Handles initialization, task loading, execution, and error reporting.
    Does NOT set isRunning=False — the supervisor manages task lifecycle.

    Args:
        task_id: ID of the trading task to run
    """
    setup_logging()
    signal.signal(signal.SIGTERM, _handle_sigterm)

    reload_runtime_config(exchange_settings_only=True)

    params = redis_params()
    TradingTaskList(redis_params=params)
    QuotesClient(redis_params=params)

    task_list = _get_task_list()
    task = task_list.load(task_id)

    if task is None:
        logger.error(f"Trading task {task_id} not found in worker process")
        return

    logger.info(f"Worker started for trading task {task_id}")

    try:
        process_trading_task(task)
    except Exception as e:
        is_strategy, strategy_msg = Strategy.is_strategy_error(e)
        if is_strategy:
            logger.error(f"Strategy error in trading task {task_id}: {strategy_msg}", exc_info=True)
            try:
                task.message(strategy_msg or "Strategy error", level="error")
            except Exception:
                pass
        else:
            logger.error(f"Error in trading task {task_id}: {e}", exc_info=True)
            try:
                task.message(f"Trading error: {e}", level="error")
            except Exception:
                pass
        try:
            task.send_message(MessageType.EVENT, {"event": "trading_stopped", "result_id": TRADING_RESULT_ID, "error": True})
        except Exception:
            pass
