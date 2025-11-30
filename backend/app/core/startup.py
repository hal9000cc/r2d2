"""
Startup procedures for the application.
This module contains initialization logic that runs when the backend starts.
"""

from app.core.logger import setup_logging, get_logger
from app.core.active_strategies import startup as startup_active_strategies, shutdown as shutdown_active_strategies
from app.core.config import (
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
    REDIS_QUOTE_REQUEST_LIST, REDIS_QUOTE_RESPONSE_PREFIX,
    CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USERNAME,
    CLICKHOUSE_PASSWORD, CLICKHOUSE_DATABASE
)
from app.services.quotes.server import start_quotes_service, stop_quotes_service

logger = get_logger(__name__)


def startup_quote_service():
    """
    Start quotes service with configuration from environment.
    """
    redis_params = {
        'host': REDIS_HOST,
        'port': REDIS_PORT,
        'db': REDIS_DB,
        'password': REDIS_PASSWORD
    }
    clickhouse_params = {
        'host': CLICKHOUSE_HOST,
        'port': CLICKHOUSE_PORT,
        'username': CLICKHOUSE_USERNAME,
        'password': CLICKHOUSE_PASSWORD,
        'database': CLICKHOUSE_DATABASE
    }
    if start_quotes_service(
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX,
        redis_params=redis_params,
        clickhouse_params=clickhouse_params
    ):
        logger.info("Quotes service started successfully")
    else:
        logger.warning("Quotes service failed to start or was already running")


def startup():
    """
    Initialize application on startup.
    This function is called when FastAPI application starts.
    Execution blocks until this function completes - no requests are processed until it finishes.
    """
    # Setup logging first
    setup_logging()
    logger.info("Starting R2D2 backend application")
    
    # Initialize active strategies storage (load from file, put in Redis, init counter)
    startup_active_strategies()
    
    # Start quotes service
    startup_quote_service()


def shutdown():
    """
    Cleanup procedures on application shutdown.
    This function is called when FastAPI application shuts down.
    """
    logger.info("Shutting down R2D2 backend application")
    
    # Stop quotes service
    if stop_quotes_service():
        logger.info("Quotes service stopped successfully")
    else:
        logger.warning("Quotes service was not running or failed to stop")
    
    shutdown_active_strategies()
    logger.info("Shutdown complete")

