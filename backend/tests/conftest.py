"""
Pytest configuration and shared fixtures.

- Controls test ordering (test_quotes.py first).
- Provides quotes_service fixture for tests requiring quotes server with test database.
- Provides quotes_service_production fixture for performance tests with production database.
"""
import os
import time
import logging
import subprocess
from pathlib import Path
from typing import Dict, Tuple, Optional

import clickhouse_connect
import pytest
from dotenv import load_dotenv

from app.core.config import (
    REDIS_QUOTE_REQUEST_LIST,
    REDIS_QUOTE_RESPONSE_PREFIX,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PORT,
    CLICKHOUSE_USERNAME,
    CLICKHOUSE_PASSWORD,
    redis_params as get_redis_params,
    STATE_DIR,
    DEFAULT_REDIS_PORT,
)
from app.core.logger import setup_logging
from app.core.startup import startup_redis, shutdown_redis
from app.services.quotes.client import Client
from app.services.quotes.server import start_quotes_service, stop_quotes_service, QuotesServer


def pytest_collection_modifyitems(config, items):
    """
    Automatically set order for tests based on file name.
    Tests from test_quotes.py get order=1, all others get order=2, 
    test_quotes_performance.py gets order=3.
    This ensures test_quotes.py runs first, then all other tests, then performance tests.
    Works with both sequential and parallel test execution (pytest-xdist).
    """
    for item in items:
        # Get the file path - try different attributes for compatibility
        file_path = str(getattr(item, "fspath", None) or getattr(item, "path", None) or "")

        # Check if it's test_quotes.py
        if "test_quotes" in file_path and "performance" not in file_path:
            # Add order=1 marker if not already present
            if not any(mark.name == "order" for mark in item.iter_markers()):
                item.add_marker(pytest.mark.order(1))
        elif "test_quotes_performance" in file_path:
            # Add order=3 marker if not already present
            if not any(mark.name == "order" for mark in item.iter_markers()):
                item.add_marker(pytest.mark.order(3))
        else:
            # Add order=2 marker if not already present
            if not any(mark.name == "order" for mark in item.iter_markers()):
                item.add_marker(pytest.mark.order(2))


def load_test_env():
    """Load environment variables for tests from backend/.env (if present)."""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    # Always set REDIS_DB to 1 for tests, overriding any value from .env
    os.environ["REDIS_DB"] = "1"
    # Use defaults if .env doesn't exist
    os.environ.setdefault("REDIS_HOST", "localhost")
    os.environ.setdefault("REDIS_PORT", "6379")
    os.environ.setdefault("REDIS_PASSWORD", "")
    os.environ.setdefault("CLICKHOUSE_HOST", "localhost")
    os.environ.setdefault("CLICKHOUSE_PORT", "8123")
    os.environ.setdefault("CLICKHOUSE_USERNAME", "default")
    os.environ.setdefault("CLICKHOUSE_PASSWORD", "")
    os.environ.setdefault("CLICKHOUSE_DATABASE", "quotes_test")


def load_production_env():
    """Load environment variables for production tests from ~/.config/r2d2/.env."""
    from app.core.config import ENV_FILE
    if not ENV_FILE.exists():
        raise RuntimeError(f"Production environment file not found: {ENV_FILE}. Please create it at ~/.config/r2d2/.env")
    load_dotenv(ENV_FILE, override=True)


def _stop_redis_manual(redis_process: subprocess.Popen):
    """Stop Redis process manually."""
    logger = logging.getLogger(__name__)
    try:
        redis_process.terminate()
        redis_process.wait(timeout=5)
        logger.info("Redis stopped")
    except subprocess.TimeoutExpired:
        redis_process.kill()
        redis_process.wait()
        logger.info("Redis force stopped")
    except Exception as e:
        logger.warning(f"Error stopping Redis: {e}")


