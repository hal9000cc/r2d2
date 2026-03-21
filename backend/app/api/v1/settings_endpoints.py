from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from typing import List
from app.core.config import read_config, write_config
from app.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

MASK = "••••••••"

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_ENVIRONMENTS = {"development", "production"}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ExchangeApiKey(BaseModel):
    source: str
    api_key: str = ""
    api_secret: str = ""

    @field_validator("source")
    @classmethod
    def source_not_empty(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("Exchange source name must not be empty")
        return v


class ExchangeApiUrl(BaseModel):
    source: str
    public_api: str = ""
    private_api: str = ""

    @field_validator("source")
    @classmethod
    def source_not_empty(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("Exchange source name must not be empty")
        return v


class GeneralSettings(BaseModel):
    ENVIRONMENT: str
    DATA_DIR: str
    LOGS: str
    LOG_LEVEL: str

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        if v.upper() not in _VALID_LOG_LEVELS:
            raise ValueError(f"Must be one of: {', '.join(sorted(_VALID_LOG_LEVELS))}")
        return v.upper()

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v.lower() not in _VALID_ENVIRONMENTS:
            raise ValueError(f"Must be one of: {', '.join(sorted(_VALID_ENVIRONMENTS))}")
        return v.lower()

    @field_validator("DATA_DIR", "LOGS")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Path must not be empty")
        return v.strip()


class ClickhouseSettings(BaseModel):
    CLICKHOUSE_HOST: str
    CLICKHOUSE_PORT: str
    CLICKHOUSE_USERNAME: str
    CLICKHOUSE_PASSWORD: str
    CLICKHOUSE_DATABASE: str

    @field_validator("CLICKHOUSE_PORT")
    @classmethod
    def validate_port(cls, v: str) -> str:
        try:
            port = int(v)
            if not (1 <= port <= 65535):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Port must be an integer between 1 and 65535")
        return v

    @field_validator("CLICKHOUSE_HOST")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Host must not be empty")
        return v.strip()


class RedisSettings(BaseModel):
    REDIS_HOST: str
    REDIS_PORT: str
    REDIS_DB: str
    REDIS_PASSWORD: str

    @field_validator("REDIS_PORT")
    @classmethod
    def validate_port(cls, v: str) -> str:
        try:
            port = int(v)
            if not (1 <= port <= 65535):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Port must be an integer between 1 and 65535")
        return v

    @field_validator("REDIS_DB")
    @classmethod
    def validate_db(cls, v: str) -> str:
        try:
            int(v)
        except (ValueError, TypeError):
            raise ValueError("REDIS_DB must be an integer")
        return v

    @field_validator("REDIS_HOST")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Host must not be empty")
        return v.strip()


class QuotesSettings(BaseModel):
    clickhouse: ClickhouseSettings
    REDIS_QUOTE_REQUEST_LIST: str
    REDIS_QUOTE_RESPONSE_PREFIX: str
    QUOTES_FETCH_RETRY_ATTEMPTS: str
    QUOTES_FETCH_RETRY_DELAY: str

    @field_validator("QUOTES_FETCH_RETRY_ATTEMPTS")
    @classmethod
    def validate_positive_int(cls, v: str) -> str:
        try:
            val = int(v)
            if val < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Must be a positive integer")
        return v

    @field_validator("QUOTES_FETCH_RETRY_DELAY")
    @classmethod
    def validate_non_negative_float(cls, v: str) -> str:
        try:
            val = float(v)
            if val < 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Must be a non-negative number")
        return v


class BrokerSettings(BaseModel):
    BAR_WAIT_INTERVAL: str
    ORDER_WAIT_INTERVAL: str
    ORDER_PLACEMENT_TIMEOUT: str

    @field_validator("BAR_WAIT_INTERVAL", "ORDER_WAIT_INTERVAL", "ORDER_PLACEMENT_TIMEOUT")
    @classmethod
    def validate_positive_float(cls, v: str) -> str:
        try:
            val = float(v)
            if val <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Must be a positive number")
        return v


class OtherSettings(BaseModel):
    SYMBOLS_CACHE_TTL_SECONDS: str

    @field_validator("SYMBOLS_CACHE_TTL_SECONDS")
    @classmethod
    def validate_positive_int(cls, v: str) -> str:
        try:
            val = int(v)
            if val < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Must be a positive integer")
        return v


class SupervisorSettings(BaseModel):
    SUPERVISOR_POLL_INTERVAL: str
    SUPERVISOR_MAX_RESTARTS: str
    SUPERVISOR_CRASH_INTERVAL: str
    SUPERVISOR_FORCE_KILL_TIMEOUT: str

    @field_validator("SUPERVISOR_POLL_INTERVAL", "SUPERVISOR_CRASH_INTERVAL", "SUPERVISOR_FORCE_KILL_TIMEOUT")
    @classmethod
    def validate_positive_float(cls, v: str) -> str:
        try:
            val = float(v)
            if val <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Must be a positive number")
        return v

    @field_validator("SUPERVISOR_MAX_RESTARTS")
    @classmethod
    def validate_positive_int(cls, v: str) -> str:
        try:
            val = int(v)
            if val < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Must be a positive integer")
        return v


class ConfigRequest(BaseModel):
    general: GeneralSettings
    redis: RedisSettings
    quotes: QuotesSettings
    broker: BrokerSettings
    others: OtherSettings
    supervisor: SupervisorSettings
    exchange_api_keys: List[ExchangeApiKey] = []
    exchange_api_urls: List[ExchangeApiUrl] = []


class SaveResponse(BaseModel):
    success: bool
    changed_keys: List[str]
    actions_taken: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# Warning codes returned to the frontend (human-readable descriptions)
# ---------------------------------------------------------------------------

WARNING_DESCRIPTIONS = {
    "restart_required": (
        "Full application restart required — changes to Redis connection or "
        "environment settings take effect only after restart."
    ),
    "restart_trading_tasks": (
        "Restart active trading tasks — broker timing or API key settings "
        "take effect when tasks are next started."
    ),
    "restart_supervisor": (
        "Restart supervisor — supervisor timing settings take effect only "
        "after the supervisor process is restarted."
    ),
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def get_settings():
    """Return current application settings (sensitive values masked)."""
    try:
        return read_config()
    except Exception as exc:
        logger.error(f"Failed to read settings: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read settings: {exc}")


@router.put("", response_model=SaveResponse)
async def save_settings(config: ConfigRequest) -> SaveResponse:
    """
    Save application settings.

    Applies changes immediately where possible:
    - ClickHouse / quotes settings: quotes service is restarted automatically.
    - API key cache: cleared immediately, new values available to next task start.
    - Redis / environment settings: full restart required (warned but not performed).
    - Supervisor settings: supervisor restart required (warned but not performed).
    """
    try:
        data = config.model_dump()
        result = write_config(data)
        logger.info(
            f"Settings saved. Changed keys: {result['changed_keys']}, "
            f"actions: {result['actions_taken']}, warnings: {result['warnings']}"
        )
        return SaveResponse(
            success=True,
            changed_keys=result["changed_keys"],
            actions_taken=result["actions_taken"],
            warnings=result["warnings"],
        )
    except Exception as exc:
        logger.error(f"Failed to save settings: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {exc}")
