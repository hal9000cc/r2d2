"""
Pytest configuration and shared fixtures.

- Controls test ordering (test_quotes.py first).
- Provides quotes_service fixture for tests requiring quotes server with test database.
- Provides quotes_service_production fixture for performance tests with production database.
"""
import os
import time
import logging
from pathlib import Path
from typing import Dict

import clickhouse_connect
import pytest
import redis
from dotenv import load_dotenv

from app.core.config import (
    REDIS_QUOTE_REQUEST_LIST,
    REDIS_QUOTE_RESPONSE_PREFIX,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PORT,
    CLICKHOUSE_USERNAME,
    CLICKHOUSE_PASSWORD,
    redis_params as get_redis_params,
    DEFAULT_REDIS_PORT,
)
from app.core.logger import setup_logging
from app.services.quotes.client import QuotesClient
from app.services.quotes.server import start_quotes_service, stop_quotes_service, QuotesServer


def pytest_collection_modifyitems(config, items):
    """
    Automatically set order for tests based on file name.
    Tests from test_quotes.py get order=1, all others get order=2, 
    test_quotes_performance.py and test_get_quotes.py get order=3.
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
        elif "test_quotes_performance" in file_path or "test_get_quotes" in file_path:
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
    # Always set REDIS_DB to 3 for tests, overriding any value from .env
    os.environ["REDIS_DB"] = "3"
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


def _check_redis_connection(redis_params_dict: Dict):
    """
    Check if Redis is available and responding.
    
    Args:
        redis_params_dict: Redis connection parameters
        
    Raises:
        pytest.skip: If Redis is not available
    """
    try:
        test_client = redis.Redis(
            host=redis_params_dict["host"],
            port=redis_params_dict["port"],
            db=redis_params_dict["db"],
            password=redis_params_dict.get("password"),
            socket_connect_timeout=5
        )
        test_client.ping()
    except Exception as e:
        pytest.skip(f"Redis is not available at {redis_params_dict['host']}:{redis_params_dict['port']} (db={redis_params_dict['db']}): {e}")


def _setup_quotes_service(
    redis_params_dict: Dict,
    clickhouse_params: Dict,
    drop_database: bool = False,
    log_level: int = logging.DEBUG
):
    """
    Common function to setup quotes service with given parameters.
    
    Args:
        redis_params_dict: Redis connection parameters
        clickhouse_params: ClickHouse connection parameters
        drop_database: Whether to drop database before starting
        log_level: Logging level
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)
    
    # Check Redis connection
    _check_redis_connection(redis_params_dict)
    logger.info(f"Redis connection verified at {redis_params_dict['host']}:{redis_params_dict['port']} (db={redis_params_dict['db']})")
    
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
        pytest.skip("Could not start quotes service")
    
    # Initialize quotes client
    QuotesClient(
        redis_params=redis_params_dict,
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX,
    )
    
    time.sleep(0.1)


def _teardown_quotes_service():
    """Common function to teardown quotes service."""
    stop_quotes_service(timeout=5.0)
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
    
    _setup_quotes_service(
        redis_params_dict=redis_params_dict,
        clickhouse_params=clickhouse_params,
        drop_database=True,
        log_level=logging.DEBUG
    )
    
    yield
    
    _teardown_quotes_service()


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
        "db": int(os.getenv("REDIS_DB", "0")),
        "password": os.getenv("REDIS_PASSWORD") or None,
    }
    clickhouse_params = {
        "host": os.getenv("CLICKHOUSE_HOST", "localhost"),
        "port": int(os.getenv("CLICKHOUSE_PORT", "8123")),
        "username": os.getenv("CLICKHOUSE_USERNAME", "default"),
        "password": os.getenv("CLICKHOUSE_PASSWORD", ""),
        "database": os.getenv("CLICKHOUSE_DATABASE", "quotes"),
    }
    
    # Stop any existing quotes service before starting production one
    _teardown_quotes_service()
    
    _setup_quotes_service(
        redis_params_dict=redis_params_dict,
        clickhouse_params=clickhouse_params,
        drop_database=False,
        log_level=logging.INFO
    )
    
    yield
    
    _teardown_quotes_service()
