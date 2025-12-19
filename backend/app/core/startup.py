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
from typing import Optional
import psutil

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


def startup_redis(redis_host: Optional[str] = None, redis_port: Optional[int] = None, redis_db: Optional[int] = None, register_atexit: bool = True) -> subprocess.Popen:
    """
    Start Redis server with data directory in STATE_DIR.
    
    Args:
        redis_host: Redis host (default: from config)
        redis_port: Redis port (default: from config)
        redis_db: Redis database number (default: from config)
        register_atexit: If True, register atexit handler (default: True)
    
    Returns:
        subprocess.Popen: Redis process object
    
    Raises:
        RuntimeError: If Redis fails to start
    """
    global _redis_process
    
    # Use provided parameters or fall back to config
    host = redis_host if redis_host is not None else REDIS_HOST
    port = redis_port if redis_port is not None else REDIS_PORT
    db = redis_db if redis_db is not None else REDIS_DB
    
    # Check if redis-server is available
    redis_server_path = shutil.which('redis-server')
    if not redis_server_path:
        logger.error("redis-server not found in PATH. Please install Redis.")
        raise RuntimeError("redis-server not found")
    
    # Check if Redis is already running on the port
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((host, port))
        sock.close()
    except Exception as e:
        logger.debug(f"Could not check Redis port: {e}")
        result = -1

    if result == 0:
        raise RuntimeError(f"Port {host}:{port} is already in use")
    
    # Prepare Redis data directory (use STATE_DIR directly)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Prepare Redis command line arguments
    redis_bind = host if host != 'localhost' else '127.0.0.1'
    redis_pidfile = STATE_DIR / 'redis.pid'
    
    # Build Redis command with arguments
    redis_args = [
        redis_server_path,
        '--port', str(port),
        '--dir', str(STATE_DIR),
        '--bind', redis_bind,
        '--daemonize', 'no',
        '--pidfile', str(redis_pidfile),
        '--appendonly', 'yes'
    ]
    
    try:
        # Start Redis server
        logger.info(f"Starting Redis server on {host}:{port} with data dir: {STATE_DIR}")
        redis_process = subprocess.Popen(
            redis_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
            # Note: NOT using preexec_fn=os.setsid
            # This allows Redis to be child process that will be terminated with parent
        )
        
        # Store in global variable if register_atexit is True (for backward compatibility)
        if register_atexit:
            _redis_process = redis_process
            # Register cleanup to ensure Redis is stopped on exit
            atexit.register(shutdown_redis)
        
        # Wait a bit and check if process is still running
        time.sleep(1.0)  # Give Redis more time to start
        
        # Check if process is still running
        if redis_process.poll() is not None:
            # Process exited, try to get error message
            error_msg = ""
            returncode = redis_process.returncode
            
            # Try to read from stderr (may be empty if process exited quickly)
            try:
                # Use a thread to read stderr with timeout
                stderr_data = []
                
                def read_stderr():
                    try:
                        if redis_process.stderr:
                            data = redis_process.stderr.read()
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
            test_client = redis.Redis(host=host, port=port, db=db, socket_connect_timeout=2)
            test_client.ping()
            logger.info("Redis server started successfully and is responding")
        except Exception as e:
            # If process is still running but not responding, kill it
            if redis_process.poll() is None:
                logger.warning(f"Redis process is running but not responding: {e}")
                try:
                    redis_process.terminate()
                    redis_process.wait(timeout=2)
                except Exception:
                    pass
            raise RuntimeError(f"Redis server started but is not responding: {e}")
        
        return redis_process
        
    except Exception as e:
        logger.error(f"Failed to start Redis server: {e}")
        raise


def _find_redis_by_pidfile() -> Optional[int]:
    """
    Find Redis process by PID file.
    
    Returns:
        int: Process ID if found, None otherwise
    """
    redis_pidfile = STATE_DIR / 'redis.pid'
    if redis_pidfile.exists():
        try:
            with open(redis_pidfile, 'r') as f:
                pid = int(f.read().strip())
            # Check if process exists and is actually redis-server
            try:
                proc = psutil.Process(pid)
                if 'redis-server' in proc.name().lower() or 'redis-server' in ' '.join(proc.cmdline()):
                    return pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        except (ValueError, IOError):
            pass
    return None