def _setup_quotes_service(
    redis_params_dict: Dict,
    clickhouse_params: Dict,
    drop_database: bool = False,
    use_startup_redis: bool = True,
    log_level: int = logging.DEBUG
) -> Tuple[bool, Optional[subprocess.Popen]]:
    """
    Common function to setup quotes service with given parameters.
    
    Args:
        redis_params_dict: Redis connection parameters
        clickhouse_params: ClickHouse connection parameters
        drop_database: Whether to drop database before starting
        use_startup_redis: If True, use startup_redis() function, else start manually
        log_level: Logging level
    
    Returns:
        Tuple (redis_started, redis_process) where:
        - redis_started: True if we started Redis (always True)
        - redis_process: Popen object if we started Redis manually, None if using startup_redis with atexit
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)
    
    # Drop database if requested
    if drop_database:
        try:
            client = clickhouse_connect.get_client(
                host=clickhouse_params["host"],
                port=clickhouse_params["port"],
                username=clickhouse_params["username"],
                password=clickhouse_params["password"],
            )
            client.command(f"DROP DATABASE IF EXISTS {clickhouse_params['database']}")
        except Exception:
            pass  # Ignore errors if database doesn't exist
    
    # Start Redis using startup_redis() with given parameters
    try:
        redis_process = startup_redis(
            redis_host=redis_params_dict["host"],
            redis_port=redis_params_dict["port"],
            redis_db=redis_params_dict["db"],
            register_atexit=use_startup_redis  # Only register atexit if using startup_redis mode
        )
        redis_started = True
        logger.info(f"Redis started on {redis_params_dict['host']}:{redis_params_dict['port']}")
    except RuntimeError as e:
        pytest.skip(f"Could not start Redis server: {e}")
    
    # Reset QuotesServer singleton if needed
    QuotesServer._instance = None
    QuotesServer._initialized = False
    
    # Start quotes service
    service_started = start_quotes_service(
        redis_params=redis_params_dict,
        clickhouse_params=clickhouse_params,
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX,
    )
    
    if not service_started:
        if redis_started:
            if redis_process:
                redis_process.terminate()
                redis_process.wait(timeout=2)
            else:
                shutdown_redis()
        pytest.skip("Could not start quotes service")
    
    # Initialize quotes client
    Client(
        redis_params=redis_params_dict,
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX,
    )
    
    time.sleep(0.1)
    
    return redis_started, redis_process


def _teardown_quotes_service(redis_started: bool, redis_process: Optional[subprocess.Popen], use_startup_redis: bool = True):
    """Common function to teardown quotes service."""
    logger = logging.getLogger(__name__)
    
    stop_quotes_service(timeout=5.0)
    
    if redis_started:
        if use_startup_redis:
            shutdown_redis()
        elif redis_process:
            _stop_redis_manual(redis_process)
    
    QuotesServer._instance = None
    QuotesServer._initialized = False


@pytest.fixture
def redis_params():
    """
    Redis connection parameters for testing.
    
    Uses configuration from app.core.config, which reads from environment variables
    set by load_test_env(). This ensures all tests use the same Redis connection.
    """
    return get_redis_params()


@pytest.fixture(scope="session")
def quotes_service():
    """Fixture for tests that need quotes service with test database."""
    load_test_env()
    
    redis_params_dict = get_redis_params()
    clickhouse_params = {
        "host": CLICKHOUSE_HOST,
        "port": CLICKHOUSE_PORT,
        "username": CLICKHOUSE_USERNAME,
        "password": CLICKHOUSE_PASSWORD,
        "database": "quotes_test",
    }
    
    redis_started, redis_process = _setup_quotes_service(
        redis_params_dict=redis_params_dict,
        clickhouse_params=clickhouse_params,
        drop_database=True,
        use_startup_redis=True,
        log_level=logging.DEBUG
    )
    
    yield
    
    _teardown_quotes_service(redis_started, redis_process, use_startup_redis=True)


@pytest.fixture(scope="session")
def quotes_service_production():
    """Fixture for performance tests that need quotes service with production database."""
    import sys
    
    try:
        load_production_env()
        print("INFO: Production environment loaded successfully", file=sys.stderr)
    except RuntimeError as e:
        print(f"ERROR: Failed to load production environment: {e}", file=sys.stderr)
        pytest.skip(f"Failed to load production environment: {e}")
    
    redis_params_dict = {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", str(DEFAULT_REDIS_PORT))),
        "db": int(os.getenv("REDIS_DB", "1")),
        "password": os.getenv("REDIS_PASSWORD") or None,
    }
    clickhouse_params = {
        "host": os.getenv("CLICKHOUSE_HOST", "localhost"),
        "port": int(os.getenv("CLICKHOUSE_PORT", "8123")),
        "username": os.getenv("CLICKHOUSE_USERNAME", "default"),
        "password": os.getenv("CLICKHOUSE_PASSWORD", ""),
        "database": os.getenv("CLICKHOUSE_DATABASE", "quotes"),
    }
    
    redis_started, redis_process = _setup_quotes_service(
        redis_params_dict=redis_params_dict,
        clickhouse_params=clickhouse_params,
        drop_database=False,
        use_startup_redis=False,  # Use manual start to use production port
        log_level=logging.INFO
    )
    
    yield
    
    _teardown_quotes_service(redis_started, redis_process, use_startup_redis=False)
