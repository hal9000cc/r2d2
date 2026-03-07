import numpy as np

PRICE_TYPE = float
VOLUME_TYPE = float
VOLUME_TYPE_PRECISION = 15

UNKNOWN_PRICE = np.nan

TIME_TYPE = 'datetime64[ms]'
TIME_TYPE_UNIT = 'ms'
TIME_UNITS_IN_ONE_SECOND = 1000
TIME_UNITS_NAME_FOR_TIMEDELTA = 'milliseconds'
TIME_UNITS_IN_ONE_DAY = 24 * 60 * 60 * 1000

# Redis Pub/Sub channel prefix for completed bars: quotes:bars:{source}:{symbol}:{timeframe}
PUBSUB_BAR_CHANNEL_PREFIX = "quotes:bars"

# Subscription message types (published via Redis Pub/Sub)
SUB_MSG_BAR = "bar"          # A completed bar with OHLCV data
SUB_MSG_ERROR = "error"      # WebSocket/connection error (server is reconnecting)
SUB_MSG_SHUTDOWN = "shutdown" # Server is shutting down gracefully

# Subscription action values (sent in the Redis request queue)
SUB_ACTION_SUBSCRIBE = "subscribe"
SUB_ACTION_UNSUBSCRIBE = "unsubscribe"

# WebSocket reconnect parameters
WS_RECONNECT_DELAY = 5.0       # Initial delay in seconds between reconnect attempts
WS_RECONNECT_MAX_DELAY = 60.0  # Maximum delay cap for exponential backoff


