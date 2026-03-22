"""
Startup procedures for the application.
This module contains initialization logic that runs when the backend starts.
"""

from app.core.logger import setup_logging, get_logger
from app.services.tasks.tasks import TaskList, BacktestingTaskList, TradingTaskList
from app.core.config import (
    REDIS_QUOTE_REQUEST_LIST, REDIS_QUOTE_RESPONSE_PREFIX,
    redis_params
)
from app.services.quotes.client import QuotesClient

logger = get_logger(__name__)


def check_redis_connection():
    """
    Check if Redis server is available and responding.
    
    Raises:
        RuntimeError: If Redis is not available or not responding
    """
    try:
        import redis
        params = redis_params()
        test_client = redis.Redis(
            host=params['host'],
            port=params['port'],
            db=params['db'],
            password=params.get('password'),
            socket_connect_timeout=5
        )
        test_client.ping()
        logger.info(f"Redis connection verified at {params['host']}:{params['port']} (db={params['db']})")
    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis at {params['host']}:{params['port']}: {e}")
        raise RuntimeError(f"Redis server is not available at {params['host']}:{params['port']}. "
                          f"Please ensure Redis is running and accessible.")
    except Exception as e:
        logger.error(f"Error checking Redis connection: {e}")
        raise RuntimeError(f"Failed to verify Redis connection: {e}")


def startup():
    """
    Initialize application on startup.
    This function is called when FastAPI application starts.
    Execution blocks until this function completes - no requests are processed until it finishes.
    """
    # Setup logging first
    setup_logging()
    logger.info("Starting R2D2 backend application")
    
    # Check Redis connection
    check_redis_connection()
    
    # Initialize TaskList (connects to Redis)
    params = redis_params()
    task_list = TaskList(redis_params=params)
    task_list.startup()
    
    # Initialize BacktestingTaskList (connects to Redis)
    backtesting_task_list = BacktestingTaskList(redis_params=params)
    backtesting_task_list.startup()
    
    # Initialize TradingTaskList (connects to Redis)
    trading_task_list = TradingTaskList(redis_params=params)
    trading_task_list.startup()
    
    # Initialize quotes client with configuration
    QuotesClient(
        redis_params=params,
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX
    )
    logger.info("Quotes client initialized")


def shutdown():
    """
    Cleanup procedures on application shutdown.
    This function is called when FastAPI application shuts down.
    Uses shorter timeout for quotes service to allow faster reload.
    """
    logger.info("Shutting down R2D2 backend application")
    
    # Shutdown TaskList
    task_list = TaskList()
    task_list.shutdown()
    
    # Shutdown BacktestingTaskList
    backtesting_task_list = BacktestingTaskList()
    backtesting_task_list.shutdown()
    
    # Shutdown TradingTaskList
    trading_task_list = TradingTaskList()
    trading_task_list.shutdown()
    
    logger.info("Shutdown complete")

