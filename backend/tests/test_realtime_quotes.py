"""
Integration test for real-time bar subscription via QuotesClient / QuotesServer.

Strategy to guarantee no gap and no duplicate between history and live bars:

  1. Subscribe FIRST (server starts watch_ohlcv WebSocket).
  2. Receive the very first bar that arrives from the exchange (bar_0).
  3. THEN load 5 historical bars whose last timestamp = bar_0.time - 1s.
     This is the only reliable way to align history with the live stream
     without relying on wall-clock timing assumptions.
  4. Verify bar_0 is exactly the next expected bar after history.
  5. Append bar_0 to RealTimeQuotesProvider (internal continuity check fires).
  6. Receive and verify two more bars the same way.
  7. Unsubscribe.
  8. Final check: 8 strictly consecutive bars in provider.
"""
import pytest
import numpy as np
from datetime import datetime, UTC, timedelta

import pyita as ta

from app.services.quotes.client import QuotesClient
from app.services.quotes.constants import TIME_TYPE
from app.services.quotes.timeframe import Timeframe
from app.services.tasks.quotes_provider import RealTimeQuotesProvider

SOURCE = "binance"
SYMBOL = "BTC/USDT"
TIMEFRAME = Timeframe.t1s
HISTORY_SIZE = 5
BARS_TO_RECEIVE = 3
BAR_TIMEOUT = 10  # seconds per bar


def _assert_bar_valid(bar_data: dict, label: str) -> None:
    """Verify that a bar_data dict contains a single valid OHLCV bar."""
    for key in ("time", "open", "high", "low", "close", "volume"):
        assert len(bar_data[key]) == 1, f"{label}: '{key}' array must have exactly 1 element"

    o = bar_data["open"][0]
    h = bar_data["high"][0]
    l = bar_data["low"][0]
    c = bar_data["close"][0]
    v = bar_data["volume"][0]

    assert o > 0, f"{label}: open must be positive, got {o}"
    assert h > 0, f"{label}: high must be positive, got {h}"
    assert l > 0, f"{label}: low must be positive, got {l}"
    assert c > 0, f"{label}: close must be positive, got {c}"
    assert v >= 0, f"{label}: volume must be non-negative, got {v}"
    assert h >= o, f"{label}: high {h} < open {o}"
    assert h >= c, f"{label}: high {h} < close {c}"
    assert l <= o, f"{label}: low {l} > open {o}"
    assert l <= c, f"{label}: low {l} > close {c}"


