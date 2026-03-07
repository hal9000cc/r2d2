"""
Quotes provider classes for strategy execution.
Provides access to quotes data for different symbols and timeframes.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np
import pyita as ta

from app.services.quotes.timeframe import Timeframe
from app.services.quotes.client import QuotesClient
from app.services.quotes.constants import TIME_TYPE
from app.core.datetime_utils import datetime64_to_datetime
from app.core.logger import get_logger

logger = get_logger(__name__)


class QuotesProvider(ABC):
    """
    Abstract base class for quotes data access.
    Provides quotes for different symbols and timeframes.
    """

    @property
    @abstractmethod
    def primary(self) -> ta.Quotes:
        """Primary quotes (main symbol and timeframe)."""
        pass

    @property
    @abstractmethod
    def primary_timeframe(self) -> Timeframe:
        """Primary timeframe."""
        pass

    @abstractmethod
    def get_quotes(self, symbol: str, timeframe: Timeframe) -> ta.Quotes:
        """
        Get quotes for the specified symbol and timeframe.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT:USDT')
            timeframe: Timeframe object

        Returns:
            Quotes object with OHLCV data
        """
        pass

    def get_slice_size(self, quotes: ta.Quotes, timeframe: Timeframe, current_time: np.datetime64) -> int:
        """
        Calculate slice size for indicator on the given timeframe at current_time.

        For primary timeframe: includes the current bar (it's complete in backtesting).
        For higher timeframe: only closed bars (excludes the forming bar).

        Args:
            quotes: Quotes data for the requested timeframe
            timeframe: Requested timeframe
            current_time: Current bar time from broker

        Returns:
            Number of bars to include in the slice
        """
        if len(quotes.time) == 0:
            return 0

        first_bar_time = quotes.time[0]
        tf_duration = timeframe.timedelta64()

        if timeframe == self.primary_timeframe:
            if current_time < first_bar_time:
                return 0
            n_bars = int((current_time - first_bar_time) // tf_duration) + 1
            expected_last = current_time
        else:
            forming_bar_start = timeframe.begin_of_tf(current_time)
            if forming_bar_start <= first_bar_time:
                return 0
            n_bars = int((forming_bar_start - first_bar_time) // tf_duration)
            expected_last = forming_bar_start - tf_duration

        n_bars = min(n_bars, len(quotes.time))

        if n_bars > 0:
            assert quotes.time[n_bars - 1] == expected_last, (
                f"Slice verification failed: expected last bar at {expected_last}, "
                f"got {quotes.time[n_bars - 1]} (n_bars={n_bars}, timeframe={timeframe}, "
                f"current_time={current_time})"
            )

        return n_bars


class BacktestingQuotesProvider(QuotesProvider):
    """
    Quotes provider for backtesting mode.
    Loads quotes on demand and caches them for the entire backtesting period.
    """

    def __init__(
        self,
        source: str,
        symbol: str,
        timeframe: Timeframe,
        history_start: datetime,
        date_end: datetime,
        primary_quotes: ta.Quotes
    ):
        """
        Initialize backtesting quotes provider.

        Args:
            source: Data source (e.g., 'binance')
            symbol: Primary trading symbol
            timeframe: Primary timeframe
            history_start: Start date including history period
            date_end: End date for backtesting period
            primary_quotes: Pre-loaded primary quotes data
        """
        self._source = source
        self._primary_symbol = symbol
        self._primary_timeframe = timeframe
        self._history_start = history_start
        self._date_end = date_end
        self._cache: Dict[Tuple[str, Timeframe], ta.Quotes] = {
            (symbol, timeframe): primary_quotes
        }

    @property
    def primary(self) -> ta.Quotes:
        return self._cache[(self._primary_symbol, self._primary_timeframe)]

    @property
    def primary_timeframe(self) -> Timeframe:
        return self._primary_timeframe

    def get_quotes(self, symbol: str, timeframe: Timeframe) -> ta.Quotes:
        """
        Get quotes for the specified symbol and timeframe.
        Loads from QuotesClient on first access, then caches.

        Only timeframes >= primary timeframe are supported.
        """
        key = (symbol, timeframe)
        if key not in self._cache:
            if timeframe < self._primary_timeframe:
                raise ValueError(
                    f"Requested timeframe {timeframe} is lower than "
                    f"primary timeframe {self._primary_timeframe}. "
                    f"Only higher or equal timeframes are supported."
                )

            client = QuotesClient()
            logger.debug(
                f"Loading additional quotes: {self._source}:{symbol}:{timeframe} "
                f"from {self._history_start} to {self._date_end}"
            )
            quotes_dict = client.get_quotes(
                self._source, symbol, timeframe,
                self._history_start, self._date_end
            )

            if len(quotes_dict['time']) == 0:
                raise RuntimeError(
                    f"No quotes data available for {symbol}:{timeframe}"
                )

            self._cache[key] = ta.Quotes(**{k: quotes_dict[k] for k in ('time', 'open', 'high', 'low', 'close', 'volume')})
            logger.debug(f"Additional quotes loaded: {len(quotes_dict['time'])} bars")

        return self._cache[key]


class RealTimeQuotesProvider(QuotesProvider):
    """
    Quotes provider for live (real-time) trading mode.

    Initialised with pre-loaded historical data.  After each completed bar
    arrives from the WebSocket subscription the caller must call
    append_bar() to extend the primary series.

    Higher timeframes are fetched on demand from ClickHouse via QuotesClient
    (same as BacktestingQuotesProvider), but the cache is invalidated on every
    append_bar() call so that the next access always reflects the latest data.
    """

    def __init__(
        self,
        source: str,
        symbol: str,
        timeframe: Timeframe,
        history_start: datetime,
        primary_quotes: ta.Quotes,
    ):
        """
        Initialize the real-time quotes provider.

        Args:
            source: Exchange name (e.g., 'binance')
            symbol: Primary trading symbol (e.g., 'BTC/USDT')
            timeframe: Primary timeframe
            history_start: Start date used when fetching historical data
            primary_quotes: Pre-loaded primary quotes (history up to now)
        """
        self._source = source
        self._primary_symbol = symbol
        self._primary_timeframe = timeframe
        self._history_start = history_start

        # Mutable arrays for primary series (new bars are appended)
        self._time: np.ndarray = np.copy(primary_quotes.time)
        self._open: np.ndarray = np.copy(primary_quotes.open)
        self._high: np.ndarray = np.copy(primary_quotes.high)
        self._low: np.ndarray = np.copy(primary_quotes.low)
        self._close: np.ndarray = np.copy(primary_quotes.close)
        self._volume: np.ndarray = np.copy(primary_quotes.volume)

        # Cache for higher-timeframe quotes, cleared on each append_bar()
        self._cache: Dict[Tuple[str, Timeframe], ta.Quotes] = {}

    # ------------------------------------------------------------------
    # QuotesProvider interface
    # ------------------------------------------------------------------

    @property
    def primary(self) -> ta.Quotes:
        """Return current primary quotes (rebuilt from mutable arrays)."""
        return ta.Quotes(
            time=self._time,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
        )

    @property
    def primary_timeframe(self) -> Timeframe:
        return self._primary_timeframe

    def get_quotes(self, symbol: str, timeframe: Timeframe) -> ta.Quotes:
        """
        Get quotes for the specified symbol and timeframe.

        For the primary symbol+timeframe returns the live-updated series.
        For other combinations fetches from ClickHouse via QuotesClient and
        caches until the next append_bar() call.

        Only timeframes >= primary timeframe are supported.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe object

        Returns:
            ta.Quotes with OHLCV data

        Raises:
            ValueError: If requested timeframe is lower than primary
            RuntimeError: If no data is available
        """
        if symbol == self._primary_symbol and timeframe == self._primary_timeframe:
            return self.primary

        key = (symbol, timeframe)
        if key not in self._cache:
            if timeframe < self._primary_timeframe:
                raise ValueError(
                    f"Requested timeframe {timeframe} is lower than "
                    f"primary timeframe {self._primary_timeframe}. "
                    f"Only higher or equal timeframes are supported."
                )

            if len(self._time) == 0:
                raise RuntimeError("No primary quotes available yet")

            # Use the timestamp of the last primary bar as the end boundary
            date_end = datetime64_to_datetime(self._time[-1])

            client = QuotesClient()
            logger.debug(
                "Loading higher-TF quotes: %s:%s:%s from %s to %s",
                self._source, symbol, timeframe,
                self._history_start, date_end,
            )
            quotes_dict = client.get_quotes(
                self._source, symbol, timeframe,
                self._history_start, date_end,
            )

            if len(quotes_dict["time"]) == 0:
                raise RuntimeError(
                    f"No quotes data available for {symbol}:{timeframe}"
                )

            self._cache[key] = ta.Quotes(
                **{k: quotes_dict[k] for k in ("time", "open", "high", "low", "close", "volume")}
            )
            logger.debug(
                "Higher-TF quotes loaded: %d bars for %s:%s",
                len(quotes_dict["time"]), symbol, timeframe,
            )

        return self._cache[key]

    # ------------------------------------------------------------------
    # Real-time specific methods
    # ------------------------------------------------------------------

    def append_bar(self, bar_data: dict) -> None:
        """
        Append a new completed bar to the primary series.

        Verifies that the incoming bar is the immediately expected next bar
        (no gaps allowed).  After appending, invalidates the higher-TF cache
        so that the next get_quotes() call fetches fresh data from ClickHouse.

        Args:
            bar_data: Dict with 1-element numpy arrays:
                      {time, open, high, low, close, volume}
                      (as returned by QuotesClient.wait_next_bar())

        Raises:
            ValueError: If the bar timestamp is not the expected next bar
                        (gap detected in the real-time stream).
        """
        new_time = bar_data["time"][0]

        if len(self._time) > 0:
            expected_time = self._time[-1] + self._primary_timeframe.timedelta64()
            if new_time != expected_time:
                raise ValueError(
                    f"Gap in real-time data: expected next bar at "
                    f"{expected_time}, got {new_time}."
                )

        self._time = np.append(self._time, bar_data["time"])
        self._open = np.append(self._open, bar_data["open"])
        self._high = np.append(self._high, bar_data["high"])
        self._low = np.append(self._low, bar_data["low"])
        self._close = np.append(self._close, bar_data["close"])
        self._volume = np.append(self._volume, bar_data["volume"])

        # Invalidate higher-TF cache so the next access re-fetches from DB
        self._cache.clear()

        logger.debug("Appended bar at %s; total primary bars: %d", new_time, len(self._time))

    def verify_higher_timeframe(
        self,
        symbol: str,
        timeframe: Timeframe,
        current_time: np.datetime64,
    ) -> bool:
        """
        Check that the cached higher-TF data is complete up to current_time.

        The last bar in the cached series should equal the last fully closed
        higher-TF bar relative to current_time.

        Args:
            symbol: Trading symbol
            timeframe: Higher timeframe to verify
            current_time: Latest primary bar timestamp

        Returns:
            True if data is current and complete, False otherwise.
        """
        key = (symbol, timeframe)
        if key not in self._cache:
            return False

        quotes = self._cache[key]
        if len(quotes.time) == 0:
            return False

        forming_bar_start = timeframe.begin_of_tf(current_time)
        expected_last_bar = forming_bar_start - timeframe.timedelta64()

        return bool(quotes.time[-1] == expected_last_bar)

