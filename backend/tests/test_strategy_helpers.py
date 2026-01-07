"""
Common helpers and utilities for strategy tests.

This module contains shared components used across all strategy test files:
- TestStrategy class
- Helper functions for creating test data
- Fixtures
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any, Tuple

from app.services.tasks.strategy import Strategy, OrderOperationResult
from app.services.tasks.broker_backtesting import BrokerBacktesting
from app.services.tasks.broker import Order
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide, OrderType, OrderStatus, OrderGroup
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.core.objects2redis import MessageType

# Import helper functions from broker tests
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tests.test_broker_backtesting import (
    create_test_quotes_data,
    assert_order_executed,
    assert_order_active,
    assert_order_error
)


# ============================================================================
# Universal Test Strategy
# ============================================================================

class TestStrategy(Strategy):
    """
    Universal test strategy that executes actions based on a protocol.
    
    Protocol is a list of dictionaries with:
    - 'bar_index': int - bar index when to execute action (0-based)
    - 'method': str - method name to call (e.g., 'buy_sltp', 'sell_sltp')
    - 'args': dict - method arguments (kwargs)
    
    Callback function is called on every bar with:
    - strategy: TestStrategy instance
    - bar_index: int - current bar index
    - current_price: float - current price
    - method_result: Optional[OrderOperationResult] - result of method call if method was called on this bar
    """
    
    def on_start(self):
        """Initialize test strategy."""
        # Get protocol and callback from parameters
        self.test_protocol = self.parameters.get('test_protocol', [])
        self.test_callback = self.parameters.get('test_callback', None)
        
        # Initialize bar index counter
        self.bar_index = -1
        
        # Initialize data collection
        self.test_data = []
    
    def on_bar(self):
        """Execute protocol actions and call callback."""
        # Increment bar index (starts at 0 for first bar)
        self.bar_index += 1
        
        # Get current price
        current_price = self.close[-1] if len(self.close) > 0 else 0.0
        
        # Check if there's an action for this bar
        method_result = None
        action = None
        
        for protocol_action in self.test_protocol:
            if protocol_action.get('bar_index') == self.bar_index:
                action = protocol_action
                break
        
        # Execute action if found
        if action and 'method' in action:
            method_name = action['method']
            method_args = action.get('args', {})
            
            # Get method from strategy
            method = getattr(self, method_name, None)
            if method:
                try:
                    method_result = method(**method_args)
                except Exception as e:
                    # Create error result
                    method_result = OrderOperationResult(
                        orders=[],
                        error_messages=[f"Exception calling {method_name}: {str(e)}"],
                        active=[],
                        executed=[],
                        canceled=[],
                        error=[],
                        deal_id=0,
                        volume=0.0
                    )
        
        # Call callback if provided
        if self.test_callback:
            self.test_callback(
                strategy=self,
                bar_index=self.bar_index,
                current_price=current_price,
                method_result=method_result
            )


# ============================================================================
# Helper Functions
# ============================================================================

def create_broker_and_strategy(
    test_task: Task,
    quotes_data: Dict[str, np.ndarray],
    test_name: str = "test"
) -> Tuple[BrokerBacktesting, TestStrategy]:
    """
    Helper function to create BrokerBacktesting with TestStrategy.
    Should be called inside a patch context.
    
    Args:
        test_task: Task instance (should have parameters set with protocol and callback)
        quotes_data: Quotes data dictionary
        test_name: Test name for result_id
    
    Returns:
        Tuple of (broker, strategy)
    """
    # Create strategy instance
    strategy = TestStrategy()
    
    # Create callbacks
    callbacks = Strategy.create_strategy_callbacks(strategy)
    
    # Create broker
    result_id = f"test_{test_name}"
    broker = BrokerBacktesting(
        task=test_task,
        result_id=result_id,
        callbacks_dict=callbacks,
        results_save_period=1.0
    )
    
    # Set broker reference in strategy
    strategy.broker = broker
    
    # Mock logging to avoid Task.send_message errors
    broker.logging = Mock()
    
    # Mock task._list.send_message to raise exception with message info instead of failing silently
    # This helps catch backtesting errors in tests with informative error messages
    mock_list = Mock()
    def send_message_side_effect(obj_id, msg_type, data):
        """Side effect for mocked send_message that raises exception with message info."""
        if msg_type == MessageType.MESSAGE:
            # For error messages, raise exception with the actual error message
            if data.get('level') == 'error':
                error_msg = data.get('message', 'Unknown error')
                raise RuntimeError(f"Backtesting error: {error_msg}")
            else:
                # For non-error messages, just log (don't raise)
                return
        elif msg_type == MessageType.EVENT:
            # For backtesting_error events, wait for the MESSAGE call which will have the actual error
            if data.get('event') == 'backtesting_error':
                # Don't raise here, the actual error message comes in the next MESSAGE call
                return
            else:
                # For other events, just return (don't raise)
                return
        else:
            error_msg = f"Task tried to send message: type={msg_type}, data={data}"
            raise RuntimeError(error_msg)
    mock_list.send_message = Mock(side_effect=send_message_side_effect)
    test_task._list = mock_list
    
    # Set result_id on task to match broker's result_id
    # This is needed because broker_backtesting checks result_id in update_state()
    test_task.result_id = result_id
    
    return broker, strategy

def create_custom_quotes_data(
    prices: List[PRICE_TYPE], 
    highs: Optional[List[PRICE_TYPE]] = None,
    lows: Optional[List[PRICE_TYPE]] = None,
    times: Optional[List[np.datetime64]] = None
) -> Dict[str, np.ndarray]:
    """
    Create custom quotes data with specified prices.
    
    Args:
        prices: List of close prices for each bar
        highs: Optional list of high prices. If None, calculated from close with spread.
        lows: Optional list of low prices. If None, calculated from close with spread.
        times: Optional list of times. If None, generates sequential times.
    
    Returns:
        Dictionary with 'time', 'open', 'high', 'low', 'close', 'volume' arrays
    """
    n_bars = len(prices)
    if times is None:
        base_time = np.datetime64('2024-01-01T00:00:00', 'ms')
        time_array = np.array([base_time + np.timedelta64(i, 'h') for i in range(n_bars)], dtype='datetime64[ms]')
    else:
        time_array = np.array(times, dtype='datetime64[ms]')
    
    close_prices = np.array(prices, dtype=PRICE_TYPE)
    
    # Generate OHLC from close prices
    open_prices = np.roll(close_prices, 1)
    open_prices[0] = close_prices[0]
    
    # High and low with spread
    if highs is None:
        spread = close_prices * 0.01  # 1% spread
        high_prices = close_prices + spread
    else:
        high_prices = np.array(highs, dtype=PRICE_TYPE)
    
    if lows is None:
        spread = close_prices * 0.01  # 1% spread
        low_prices = close_prices - spread
    else:
        low_prices = np.array(lows, dtype=PRICE_TYPE)
    
    # Ensure high >= close >= low
    high_prices = np.maximum(high_prices, close_prices)
    low_prices = np.minimum(low_prices, close_prices)
    
    volume = np.full(n_bars, 1000.0, dtype=VOLUME_TYPE)
    
    return {
        'time': time_array,
        'open': open_prices.astype(PRICE_TYPE),
        'high': high_prices.astype(PRICE_TYPE),
        'low': low_prices.astype(PRICE_TYPE),
        'close': close_prices.astype(PRICE_TYPE),
        'volume': volume
    }


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def test_task():
    """Create a test Task instance."""
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    task = Task(
        id=1,  # Required field from Objects2Redis
        file_name="test_strategy.py",
        name="Test Strategy",
        source="test",
        symbol="TEST/USD",
        timeframe="1h",
        dateStart=(base_time - timedelta(days=1)).isoformat(),
        dateEnd=base_time.isoformat(),
        fee_taker=0.001,  # 0.1%
        fee_maker=0.0005,  # 0.05%
        price_step=0.1,
        slippage_in_steps=1.0,
        precision_amount=0.1,  # Volume precision
        precision_price=0.01,  # Price precision
        parameters={}
    )
    # Set isRunning to True so broker doesn't think task was stopped
    task.isRunning = True
    return task

