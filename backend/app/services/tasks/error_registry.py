"""
Centralized error registry for broker error tracking and persistence.

Errors of level 'error' and 'critical' are stored here and saved to Redis.
Regular info/warning messages are NOT stored here - they go only via pub/sub.
"""
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
from enum import Enum

from pydantic import BaseModel, Field

from app.core.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class ErrorCategory(str, Enum):
    """Error category for classification."""
    EXCHANGE = "exchange"           # Exchange API errors, order placement failures, timeouts
    TRADING = "trading"             # Trade processing, deal closure, integrity checks, emergency close
    DATA = "data"                   # Bar subscription errors, data feed issues
    INFRASTRUCTURE = "infrastructure"  # Redis, serialization, result saving failures
    STRATEGY = "strategy"           # Unhandled exceptions in strategy code (on_bar, on_start, on_finish)


class ErrorLevel(str, Enum):
    """Severity level for stored errors."""
    ERROR = "error"
    CRITICAL = "critical"


class ErrorEntry(BaseModel):
    """Single error record stored in the registry."""
    id: int = Field(gt=0, description="Sequential error ID within this run")
    timestamp: str = Field(description="Server UTC time in ISO format when error was registered")
    broker_time: Optional[str] = Field(default=None, description="Broker bar time in ISO format (may be None)")
    level: ErrorLevel
    category: ErrorCategory
    message: str
    deal_id: Optional[int] = Field(default=None, description="Associated deal ID (if applicable)")
    order_id: Optional[int] = Field(default=None, description="Associated order ID (if applicable)")


class ErrorRegistry:
    """
    Centralized registry of broker errors for persistence and later retrieval.

    Stores errors (level 'error' and 'critical') in memory during a run.
    Errors are flushed to Redis periodically via TaskResults.put_result().
    Regular info/warning messages bypass this registry entirely.

    Usage:
        registry.register_error(
            level="error",
            category=ErrorCategory.EXCHANGE,
            message="exchange_create_order failed: ...",
            deal_id=5,
            order_id=12,
            broker_time="2026-03-07T20:13:00Z"
        )
    """

    def __init__(self) -> None:
        self._errors: List[ErrorEntry] = []
        self._next_id: int = 1
        self._flush_index: int = 0  # Index up to which errors have been flushed to Redis

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_error(
        self,
        level: str,
        category: ErrorCategory,
        message: str,
        deal_id: Optional[int] = None,
        order_id: Optional[int] = None,
        broker_time: Optional[str] = None,
    ) -> ErrorEntry:
        """
        Register an error in the registry.

        Args:
            level: Severity - "error" or "critical". Other values are silently ignored.
            category: ErrorCategory enum value.
            message: Human-readable error message.
            deal_id: Associated deal ID (optional).
            order_id: Associated order ID (optional).
            broker_time: Broker bar time in ISO format (optional).

        Returns:
            Created ErrorEntry, or raises ValueError if level is unsupported.
        """
        if level not in ("error", "critical"):
            raise ValueError(f"ErrorRegistry only stores 'error' or 'critical', got '{level}'")

        entry = ErrorEntry(
            id=self._next_id,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            broker_time=broker_time,
            level=ErrorLevel(level),
            category=category,
            message=message,
            deal_id=deal_id,
            order_id=order_id,
        )
        self._errors.append(entry)
        self._next_id += 1
        
        self.notify_user(entry)
        
        return entry

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_errors(self) -> List[ErrorEntry]:
        """Return all registered errors (copy of the internal list)."""
        return list(self._errors)

    def get_deal_errors(self, deal_id: int) -> List[ErrorEntry]:
        """Return all errors associated with a specific deal."""
        return [e for e in self._errors if e.deal_id == deal_id]

    def get_new_errors(self) -> List[ErrorEntry]:
        """
        Return errors that have not yet been flushed to Redis.
        Call mark_flushed() after successfully saving them.
        """
        return self._errors[self._flush_index:]

    def mark_flushed(self) -> None:
        """Mark all currently known errors as flushed to Redis."""
        self._flush_index = len(self._errors)

    @property
    def total_count(self) -> int:
        """Total number of registered errors."""
        return len(self._errors)

    # ------------------------------------------------------------------
    # Serialization helpers (for Redis storage)
    # ------------------------------------------------------------------

    @staticmethod
    def serialize_entry(entry: ErrorEntry) -> str:
        """
        Serialize ErrorEntry to pipe-delimited string for Redis Sorted Set storage.

        Format:
            id|timestamp|broker_time|level|category|message|deal_id|order_id

        Empty optional fields are stored as empty string.
        Message pipe characters are escaped as \\|
        """
        def _fmt(v) -> str:
            if v is None:
                return ""
            return str(v).replace("|", "\\|")

        return "|".join([
            str(entry.id),
            entry.timestamp,
            entry.broker_time or "",
            entry.level.value,
            entry.category.value,
            _fmt(entry.message),
            str(entry.deal_id) if entry.deal_id is not None else "",
            str(entry.order_id) if entry.order_id is not None else "",
        ])

    @staticmethod
    def deserialize_entry(raw: str) -> Optional[ErrorEntry]:
        """
        Deserialize ErrorEntry from pipe-delimited string.

        Returns None if the string is malformed.
        """
        try:
            parts = raw.split("|", 7)
            if len(parts) != 8:
                logger.warning("ErrorRegistry: malformed entry (expected 8 fields): %s", raw[:120])
                return None

            entry_id_str, timestamp, broker_time, level, category, message, deal_id_str, order_id_str = parts
            message = message.replace("\\|", "|")

            return ErrorEntry(
                id=int(entry_id_str),
                timestamp=timestamp,
                broker_time=broker_time or None,
                level=ErrorLevel(level),
                category=ErrorCategory(category),
                message=message,
                deal_id=int(deal_id_str) if deal_id_str else None,
                order_id=int(order_id_str) if order_id_str else None,
            )
        except Exception as e:
            logger.warning("ErrorRegistry: failed to deserialize entry: %s | error: %s", raw[:120], e)
            return None

    # ------------------------------------------------------------------
    # Notifications (stub for future implementation)
    # ------------------------------------------------------------------

    def notify_user(self, entry: ErrorEntry) -> None:
        """
        Send critical error notification to user via external channel.

        TODO: implement actual notification (e.g. Telegram, email, push).
        Currently a no-op stub.
        """
        pass
