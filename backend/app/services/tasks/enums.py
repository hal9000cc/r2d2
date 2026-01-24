"""
Enumerations for trading tasks.
"""
from enum import Enum, IntEnum


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(IntEnum):
    NEW = 0  # Only created, not processed
    ACTIVE = 1  # Validated and active (only limit and stop orders)
    EXECUTED = 2  # Executed (market immediately, limit/stop after execution)
    CANCELED = 3  # Was active, canceled (in real trading may be partially executed)
    ERROR = 4  # Failed validation (in real trading may be other reasons)


class OrderGroup(IntEnum):
    NONE = 0  # Outside of group (default)
    STOP_LOSS = 1  # Stop loss order
    TAKE_PROFIT = 2  # Take profit order


class DealType(Enum):
    LONG = "long"
    SHORT = "short"


class BarStatus(IntEnum):
    RECEIVED = 1  # Data received
    WAITING = 2   # Waiting for data
    FINISHED = 3  # No more data (finish)

