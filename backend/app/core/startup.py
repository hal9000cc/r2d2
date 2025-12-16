"""
Startup procedures for the application.
This module contains initialization logic that runs when the backend starts.
"""

import subprocess
import shutil
import time
import threading
import signal
import os
import socket
import atexit

from app.core.logger import setup_logging, get_logger
from app.services.tasks.tasks import TaskList, BacktestingTaskList
from app.core.config import (
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
    REDIS_QUOTE_REQUEST_LIST, REDIS_QUOTE_RESPONSE_PREFIX,
    CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USERNAME,
    CLICKHOUSE_PASSWORD, CLICKHOUSE_DATABASE,
    STATE_DIR, redis_params
)
from app.services.quotes.server import start_quotes_service, stop_quotes_service
from app.services.quotes.client import Client

logger = get_logger(__name__)

# Global variable to store Redis process
_redis_process = None


def startup_redis():
    """
    Start Redis server with data directory in STATE_DIR.
    """
    global _redis_process
    
    # Check if redis-server is available
    redis_server_path = shutil.which('redis-server')
    if not redis_server_path:
        logger.error("redis-server not found in PATH. Please install Redis.")
        raise RuntimeError("redis-server not found")
    
    # Check if Redis is already running on the port
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((REDIS_HOST, REDIS_PORT))
        sock.close()
    except Exception as e:
        logger.debug(f"Could not check Redis port: {e}")

    if result == 0:
        raise RuntimeError(f"Port {REDIS_HOST}:{REDIS_PORT} is already in use")
    
    # Prepare Redis data directory (use STATE_DIR directly)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Prepare Redis command line arguments
    redis_bind = REDIS_HOST if REDIS_HOST != 'localhost' else '127.0.0.1'
    redis_pidfile = STATE_DIR / 'redis.pid'
    
    # Build Redis command with arguments
    redis_args = [
        redis_server_path,
        '--port', str(REDIS_PORT),
        '--dir', str(STATE_DIR),
        '--bind', redis_bind,
        '--daemonize', 'no',
        '--pidfile', str(redis_pidfile),
        '--appendonly', 'yes'
    ]
    
    try:
        # Start Redis server
        logger.info(f"Starting Redis server on {REDIS_HOST}:{REDIS_PORT} with data dir: {STATE_DIR}")
        _redis_process = subprocess.Popen(
            redis_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
            # Note: NOT using preexec_fn=os.setsid
            # This allows Redis to be child process that will be terminated with parent
        )
        
        # Register cleanup to ensure Redis is stopped on exit
        atexit.register(shutdown_redis)
        
        # Wait a bit and check if process is still running
        time.sleep(1.0)  # Give Redis more time to start
        
        # Check if process is still running
        if _redis_process.poll() is not None:
            # Process exited, try to get error message
            error_msg = ""
            returncode = _redis_process.returncode
            
            # Try to read from stderr (may be empty if process exited quickly)
            try:
                # Use a thread to read stderr with timeout
                stderr_data = []
                
                def read_stderr():
                    try:
                        if _redis_process.stderr:
                            data = _redis_process.stderr.read()
                            if data:
                                stderr_data.append(data)
                    except Exception:
                        pass
                
                stderr_thread = threading.Thread(target=read_stderr, daemon=True)
                stderr_thread.start()
                stderr_thread.join(timeout=0.1)  # Wait max 100ms
                
                if stderr_data:
                    error_msg = "".join(stderr_data).strip()
            except Exception:
                pass
            
            if not error_msg:
                error_msg = f"Process exited with code {returncode}"
            
            logger.error(f"Redis server failed to start: {error_msg}")
            raise RuntimeError(f"Redis server failed to start: {error_msg}")
        
        # Verify Redis is actually running by trying to connect
        try:
            import redis
            test_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, socket_connect_timeout=2)
            test_client.ping()
            logger.info("Redis server started successfully and is responding")
        except Exception as e:
            # If process is still running but not responding, kill it
            if _redis_process.poll() is None:
                logger.warning(f"Redis process is running but not responding: {e}")
                try:
                    _redis_process.terminate()
                    _redis_process.wait(timeout=2)
                except Exception:
                    pass
            raise RuntimeError(f"Redis server started but is not responding: {e}")
        
    except Exception as e:
        logger.error(f"Failed to start Redis server: {e}")
        raise


def shutdown_redis():
    """
    Stop Redis server.
    """
    global _redis_process
    
    if _redis_process is None:
        logger.debug("Redis process not found, may already be stopped")
        return
    
    try:
        # Try graceful shutdown
        if _redis_process.poll() is None:  # Process is still running
            logger.info("Stopping Redis server...")
            # Send SIGTERM
            _redis_process.terminate()
            
            # Wait for process to terminate (max 5 seconds)
            try:
                _redis_process.wait(timeout=5)
                logger.info("Redis server stopped successfully")
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't stop
                logger.warning("Redis server did not stop gracefully, forcing shutdown...")
                _redis_process.kill()
                _redis_process.wait()
                logger.info("Redis server force stopped")
        
        _redis_process = None
        
    except Exception as e:
        logger.error(f"Error stopping Redis server: {e}")


def startup_quote_service():
    """
    Start quotes service with configuration from environment.
    """
    clickhouse_params = {
        'host': CLICKHOUSE_HOST,
        'port': CLICKHOUSE_PORT,
        'username': CLICKHOUSE_USERNAME,
        'password': CLICKHOUSE_PASSWORD,
        'database': CLICKHOUSE_DATABASE
    }
    if start_quotes_service(
        redis_params=redis_params(),
        clickhouse_params=clickhouse_params,
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX
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
    
    # Start Redis server
    startup_redis()
    
    # Initialize TaskList (connects to Redis)
    params = redis_params()
    task_list = TaskList(redis_params=params)
    task_list.startup()
    
    # Initialize BacktestingTaskList (connects to Redis)
    backtesting_task_list = BacktestingTaskList(redis_params=params)
    backtesting_task_list.startup()
    
    # Initialize quotes client with configuration
    Client(
        redis_params=params,
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX
    )
    logger.info("Quotes client initialized")
    
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
    
    # Shutdown TaskList
    task_list = TaskList()
    task_list.shutdown()
    
    # Shutdown BacktestingTaskList
    backtesting_task_list = BacktestingTaskList()
    backtesting_task_list.shutdown()
    
    # Stop Redis server
    shutdown_redis()
    
    logger.info("Shutdown complete")

