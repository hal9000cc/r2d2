"""
Startup procedures for the application.
This module contains initialization logic that runs when the backend starts.
"""

from app.core.logger import setup_logging, get_logger
from app.core.active_strategy import startup as startup_active_strategies, shutdown as shutdown_active_strategies

logger = get_logger(__name__)


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


def shutdown():
    """
    Cleanup procedures on application shutdown.
    This function is called when FastAPI application shuts down.
    """
    logger.info("Shutting down R2D2 backend application")
    shutdown_active_strategies()
    logger.info("Shutdown complete")

