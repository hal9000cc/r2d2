import os
from pathlib import Path
from typing import List, Optional, Dict
from dotenv import load_dotenv, dotenv_values

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

# Mask displayed for sensitive values in settings API
SETTINGS_MASK = "••••••••"

# Keys that contain sensitive data (passwords, secrets)
_SENSITIVE_KEYS: frozenset = frozenset({
    "CLICKHOUSE_PASSWORD",
    "REDIS_PASSWORD",
})

# Parameters that require full application restart to take effect
RESTART_REQUIRED_KEYS: frozenset = frozenset({
    "ENVIRONMENT", "DATA_DIR", "LOGS", "LOG_LEVEL",
    "REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_PASSWORD",
})

# Parameters that require quotes service restart (ClickHouse or Redis queue settings)
RESTART_QUOTES_SERVICE_KEYS: frozenset = frozenset({
    "CLICKHOUSE_HOST", "CLICKHOUSE_PORT", "CLICKHOUSE_USERNAME",
    "CLICKHOUSE_PASSWORD", "CLICKHOUSE_DATABASE",
    "REDIS_QUOTE_REQUEST_LIST", "REDIS_QUOTE_RESPONSE_PREFIX",
    "QUOTES_FETCH_RETRY_ATTEMPTS", "QUOTES_FETCH_RETRY_DELAY",
    "SYMBOLS_CACHE_TTL_SECONDS",
})

# Parameters that require restarting active trading tasks
RESTART_TRADING_TASKS_KEYS: frozenset = frozenset({
    "BAR_WAIT_INTERVAL", "ORDER_WAIT_INTERVAL", "ORDER_PLACEMENT_TIMEOUT",
})

# Parameters that require supervisor restart (read at process startup)
RESTART_SUPERVISOR_KEYS: frozenset = frozenset({
    "SUPERVISOR_POLL_INTERVAL", "SUPERVISOR_MAX_RESTARTS",
    "SUPERVISOR_CRASH_INTERVAL", "SUPERVISOR_FORCE_KILL_TIMEOUT",
})

# Default values for all known parameters
_CONFIG_DEFAULTS: Dict[str, str] = {
    "ENVIRONMENT": "development",
    "DATA_DIR": _DEFAULT_DATA_DIR,
    "LOGS": _DEFAULT_LOGS_DIR,
    "LOG_LEVEL": "INFO",
    "CLICKHOUSE_HOST": "localhost",
    "CLICKHOUSE_PORT": "8123",
    "CLICKHOUSE_USERNAME": "default",
    "CLICKHOUSE_PASSWORD": "",
    "CLICKHOUSE_DATABASE": "quotes",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": str(DEFAULT_REDIS_PORT),
    "REDIS_DB": "0",
    "REDIS_PASSWORD": "",
    "REDIS_QUOTE_REQUEST_LIST": "quotes:requests",
    "REDIS_QUOTE_RESPONSE_PREFIX": "quotes:responses",
    "QUOTES_FETCH_RETRY_ATTEMPTS": "3",
    "QUOTES_FETCH_RETRY_DELAY": "1",
    "SYMBOLS_CACHE_TTL_SECONDS": "600",
    "BAR_WAIT_INTERVAL": "60.0",
    "ORDER_WAIT_INTERVAL": "1.0",
    "ORDER_PLACEMENT_TIMEOUT": "60.0",
    "SUPERVISOR_POLL_INTERVAL": "3.0",
    "SUPERVISOR_MAX_RESTARTS": "3",
    "SUPERVISOR_CRASH_INTERVAL": "60.0",
    "SUPERVISOR_FORCE_KILL_TIMEOUT": "300.0",
}


def _is_sensitive_key(key: str) -> bool:
    """Check if a config key holds sensitive data (password or API key/secret)."""
    key_lower = key.lower()
    return (
        key in _SENSITIVE_KEYS
        or key_lower.startswith("api_key_")
        or key_lower.startswith("api_secret_")
    )


def _read_raw_env() -> Dict[str, str]:
    """
    Read raw (unmasked) values from .env file using dotenv parser.
    Returns empty dict if file does not exist.
    """
    if ENV_FILE.exists():
        return {k: (v or "") for k, v in dotenv_values(ENV_FILE).items()}
    return {}


