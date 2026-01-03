"""
Test for Strategy with moving average crossover strategy.
"""
import pytest
import numpy as np
from typing import Dict, Tuple, Any
from app.services.tasks.tasks import Task
from app.services.tasks.strategy import Strategy
from app.services.tasks.broker import OrderSide


@pytest.fixture(scope='module')
def app_startup(quotes_service):
    """
    Fixture to ensure quotes service and Redis are running for strategy tests.
    Reuses shared quotes_service fixture defined in conftest.py.
    """
    # quotes_service session fixture guarantees quotes server + Redis are up
    yield


class MovingAverageCrossoverStrategy(Strategy):
    """
    Simple moving average crossover strategy.
    Buys when fast MA crosses above slow MA, sells when fast MA crosses below slow MA.
    """
    
    def __init__(self):
        super().__init__()
        self.ma_fast_period = None
        self.ma_slow_period = None
        self.ma_fast = None
        self.ma_slow = None
        self.position = None  # 'long', 'short', or None
    
    def on_start(self):
        """
        Initialize strategy parameters from self.parameters.
        """
        self.ma_fast_period = self.parameters['ma_fast']
        self.ma_slow_period = self.parameters['ma_slow']
    
    @staticmethod
    def get_parameters_description() -> Dict[str, Tuple[Any, str]]:
        """
        Get parameters description of the strategy.
        
        Returns:
            Dictionary where keys are parameter names (str) and values are tuples
            of (default_value, description). Type is determined automatically from default_value.
        """
        return {
            'ma_fast': (20, 'Fast moving average period'),
            'ma_slow': (100, 'Slow moving average period')
        }
    
    def on_bar(self):
        """
        Called when a new bar is received.
        Implements moving average crossover logic.
        """
        close_prices = self.close

        if len(close_prices) < self.ma_slow_period:
            return
        
        if len(close_prices) < self.ma_slow_period + 1:
            return
        
        self.ma_fast = self.talib.SMA(value='close', timeperiod=self.ma_fast_period)
        self.ma_slow = self.talib.SMA(value='close', timeperiod=self.ma_slow_period)
        
        valid_slow_indices = ~np.isnan(self.ma_slow)
        if not np.any(valid_slow_indices) or np.sum(valid_slow_indices) < 2:
            return
        
        # Get last two valid indices
        valid_indices = np.where(valid_slow_indices)[0]
        if len(valid_indices) < 2:
            return
        
        prev_idx = valid_indices[-2]
        curr_idx = valid_indices[-1]
        
        # Get MA values
        prev_fast = self.ma_fast[prev_idx]
        prev_slow = self.ma_slow[prev_idx]
        current_fast = self.ma_fast[curr_idx]
        current_slow = self.ma_slow[curr_idx]
        
        # Check for crossover
        # Bullish crossover: fast MA crosses above slow MA
        if prev_fast <= prev_slow and current_fast > current_slow:
            if self.position != 'long':
                # Buy signal
                self.order(OrderSide.BUY, quantity=0.001)  # Small quantity for testing
                self.position = 'long'
        
        # Bearish crossover: fast MA crosses below slow MA
        elif prev_fast >= prev_slow and current_fast < current_slow:
            if self.position == 'long':
                # Sell signal
                self.order(OrderSide.SELL, quantity=0.001)
                self.position = None


def test_moving_average_crossover_strategy(app_startup):
    """
    Test moving average crossover strategy on BTC/USDT hourly data.
    """
    # Create task with test parameters
    task = Task(
        id=1,
        file_name="ma_crossover.py",
        name="Moving Average Crossover Test",
        source="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        isRunning=False,
        dateStart="2025-01-01T00:00:00",
        dateEnd="2025-04-01T00:00:00",
        parameters={
            "ma_fast": 80,
            "ma_slow": 100
        }
    )
    
    # Create strategy instance
    strategy = MovingAverageCrossoverStrategy()
    
    # Create broker with strategy callbacks and run
    from app.services.tasks.broker_backtesting import BrokerBacktesting
    from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
    callbacks = Strategy.create_strategy_callbacks(strategy)
    broker = BrokerBacktesting(
        fee=0.001,
        task=task,
        result_id="test-result-id",
        callbacks_dict=callbacks,
        results_save_period=TRADE_RESULTS_SAVE_PERIOD
    )
    strategy.broker = broker
    broker.run(save_results=False)
    
    # Basic assertions - strategy should have processed data
    assert strategy.close is not None, "Close prices should be loaded"
    assert len(strategy.close) > 0, "Should have at least some price data"
    
    # Check that broker was created
    assert strategy.broker is not None, "Broker should be created after run()"
    
    # Check that all positions are closed (equity_symbol == 0)
    assert strategy.broker.equity_symbol == 0, "All positions should be closed (equity_symbol == 0)"
    
    # Check that indicators were calculated
    assert strategy.ma_fast is not None, "Fast MA should be calculated"
    assert strategy.ma_slow is not None, "Slow MA should be calculated"
    
    # Check that indicators have correct length (should match close prices length)
    assert len(strategy.ma_fast) == len(strategy.close), "Fast MA length should match close prices length"
    assert len(strategy.ma_slow) == len(strategy.close), "Slow MA length should match close prices length"
    
    # Check that indicators contain valid values (not all NaN)
    assert np.any(~np.isnan(strategy.ma_fast)), "Fast MA should have at least some valid values"
    assert np.any(~np.isnan(strategy.ma_slow)), "Slow MA should have at least some valid values"
    
    # Check that position was closed (strategy should close position at the end)
    assert strategy.position is None, "Position should be closed at the end"
    
    # Check that trades were executed (should have at least some trades if strategy worked)
    assert len(strategy.broker.trades) > 0, "Strategy should have executed at least some trades"
    
    # Check that deals were created and closed
    assert strategy.broker.deals is not None, "Deals list should be initialized"
    assert len(strategy.broker.deals) > 0, "Should have at least one deal"
    # All deals should be closed
    for deal in strategy.broker.deals:
        assert deal.is_closed, f"Deal {deal.deal_id} should be closed"
