"""
Integration tests for TA-Lib and pyita indicators.

Tests that indicator values computed during strategy execution match
direct library calls on the full dataset.
"""
import pytest
import numpy as np
import talib
import pyita as ta
from unittest.mock import Mock, patch
from typing import Dict, Any

from app.services.tasks.broker_backtesting import BrokerBacktesting
from app.services.tasks.strategy import Strategy
from app.services.tasks.tasks import Task
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from tests.test_broker_backtesting import create_test_quotes_data


class IndicatorTestStrategy(Strategy):
    """Test strategy that saves indicator values on each bar."""
    
    def __init__(self, proxy_name: str):
        super().__init__()
        self.proxy_name = proxy_name  # 'talib' or 'ta' (for pyita)
        self.saved_indicators: Dict[int, Dict[str, ta.IndicatorResult]] = {}
        self.bar_index = -1
    
    def on_bar(self):
        """Calculate and save indicators on each bar."""
        self.bar_index += 1
        
        # Get proxy (talib or ta for pyita)
        proxy = getattr(self, self.proxy_name)
        
        # Calculate indicators
        if self.proxy_name == 'talib':
            sma = proxy.SMA(value='close', timeperiod=20)
            bb = proxy.BBANDS(value='close', timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
            macd = proxy.MACD(value='close', fastperiod=12, slowperiod=26, signalperiod=9)
        else:  # ta (pyita)
            sma = proxy.sma(period=20)
            bb = proxy.bollinger_bands(period=20, deviation=2)
            macd = proxy.macd(period_short=12, period_long=26, period_signal=9)
        
        # Save IndicatorResult objects
        self.saved_indicators[self.bar_index] = {
            'sma': sma,
            'bollinger_bands': bb,
            'macd': macd
        }


def create_mock_task(quotes_data: Dict[str, np.ndarray], history_size: int = 100) -> Task:
    """Create a mock Task for testing."""
    task = Mock(spec=Task)
    task.source = "test"
    task.symbol = "TEST/USDT"
    task.timeframe = "1h"
    task.dateStart = "2024-01-01T00:00:00Z"
    task.dateEnd = "2024-01-11T00:00:00Z"
    task.history_size = history_size
    task.precision_price = 0.01
    task.precision_amount = 0.001  # Note: precision_amount, not precision_volume
    task.price_step = 0.1
    task.slippage_in_steps = 1.0
    task.fee_taker = 0.001
    task.fee_maker = 0.0005
    task.parameters = {}
    task._list = None  # Standalone mode - skip state updates
    task.get_redis_client = Mock(return_value=Mock())
    task.get_result_key = Mock(return_value="test:result")
    return task


def convert_talib_result_to_indicator_result(indicator_name: str, talib_result) -> ta.IndicatorResult:
    """Convert TA-Lib result to IndicatorResult."""
    if indicator_name == 'SMA':
        return ta.IndicatorResult({'SMA': talib_result})
    elif indicator_name == 'BBANDS':
        return ta.IndicatorResult({
            'upperband': talib_result[0],
            'middleband': talib_result[1],
            'lowerband': talib_result[2]
        })
    elif indicator_name == 'MACD':
        return ta.IndicatorResult({
            'macd': talib_result[0],
            'macdsignal': talib_result[1],
            'macdhist': talib_result[2]
        })
    else:
        raise ValueError(f"Unknown indicator: {indicator_name}")


def get_series_names_from_result(indicator_result: ta.IndicatorResult, indicator_name: str, proxy_name: str) -> list:
    """Extract series names from IndicatorResult by trying known names."""
    known_names = []
    
    if indicator_name in ('SMA', 'sma'):
        known_names = ['SMA'] if proxy_name == 'talib' else ['sma']
    elif indicator_name in ('BBANDS', 'bollinger_bands'):
        if proxy_name == 'talib':
            known_names = ['upperband', 'middleband', 'lowerband']
        else:  # pyita
            known_names = ['up_line', 'mid_line', 'down_line']
    elif indicator_name in ('MACD', 'macd'):
        if proxy_name == 'talib':
            known_names = ['macd', 'macdsignal', 'macdhist']
        else:  # pyita
            known_names = ['macd', 'signal', 'hist']
    
    # Try to access each known name and collect those that exist
    existing_names = []
    for name in known_names:
        try:
            _ = indicator_result[name]
            existing_names.append(name)
        except (KeyError, AttributeError):
            pass
    
    return existing_names if existing_names else known_names


def get_series_names_for_indicator(indicator_name: str, proxy_name: str) -> list:
    """Get expected series names for an indicator."""
    if indicator_name in ('SMA', 'sma'):
        return ['SMA'] if proxy_name == 'talib' else ['sma']
    elif indicator_name in ('BBANDS', 'bollinger_bands'):
        if proxy_name == 'talib':
            return ['upperband', 'middleband', 'lowerband']
        else:  # pyita
            return ['up_line', 'mid_line', 'down_line']
    elif indicator_name in ('MACD', 'macd'):
        if proxy_name == 'talib':
            return ['macd', 'macdsignal', 'macdhist']
        else:  # pyita
            return ['macd', 'signal', 'hist']
    else:
        raise ValueError(f"Unknown indicator: {indicator_name}")


def compare_indicator_results(
    saved: ta.IndicatorResult,
    computed: ta.IndicatorResult,
    indicator_name: str,
    proxy_name: str
) -> None:
    """Compare saved indicator result with computed result."""
    # Get series names from computed result (more reliable)
    series_names = get_series_names_from_result(computed, indicator_name, proxy_name)
    
    # If we couldn't get names from computed, try saved
    if not series_names:
        series_names = get_series_names_from_result(saved, indicator_name, proxy_name)
    
    # Fallback to known names
    if not series_names:
        series_names = get_series_names_for_indicator(indicator_name, proxy_name)
    
    for series_name in series_names:
        # Extract arrays
        saved_array = saved[series_name]
        computed_array = computed[series_name]
        
        # Get length of saved array
        length = len(saved_array)
        
        # Take slice from computed array
        computed_slice = computed_array[:length]
        
        # Replace NaN with 0
        saved_array = np.nan_to_num(saved_array, nan=0.0)
        computed_slice = np.nan_to_num(computed_slice, nan=0.0)
        
        # Compare arrays
        assert np.array_equal(saved_array, computed_slice), (
            f"Indicator {indicator_name}, series {series_name} mismatch:\n"
            f"Saved: {saved_array}\n"
            f"Computed: {computed_slice}"
        )


@pytest.fixture
def quotes_data_110_bars():
    """Create 110 bars of test quotes data."""
    return create_test_quotes_data(n_bars=110, start_price=100.0, trend='up')


@patch('app.services.tasks.broker_backtesting.QuotesClient')
def test_talib_indicators_integration(mock_quotes_client_class, quotes_data_110_bars):
    """Test that TA-Lib indicators computed during strategy match direct library calls."""
    # Setup mock QuotesClient
    mock_client = Mock()
    mock_client.get_quotes.return_value = quotes_data_110_bars
    mock_quotes_client_class.return_value = mock_client
    
    # Create mock task
    task = create_mock_task(quotes_data_110_bars, history_size=100)
    
    # Create strategy
    strategy = IndicatorTestStrategy(proxy_name='talib')
    
    # Create callbacks from strategy
    callbacks = Strategy.create_strategy_callbacks(strategy)
    
    # Create broker
    broker = BrokerBacktesting(task, result_id='test_result', callbacks_dict=callbacks)
    
    # Run strategy (will execute 10 bars: 100-109)
    broker.run(save_results=False)
    
    # Verify we executed 10 bars
    assert len(strategy.saved_indicators) == 10, f"Expected 10 bars, got {len(strategy.saved_indicators)}"
    
    # Extract arrays for direct TA-Lib calls
    close = quotes_data_110_bars['close']
    
    # Compute indicators directly using TA-Lib
    sma_computed = talib.SMA(close, timeperiod=20)
    bb_computed = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    macd_computed = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    
    # Convert to IndicatorResult
    sma_result = convert_talib_result_to_indicator_result('SMA', sma_computed)
    bb_result = convert_talib_result_to_indicator_result('BBANDS', bb_computed)
    macd_result = convert_talib_result_to_indicator_result('MACD', macd_computed)
    
    # Compare for each bar
    for bar_index in range(10):
        # Compare SMA
        compare_indicator_results(
            strategy.saved_indicators[bar_index]['sma'],
            sma_result,
            'SMA',
            'talib'
        )
        
        # Compare Bollinger Bands
        compare_indicator_results(
            strategy.saved_indicators[bar_index]['bollinger_bands'],
            bb_result,
            'BBANDS',
            'talib'
        )
        
        # Compare MACD
        compare_indicator_results(
            strategy.saved_indicators[bar_index]['macd'],
            macd_result,
            'MACD',
            'talib'
        )


@patch('app.services.tasks.broker_backtesting.QuotesClient')
def test_pyita_indicators_integration(mock_quotes_client_class, quotes_data_110_bars):
    """Test that pyita indicators computed during strategy match direct library calls."""
    # Setup mock QuotesClient
    mock_client = Mock()
    mock_client.get_quotes.return_value = quotes_data_110_bars
    mock_quotes_client_class.return_value = mock_client
    
    # Create mock task
    task = create_mock_task(quotes_data_110_bars, history_size=100)
    
    # Create strategy (use 'ta' as proxy_name, as that's what broker.run() creates)
    strategy = IndicatorTestStrategy(proxy_name='ta')
    
    # Create callbacks from strategy
    callbacks = Strategy.create_strategy_callbacks(strategy)
    
    # Create broker
    broker = BrokerBacktesting(task, result_id='test_result', callbacks_dict=callbacks)
    
    # Run strategy (will execute 10 bars: 100-109)
    broker.run(save_results=False)
    
    # Verify we executed 10 bars
    assert len(strategy.saved_indicators) == 10, f"Expected 10 bars, got {len(strategy.saved_indicators)}"
    
    # Create Quotes object for direct pyita calls
    quotes_full = ta.Quotes(**quotes_data_110_bars)
    
    # Compute indicators directly using pyita
    sma_result = ta.sma(quotes_full, period=20)
    bb_result = ta.bollinger_bands(quotes_full, period=20, deviation=2)
    macd_result = ta.macd(quotes_full, period_short=12, period_long=26, period_signal=9)
    
    # Compare for each bar
    for bar_index in range(10):
        # Compare SMA
        compare_indicator_results(
            strategy.saved_indicators[bar_index]['sma'],
            sma_result,
            'sma',
            'pyita'
        )
        
        # Compare Bollinger Bands
        compare_indicator_results(
            strategy.saved_indicators[bar_index]['bollinger_bands'],
            bb_result,
            'bollinger_bands',
            'pyita'
        )
        
        # Compare MACD
        compare_indicator_results(
            strategy.saved_indicators[bar_index]['macd'],
            macd_result,
            'macd',
            'pyita'
        )

