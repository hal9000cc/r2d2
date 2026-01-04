import os
from pathlib import Path
from typing import List, Optional, Dict
from dotenv import load_dotenv

# Base directory (backend/)
BASE_DIR = Path(__file__).parent.parent.parent

# Configuration directory (~/.config/r2d2/)
CONFIG_DIR = Path.home() / ".config" / "r2d2"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_REDIS_PORT = 6379

# Default paths
_DEFAULT_DATA_DIR = str(Path.home() / ".local" / "share" / "r2d2")
_DEFAULT_LOGS_DIR = str(Path.home() / ".local" / "state" / "r2d2")

# .env file path
ENV_FILE = CONFIG_DIR / ".env"
ENV_EXAMPLE_FILE = CONFIG_DIR / ".env.example"

# Initialize configuration directory
def init_config_dir():
    """Initialize configuration directory with .env and .env.example files if needed"""
    if not ENV_FILE.exists():
        # Create both .env and .env.example files
        create_env_files()

def create_env_files():
    """Create .env and .env.example files with default values"""
    # Base content with all configuration parameters
    base_content = f"""# Backend configuration
# Environment
ENVIRONMENT=development

# Data directory for storing files
DATA_DIR={_DEFAULT_DATA_DIR}

# Logs directory
LOGS={_DEFAULT_LOGS_DIR}

# Log level
LOG_LEVEL=INFO

# ClickHouse configuration
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_DATABASE=quotes

# Redis configuration
REDIS_HOST=localhost
REDIS_PORT={DEFAULT_REDIS_PORT} # Standard Redis port
REDIS_DB=0
REDIS_PASSWORD=
REDIS_QUOTE_REQUEST_LIST=quotes:requests
REDIS_QUOTE_RESPONSE_PREFIX=quotes:responses

# Quotes fetch retry configuration
QUOTES_FETCH_RETRY_ATTEMPTS=3
QUOTES_FETCH_RETRY_DELAY=1

# Symbols cache TTL (time-to-live) in seconds
SYMBOLS_CACHE_TTL_SECONDS=600

# Exchange API keys and secrets
# Format: api_key_<source> and api_secret_<source>
# Example:
# api_key_bybit=your_bybit_api_key
# api_secret_bybit=your_bybit_api_secret
# api_key_binance=your_binance_api_key
# api_secret_binance=your_binance_api_secret
"""
    
    # Generate .env content by commenting all parameter lines but keeping default values visible
    env_lines = []
    for line in base_content.split('\n'):
        stripped = line.strip()
        # Comment parameter lines (lines that start with uppercase letter and contain =)
        # But keep the values visible so user knows what defaults will be used
        if stripped and not stripped.startswith('#') and '=' in stripped and stripped[0].isupper():
            env_lines.append(f"# {line}")
        else:
            env_lines.append(line)
    env_content = '\n'.join(env_lines)
    
    # Write .env.example (template with uncommented values)
    with open(ENV_EXAMPLE_FILE, 'w', encoding='utf-8') as f:
        f.write(base_content)
    
    # Write .env (all parameters commented with default values visible)
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.write(env_content)

# Initialize config directory on import
init_config_dir()

# Load environment variables from .env file
load_dotenv(ENV_FILE)

# Get environment (development or production) - after loading .env
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Data directory for storing files (read from .env, default: ~/.local/share/r2d2/)
DATA_DIR = Path(os.getenv("DATA_DIR", _DEFAULT_DATA_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_DIR = DATA_DIR / 'state'
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Strategies directory (read from .env, default: DATA_DIR/strategies)
STRATEGIES_DIR = Path(os.getenv("STRATEGIES_DIR", str(DATA_DIR / 'strategies')))
STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)

# Logs directory (read from .env, default: ~/.local/state/r2d2/)
LOGS_DIR = Path(os.getenv("LOGS", _DEFAULT_LOGS_DIR))
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Log level (read from .env, default: INFO)
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

# CORS settings based on environment
if ENVIRONMENT == "production":
    # In production, specify exact frontend domain(s)
    CORS_ORIGINS: List[str] = [
        # Add your production frontend URL(s) here
        # "https://yourdomain.com",
        # "https://www.yourdomain.com",
    ]
    # In production, be more restrictive with methods and headers
    CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE"]
    CORS_ALLOW_HEADERS = ["Content-Type", "Authorization"]
else:
    # Development: allow localhost ports
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    # Development: allow all methods and headers for flexibility
    CORS_ALLOW_METHODS = ["*"]
    CORS_ALLOW_HEADERS = ["*"]

# ClickHouse configuration
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USERNAME = os.getenv("CLICKHOUSE_USERNAME", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "quotes")

# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", DEFAULT_REDIS_PORT))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_QUOTE_REQUEST_LIST = os.getenv("REDIS_QUOTE_REQUEST_LIST", "quotes:requests")
REDIS_QUOTE_RESPONSE_PREFIX = os.getenv("REDIS_QUOTE_RESPONSE_PREFIX", "quotes:responses")

# Quotes fetch retry configuration
QUOTES_FETCH_RETRY_ATTEMPTS = int(os.getenv("QUOTES_FETCH_RETRY_ATTEMPTS", "3"))
QUOTES_FETCH_RETRY_DELAY = float(os.getenv("QUOTES_FETCH_RETRY_DELAY", "1.0"))

# Symbols cache TTL configuration (in seconds)
SYMBOLS_CACHE_TTL_SECONDS = int(os.getenv("SYMBOLS_CACHE_TTL_SECONDS", "3600"))

# API keys and secrets cache (lazy loading)
_api_keys_cache: Dict[str, Optional[str]] = {}
_api_secrets_cache: Dict[str, Optional[str]] = {}


def get_api_key(source: str) -> Optional[str]:
    """
    Get API key for a given source (exchange).
    
    Reads from environment variable api_key_{source} (e.g., api_key_bybit).
    Results are cached after first read.
    
    Args:
        source: Exchange name (e.g., 'bybit', 'binance')
    
    Returns:
        API key string if found, None otherwise
    """
    if source not in _api_keys_cache:
        env_key = f"api_key_{source.lower()}"
        _api_keys_cache[source] = os.getenv(env_key) or None
    return _api_keys_cache[source]


def get_api_secret(source: str) -> Optional[str]:
    """
    Get API secret for a given source (exchange).
    
    Reads from environment variable api_secret_{source} (e.g., api_secret_bybit).
    Results are cached after first read.
    
    Args:
        source: Exchange name (e.g., 'bybit', 'binance')
    
    Returns:
        API secret string if found, None otherwise
    """
    if source not in _api_secrets_cache:
        env_key = f"api_secret_{source.lower()}"
        _api_secrets_cache[source] = os.getenv(env_key) or None
    return _api_secrets_cache[source]


def redis_params() -> dict:
    """
    Returns dictionary with Redis connection parameters.
    
    Returns:
        dict: Dictionary with keys: host, port, db, password
    """
    return {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "db": REDIS_DB,
        "password": REDIS_PASSWORD,
    }

