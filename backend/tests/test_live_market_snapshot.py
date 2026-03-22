import numpy as np

from app.services.quotes.constants import (
    SUB_MSG_COMPLETED_BAR,
    SUB_MSG_MARKET_SNAPSHOT,
)
from app.services.quotes.serialization import encode_bar_message, decode_bar_message


def _build_bar(timestamp_ms: int, close_price: float) -> dict:
    return {
        "time": np.array([np.datetime64(timestamp_ms, "ms")], dtype="datetime64[ms]"),
        "open": np.array([close_price - 1.0], dtype=np.float64),
        "high": np.array([close_price + 1.0], dtype=np.float64),
        "low": np.array([close_price - 2.0], dtype=np.float64),
        "close": np.array([close_price], dtype=np.float64),
        "volume": np.array([10.0], dtype=np.float64),
    }


def test_market_snapshot_message_roundtrip():
    snapshot = _build_bar(1710000000000, 101.5)
    encoded = encode_bar_message(SUB_MSG_MARKET_SNAPSHOT, bar_data=snapshot)
    decoded = decode_bar_message(encoded)

    assert decoded["type"] == SUB_MSG_MARKET_SNAPSHOT
    assert decoded["bar_data"]["time"][0] == snapshot["time"][0]
    assert decoded["bar_data"]["close"][0] == snapshot["close"][0]


def test_completed_bar_message_roundtrip():
    completed_bar = _build_bar(1710003600000, 105.0)
    encoded = encode_bar_message(SUB_MSG_COMPLETED_BAR, bar_data=completed_bar)
    decoded = decode_bar_message(encoded)

    assert decoded["type"] == SUB_MSG_COMPLETED_BAR
    assert decoded["bar_data"]["time"][0] == completed_bar["time"][0]
    assert decoded["bar_data"]["close"][0] == completed_bar["close"][0]