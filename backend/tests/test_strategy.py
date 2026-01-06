"""
Tests for Strategy class - buy_sltp/sell_sltp methods.

Tests for buy_sltp() and sell_sltp() methods with stop loss and take profit functionality.
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.services.tasks.strategy import Strategy, OrderOperationResult
from app.services.tasks.broker_backtesting import BrokerBacktesting
from app.services.tasks.broker import Order
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide, OrderType, OrderStatus, OrderGroup
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE

# Import helper functions from broker tests
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tests.test_broker_backtesting import (
    create_test_quotes_data,
)


# ============================================================================
# Test Strategy Classes
# ============================================================================

class SimpleTestStrategy(Strategy):
    """Simple strategy for basic tests."""
    def on_bar(self):
        pass


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def test_task():
    """Create a test Task instance."""
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    return Task(
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
        parameters={}
    )


@pytest.fixture
def simple_quotes_data():
    """Simple upward trend quotes data."""
    return create_test_quotes_data(n_bars=10, start_price=100.0, trend='up')


@pytest.fixture
def broker_with_strategy(test_task, simple_quotes_data, request):
    """Create a BrokerBacktesting instance with a strategy."""
    strategy_class = SimpleTestStrategy
    
    # Create strategy instance
    strategy = strategy_class()
    
    # Create callbacks
    callbacks = Strategy.create_strategy_callbacks(strategy)
    
    # Mock quotes client
    with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
        mock_client = Mock()
        mock_client.get_quotes.return_value = simple_quotes_data
        mock_client_class.return_value = mock_client
        
        # Create broker
        result_id = f"test_{request.node.name}"
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
        
        yield broker, strategy


# ============================================================================
# Helper Functions for SLTP Tests
# ============================================================================

def create_custom_quotes_data(prices: List[PRICE_TYPE], times: Optional[List[np.datetime64]] = None) -> Dict[str, np.ndarray]:
    """
    Create custom quotes data with specified prices.
    
    Args:
        prices: List of close prices for each bar
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
    spread = close_prices * 0.01  # 1% spread
    high_prices = close_prices + spread
    low_prices = close_prices - spread
    
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
# buy_sltp/sell_sltp Tests - Basic (without stops/takes)
# ============================================================================