def _write_env_file(values: Dict[str, str]) -> None:
    """
    Write configuration to .env file in structured format.
    Empty API key entries are skipped to keep the file clean.
    """
    lines = [
        "# R2D2 Configuration\n",
        "# Managed by settings panel\n",
        "\n",
    ]

    sections = [
        ("# General", ["ENVIRONMENT", "DATA_DIR", "LOGS", "LOG_LEVEL"]),
        ("# Redis", [
            "REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_PASSWORD",
        ]),
        ("# Quotes service", [
            "CLICKHOUSE_HOST", "CLICKHOUSE_PORT", "CLICKHOUSE_USERNAME",
            "CLICKHOUSE_PASSWORD", "CLICKHOUSE_DATABASE",
            "REDIS_QUOTE_REQUEST_LIST", "REDIS_QUOTE_RESPONSE_PREFIX",
            "QUOTES_FETCH_RETRY_ATTEMPTS", "QUOTES_FETCH_RETRY_DELAY",
        ]),
        ("# Broker", [
            "BAR_WAIT_INTERVAL", "ORDER_WAIT_INTERVAL", "ORDER_PLACEMENT_TIMEOUT",
        ]),
        ("# Others", [
            "SYMBOLS_CACHE_TTL_SECONDS",
        ]),
        ("# Supervisor", [
            "SUPERVISOR_POLL_INTERVAL", "SUPERVISOR_MAX_RESTARTS",
            "SUPERVISOR_CRASH_INTERVAL", "SUPERVISOR_FORCE_KILL_TIMEOUT",
        ]),
    ]

    written_keys: set = set()
    for section_name, keys in sections:
        lines.append(f"{section_name}\n")
        for key in keys:
            value = values.get(key, "")
            lines.append(f"{key}={value}\n")
            written_keys.add(key)
        lines.append("\n")

    # Write API keys (skip entries with empty values — means they were deleted)
    api_entries = {
        k: v for k, v in values.items()
        if k not in written_keys and v and (
            k.lower().startswith("api_key_") or k.lower().startswith("api_secret_")
        )
    }
    if api_entries:
        lines.append("# Exchange API Keys\n")
        for key in sorted(api_entries.keys()):
            lines.append(f"{key}={api_entries[key]}\n")
        lines.append("\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def read_config() -> dict:
    """
    Read configuration from .env file.

    Returns a structured dict grouped by category.
    Sensitive values (passwords, API keys) are replaced with SETTINGS_MASK
    if a non-empty value is stored.
    """
    raw = _read_raw_env()

    def get_val(key: str, default: str = "") -> str:
        val = raw.get(key, os.getenv(key, _CONFIG_DEFAULTS.get(key, default)))
        if _is_sensitive_key(key) and val:
            return SETTINGS_MASK
        return val or ""

    # Detect exchange sources from api_key_* / api_secret_* entries in the file
    sources: set = set()
    for key in raw:
        key_lower = key.lower()
        if key_lower.startswith("api_key_"):
            sources.add(key_lower[len("api_key_"):])
        elif key_lower.startswith("api_secret_"):
            sources.add(key_lower[len("api_secret_"):])

    exchange_api_keys = []
    for source in sorted(sources):
        raw_key = raw.get(f"api_key_{source}", "")
        raw_secret = raw.get(f"api_secret_{source}", "")
        exchange_api_keys.append({
            "source": source,
            "api_key": SETTINGS_MASK if raw_key else "",
            "api_secret": SETTINGS_MASK if raw_secret else "",
        })

    return {
        "general": {
            "ENVIRONMENT": get_val("ENVIRONMENT", "development"),
            "DATA_DIR": get_val("DATA_DIR", _DEFAULT_DATA_DIR),
            "LOGS": get_val("LOGS", _DEFAULT_LOGS_DIR),
            "LOG_LEVEL": get_val("LOG_LEVEL", "INFO"),
        },
        "redis": {
            "REDIS_HOST": get_val("REDIS_HOST", "localhost"),
            "REDIS_PORT": get_val("REDIS_PORT", str(DEFAULT_REDIS_PORT)),
            "REDIS_DB": get_val("REDIS_DB", "0"),
            "REDIS_PASSWORD": get_val("REDIS_PASSWORD", ""),
        },
        "quotes": {
            "clickhouse": {
                "CLICKHOUSE_HOST": get_val("CLICKHOUSE_HOST", "localhost"),
                "CLICKHOUSE_PORT": get_val("CLICKHOUSE_PORT", "8123"),
                "CLICKHOUSE_USERNAME": get_val("CLICKHOUSE_USERNAME", "default"),
                "CLICKHOUSE_PASSWORD": get_val("CLICKHOUSE_PASSWORD", ""),
                "CLICKHOUSE_DATABASE": get_val("CLICKHOUSE_DATABASE", "quotes"),
            },
            "REDIS_QUOTE_REQUEST_LIST": get_val("REDIS_QUOTE_REQUEST_LIST", "quotes:requests"),
            "REDIS_QUOTE_RESPONSE_PREFIX": get_val("REDIS_QUOTE_RESPONSE_PREFIX", "quotes:responses"),
            "QUOTES_FETCH_RETRY_ATTEMPTS": get_val("QUOTES_FETCH_RETRY_ATTEMPTS", "3"),
            "QUOTES_FETCH_RETRY_DELAY": get_val("QUOTES_FETCH_RETRY_DELAY", "1"),
        },
        "broker": {
            "BAR_WAIT_INTERVAL": get_val("BAR_WAIT_INTERVAL", "60.0"),
            "ORDER_WAIT_INTERVAL": get_val("ORDER_WAIT_INTERVAL", "1.0"),
            "ORDER_PLACEMENT_TIMEOUT": get_val("ORDER_PLACEMENT_TIMEOUT", "60.0"),
        },
        "others": {
            "SYMBOLS_CACHE_TTL_SECONDS": get_val("SYMBOLS_CACHE_TTL_SECONDS", "600"),
        },
        "supervisor": {
            "SUPERVISOR_POLL_INTERVAL": get_val("SUPERVISOR_POLL_INTERVAL", "3.0"),
            "SUPERVISOR_MAX_RESTARTS": get_val("SUPERVISOR_MAX_RESTARTS", "3"),
            "SUPERVISOR_CRASH_INTERVAL": get_val("SUPERVISOR_CRASH_INTERVAL", "60.0"),
            "SUPERVISOR_FORCE_KILL_TIMEOUT": get_val("SUPERVISOR_FORCE_KILL_TIMEOUT", "300.0"),
        },
        "exchange_api_keys": exchange_api_keys,
    }


def write_config(data: dict) -> dict:
    """
    Write configuration to .env file and apply changes where possible.

    For sensitive fields arriving with the mask value, the existing stored value
    is preserved (user did not change it).

    Automatic actions:
    - Quotes service is restarted if ClickHouse / queue settings changed
      (unless a full restart is also required, in which case it is deferred).
    - API key in-memory cache is cleared when API keys change.

    Args:
        data: Config dict in the same format returned by read_config().

    Returns:
        dict with:
        - changed_keys: list of parameter names that actually changed
        - actions_taken: list of automatic actions performed
        - warnings: list of warning codes requiring manual action
    """
    raw_old = _read_raw_env()

    # Flatten standard groups into key -> value
    new_values: Dict[str, str] = {}
    for group in ("general", "redis", "broker", "others", "supervisor"):
        if group in data and isinstance(data[group], dict):
            for key, value in data[group].items():
                new_values[key] = str(value) if value is not None else ""

    # Flatten quotes group (contains nested clickhouse sub-group)
    if "quotes" in data and isinstance(data["quotes"], dict):
        quotes_data = data["quotes"]
        if "clickhouse" in quotes_data and isinstance(quotes_data["clickhouse"], dict):
            for key, value in quotes_data["clickhouse"].items():
                new_values[key] = str(value) if value is not None else ""
        for key, value in quotes_data.items():
            if key != "clickhouse":
                new_values[key] = str(value) if value is not None else ""

    # For sensitive non-API keys carrying the mask, restore old value
    for key in list(new_values.keys()):
        if _is_sensitive_key(key) and new_values[key] == SETTINGS_MASK:
            new_values[key] = raw_old.get(key, "")

    # Process exchange API keys list
    new_api_sources: set = set()
    if "exchange_api_keys" in data and isinstance(data["exchange_api_keys"], list):
        for entry in data["exchange_api_keys"]:
            source = (entry.get("source") or "").strip().lower()
            if not source:
                continue
            new_api_sources.add(source)

            api_key_env = f"api_key_{source}"
            api_secret_env = f"api_secret_{source}"

            api_key_val = entry.get("api_key", "")
            api_secret_val = entry.get("api_secret", "")

            new_values[api_key_env] = (
                raw_old.get(api_key_env, "") if api_key_val == SETTINGS_MASK else api_key_val
            )
            new_values[api_secret_env] = (
                raw_old.get(api_secret_env, "") if api_secret_val == SETTINGS_MASK else api_secret_val
            )

    # Mark deleted exchanges by setting their keys to empty string
    for old_key in raw_old:
        old_lower = old_key.lower()
        if old_lower.startswith("api_key_") or old_lower.startswith("api_secret_"):
            prefix = "api_key_" if old_lower.startswith("api_key_") else "api_secret_"
            source = old_lower[len(prefix):]
            if source not in new_api_sources and old_key not in new_values:
                new_values[old_key] = ""  # will be omitted from file by _write_env_file

    # Compute changed keys
    changed_keys: List[str] = []
    for key, new_val in new_values.items():
        old_val = raw_old.get(key, _CONFIG_DEFAULTS.get(key, ""))
        if new_val != old_val:
            changed_keys.append(key)

    # Write .env file
    _write_env_file(new_values)

    # Update os.environ so running process sees new values immediately
    for key, value in new_values.items():
        if value:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]

    # Determine impact categories
    changed_set = set(changed_keys)
    actions_taken: List[str] = []
    warnings: List[str] = []

    needs_full_restart = bool(changed_set & RESTART_REQUIRED_KEYS)
    needs_quotes_restart = bool(changed_set & RESTART_QUOTES_SERVICE_KEYS)
    needs_tasks_restart = bool(changed_set & RESTART_TRADING_TASKS_KEYS)
    needs_supervisor_restart = bool(changed_set & RESTART_SUPERVISOR_KEYS)
    api_keys_changed = any(
        k.lower().startswith("api_key_") or k.lower().startswith("api_secret_")
        for k in changed_set
    )

    if needs_full_restart:
        warnings.append("restart_required")

    if needs_quotes_restart and not needs_full_restart:
        try:
            from app.services.quotes.server import stop_quotes_service, start_quotes_service
            stop_quotes_service(timeout=5.0)
            ch_params = {
                "host": new_values.get("CLICKHOUSE_HOST", CLICKHOUSE_HOST),
                "port": int(new_values.get("CLICKHOUSE_PORT", str(CLICKHOUSE_PORT))),
                "username": new_values.get("CLICKHOUSE_USERNAME", CLICKHOUSE_USERNAME),
                "password": new_values.get("CLICKHOUSE_PASSWORD", CLICKHOUSE_PASSWORD),
                "database": new_values.get("CLICKHOUSE_DATABASE", CLICKHOUSE_DATABASE),
            }
            start_quotes_service(
                redis_params=redis_params(),
                clickhouse_params=ch_params,
                request_list=new_values.get("REDIS_QUOTE_REQUEST_LIST", REDIS_QUOTE_REQUEST_LIST),
                response_prefix=new_values.get("REDIS_QUOTE_RESPONSE_PREFIX", REDIS_QUOTE_RESPONSE_PREFIX),
            )
            actions_taken.append("quotes_service_restarted")
        except Exception as exc:
            warnings.append(f"quotes_service_restart_failed:{exc}")
    elif needs_quotes_restart and needs_full_restart:
        pass  # covered by restart_required

    if needs_tasks_restart or api_keys_changed:
        _api_keys_cache.clear()
        _api_secrets_cache.clear()
        warnings.append("restart_trading_tasks")

    if needs_supervisor_restart:
        warnings.append("restart_supervisor")

    return {
        "changed_keys": changed_keys,
        "actions_taken": actions_taken,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Startup initialization
# ---------------------------------------------------------------------------

def init_config_dir():
    """Initialize configuration directory with .env and .env.example files if needed"""
    if not ENV_FILE.exists():
        create_env_files()

def create_env_files():
    """Create .env and .env.example files with default values"""
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

# Broker settings
BAR_WAIT_INTERVAL=60.0
ORDER_WAIT_INTERVAL=1.0
ORDER_PLACEMENT_TIMEOUT=60.0

# Symbols cache TTL (time-to-live) in seconds
SYMBOLS_CACHE_TTL_SECONDS=600

# Supervisor settings
SUPERVISOR_POLL_INTERVAL=3.0
SUPERVISOR_MAX_RESTARTS=3
SUPERVISOR_CRASH_INTERVAL=60.0
SUPERVISOR_FORCE_KILL_TIMEOUT=300.0

# Exchange API keys and secrets
# Format: api_key_<source> and api_secret_<source>
# Example:
# api_key_bybit=your_bybit_api_key
# api_secret_bybit=your_bybit_api_secret
# api_key_binance=your_binance_api_key
# api_secret_binance=your_binance_api_secret
"""

    env_lines = []
    for line in base_content.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped and stripped[0].isupper():
            env_lines.append(f"# {line}")
        else:
            env_lines.append(line)
    env_content = '\n'.join(env_lines)

    with open(ENV_EXAMPLE_FILE, 'w', encoding='utf-8') as f:
        f.write(base_content)

    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.write(env_content)


# Initialize config directory on import
init_config_dir()

# Load environment variables from .env file
load_dotenv(ENV_FILE)

# ---------------------------------------------------------------------------
# Module-level configuration constants (read at startup)
# ---------------------------------------------------------------------------

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

DATA_DIR = Path(os.getenv("DATA_DIR", _DEFAULT_DATA_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_DIR = DATA_DIR / 'state'
STATE_DIR.mkdir(parents=True, exist_ok=True)

STRATEGIES_DIR = Path(os.getenv("STRATEGIES_DIR", str(DATA_DIR / 'strategies')))
STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)

LOGS_DIR = Path(os.getenv("LOGS", _DEFAULT_LOGS_DIR))
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

# CORS settings based on environment
if ENVIRONMENT == "production":
    CORS_ORIGINS: List[str] = []
    CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE"]
    CORS_ALLOW_HEADERS = ["Content-Type", "Authorization"]
else:
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
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

# Broker settings
BAR_WAIT_INTERVAL = float(os.getenv("BAR_WAIT_INTERVAL", "60.0"))
ORDER_WAIT_INTERVAL = float(os.getenv("ORDER_WAIT_INTERVAL", "1.0"))
ORDER_PLACEMENT_TIMEOUT = float(os.getenv("ORDER_PLACEMENT_TIMEOUT", "60.0"))

# Supervisor settings
SUPERVISOR_POLL_INTERVAL = float(os.getenv("SUPERVISOR_POLL_INTERVAL", "3.0"))
SUPERVISOR_MAX_RESTARTS = int(os.getenv("SUPERVISOR_MAX_RESTARTS", "3"))
SUPERVISOR_CRASH_INTERVAL = float(os.getenv("SUPERVISOR_CRASH_INTERVAL", "60.0"))
SUPERVISOR_FORCE_KILL_TIMEOUT = float(os.getenv("SUPERVISOR_FORCE_KILL_TIMEOUT", "300.0"))

# API keys and secrets cache (lazy loading)
_api_keys_cache: Dict[str, Optional[str]] = {}
_api_secrets_cache: Dict[str, Optional[str]] = {}


def get_api_key(source: str) -> Optional[str]:
    """
    Get API key for a given source (exchange).

    Reads from environment variable api_key_{source} (e.g., api_key_bybit).
    Results are cached after first read.
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
    """
    if source not in _api_secrets_cache:
        env_key = f"api_secret_{source.lower()}"
        _api_secrets_cache[source] = os.getenv(env_key) or None
    return _api_secrets_cache[source]


# ---------------------------------------------------------------------------
# Redis key constants (shared between supervisor and API endpoints)
# ---------------------------------------------------------------------------

# Supervisor instance lock
SUPERVISOR_LOCK_KEY = "r2d2:instance_lock"

# Hash: task_id (str) → pid (str) — tracking live trading process PIDs
SUPERVISOR_PIDS_KEY = "r2d2:supervisor:pids"

# Per-task supervisor error log: list of JSON entries
SUPERVISOR_ERRORS_KEY = "trading_tasks:supervisor_errors:{task_id}"

# Prefix for scanning all per-task supervisor error keys
SUPERVISOR_ERRORS_KEY_PREFIX = "trading_tasks:supervisor_errors:"

# Global pub/sub channel for real-time supervisor events (all tasks combined)
SUPERVISOR_GLOBAL_CHANNEL = "supervisor:messages"

# Per-task pub/sub channel for trading messages (strategy logs, events)
TRADING_MESSAGES_CHANNEL = "trading_tasks:messages:{task_id}"


def redis_params() -> dict:
    """
    Returns dictionary with Redis connection parameters.

    Reads from os.environ dynamically so that changes made by write_config()
    are reflected immediately.
    """
    return {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", str(DEFAULT_REDIS_PORT))),
        "db": int(os.getenv("REDIS_DB", "0")),
        "password": os.getenv("REDIS_PASSWORD") or None,
    }


def clickhouse_params() -> dict:
    """
    Returns dictionary with ClickHouse connection parameters.

    Reads from os.environ dynamically so that changes made by write_config()
    are reflected immediately.
    """
    return {
        "host": os.getenv("CLICKHOUSE_HOST", "localhost"),
        "port": int(os.getenv("CLICKHOUSE_PORT", "8123")),
        "username": os.getenv("CLICKHOUSE_USERNAME", "default"),
        "password": os.getenv("CLICKHOUSE_PASSWORD", ""),
        "database": os.getenv("CLICKHOUSE_DATABASE", "quotes"),
    }
