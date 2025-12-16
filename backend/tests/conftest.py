"""
Pytest configuration and shared fixtures.

- Controls test ordering (test_quotes.py first).
- Provides shared quotes_service fixture for tests requiring quotes server.
"""
import os
import time
import logging
from pathlib import Path

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
)
from app.core.logger import setup_logging
from app.core.startup import startup_redis, shutdown_redis
from app.services.quotes.client import Client
from app.services.quotes.server import start_quotes_service, stop_quotes_service


def pytest_collection_modifyitems(config, items):
    """
    Automatically set order for tests based on file name.
    Tests from test_quotes.py get order=1, all others get order=2.
    This ensures test_quotes.py runs first, then all other tests.
    Works with both sequential and parallel test execution (pytest-xdist).
    """
    for item in items:
        # Get the file path - try different attributes for compatibility
        file_path = str(getattr(item, "fspath", None) or getattr(item, "path", None) or "")

        # Check if it's test_quotes.py
        if "test_quotes" in file_path:
            # Add order=1 marker if not already present
            if not any(mark.name == "order" for mark in item.iter_markers()):
                item.add_marker(pytest.mark.order(1))
        else:
            # Add order=2 marker if not already present
            if not any(mark.name == "order" for mark in item.iter_markers()):
                item.add_marker(pytest.mark.order(2))


def load_test_env():
    """Load environment variables for tests from backend/.env (if present)."""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        # Use defaults if .env doesn't exist
        os.environ.setdefault("REDIS_HOST", "localhost")
        os.environ.setdefault("REDIS_PORT", "6379")
        os.environ.setdefault("REDIS_DB", "0")
        os.environ.setdefault("REDIS_PASSWORD", "")
        os.environ.setdefault("CLICKHOUSE_HOST", "localhost")
        os.environ.setdefault("CLICKHOUSE_PORT", "8123")
        os.environ.setdefault("CLICKHOUSE_USERNAME", "default")
        os.environ.setdefault("CLICKHOUSE_PASSWORD", "")
        os.environ.setdefault("CLICKHOUSE_DATABASE", "quotes_test")


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_env():
    """Ensure test environment is loaded before any tests run."""
    load_test_env()


@pytest.fixture
def redis_params():
    """
    Redis connection parameters for testing.
    
    Uses configuration from app.core.config, which reads from environment variables
    set by load_test_env(). This ensures all tests use the same Redis connection.
    """
    return get_redis_params()


# Global state to track if we started Redis
_redis_started_by_us = False


@pytest.fixture(scope="session", autouse=True)
def _global_test_setup():
    """
    Global setup for all tests: start Redis and quotes service once per test session.
    This runs automatically before any tests (autouse=True).
    """
    global _redis_started_by_us
    
    # Load environment variables
    load_test_env()

    # Setup logging with DEBUG level for tests
    setup_logging()
    logging.getLogger().setLevel(logging.DEBUG)

    # Import connection parameters from config
    params = get_redis_params()
    clickhouse_params = {
        "host": CLICKHOUSE_HOST,
        "port": CLICKHOUSE_PORT,
        "username": CLICKHOUSE_USERNAME,
        "password": CLICKHOUSE_PASSWORD,
        "database": "quotes_test",  # Use test database instead of production
    }

    # Drop test database before starting service
    try:
        client = clickhouse_connect.get_client(
            host=clickhouse_params["host"],
            port=clickhouse_params["port"],
            username=clickhouse_params["username"],
            password=clickhouse_params["password"],
        )
        client.command(f"DROP DATABASE IF EXISTS {clickhouse_params['database']}")
    except Exception:
        # Ignore errors if database doesn't exist
        pass

    # Start Redis server for tests (or use existing one)
    _redis_started_by_us = False
    try:
        startup_redis()
        _redis_started_by_us = True
    except RuntimeError as e:
        # Check if Redis is already running and accessible
        error_msg = str(e)
        if "already in use" in error_msg or "Port" in error_msg:
            # Redis is already running, try to connect to it
            try:
                import redis
                test_client = redis.Redis(
                    host=get_redis_params()["host"],
                    port=get_redis_params()["port"],
                    db=get_redis_params()["db"],
                    password=get_redis_params().get("password"),
                    socket_connect_timeout=2
                )
                test_client.ping()
                # Redis is accessible, we can use it
            except Exception as conn_error:
                pytest.skip(f"Redis port is in use but not accessible: {conn_error}")
        else:
            pytest.skip(f"Could not start Redis server for tests: {e}")

    # Start quotes service with test database
    started = start_quotes_service(
        redis_params=params,
        clickhouse_params=clickhouse_params,
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX,
    )

    if not started:
        # Stop Redis if service failed to start (only if we started it)
        if _redis_started_by_us:
            shutdown_redis()
        pytest.skip("Could not start quotes service")

    # Initialize quotes client with test configuration
    Client(
        redis_params=params,
        request_list=REDIS_QUOTE_REQUEST_LIST,
        response_prefix=REDIS_QUOTE_RESPONSE_PREFIX,
    )

    # Wait a bit for service to initialize
    time.sleep(0.1)

    yield

    # Global teardown: stop quotes service and Redis
    stop_quotes_service(timeout=2.0)

    # Stop Redis server only if we started it
    if _redis_started_by_us:
        shutdown_redis()


@pytest.fixture(scope="session")
def quotes_service():
    """
    Fixture for tests that need quotes service.
    The actual setup is done by _global_test_setup (autouse=True).
    This fixture just ensures the service is available.
    """
    # Service is already started by _global_test_setup
    yield