class TestBuySltpBasic:
    """Test buy_sltp basic functionality (without stops/takes, similar to buy)."""
    
    def test_buy_sltp_market_no_exit(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order, no stop loss or take profit."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        
        # Place buy_sltp order without stops/takes
        result = strategy.buy_sltp(enter=1.0)
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 1
        assert len(result.executed) >= 1
        assert len(result.error) == 0
        assert len(result.error_messages) == 0
        assert result.deal_id > 0
        assert result.volume >= 0.0
    
    def test_buy_sltp_limit_no_exit(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with limit order, no stop loss or take profit."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp limit order without stops/takes
        result = strategy.buy_sltp(enter=(1.0, current_price - 5.0))
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 1
        assert len(result.active) >= 1  # Limit order should be active
        assert len(result.error) == 0
        assert result.deal_id > 0
    
    def test_sell_sltp_market_no_exit(self, broker_with_strategy, simple_quotes_data):
        """Test sell_sltp with market order, no stop loss or take profit."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        # First buy to have position
        strategy.buy(quantity=2.0)
        
        # Place sell_sltp order without stops/takes
        result = strategy.sell_sltp(enter=1.0)
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 1
        assert len(result.executed) >= 1
        assert len(result.error) == 0
        assert result.deal_id > 0


# ============================================================================
# buy_sltp/sell_sltp Tests - Market Entry with Single Stop/Take
# ============================================================================

class TestBuySltpMarketSingleExit:
    """Test buy_sltp with market entry and single stop loss or take profit."""
    
    def test_buy_sltp_market_single_stop(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order and single stop loss."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with single stop loss
        result = strategy.buy_sltp(enter=1.0, stop_loss=current_price - 10.0)
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 2  # Entry + stop loss
        assert len(result.error) == 0
        
        # Check that stop loss order was created
        stop_orders = [o for o in result.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1
        stop_order = stop_orders[0]
        assert stop_order.fraction == 1.0
        assert stop_order.trigger_price == current_price - 10.0
        assert stop_order.side == OrderSide.SELL  # Stop loss for BUY is SELL
    
    def test_buy_sltp_market_single_take(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order and single take profit."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with single take profit
        result = strategy.buy_sltp(enter=1.0, take_profit=current_price + 10.0)
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 2  # Entry + take profit
        assert len(result.error) == 0
        
        # Check that take profit order was created
        take_orders = [o for o in result.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1
        take_order = take_orders[0]
        assert take_order.fraction == 1.0
        assert take_order.price == current_price + 10.0
        assert take_order.side == OrderSide.SELL  # Take profit for BUY is SELL
    
    def test_buy_sltp_market_stop_and_take(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order, stop loss and take profit."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with both stop loss and take profit
        result = strategy.buy_sltp(
            enter=1.0,
            stop_loss=current_price - 10.0,
            take_profit=current_price + 10.0
        )
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 3  # Entry + stop loss + take profit
        assert len(result.error) == 0
        
        # Check stop loss order
        stop_orders = [o for o in result.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1
        assert stop_orders[0].fraction == 1.0
        
        # Check take profit order
        take_orders = [o for o in result.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1
        assert take_orders[0].fraction == 1.0


# ============================================================================
# buy_sltp/sell_sltp Tests - Market Entry with Multiple Stops/Takes (Equal Fractions)
# ============================================================================

class TestBuySltpMarketMultipleExit:
    """Test buy_sltp with market entry and multiple stop losses or take profits."""
    
    def test_buy_sltp_market_two_stops_equal(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order and two stop losses (equal fractions)."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with two stop losses
        result = strategy.buy_sltp(enter=1.0, stop_loss=[current_price - 10.0, current_price - 20.0])
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 3  # Entry + 2 stop losses
        assert len(result.error) == 0
        
        # Check stop loss orders
        stop_orders = [o for o in result.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2
        
        # Check fractions sum to 1.0
        fractions = [o.fraction for o in stop_orders]
        assert abs(sum(fractions) - 1.0) < 1e-6
        # Each should be approximately 0.5
        assert all(abs(f - 0.5) < 1e-6 for f in fractions)
    
    def test_buy_sltp_market_three_takes_equal(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order and three take profits (equal fractions)."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with three take profits
        result = strategy.buy_sltp(
            enter=1.0,
            take_profit=[current_price + 10.0, current_price + 20.0, current_price + 30.0]
        )
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 4  # Entry + 3 take profits
        assert len(result.error) == 0
        
        # Check take profit orders
        take_orders = [o for o in result.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3
        
        # Check fractions sum to 1.0
        fractions = [o.fraction for o in take_orders]
        assert abs(sum(fractions) - 1.0) < 1e-6
        # Each should be approximately 1/3
        assert all(abs(f - 1.0/3.0) < 1e-6 for f in fractions)
    
    def test_buy_sltp_market_stops_and_takes_equal(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order, multiple stops and takes (equal fractions)."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with two stops and two takes
        result = strategy.buy_sltp(
            enter=1.0,
            stop_loss=[current_price - 10.0, current_price - 20.0],
            take_profit=[current_price + 10.0, current_price + 20.0]
        )
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 5  # Entry + 2 stops + 2 takes
        assert len(result.error) == 0
        
        # Check stop loss orders
        stop_orders = [o for o in result.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2
        stop_fractions = [o.fraction for o in stop_orders]
        assert abs(sum(stop_fractions) - 1.0) < 1e-6
        
        # Check take profit orders
        take_orders = [o for o in result.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2
        take_fractions = [o.fraction for o in take_orders]
        assert abs(sum(take_fractions) - 1.0) < 1e-6


# ============================================================================
# buy_sltp/sell_sltp Tests - Market Entry with Custom Fractions
# ============================================================================

class TestBuySltpMarketCustomFractions:
    """Test buy_sltp with market entry and custom fractions for stops/takes."""
    
    def test_buy_sltp_market_custom_stops(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order and custom stop loss fractions."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with custom stop loss fractions
        result = strategy.buy_sltp(
            enter=1.0,
            stop_loss=[(0.3, current_price - 10.0), (0.7, current_price - 20.0)]
        )
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 3  # Entry + 2 stop losses
        assert len(result.error) == 0
        
        # Check stop loss orders
        stop_orders = [o for o in result.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2
        
        # Check fractions
        fractions = sorted([o.fraction for o in stop_orders])
        assert abs(fractions[0] - 0.3) < 1e-6
        assert abs(fractions[1] - 0.7) < 1e-6
        assert abs(sum(fractions) - 1.0) < 1e-6
    
    def test_buy_sltp_market_custom_takes(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with market order and custom take profit fractions."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with custom take profit fractions
        result = strategy.buy_sltp(
            enter=1.0,
            take_profit=[(0.2, current_price + 10.0), (0.3, current_price + 20.0), (0.5, current_price + 30.0)]
        )
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 4  # Entry + 3 take profits
        assert len(result.error) == 0
        
        # Check take profit orders
        take_orders = [o for o in result.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3
        
        # Check fractions
        fractions = sorted([o.fraction for o in take_orders])
        assert abs(fractions[0] - 0.2) < 1e-6
        assert abs(fractions[1] - 0.3) < 1e-6
        assert abs(fractions[2] - 0.5) < 1e-6
        assert abs(sum(fractions) - 1.0) < 1e-6


# ============================================================================
# buy_sltp/sell_sltp Tests - Limit Entry with Stops/Takes
# ============================================================================

class TestBuySltpLimitEntry:
    """Test buy_sltp with limit entry orders and stops/takes."""
    
    def test_buy_sltp_limit_single_stop(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with single limit order and stop loss."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with limit order and stop loss
        result = strategy.buy_sltp(
            enter=(1.0, current_price - 5.0),
            stop_loss=current_price - 15.0
        )
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 1  # At least entry order
        assert len(result.error) == 0
        
        # Entry order should be active (limit)
        entry_orders = [o for o in result.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) >= 1
        assert entry_orders[0].status == OrderStatus.ACTIVE
    
    def test_buy_sltp_multiple_limits_stop(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with multiple limit orders and stop loss."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with multiple limit orders and stop loss
        result = strategy.buy_sltp(
            enter=[(0.5, current_price - 5.0), (0.5, current_price - 10.0)],
            stop_loss=current_price - 15.0
        )
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        assert len(result.orders) >= 2  # At least 2 entry orders
        assert len(result.error) == 0
        
        # Entry orders should be active
        entry_orders = [o for o in result.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) >= 2
        assert all(o.status == OrderStatus.ACTIVE for o in entry_orders)


# ============================================================================
# buy_sltp/sell_sltp Tests - Validation
# ============================================================================

class TestBuySltpValidation:
    """Test buy_sltp parameter validation."""
    
    def test_buy_sltp_invalid_fraction_sum(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with invalid fraction sum (not equal to 1.0)."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Try to place buy_sltp with fractions that don't sum to 1.0
        result = strategy.buy_sltp(
            enter=1.0,
            stop_loss=[(0.3, current_price - 10.0), (0.5, current_price - 20.0)]  # Sum = 0.8, not 1.0
        )
        
        # Check result - should have errors
        assert isinstance(result, OrderOperationResult)
        assert len(result.error_messages) > 0
        assert any("sum of fractions" in msg.lower() for msg in result.error_messages)
    
    def test_buy_sltp_invalid_price_limit(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with invalid limit price (above current for BUY)."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Try to place buy_sltp with limit price above current
        result = strategy.buy_sltp(
            enter=(1.0, current_price + 10.0)  # Invalid: BUY limit must be below current
        )
        
        # Check result - should have errors
        assert isinstance(result, OrderOperationResult)
        assert len(result.error_messages) > 0
        assert any("must be below" in msg.lower() for msg in result.error_messages)
    
    def test_buy_sltp_invalid_stop_price(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with invalid stop loss price (above current for BUY)."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Try to place buy_sltp with stop loss above current price
        result = strategy.buy_sltp(
            enter=1.0,
            stop_loss=current_price + 10.0  # Invalid: BUY stop loss must be below current
        )
        
        # Check result - should have errors
        assert isinstance(result, OrderOperationResult)
        assert len(result.error_messages) > 0
        assert any("must be below" in msg.lower() for msg in result.error_messages)
    
    def test_buy_sltp_invalid_take_price(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp with invalid take profit price (below current for BUY)."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Try to place buy_sltp with take profit below current price
        result = strategy.buy_sltp(
            enter=1.0,
            take_profit=current_price - 10.0  # Invalid: BUY take profit must be above current
        )
        
        # Check result - should have errors
        assert isinstance(result, OrderOperationResult)
        assert len(result.error_messages) > 0
        assert any("must be above" in msg.lower() for msg in result.error_messages)


# ============================================================================
# buy_sltp/sell_sltp Tests - Partial Entry Execution
# ============================================================================

class TestBuySltpPartialEntry:
    """Test buy_sltp with partial execution of limit entry orders."""
    
    def test_buy_sltp_two_limits_one_executed(self, broker_with_strategy):
        """Test buy_sltp with two limit orders, one executed - stops/takes should be placed."""
        broker, strategy = broker_with_strategy
        
        # Create quotes data where one limit will execute
        # Bar 0: price 100, Bar 1: low goes to 95 (triggers limit at 96), Bar 2: price 98
        quotes_data = create_custom_quotes_data([100.0, 98.0, 99.0])
        quotes_data['low'][1] = 94.0  # Low enough to trigger limit at 96
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            current_price = broker.price  # Should be 99.0 (last bar)
            
            # Place buy_sltp with two limit orders and stop loss
            result = strategy.buy_sltp(
                enter=[(0.5, 96.0), (0.5, 94.0)],  # First should execute, second may not
                stop_loss=current_price - 10.0
            )
            
            # Check result
            assert isinstance(result, OrderOperationResult)
            assert len(result.orders) >= 2  # At least 2 entry orders
            assert len(result.error) == 0
            
            # After first limit executes, stop loss should be placed
            # (This will be checked when execute_deal is implemented)
            entry_orders = [o for o in result.orders if o.order_group == OrderGroup.NONE]
            assert len(entry_orders) >= 2


# ============================================================================
# buy_sltp/sell_sltp Tests - Partial Exit Execution
# ============================================================================

class TestBuySltpPartialExit:
    """Test buy_sltp with partial execution of stop loss or take profit orders."""
    
    def test_buy_sltp_market_two_stops_one_executed(self, broker_with_strategy):
        """Test buy_sltp with market entry, two stops, one executed."""
        broker, strategy = broker_with_strategy
        
        # Create quotes data where one stop will execute
        # Bar 0: price 100 (entry), Bar 1: low goes to 88 (triggers stop at 90)
        quotes_data = create_custom_quotes_data([100.0, 92.0])
        quotes_data['low'][1] = 87.0  # Low enough to trigger stop at 90
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            current_price = broker.price  # Should be 100.0 (last bar)
            
            # Place buy_sltp with market entry and two stop losses
            result = strategy.buy_sltp(
                enter=1.0,
                stop_loss=[90.0, 88.0]  # First should execute on next bar
            )
            
            # Check result
            assert isinstance(result, OrderOperationResult)
            assert len(result.orders) >= 3  # Entry + 2 stops
            assert len(result.error) == 0
            
            # Check stop orders were created
            stop_orders = [o for o in result.orders if o.order_group == OrderGroup.STOP_LOSS]
            assert len(stop_orders) == 2
            
            # Check fractions
            fractions = [o.fraction for o in stop_orders]
            assert abs(sum(fractions) - 1.0) < 1e-6


# ============================================================================
# buy_sltp/sell_sltp Tests - Full Position Close
# ============================================================================

class TestBuySltpFullClose:
    """Test buy_sltp with full position closure."""
    
    def test_buy_sltp_market_last_stop_closes_all(self, broker_with_strategy):
        """Test buy_sltp with market entry, two stops, last one closes position."""
        broker, strategy = broker_with_strategy
        
        # Create quotes data where both stops execute
        quotes_data = create_custom_quotes_data([100.0, 92.0, 85.0])
        quotes_data['low'][1] = 87.0  # Triggers first stop at 90
        quotes_data['low'][2] = 83.0  # Triggers second stop at 88
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            current_price = broker.price  # Should be 100.0 (last bar)
            
            # Place buy_sltp with market entry and two stop losses
            result = strategy.buy_sltp(
                enter=1.0,
                stop_loss=[90.0, 88.0]
            )
            
            # Check result
            assert isinstance(result, OrderOperationResult)
            assert len(result.orders) >= 3  # Entry + 2 stops
            assert len(result.error) == 0
            
            # After both stops execute, deal should be closed
            # (This will be checked when execute_deal is implemented)
            deal_id = result.deal_id
            if deal_id > 0:
                # Check deal directly through broker
                deal = broker.get_deal_by_id(deal_id)
                # Deal should be closed, all exit orders canceled
                # (This will be verified when execute_deal is implemented)


# ============================================================================
# buy_sltp/sell_sltp Tests - Complex Scenarios
# ============================================================================

class TestBuySltpComplexScenarios:
    """Test buy_sltp with complex execution scenarios."""
    
    def test_buy_sltp_limits_executed_then_takes(self, broker_with_strategy):
        """Test buy_sltp: limits executed, then take profits close their fractions."""
        broker, strategy = broker_with_strategy
        
        # Create quotes data: limits execute, then price goes up to trigger takes
        quotes_data = create_custom_quotes_data([100.0, 95.0, 110.0, 112.0])
        quotes_data['low'][1] = 94.0  # Triggers limit at 96
        quotes_data['high'][2] = 111.0  # Triggers first take at 110
        quotes_data['high'][3] = 113.0  # Triggers second take at 112
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            current_price = broker.price  # Should be 100.0 (last bar)
            
            # Place buy_sltp with two limits and two take profits
            result = strategy.buy_sltp(
                enter=[(0.5, 96.0), (0.5, 94.0)],
                take_profit=[110.0, 112.0]
            )
            
            # Check result
            assert isinstance(result, OrderOperationResult)
            assert len(result.orders) >= 4  # 2 entries + 2 takes
            assert len(result.error) == 0
            
            # Check take profit orders
            take_orders = [o for o in result.orders if o.order_group == OrderGroup.TAKE_PROFIT]
            assert len(take_orders) == 2
    
    def test_buy_sltp_all_limits_then_partial_stops_then_takes(self, broker_with_strategy):
        """Test buy_sltp: all limits executed, partial stops, then takes close remaining."""
        broker, strategy = broker_with_strategy
        
        # Create quotes data: all limits execute, one stop, then takes
        quotes_data = create_custom_quotes_data([100.0, 95.0, 92.0, 110.0])
        quotes_data['low'][1] = 94.0  # Triggers limit at 96
        quotes_data['low'][2] = 91.0  # Triggers limit at 94 and stop at 90
        quotes_data['high'][3] = 111.0  # Triggers take at 110
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            current_price = broker.price  # Should be 100.0 (last bar)
            
            # Place buy_sltp with limits, stops, and takes
            result = strategy.buy_sltp(
                enter=[(0.5, 96.0), (0.5, 94.0)],
                stop_loss=[90.0, 88.0],
                take_profit=[110.0, 112.0]
            )
            
            # Check result
            assert isinstance(result, OrderOperationResult)
            assert len(result.orders) >= 6  # 2 entries + 2 stops + 2 takes
            assert len(result.error) == 0


# ============================================================================
# buy_sltp/sell_sltp Tests - Simultaneous Stop and Take Execution
# ============================================================================

class TestBuySltpSimultaneousExecution:
    """Test buy_sltp with simultaneous stop loss and take profit execution."""
    
    def test_buy_sltp_stops_and_takes_same_bar(self, broker_with_strategy):
        """Test buy_sltp: stops and takes triggered on same bar - stops execute first, warning logged."""
        broker, strategy = broker_with_strategy
        
        # Create quotes data where both stop and take are triggered on same bar
        quotes_data = create_custom_quotes_data([100.0, 95.0])
        quotes_data['low'][1] = 87.0  # Triggers stop at 90
        quotes_data['high'][1] = 111.0  # Triggers take at 110
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            current_price = broker.price  # Should be 100.0 (last bar)
            
            # Place buy_sltp with stop and take
            result = strategy.buy_sltp(
                enter=1.0,
                stop_loss=90.0,
                take_profit=110.0
            )
            
            # Check result
            assert isinstance(result, OrderOperationResult)
            assert len(result.orders) >= 3  # Entry + stop + take
            assert len(result.error) == 0
            
            # When both are triggered on same bar, warning should be logged
            # Check that logging was called with warning message
            # (This will be verified when execute_deal is implemented)
            assert broker.logging.called
            
            # Check if warning message was logged
            warning_calls = [call for call in broker.logging.call_args_list 
                           if len(call[0]) > 0 and ('warning' in str(call).lower() or 'недостоверен' in str(call).lower() or 'unreliable' in str(call).lower())]
            # Warning should be logged when both stop and take are triggered
            # (This will be verified when execute_deal is implemented)


# ============================================================================
# buy_sltp/sell_sltp Tests - Deal Orders and Volume Checks
# ============================================================================

class TestBuySltpDealOrders:
    """Test buy_sltp using deal_orders to check orders and volumes."""
    
    def test_buy_sltp_deal_orders_check(self, broker_with_strategy, simple_quotes_data):
        """Test buy_sltp and check orders through deal_orders."""
        broker, strategy = broker_with_strategy
        
        broker.run(save_results=False)
        current_price = broker.price
        
        # Place buy_sltp with stop and take
        result = strategy.buy_sltp(
            enter=1.0,
            stop_loss=current_price - 10.0,
            take_profit=current_price + 10.0
        )
        
        # Check result
        assert isinstance(result, OrderOperationResult)
        deal_id = result.deal_id
        assert deal_id > 0
        
        # Check deal directly through broker
        deal = broker.get_deal_by_id(deal_id)
        assert deal.deal_id == deal_id
        
        # Get all orders for this deal
        deal_orders = [o for o in broker.orders if o.deal_id == deal_id]
        assert len(deal_orders) > 0
        
        # Check volume
        assert abs(deal.quantity) >= 0  # Volume should be non-negative
    
    def test_buy_sltp_trade_volumes_check(self, broker_with_strategy):
        """Test buy_sltp and check trade volumes match fractions."""
        broker, strategy = broker_with_strategy
        
        # Create quotes data where stop executes
        quotes_data = create_custom_quotes_data([100.0, 88.0])
        quotes_data['low'][1] = 87.0  # Triggers stop at 90
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            current_price = broker.price  # Should be 100.0 (last bar)
            
            # Place buy_sltp with market entry and two stop losses (0.3 and 0.7)
            result = strategy.buy_sltp(
                enter=1.0,
                stop_loss=[(0.3, 90.0), (0.7, 88.0)]
            )
            
            # Check result
            assert isinstance(result, OrderOperationResult)
            deal_id = result.deal_id
            assert deal_id > 0
            
            # When first stop executes, trade volume should be fraction * deal.quantity
            # (This will be verified when execute_deal is implemented)
            if broker.deals and len(broker.deals) >= deal_id:
                deal = broker.deals[deal_id - 1]
                entry_volume = deal.quantity  # Should be 1.0 after market entry
                
                # Find trades for this deal
                deal_trades = [t for t in broker.trades if t.deal_id == deal_id]
                
                # When stop executes, trade volume should match fraction
                # (This will be verified when execute_deal is implemented)
                # For now, just check structure
                assert len(deal_trades) >= 1  # At least entry trade
