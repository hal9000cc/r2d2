"""
Serialization utilities for quotes bar data (numpy arrays <-> MessagePack).

Used by QuotesServer (publishing) and QuotesClient (receiving) for consistent
encoding and decoding of real-time bar subscription messages.
"""
from typing import Optional
import numpy as np
import msgpack

from .constants import (
    TIME_TYPE,
    PUBSUB_BAR_CHANNEL_PREFIX,
    SUB_MSG_BAR,
    SUB_MSG_ERROR,
    SUB_MSG_SHUTDOWN,
)


def build_bar_channel(source: str, symbol: str, timeframe_str: str) -> str:
    """
    Build Redis Pub/Sub channel name for a bar subscription.

    Args:
        source: Exchange name (e.g., 'binance')
        symbol: Trading pair symbol (e.g., 'BTC/USDT')
        timeframe_str: Timeframe string (e.g., '15m')

    Returns:
        Channel name, e.g. 'quotes:bars:binance:BTC/USDT:15m'
    """
    return f"{PUBSUB_BAR_CHANNEL_PREFIX}:{source}:{symbol}:{timeframe_str}"


def encode_bar_message(
    msg_type: str,
    bar_data: Optional[dict] = None,
    error: Optional[str] = None,
) -> bytes:
    """
    Encode a subscription message to MessagePack bytes.

    Args:
        msg_type: One of SUB_MSG_BAR, SUB_MSG_ERROR, SUB_MSG_SHUTDOWN.
        bar_data: For SUB_MSG_BAR — dict with numpy arrays (1 element each):
                  {time, open, high, low, close, volume}.
        error: For SUB_MSG_ERROR — human-readable error description.

    Returns:
        MessagePack-encoded bytes ready for redis.publish().
    """
    message: dict = {"type": msg_type}

    if msg_type == SUB_MSG_BAR and bar_data is not None:
        message["binary_data"] = {
            "time": bar_data["time"].tobytes(),
            "open": bar_data["open"].tobytes(),
            "high": bar_data["high"].tobytes(),
            "low": bar_data["low"].tobytes(),
            "close": bar_data["close"].tobytes(),
            "volume": bar_data["volume"].tobytes(),
        }
    elif msg_type == SUB_MSG_ERROR and error is not None:
        message["error"] = error
    # SUB_MSG_SHUTDOWN carries no payload

    return msgpack.packb(message, use_bin_type=True)


def decode_bar_message(data: bytes) -> dict:
    """
    Decode a subscription message from MessagePack bytes.

    Returns:
        dict with key 'type' (str) and type-specific fields:
        - SUB_MSG_BAR:      'bar_data' -> dict with 1-element numpy arrays
                             {time, open, high, low, close, volume}
        - SUB_MSG_ERROR:    'error' -> str
        - SUB_MSG_SHUTDOWN: no extra fields
    """
    message = msgpack.unpackb(data, raw=False)
    result: dict = {"type": message["type"]}

    if message["type"] == SUB_MSG_BAR:
        bd = message["binary_data"]
        result["bar_data"] = {
            "time": np.frombuffer(bd["time"], dtype=TIME_TYPE).copy(),
            "open": np.frombuffer(bd["open"], dtype=np.float64).copy(),
            "high": np.frombuffer(bd["high"], dtype=np.float64).copy(),
            "low": np.frombuffer(bd["low"], dtype=np.float64).copy(),
            "close": np.frombuffer(bd["close"], dtype=np.float64).copy(),
            "volume": np.frombuffer(bd["volume"], dtype=np.float64).copy(),
        }
    elif message["type"] == SUB_MSG_ERROR:
        result["error"] = message.get("error", "Unknown error")

    return result
