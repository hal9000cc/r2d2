"""
Cross-timeframe indicator and quotes proxy tests.

Verifies that indicators requested on a higher timeframe (1h)
from within a 5m strategy produce correct slice sizes and values.
Also tests QuotesProxy for accessing quotes of different timeframes/symbols.
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

import pyita as ta

from app.services.tasks.broker_backtesting import BrokerBacktesting
from app.services.tasks.strategy import Strategy
from app.services.tasks.tasks import Task
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.quotes.timeframe import Timeframe

BARS_PER_HOUR = 12  # 5m bars per 1h bar


# ============================================================================
# Strategy
# ============================================================================

class CrossTimeframeStrategy(Strategy):
    """Strategy that calculates SMA on 1h timeframe and saves results."""

    def __init__(self):
        super().__init__()

    def on_start(self, state=None):
        self.sma_period = self.parameters['sma_period']
        self.results = []
        self.bar_count = 0

    def on_bar(self):
        sma_close = self.ta.sma(period=self.sma_period, timeframe='1h')
        sma_high = self.ta.sma(period=self.sma_period, value='high', timeframe='1h')

        close_arr = sma_close['sma']
        high_arr = sma_high['sma']

        self.results.append({
            'bar_count': self.bar_count,
            'current_time': self.broker.current_time,
            'close_size': len(close_arr),
            'high_size': len(high_arr),
            'last_close': float(close_arr[-1]) if len(close_arr) > 0 else None,
            'last_high': float(high_arr[-1]) if len(high_arr) > 0 else None,
        })
        self.bar_count += 1


# ============================================================================
# Helpers
# ============================================================================

def generate_5m_quotes(n_bars, base_time=None):
    """Generate deterministic 5m OHLCV data with linear close trend."""
    if base_time is None:
        base_time = np.datetime64('2024-01-01T00:00:00', 'ms')

    time_arr = np.array(
        [base_time + np.timedelta64(i * 5, 'm') for i in range(n_bars)],
        dtype='datetime64[ms]',
    )

    close = (100.0 + np.arange(n_bars) * 0.1).astype(PRICE_TYPE)
    high = (close + 0.5).astype(PRICE_TYPE)
    low = (close - 0.3).astype(PRICE_TYPE)
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    volume = np.full(n_bars, 1000.0, dtype=VOLUME_TYPE)

    return {
        'time': time_arr,
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }


def aggregate_5m_to_1h(quotes_5m, start_idx=0):
    """Aggregate aligned 5m bars to 1h using reshape (vectorized)."""
    n = len(quotes_5m['time']) - start_idx
    n_hours = n // BARS_PER_HOUR
    trim = n_hours * BARS_PER_HOUR
    sl = slice(start_idx, start_idx + trim)

    def _reshape(arr):
        return arr[sl].reshape(n_hours, BARS_PER_HOUR)

    time_r = _reshape(quotes_5m['time'])
    open_r = _reshape(quotes_5m['open'])
    high_r = _reshape(quotes_5m['high'])
    low_r = _reshape(quotes_5m['low'])
    close_r = _reshape(quotes_5m['close'])
    volume_r = _reshape(quotes_5m['volume'])

    return {
        'time': time_r[:, 0].copy(),
        'open': open_r[:, 0].copy(),
        'high': high_r.max(axis=1),
        'low': low_r.min(axis=1),
        'close': close_r[:, -1].copy(),
        'volume': volume_r.sum(axis=1),
    }


def compute_sma(data, period):
    """Compute SMA; first (period-1) values are NaN."""
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result
    cs = np.cumsum(data)
    result[period - 1] = cs[period - 1] / period
    if n > period:
        result[period:] = (cs[period:] - cs[:-period]) / period
    return result


def generate_independent_1h_quotes(n_hours, base_time=None):
    """Generate independent 1h OHLCV data (not aggregated from 5m)."""
    if base_time is None:
        base_time = np.datetime64('2024-01-01T00:00:00', 'ms')

    time_arr = np.array(
        [base_time + np.timedelta64(i, 'h') for i in range(n_hours)],
        dtype='datetime64[ms]',
    )

    close = (100.0 + np.arange(n_hours) * 1.2).astype(PRICE_TYPE)
    high = (close + 0.5).astype(PRICE_TYPE)
    low = (close - 0.3).astype(PRICE_TYPE)
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    volume = np.full(n_hours, 12000.0, dtype=VOLUME_TYPE)

    return {
        'time': time_arr,
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }


def create_mock_task(history_size, sma_period, total_exec_bars, base_time_dt):
    """Create a mock Task for 5m cross-timeframe testing."""
    task = Mock(spec=Task)
    task.source = "test"
    task.symbol = "TEST/USDT"
    task.timeframe = "5m"

    exec_start = base_time_dt + timedelta(minutes=history_size * 5)
    exec_end = base_time_dt + timedelta(minutes=(history_size + total_exec_bars) * 5)

    task.dateStart = exec_start.isoformat()
    task.dateEnd = exec_end.isoformat()
    task.history_size = history_size
    task.precision_price = 0.01
    task.precision_amount = 0.001
    task.price_step = 0.1
    task.slippage_in_steps = 1.0
    task.fee_taker = 0.001
    task.fee_maker = 0.0005
    task.parameters = {'sma_period': sma_period}
    task._list = None
    task.get_redis_client = Mock(return_value=Mock())
    task.get_result_key = Mock(return_value="test:result")
    task.isRunning = True
    return task


def run_strategy(quotes_5m, quotes_1h, history_size, sma_period, total_exec_bars,
                 base_time_dt, mock_broker_cls, mock_provider_cls):
    """Setup mocks, create broker, run strategy, return strategy instance."""
    mock_client = Mock()

    def side_effect(source, symbol, timeframe, start, end):
        tf = timeframe if isinstance(timeframe, Timeframe) else Timeframe.cast(timeframe)
        if tf == Timeframe.t5m:
            return quotes_5m
        if tf == Timeframe.t1h:
            return quotes_1h
        raise ValueError(f"Unexpected timeframe: {tf}")

    mock_client.get_quotes.side_effect = side_effect
    mock_broker_cls.return_value = mock_client
    mock_provider_cls.return_value = mock_client

    task = create_mock_task(history_size, sma_period, total_exec_bars, base_time_dt)
    strategy = CrossTimeframeStrategy()
    callbacks = Strategy.create_strategy_callbacks(strategy)
    broker = BrokerBacktesting(task, result_id='test_cross_tf', callbacks_dict=callbacks)
    strategy.broker = broker
    broker.run(save_results=False)
    return strategy


# ============================================================================
# Tests
# ============================================================================

class TestIndicatorCrossTimeframe:

    @pytest.mark.parametrize("sma_period", [15, 50])
    @patch('app.services.tasks.quotes_provider.QuotesClient')
    @patch('app.services.tasks.broker_backtesting.QuotesClient')
    def test_sma_on_higher_timeframe(
        self, mock_broker_cls, mock_provider_cls, sma_period
    ):
        """SMA on close and high via 1h from 5m strategy (aligned start)."""
        history_size = 600
        total_exec_bars = 300
        base_time_dt = datetime(2024, 1, 1)
        base_time_np = np.datetime64('2024-01-01T00:00:00', 'ms')

        quotes_5m = generate_5m_quotes(history_size + total_exec_bars, base_time_np)
        quotes_1h = aggregate_5m_to_1h(quotes_5m)

        sma_close_exp = compute_sma(quotes_1h['close'], sma_period)
        sma_high_exp = compute_sma(quotes_1h['high'], sma_period)

        strategy = run_strategy(
            quotes_5m, quotes_1h, history_size, sma_period,
            total_exec_bars, base_time_dt, mock_broker_cls, mock_provider_cls,
        )

        assert strategy.bar_count == total_exec_bars

        checked_close = 0
        checked_high = 0
        for r in strategy.results:
            idx_5m = history_size + r['bar_count']
            expected_n = idx_5m // BARS_PER_HOUR

            # Size checks at beginning and end
            if r['bar_count'] < 5 or r['bar_count'] >= total_exec_bars - 5:
                assert r['close_size'] == expected_n, (
                    f"Bar {r['bar_count']}: close_size {r['close_size']} != {expected_n}"
                )
                assert r['high_size'] == expected_n, (
                    f"Bar {r['bar_count']}: high_size {r['high_size']} != {expected_n}"
                )

            # Value checks
            n = r['close_size']
            if n > 0 and not np.isnan(sma_close_exp[n - 1]):
                assert r['last_close'] is not None
                assert np.allclose(r['last_close'], sma_close_exp[n - 1], rtol=1e-5, atol=1e-8), (
                    f"Bar {r['bar_count']}: close SMA {r['last_close']} != {sma_close_exp[n - 1]}"
                )
                checked_close += 1

            n = r['high_size']
            if n > 0 and not np.isnan(sma_high_exp[n - 1]):
                assert r['last_high'] is not None
                assert np.allclose(r['last_high'], sma_high_exp[n - 1], rtol=1e-5, atol=1e-8), (
                    f"Bar {r['bar_count']}: high SMA {r['last_high']} != {sma_high_exp[n - 1]}"
                )
                checked_high += 1

        assert checked_close > 0, "No close SMA values were verified"
        assert checked_high > 0, "No high SMA values were verified"

    @patch('app.services.tasks.quotes_provider.QuotesClient')
    @patch('app.services.tasks.broker_backtesting.QuotesClient')
    def test_sma_first_bar_not_on_hour_boundary(self, mock_broker_cls, mock_provider_cls):
        """5m data starts at 00:15 (offset from hour boundary)."""
        sma_period = 15
        history_size = 200
        total_exec_bars = 300
        base_time_dt = datetime(2024, 1, 1, 0, 15, 0)
        base_time_np = np.datetime64('2024-01-01T00:15:00', 'ms')

        quotes_5m = generate_5m_quotes(history_size + total_exec_bars, base_time_np)
        quotes_1h = generate_independent_1h_quotes(50)

        sma_close_exp = compute_sma(quotes_1h['close'], sma_period)
        sma_high_exp = compute_sma(quotes_1h['high'], sma_period)

        strategy = run_strategy(
            quotes_5m, quotes_1h, history_size, sma_period,
            total_exec_bars, base_time_dt, mock_broker_cls, mock_provider_cls,
        )

        assert strategy.bar_count == total_exec_bars

        tf_1h = Timeframe.cast('1h')
        first_1h = quotes_1h['time'][0]
        one_hour = np.timedelta64(1, 'h')

        for r in strategy.results:
            forming = tf_1h.begin_of_tf(r['current_time'])
            if forming <= first_1h:
                expected_n = 0
            else:
                expected_n = int((forming - first_1h) // one_hour)
            expected_n = min(expected_n, len(quotes_1h['time']))

            # Size checks at beginning and end
            if r['bar_count'] < 5 or r['bar_count'] >= total_exec_bars - 5:
                assert r['close_size'] == expected_n, (
                    f"Bar {r['bar_count']} (t={r['current_time']}): "
                    f"close_size {r['close_size']} != {expected_n}"
                )
                assert r['high_size'] == expected_n, (
                    f"Bar {r['bar_count']} (t={r['current_time']}): "
                    f"high_size {r['high_size']} != {expected_n}"
                )

            # Value checks
            n = r['close_size']
            if n > 0 and not np.isnan(sma_close_exp[n - 1]):
                assert np.allclose(r['last_close'], sma_close_exp[n - 1], rtol=1e-5, atol=1e-8), (
                    f"Bar {r['bar_count']}: close SMA {r['last_close']} != {sma_close_exp[n - 1]}"
                )
            if n > 0 and not np.isnan(sma_high_exp[n - 1]):
                assert np.allclose(r['last_high'], sma_high_exp[n - 1], rtol=1e-5, atol=1e-8), (
                    f"Bar {r['bar_count']}: high SMA {r['last_high']} != {sma_high_exp[n - 1]}"
                )

    @patch('app.services.tasks.quotes_provider.QuotesClient')
    @patch('app.services.tasks.broker_backtesting.QuotesClient')
    def test_sma_last_bar_in_middle_of_hour(self, mock_broker_cls, mock_provider_cls):
        """5m data ends mid-hour; forming bar must not be included."""
        sma_period = 15
        history_size = 200
        # 507 total = 42*12 + 3 → last 3 bars in incomplete hour
        total_exec_bars = 307
        base_time_dt = datetime(2024, 1, 1)
        base_time_np = np.datetime64('2024-01-01T00:00:00', 'ms')

        quotes_5m = generate_5m_quotes(history_size + total_exec_bars, base_time_np)
        quotes_1h = aggregate_5m_to_1h(quotes_5m)  # 42 complete hours

        sma_close_exp = compute_sma(quotes_1h['close'], sma_period)
        sma_high_exp = compute_sma(quotes_1h['high'], sma_period)

        strategy = run_strategy(
            quotes_5m, quotes_1h, history_size, sma_period,
            total_exec_bars, base_time_dt, mock_broker_cls, mock_provider_cls,
        )

        assert strategy.bar_count == total_exec_bars

        tf_1h = Timeframe.cast('1h')

        # Verify last 5 bars: forming bar should NOT be included
        for r in strategy.results[-5:]:
            idx_5m = history_size + r['bar_count']
            expected_n = idx_5m // BARS_PER_HOUR

            assert r['close_size'] == expected_n, (
                f"Bar {r['bar_count']}: close_size {r['close_size']} != {expected_n}"
            )
            assert r['high_size'] == expected_n, (
                f"Bar {r['bar_count']}: high_size {r['high_size']} != {expected_n}"
            )

            forming = tf_1h.begin_of_tf(r['current_time'])
            if r['close_size'] > 0:
                last_closed_time = quotes_1h['time'][r['close_size'] - 1]
                assert last_closed_time < forming, (
                    f"Bar {r['bar_count']}: last closed 1h bar {last_closed_time} "
                    f"should be before forming bar {forming}"
                )

            n = r['close_size']
            if n > 0 and not np.isnan(sma_close_exp[n - 1]):
                assert np.allclose(r['last_close'], sma_close_exp[n - 1], rtol=1e-5, atol=1e-8), (
                    f"Bar {r['bar_count']}: close SMA {r['last_close']} != {sma_close_exp[n - 1]}"
                )
            if n > 0 and not np.isnan(sma_high_exp[n - 1]):
                assert np.allclose(r['last_high'], sma_high_exp[n - 1], rtol=1e-5, atol=1e-8), (
                    f"Bar {r['bar_count']}: high SMA {r['last_high']} != {sma_high_exp[n - 1]}"
                )

        # Also verify first 5 bars
        for r in strategy.results[:5]:
            idx_5m = history_size + r['bar_count']
            expected_n = idx_5m // BARS_PER_HOUR
            assert r['close_size'] == expected_n, (
                f"Bar {r['bar_count']}: close_size {r['close_size']} != {expected_n}"
            )


# ============================================================================
# QuotesProxy strategy and tests
# ============================================================================

class QuotesProxyStrategy(Strategy):
    """Strategy that uses self.quotes() proxy to get quotes on different TFs."""

    def __init__(self):
        super().__init__()

    def on_start(self, state=None):
        self.results = []
        self.bar_count = 0

    def on_bar(self):
        primary = self.quotes()
        higher_tf = self.quotes(timeframe='1h')

        self.results.append({
            'bar_count': self.bar_count,
            'current_time': self.broker.current_time,
            'proxy_len': len(self.quotes),
            'primary_len': len(primary.close),
            'primary_last_close': float(primary.close[-1]),
            'higher_len': len(higher_tf.close),
            'higher_last_close': float(higher_tf.close[-1]) if len(higher_tf.close) > 0 else None,
            'higher_last_high': float(higher_tf.high[-1]) if len(higher_tf.high) > 0 else None,
            'higher_last_time': higher_tf.time[-1] if len(higher_tf.time) > 0 else None,
        })
        self.bar_count += 1


def run_quotes_proxy_strategy(quotes_5m, quotes_1h, history_size, total_exec_bars,
                              base_time_dt, mock_broker_cls, mock_provider_cls):
    """Run strategy with QuotesProxy."""
    mock_client = Mock()

    def side_effect(source, symbol, timeframe, start, end):
        tf = timeframe if isinstance(timeframe, Timeframe) else Timeframe.cast(timeframe)
        if tf == Timeframe.t5m:
            return quotes_5m
        if tf == Timeframe.t1h:
            return quotes_1h
        raise ValueError(f"Unexpected timeframe: {tf}")

    mock_client.get_quotes.side_effect = side_effect
    mock_broker_cls.return_value = mock_client
    mock_provider_cls.return_value = mock_client

    task = create_mock_task(history_size, 20, total_exec_bars, base_time_dt)
    strategy = QuotesProxyStrategy()
    callbacks = Strategy.create_strategy_callbacks(strategy)
    broker = BrokerBacktesting(task, result_id='test_quotes_proxy', callbacks_dict=callbacks)
    strategy.broker = broker
    broker.run(save_results=False)
    return strategy


class TestQuotesProxy:

    @patch('app.services.tasks.quotes_provider.QuotesClient')
    @patch('app.services.tasks.broker_backtesting.QuotesClient')
    def test_primary_quotes(self, mock_broker_cls, mock_provider_cls):
        """self.quotes() returns primary quotes sliced to current bar."""
        history_size = 600
        total_exec_bars = 300
        base_time_dt = datetime(2024, 1, 1)
        base_time_np = np.datetime64('2024-01-01T00:00:00', 'ms')

        quotes_5m = generate_5m_quotes(history_size + total_exec_bars, base_time_np)
        quotes_1h = aggregate_5m_to_1h(quotes_5m)

        strategy = run_quotes_proxy_strategy(
            quotes_5m, quotes_1h, history_size, total_exec_bars,
            base_time_dt, mock_broker_cls, mock_provider_cls,
        )

        assert strategy.bar_count == total_exec_bars

        for r in strategy.results[:5] + strategy.results[-5:]:
            expected_len = history_size + r['bar_count'] + 1
            assert r['proxy_len'] == expected_len, (
                f"Bar {r['bar_count']}: proxy_len {r['proxy_len']} != {expected_len}"
            )
            assert r['primary_len'] == expected_len, (
                f"Bar {r['bar_count']}: primary_len {r['primary_len']} != {expected_len}"
            )
            expected_close = float(quotes_5m['close'][history_size + r['bar_count']])
            assert np.allclose(r['primary_last_close'], expected_close, rtol=1e-5, atol=1e-8)

    @patch('app.services.tasks.quotes_provider.QuotesClient')
    @patch('app.services.tasks.broker_backtesting.QuotesClient')
    def test_higher_tf_quotes(self, mock_broker_cls, mock_provider_cls):
        """self.quotes(timeframe='1h') returns closed 1h bars only."""
        history_size = 600
        total_exec_bars = 300
        base_time_dt = datetime(2024, 1, 1)
        base_time_np = np.datetime64('2024-01-01T00:00:00', 'ms')

        quotes_5m = generate_5m_quotes(history_size + total_exec_bars, base_time_np)
        quotes_1h = aggregate_5m_to_1h(quotes_5m)

        strategy = run_quotes_proxy_strategy(
            quotes_5m, quotes_1h, history_size, total_exec_bars,
            base_time_dt, mock_broker_cls, mock_provider_cls,
        )

        assert strategy.bar_count == total_exec_bars

        for r in strategy.results[:5] + strategy.results[-5:]:
            idx_5m = history_size + r['bar_count']
            expected_n = idx_5m // BARS_PER_HOUR
            assert r['higher_len'] == expected_n, (
                f"Bar {r['bar_count']}: higher_len {r['higher_len']} != {expected_n}"
            )

            if expected_n > 0:
                expected_close = float(quotes_1h['close'][expected_n - 1])
                assert np.allclose(r['higher_last_close'], expected_close, rtol=1e-5, atol=1e-8)

                expected_high = float(quotes_1h['high'][expected_n - 1])
                assert np.allclose(r['higher_last_high'], expected_high, rtol=1e-5, atol=1e-8)

                expected_time = quotes_1h['time'][expected_n - 1]
                assert r['higher_last_time'] == expected_time

    @patch('app.services.tasks.quotes_provider.QuotesClient')
    @patch('app.services.tasks.broker_backtesting.QuotesClient')
    def test_lower_tf_raises(self, mock_broker_cls, mock_provider_cls):
        """Requesting a timeframe lower than primary raises ValueError."""
        history_size = 24
        total_exec_bars = 12
        base_time_dt = datetime(2024, 1, 1)
        base_time_np = np.datetime64('2024-01-01T00:00:00', 'ms')

        quotes_5m = generate_5m_quotes(history_size + total_exec_bars, base_time_np)
        quotes_1h = aggregate_5m_to_1h(quotes_5m)

        mock_client = Mock()
        mock_client.get_quotes.return_value = quotes_5m
        mock_broker_cls.return_value = mock_client
        mock_provider_cls.return_value = mock_client

        class LowerTfStrategy(Strategy):
            def __init__(self):
                super().__init__()

            def on_start(self, state=None):
                self.error = None

            def on_bar(self):
                if self.error is None:
                    try:
                        self.quotes(timeframe='1m')
                    except ValueError as e:
                        self.error = str(e)

        task = create_mock_task(history_size, 20, total_exec_bars, base_time_dt)
        strategy = LowerTfStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        broker = BrokerBacktesting(task, result_id='test_lower_tf', callbacks_dict=callbacks)
        strategy.broker = broker
        broker.run(save_results=False)

        assert strategy.error is not None
        assert "lower than" in strategy.error