def _find_redis_by_port(host: str, port: int) -> Optional[int]:
    """
    Find Redis process listening on specified host:port.
    
    Returns:
        int: Process ID if found, None otherwise
    """
    try:
        for proc in psutil.process_iter(['pid', 'name', 'connections']):
            try:
                # Check if it's a redis-server process
                proc_name = proc.info['name'] or ''
                if 'redis-server' not in proc_name.lower():
                    continue
                
                # Check connections
                connections = proc.info.get('connections')
                if connections:
                    for conn in connections:
                        if conn.status == psutil.CONN_LISTEN:
                            if conn.laddr.ip == host or conn.laddr.ip == '0.0.0.0' or (host == 'localhost' and conn.laddr.ip == '127.0.0.1'):
                                if conn.laddr.port == port:
                                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        logger.debug(f"Error finding Redis by port: {e}")
    return None


def _kill_redis_process(pid: int, force: bool = False) -> bool:
    """
    Kill Redis process by PID.
    
    Args:
        pid: Process ID
        force: If True, use SIGKILL instead of SIGTERM
        
    Returns:
        bool: True if process was killed successfully
    """
    try:
        proc = psutil.Process(pid)
        if force:
            proc.kill()
            logger.info(f"Force killed Redis process {pid}")
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
                logger.info(f"Terminated Redis process {pid}")
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait()
                logger.info(f"Force killed Redis process {pid} after timeout")
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        logger.debug(f"Could not kill process {pid}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error killing Redis process {pid}: {e}")
        return False


def force_stop_redis(host: str = None, port: int = None) -> bool:
    """
    Force stop Redis server by finding it via PID file or port.
    This function can stop Redis even if it wasn't started by this application.
    
    Args:
        host: Redis host (default: from config)
        port: Redis port (default: from config)
        
    Returns:
        bool: True if Redis was stopped, False otherwise
    """
    if host is None:
        host = REDIS_HOST if REDIS_HOST != 'localhost' else '127.0.0.1'
    if port is None:
        port = REDIS_PORT
    
    logger.info(f"Attempting to force stop Redis on {host}:{port}")
    
    # Try to find by PID file first
    pid = _find_redis_by_pidfile()
    if pid:
        logger.info(f"Found Redis process {pid} from PID file")
        if _kill_redis_process(pid):
            return True
    
    # Try to find by port
    pid = _find_redis_by_port(host, port)
    if pid:
        logger.info(f"Found Redis process {pid} listening on {host}:{port}")
        if _kill_redis_process(pid):
            return True
    
    logger.warning(f"Could not find Redis process on {host}:{port}")
    return False


def shutdown_redis(force: bool = False):
    """
    Stop Redis server.
    
    Args:
        force: If True, also try to find and stop Redis by PID file or port
    """
    global _redis_process
    
    stopped = False
    
    # First, try to stop via stored process handle
    if _redis_process is not None:
        try:
            # Try graceful shutdown
            if _redis_process.poll() is None:  # Process is still running
                logger.info("Stopping Redis server via process handle...")
                # Send SIGTERM
                _redis_process.terminate()
                
                # Wait for process to terminate (max 5 seconds)
                try:
                    _redis_process.wait(timeout=5)
                    logger.info("Redis server stopped successfully")
                    stopped = True
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't stop
                    logger.warning("Redis server did not stop gracefully, forcing shutdown...")
                    _redis_process.kill()
                    _redis_process.wait()
                    logger.info("Redis server force stopped")
                    stopped = True
        except Exception as e:
            logger.error(f"Error stopping Redis server via process handle: {e}")
        finally:
            _redis_process = None
    
    # If force is True or we couldn't stop via process handle, try other methods
    if force or not stopped:
        if force_stop_redis():
            stopped = True
    
    if not stopped:
        logger.debug("Redis process not found or already stopped")


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
    
    # Stop Redis server (force stop if needed)
    shutdown_redis(force=True)
    
    logger.info("Shutdown complete")

