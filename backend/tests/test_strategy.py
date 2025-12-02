"""
Test for StrategyBacktest with moving average crossover strategy.
"""
import pytest
import numpy as np
from datetime import datetime
from app.services.tasks.tasks import Task
from app.services.tasks.strategy import StrategyBacktest, OrderSide
from app.core.startup import startup


@pytest.fixture(scope='module')
def app_startup():
    """
    Fixture to initialize application services once for all tests in this module.
    """
    startup()
    yield
    # Cleanup if needed (shutdown is handled by pytest)


class MovingAverageCrossoverStrategy(StrategyBacktest):
    """
    Simple moving average crossover strategy.
    Buys when fast MA crosses above slow MA, sells when fast MA crosses below slow MA.
    """
    
    def __init__(self, task: Task):
        super().__init__(task)
        self.ma_fast_period = task.parameters.get('ma_fast', 20)
        self.ma_slow_period = task.parameters.get('ma_slow', 100)
        self.ma_fast = None
        self.ma_slow = None
        self.position = None  # 'long', 'short', or None
    
    def on_bar(self):
        """
        Called when a new bar is received.
        Implements moving average crossover logic.
        """
        if self.close is None or len(self.close) < self.ma_slow_period:
            # Not enough data yet
            return
        
        # Calculate moving averages using TA-Lib
        import talib
        
        # Get close prices as numpy array
        # self.close is already a numpy array from run()
        close_prices = self.close
        
        # Calculate MAs for all available data
        self.ma_fast = talib.SMA(close_prices, timeperiod=self.ma_fast_period)
        self.ma_slow = talib.SMA(close_prices, timeperiod=self.ma_slow_period)
        
        # Need at least ma_slow_period + 1 bars to have valid MA values
        # and at least 2 valid MA values to detect crossover
        if len(close_prices) < self.ma_slow_period + 1:
            return
        
        # Get last valid MA values (skip NaN values at the beginning)
        # Find first non-NaN index for slow MA
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
        active_strategy_id=1,
        strategy_id="ma_crossover",
        name="Moving Average Crossover Test",
        source="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        isRunning=False,
        isTrading=False,
        dateStart="2025-01-01T00:00:00",
        dateEnd="2025-04-01T00:00:00",
        parameters={
            "ma_fast": 20,
            "ma_slow": 100
        }
    )
    
    # Create strategy instance
    strategy = MovingAverageCrossoverStrategy(task)
    
    # Run strategy
    strategy.run()
    
    # Basic assertions - strategy should have processed data
    assert strategy.close is not None, "Close prices should be loaded"
    assert len(strategy.close) > 0, "Should have at least some price data"