def test_realtime_subscription_binance_1s(quotes_service):
    """
    End-to-end test of the real-time bar subscription pipeline.

    Tests that:
    - Completed bars arrive from Binance via WebSocket in a timely manner.
    - Each arriving bar is exactly 1 second after the previous one
      (no gaps, no duplicates).
    - RealTimeQuotesProvider correctly accumulates bars (append_bar
      validates continuity internally and raises ValueError on violation).
    - After receiving BARS_TO_RECEIVE bars the provider contains
      HISTORY_SIZE + BARS_TO_RECEIVE strictly consecutive bars.
    """
    client = QuotesClient()

    # ------------------------------------------------------------------ #
    # Step 1: Subscribe before loading history.                           #
    #         This ensures the server's watch_ohlcv loop is already       #
    #         running when we receive the first bar, so we can use its    #
    #         timestamp to determine the correct history window.          #
    # ------------------------------------------------------------------ #
    client.subscribe(SOURCE, SYMBOL, TIMEFRAME)

    provider = None

    try:
        for i in range(BARS_TO_RECEIVE):
            label = f"Bar {i + 1}/{BARS_TO_RECEIVE}"

            # ---------------------------------------------------------- #
            # Step 2 / 6: Wait for the next completed bar.               #
            # ---------------------------------------------------------- #
            bar_data = client.wait_next_bar(SOURCE, SYMBOL, TIMEFRAME, timeout=BAR_TIMEOUT)
            assert bar_data is not None, f"{label}: timed out after {BAR_TIMEOUT}s"

            # ---------------------------------------------------------- #
            # Step 3: Validate OHLCV fields.                             #
            # ---------------------------------------------------------- #
            _assert_bar_valid(bar_data, label)

            bar_time = bar_data["time"][0]

            if provider is None:
                # ------------------------------------------------------- #
                # First bar received — load history whose last bar is      #
                # exactly one timeframe before this bar.                   #
                # This is the KEY step that eliminates gap/duplicate risk. #
                # ------------------------------------------------------- #
                history_end_dt64 = bar_time - TIMEFRAME.timedelta64()
                history_start_dt64 = history_end_dt64 - (HISTORY_SIZE - 1) * TIMEFRAME.timedelta64()

                # Convert numpy datetime64 to Python datetime for QuotesClient
                def dt64_to_dt(dt64: np.datetime64) -> datetime:
                    ms = int(dt64.astype("datetime64[ms]").astype(np.int64))
                    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)

                history_start = dt64_to_dt(history_start_dt64)
                history_end = dt64_to_dt(history_end_dt64)

                quotes_dict = client.get_quotes(
                    source=SOURCE,
                    symbol=SYMBOL,
                    timeframe=TIMEFRAME,
                    history_start=history_start,
                    history_end=history_end,
                    timeout=30,
                )

                assert len(quotes_dict["time"]) == HISTORY_SIZE, (
                    f"Expected {HISTORY_SIZE} historical bars, "
                    f"got {len(quotes_dict['time'])}"
                )

                primary_quotes = ta.Quotes(
                    time=quotes_dict["time"],
                    open=quotes_dict["open"],
                    high=quotes_dict["high"],
                    low=quotes_dict["low"],
                    close=quotes_dict["close"],
                    volume=quotes_dict["volume"],
                )

                provider = RealTimeQuotesProvider(
                    source=SOURCE,
                    symbol=SYMBOL,
                    timeframe=TIMEFRAME,
                    history_start=history_start,
                    primary_quotes=primary_quotes,
                )

                assert len(provider.primary.time) == HISTORY_SIZE

            # ---------------------------------------------------------- #
            # Step 4 (main): No gap, no duplicate — bar must follow      #
            # immediately after the last bar in the provider.            #
            # ---------------------------------------------------------- #
            expected_time = provider._time[-1] + TIMEFRAME.timedelta64()
            assert bar_time == expected_time, (
                f"{label}: expected bar at {expected_time}, got {bar_time}. "
                f"Gap or duplicate detected!"
            )

            # ---------------------------------------------------------- #
            # Step 5: Append — also validates continuity internally.     #
            #         Raises ValueError on gap or duplicate.             #
            # ---------------------------------------------------------- #
            provider.append_bar(bar_data)

            expected_total = HISTORY_SIZE + i + 1
            assert len(provider._time) == expected_total, (
                f"{label}: expected {expected_total} bars in provider, "
                f"got {len(provider._time)}"
            )

    finally:
        # Always unsubscribe, even if an assertion failed above
        client.unsubscribe(SOURCE, SYMBOL, TIMEFRAME)

    # ------------------------------------------------------------------ #
    # Step 7: Final state — all bars must be strictly consecutive.       #
    # ------------------------------------------------------------------ #
    assert provider is not None, "Provider was never created (no bars received)"

    final_quotes = provider.primary
    total_expected = HISTORY_SIZE + BARS_TO_RECEIVE
    assert len(final_quotes.time) == total_expected, (
        f"Expected {total_expected} bars total, got {len(final_quotes.time)}"
    )

    tf_delta = TIMEFRAME.timedelta64()
    for j in range(1, len(final_quotes.time)):
        diff = final_quotes.time[j] - final_quotes.time[j - 1]
        assert diff == tf_delta, (
            f"Non-consecutive bars at index {j}: "
            f"{final_quotes.time[j - 1]} -> {final_quotes.time[j]} "
            f"(gap = {diff}, expected {tf_delta})"
        )
