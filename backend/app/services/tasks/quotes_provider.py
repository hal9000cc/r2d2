"""
Quotes provider classes for strategy execution.
Provides access to quotes data for different symbols and timeframes.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Tuple

import numpy as np
import pyita as ta

from app.services.quotes.timeframe import Timeframe
from app.services.quotes.client import QuotesClient
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

            self._cache[key] = ta.Quotes(**quotes_dict)
            logger.debug(f"Additional quotes loaded: {len(quotes_dict['time'])} bars")

        return self._cache[key]

