"""
Test for StrategyBacktest with moving average crossover strategy.
"""
import pytest
import numpy as np
from datetime import datetime
from typing import Dict, Tuple, Any
from app.services.tasks.tasks import Task
from app.services.tasks.strategy import StrategyBacktest, OrderSide
from app.core.startup import startup, shutdown
from app.services.quotes.client import Client
from app.core.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
import talib


@pytest.fixture(scope='module')
def app_startup():
    """
    Fixture to initialize application services once for all tests in this module.
    Uses production database (not test database).
    Services are started independently from quotes_service.
    """
    # Start services with production configuration
    startup()
    
    # Initialize quotes client with correct Redis connection parameters
    redis_params = {
        'host': REDIS_HOST,
        'port': REDIS_PORT,
        'db': REDIS_DB,
        'password': REDIS_PASSWORD
    }
    Client(redis_params=redis_params)
    
    yield
    
    # Cleanup: shutdown application services
    shutdown()


class MovingAverageCrossoverStrategy(StrategyBacktest):
    """
    Simple moving average crossover strategy.
    Buys when fast MA crosses above slow MA, sells when fast MA crosses below slow MA.
    """
    
    def __init__(self, task: Task):
        super().__init__(task)
        self.ma_fast_period = task.parameters['ma_fast']
        self.ma_slow_period = task.parameters['ma_slow']
        self.ma_fast = None
        self.ma_slow = None
        self.position = None  # 'long', 'short', or None
    
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
        
        self.ma_fast = talib.SMA(close_prices, timeperiod=self.ma_fast_period)
        self.ma_slow = talib.SMA(close_prices, timeperiod=self.ma_slow_period)
        
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
            "ma_fast": 80,
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
    
    # Check that global deal is closed (symbol_balance == 0)
    assert strategy.global_deal.symbol_balance == 0, "Global deal should be closed (symbol_balance == 0)"
    
    # Check that current deal is None
    assert strategy.current_deal is None, "Current deal should be None after run()"
    
    # Check that all deals in the list are closed
    for deal in strategy.deals:
        assert deal.exit_time is not None, f"Deal should have exit_time set"
        assert deal.exit_price is not None, f"Deal should have exit_price set"
        assert deal.symbol_balance == 0, f"Deal should have symbol_balance == 0 (got {deal.symbol_balance})"
    
    # Check that sum of all closed deals' balance equals global deal's balance
    total_deals_balance = sum(deal.balance for deal in strategy.deals)
    assert abs(total_deals_balance - strategy.global_deal.balance) < 1e-10, \
        f"Sum of closed deals' balance ({total_deals_balance}) should equal global deal's balance ({strategy.global_deal.balance})"
