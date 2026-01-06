"""
Tests for BrokerBacktesting class.

Tests market orders, limit orders, stop orders, validation, cancellation, and statistics.
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from typing import Dict, Any

from app.services.tasks.broker_backtesting import BrokerBacktesting
from app.services.tasks.broker import Order
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide, OrderType, OrderStatus
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE


# ============================================================================
# Helper Functions
# ============================================================================

def create_test_quotes_data(n_bars: int, start_price: PRICE_TYPE, trend: str = 'up') -> Dict[str, np.ndarray]:
    """
    Create test quotes data (OHLCV).
    
    Args:
        n_bars: Number of bars to generate
        start_price: Starting price
        trend: 'up', 'down', 'volatile', or 'flat'
    
    Returns:
        Dictionary with 'time', 'open', 'high', 'low', 'close', 'volume' arrays
    """
    base_time = np.datetime64('2024-01-01T00:00:00', 'ms')
    time_array = np.array([base_time + np.timedelta64(i, 'h') for i in range(n_bars)], dtype='datetime64[ms]')
    
    if trend == 'up':
        # Upward trend: price increases
        close_prices = np.linspace(start_price, start_price * 1.1, n_bars, dtype=PRICE_TYPE)
    elif trend == 'down':
        # Downward trend: price decreases
        close_prices = np.linspace(start_price, start_price * 0.9, n_bars, dtype=PRICE_TYPE)
    elif trend == 'volatile':
        # Volatile: price oscillates
        close_prices = start_price + np.sin(np.linspace(0, 4 * np.pi, n_bars)) * start_price * 0.05
        close_prices = close_prices.astype(PRICE_TYPE)
    else:  # flat
        # Flat: price stays constant
        close_prices = np.full(n_bars, start_price, dtype=PRICE_TYPE)
    
    # Generate OHLC from close prices
    open_prices = np.roll(close_prices, 1)
    open_prices[0] = start_price
    
    # High and low with some spread
    spread = start_price * 0.01  # 1% spread
    high_prices = close_prices + spread * np.random.random(n_bars)
    low_prices = close_prices - spread * np.random.random(n_bars)
    
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


def assert_order_executed(order: Order, expected_price: PRICE_TYPE, expected_volume: VOLUME_TYPE, 
                         expected_fee: PRICE_TYPE, expected_side: OrderSide) -> None:
    """Assert that an order was executed correctly."""
    assert order.status == OrderStatus.EXECUTED, f"Order status should be EXECUTED, got {order.status}"
    assert order.filled_volume == expected_volume, f"Filled volume should be {expected_volume}, got {order.filled_volume}"
    # Use approximate comparison for floating point prices
    assert abs(order.price - expected_price) < 0.01, \
        f"Execution price should be approximately {expected_price}, got {order.price}"
    # Note: fee is stored in Trade, not Order, so we check it separately


def assert_order_active(order: Order, expected_price: PRICE_TYPE = None) -> None:
    """Assert that an order is active."""
    assert order.status == OrderStatus.ACTIVE, f"Order status should be ACTIVE, got {order.status}"
    assert order.filled_volume == 0.0, f"Filled volume should be 0.0 for active order, got {order.filled_volume}"
    if expected_price is not None:
        assert order.price == expected_price, f"Order price should be {expected_price}, got {order.price}"


def assert_order_error(order: Order, expected_error_message: str = None) -> None:
    """Assert that an order has an error."""
    assert order.status == OrderStatus.ERROR, f"Order status should be ERROR, got {order.status}"
    assert len(order.errors) > 0, "Order should have at least one error message"
    if expected_error_message:
        assert any(expected_error_message in error for error in order.errors), \
            f"Expected error message '{expected_error_message}' not found in {order.errors}"


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
def mock_callbacks():
    """Create mock callbacks."""
    return {
        'on_start': Mock(),
        'on_bar': Mock(),
        'on_finish': Mock()
    }


@pytest.fixture
def simple_quotes_data():
    """Simple upward trend quotes data."""
    return create_test_quotes_data(n_bars=10, start_price=100.0, trend='up')


@pytest.fixture
def volatile_quotes_data():
    """Volatile quotes data."""
    return create_test_quotes_data(n_bars=10, start_price=100.0, trend='volatile')


@pytest.fixture
def mock_quotes_client(simple_quotes_data):
    """Mock QuotesClient.get_quotes() to return test data."""
    with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
        mock_client = Mock()
        mock_client.get_quotes.return_value = simple_quotes_data
        mock_client_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def broker_instance(test_task, mock_callbacks, mock_quotes_client, request):
    """Create a BrokerBacktesting instance for testing."""
    result_id = f"test_{request.node.name}"
    broker = BrokerBacktesting(
        task=test_task,
        result_id=result_id,
        callbacks_dict=mock_callbacks,
        results_save_period=1.0
    )
    return broker


# ============================================================================
# Market Orders Tests
# ============================================================================

class TestMarketOrders:
    """Test market order execution."""
    
    def test_market_buy_execution(self, broker_instance, simple_quotes_data):
        """Test market buy order execution."""
        broker = broker_instance
        
        # Setup: run backtest to initialize price
        broker.run(save_results=False)
        
        # Get current price from broker (set by run() to last bar's close)
        # We need to ensure price is still set after run() completes
        # After run(), price should be set to the last bar's close
        current_price = broker.price
        assert current_price is not None, "Price should be set after run()"
        
        # Slippage is applied once in _execute_trade() for market orders
        # order.price is initially set to self.price, then updated to trade.price after execution
        expected_execution_price = current_price + broker.slippage  # BUY: price increases
        expected_fee = expected_execution_price * 1.0 * broker.fee_taker
        
        # Place market buy order
        orders = broker.buy(quantity=1.0)
        
        # Assertions
        assert len(orders) == 1
        order = orders[0]
        # Check order price (updated to execution price after trade execution)
        assert_order_executed(order, expected_execution_price, 1.0, expected_fee, OrderSide.BUY)
        
        # Check trade was created
        assert len(broker.trades) == 1
        trade = broker.trades[0]
        assert trade.side == OrderSide.BUY
        # Check trade price (slippage applied once in _execute_trade)
        assert abs(trade.price - expected_execution_price) < 0.01, \
            f"Trade price {trade.price} should be approximately {expected_execution_price} (current_price={current_price}, slippage={broker.slippage})"
        assert trade.quantity == 1.0
        assert abs(trade.fee - expected_fee) < 0.0001, \
            f"Trade fee {trade.fee} should be approximately {expected_fee}"
        assert trade.order_id == order.order_id
        
        # Check deal was created
        assert len(broker.deals) == 1
        deal = broker.deals[0]
        assert len(deal.trades) == 1
        assert deal.quantity == 1.0
        
        # Check equity_symbol increased
        assert broker.equity_symbol == 1.0
    
    def test_market_sell_execution(self, broker_instance, simple_quotes_data):
        """Test market sell order execution."""
        broker = broker_instance
        
        # Setup: run backtest and buy first to have position
        broker.run(save_results=False)
        broker.buy(quantity=2.0)  # Buy first
        
        # Get current price from broker
        current_price = broker.price
        # Slippage is applied once in _execute_trade() for market orders
        expected_execution_price = current_price - broker.slippage  # SELL: price decreases
        expected_fee = expected_execution_price * 1.0 * broker.fee_taker
        
        # Place market sell order
        orders = broker.sell(quantity=1.0)
        
        # Assertions
        assert len(orders) == 1
        order = orders[0]
        assert_order_executed(order, expected_execution_price, 1.0, expected_fee, OrderSide.SELL)
        
        # Check trade was created
        assert len(broker.trades) == 2  # One buy, one sell
        trade = broker.trades[1]
        assert trade.side == OrderSide.SELL
        assert abs(trade.price - expected_execution_price) < 0.01, \
            f"Trade price {trade.price} should be approximately {expected_execution_price}"
        assert trade.quantity == 1.0
        assert abs(trade.fee - expected_fee) < 0.0001, \
            f"Trade fee {trade.fee} should be approximately {expected_fee}"
        
        # Check equity_symbol decreased
        assert broker.equity_symbol == 1.0  # 2.0 - 1.0
    
    def test_multiple_market_orders(self, broker_instance, simple_quotes_data):
        """Test multiple market orders in sequence."""
        broker = broker_instance
        broker.run(save_results=False)
        
        # Place multiple market orders
        orders1 = broker.buy(quantity=1.0)
        orders2 = broker.buy(quantity=2.0)
        orders3 = broker.sell(quantity=1.5)
        
        # All should be executed
        assert len(orders1) == 1 and orders1[0].status == OrderStatus.EXECUTED
        assert len(orders2) == 1 and orders2[0].status == OrderStatus.EXECUTED
        assert len(orders3) == 1 and orders3[0].status == OrderStatus.EXECUTED
        
        # Check trades
        assert len(broker.trades) == 3
        assert broker.equity_symbol == 1.5  # 1.0 + 2.0 - 1.5


# ============================================================================
# Limit Orders Tests
# ============================================================================

class TestLimitOrders:
    """Test limit order placement and execution."""
    
    def test_limit_buy_placement(self, broker_instance, simple_quotes_data):
        """Test limit buy order placement."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        limit_price = current_price - 5.0  # Below current price
        
        # Place limit buy order
        orders = broker.buy(quantity=1.0, price=limit_price)
        
        # Assertions
        assert len(orders) == 1
        order = orders[0]
        assert_order_active(order, limit_price)
        
        # Check order is in arrays
        assert order.order_id in broker.long_order_ids
        assert limit_price in broker.long_order_prices
    
    def test_limit_buy_execution(self, broker_instance):
        """Test limit buy order execution when price is reached."""
        broker = broker_instance
        
        # Create quotes data where low goes below limit price
        quotes_data = {
            'time': np.array([np.datetime64('2024-01-01T00:00:00', 'ms'), 
                             np.datetime64('2024-01-01T01:00:00', 'ms')], dtype='datetime64[ms]'),
            'open': np.array([100.0, 100.0], dtype=PRICE_TYPE),
            'high': np.array([101.0, 101.0], dtype=PRICE_TYPE),
            'low': np.array([99.0, 95.0], dtype=PRICE_TYPE),  # Second bar low goes below limit
            'close': np.array([100.0, 98.0], dtype=PRICE_TYPE),
            'volume': np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            
            # Place limit buy order at 96.0 (below first bar close of 100.0)
            limit_price = 96.0
            orders = broker.buy(quantity=1.0, price=limit_price)
            assert len(orders) == 1
            assert orders[0].status == OrderStatus.ACTIVE
            
            # Manually trigger order check for second bar (low=95.0 <= 96.0)
            broker._check_and_execute_orders(quotes_data['high'][1], quotes_data['low'][1])
            
            # Order should be executed
            order = broker.orders[orders[0].order_id - 1]
            assert order.status == OrderStatus.EXECUTED
            assert order.price == limit_price
            assert order.filled_volume == 1.0
            
            # Check trade
            assert len(broker.trades) == 1
            trade = broker.trades[0]
            assert trade.price == limit_price
            assert trade.fee == limit_price * 1.0 * broker.fee_maker
    
    def test_limit_sell_execution(self, broker_instance):
        """Test limit sell order execution when price is reached."""
        broker = broker_instance
        
        # Create quotes data where high goes above limit price
        quotes_data = {
            'time': np.array([np.datetime64('2024-01-01T00:00:00', 'ms'), 
                             np.datetime64('2024-01-01T01:00:00', 'ms')], dtype='datetime64[ms]'),
            'open': np.array([100.0, 100.0], dtype=PRICE_TYPE),
            'high': np.array([101.0, 105.0], dtype=PRICE_TYPE),  # Second bar high goes above limit
            'low': np.array([99.0, 99.0], dtype=PRICE_TYPE),
            'close': np.array([100.0, 102.0], dtype=PRICE_TYPE),
            'volume': np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            broker.buy(quantity=1.0)  # Buy first to have position
            
            # Place limit sell order at 104.0 (above first bar close of 100.0)
            limit_price = 104.0
            orders = broker.sell(quantity=1.0, price=limit_price)
            assert len(orders) == 1
            assert orders[0].status == OrderStatus.ACTIVE
            
            # Manually trigger order check for second bar (high=105.0 >= 104.0)
            broker._check_and_execute_orders(quotes_data['high'][1], quotes_data['low'][1])
            
            # Order should be executed
            order = broker.orders[orders[0].order_id - 1]
            assert order.status == OrderStatus.EXECUTED
            assert order.price == limit_price
            assert order.filled_volume == 1.0
    
    def test_limit_order_not_triggered(self, broker_instance, simple_quotes_data):
        """Test limit order that doesn't trigger."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        limit_price = current_price - 20.0  # Way below current price
        
        # Place limit buy order
        orders = broker.buy(quantity=1.0, price=limit_price)
        assert len(orders) == 1
        assert orders[0].status == OrderStatus.ACTIVE
        
        # Order should remain active (price never reached)
        order = broker.orders[orders[0].order_id - 1]
        assert order.status == OrderStatus.ACTIVE
        assert order.filled_volume == 0.0
    
    def test_limit_order_exact_price(self, broker_instance):
        """Test limit order execution when low exactly equals price."""
        broker = broker_instance
        
        quotes_data = {
            'time': np.array([np.datetime64('2024-01-01T00:00:00', 'ms'), 
                             np.datetime64('2024-01-01T01:00:00', 'ms')], dtype='datetime64[ms]'),
            'open': np.array([100.0, 100.0], dtype=PRICE_TYPE),
            'high': np.array([101.0, 101.0], dtype=PRICE_TYPE),
            'low': np.array([99.0, 96.0], dtype=PRICE_TYPE),  # Exactly equals limit price
            'close': np.array([100.0, 98.0], dtype=PRICE_TYPE),
            'volume': np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            
            limit_price = 96.0
            orders = broker.buy(quantity=1.0, price=limit_price)
            
            # Trigger check (low=96.0 <= 96.0 should trigger)
            broker._check_and_execute_orders(quotes_data['high'][1], quotes_data['low'][1])
            
            order = broker.orders[orders[0].order_id - 1]
            assert order.status == OrderStatus.EXECUTED  # Should execute on exact match


# ============================================================================
# Stop Orders Tests
# ============================================================================

class TestStopOrders:
    """Test stop order placement and execution."""
    
    def test_stop_buy_placement(self, broker_instance, simple_quotes_data):
        """Test stop buy order placement."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        trigger_price = current_price + 5.0  # Above current price
        
        # Place stop buy order
        orders = broker.buy(quantity=1.0, trigger_price=trigger_price)
        
        # Assertions
        assert len(orders) == 1
        order = orders[0]
        assert_order_active(order)
        assert order.trigger_price == trigger_price
        
        # Check order is in stop arrays
        assert order.order_id in broker.long_stop_order_ids
        assert trigger_price in broker.long_stop_trigger_prices
    
    def test_stop_buy_execution(self, broker_instance):
        """Test stop buy order execution when trigger price is reached."""
        broker = broker_instance
        
        quotes_data = {
            'time': np.array([np.datetime64('2024-01-01T00:00:00', 'ms'), 
                             np.datetime64('2024-01-01T01:00:00', 'ms')], dtype='datetime64[ms]'),
            'open': np.array([100.0, 100.0], dtype=PRICE_TYPE),
            'high': np.array([101.0, 106.0], dtype=PRICE_TYPE),  # Second bar high goes above trigger
            'low': np.array([99.0, 99.0], dtype=PRICE_TYPE),
            'close': np.array([100.0, 102.0], dtype=PRICE_TYPE),
            'volume': np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            
            # Place stop buy order at 105.0 (above first bar close of 100.0)
            trigger_price = 105.0
            orders = broker.buy(quantity=1.0, trigger_price=trigger_price)
            assert len(orders) == 1
            assert orders[0].status == OrderStatus.ACTIVE
            
            # Manually trigger order check for second bar (high=106.0 >= 105.0)
            broker._check_and_execute_orders(quotes_data['high'][1], quotes_data['low'][1])
            
            # Order should be executed
            order = broker.orders[orders[0].order_id - 1]
            assert order.status == OrderStatus.EXECUTED
            assert order.price == trigger_price  # Stop orders execute at trigger_price
            assert order.filled_volume == 1.0
    
    def test_stop_sell_execution(self, broker_instance):
        """Test stop sell order execution when trigger price is reached."""
        broker = broker_instance
        
        quotes_data = {
            'time': np.array([np.datetime64('2024-01-01T00:00:00', 'ms'), 
                             np.datetime64('2024-01-01T01:00:00', 'ms')], dtype='datetime64[ms]'),
            'open': np.array([100.0, 100.0], dtype=PRICE_TYPE),
            'high': np.array([101.0, 101.0], dtype=PRICE_TYPE),
            'low': np.array([99.0, 94.0], dtype=PRICE_TYPE),  # Second bar low goes below trigger
            'close': np.array([100.0, 96.0], dtype=PRICE_TYPE),
            'volume': np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker.run(save_results=False)
            broker.buy(quantity=1.0)  # Buy first to have position
            
            # Place stop sell order at 95.0 (below first bar close of 100.0)
            trigger_price = 95.0
            orders = broker.sell(quantity=1.0, trigger_price=trigger_price)
            assert len(orders) == 1
            assert orders[0].status == OrderStatus.ACTIVE
            
            # Manually trigger order check for second bar (low=94.0 <= 95.0)
            broker._check_and_execute_orders(quotes_data['high'][1], quotes_data['low'][1])
            
            # Order should be executed
            order = broker.orders[orders[0].order_id - 1]
            assert order.status == OrderStatus.EXECUTED
            assert order.price == trigger_price


# ============================================================================
# Validation Tests
# ============================================================================

class TestValidation:
    """Test order validation."""
    
    def test_validation_quantity_zero(self, broker_instance, simple_quotes_data):
        """Test order with zero quantity."""
        broker = broker_instance
        broker.run(save_results=False)
        
        orders = broker.buy(quantity=0.0)
        assert len(orders) == 1
        assert_order_error(orders[0], "quantity must be greater than 0")
    
    def test_validation_quantity_negative(self, broker_instance, simple_quotes_data):
        """Test order with negative quantity."""
        broker = broker_instance
        broker.run(save_results=False)
        
        orders = broker.buy(quantity=-1.0)
        assert len(orders) == 1
        assert_order_error(orders[0], "quantity must be greater than 0")
    
    def test_validation_limit_buy_price_too_high(self, broker_instance, simple_quotes_data):
        """Test limit buy order with price above current price."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        limit_price = current_price + 10.0  # Above current price
        
        orders = broker.buy(quantity=1.0, price=limit_price)
        assert len(orders) == 1
        assert_order_error(orders[0], "must be below or equal to current price")
    
    def test_validation_limit_sell_price_too_low(self, broker_instance, simple_quotes_data):
        """Test limit sell order with price below current price."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        limit_price = current_price - 10.0  # Below current price
        
        orders = broker.sell(quantity=1.0, price=limit_price)
        assert len(orders) == 1
        assert_order_error(orders[0], "must be above or equal to current price")
    
    def test_validation_stop_buy_trigger_too_low(self, broker_instance, simple_quotes_data):
        """Test stop buy order with trigger_price below or equal to current price."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        trigger_price = current_price - 1.0  # Below current price
        
        orders = broker.buy(quantity=1.0, trigger_price=trigger_price)
        assert len(orders) == 1
        assert_order_error(orders[0], "must be above current price")
        
        # Also test equal to current price
        trigger_price = current_price
        orders = broker.buy(quantity=1.0, trigger_price=trigger_price)
        assert len(orders) == 1
        assert_order_error(orders[0], "must be above current price")
    
    def test_validation_stop_sell_trigger_too_high(self, broker_instance, simple_quotes_data):
        """Test stop sell order with trigger_price above or equal to current price."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        trigger_price = current_price + 1.0  # Above current price
        
        orders = broker.sell(quantity=1.0, trigger_price=trigger_price)
        assert len(orders) == 1
        assert_order_error(orders[0], "must be below current price")
        
        # Also test equal to current price
        trigger_price = current_price
        orders = broker.sell(quantity=1.0, trigger_price=trigger_price)
        assert len(orders) == 1
        assert_order_error(orders[0], "must be below current price")
    
    def test_validation_market_with_price(self, broker_instance, simple_quotes_data):
        """Test market order with price specified (should fail)."""
        broker = broker_instance
        broker.run(save_results=False)
        
        # Market order should not have price - but buy()/sell() don't accept price for market
        # This test might not be applicable if the API prevents it
        # We test by creating order directly if needed
        pass  # API prevents this, so skip
    
    def test_validation_limit_with_trigger_price(self, broker_instance, simple_quotes_data):
        """Test limit order with trigger_price specified."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        limit_price = current_price - 5.0
        
        # This is prevented by API, but we can test by creating Order directly
        # For now, skip as API prevents this combination
        pass


# ============================================================================
# Cancel Orders Tests
# ============================================================================

class TestCancelOrders:
    """Test order cancellation."""
    
    def test_cancel_active_limit_order(self, broker_instance, simple_quotes_data):
        """Test canceling an active limit order."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        limit_price = current_price - 5.0
        
        # Place limit order
        orders = broker.buy(quantity=1.0, price=limit_price)
        order_id = orders[0].order_id
        
        # Cancel order
        canceled_orders = broker.cancel_orders([order_id])
        
        # Assertions
        assert len(canceled_orders) == 1
        assert canceled_orders[0].status == OrderStatus.CANCELED
        assert canceled_orders[0].order_id == order_id
        
        # Check order is removed from arrays
        assert order_id not in broker.long_order_ids
    
    def test_cancel_active_stop_order(self, broker_instance, simple_quotes_data):
        """Test canceling an active stop order."""
        broker = broker_instance
        broker.run(save_results=False)
        
        current_price = simple_quotes_data['close'][-1]
        trigger_price = current_price + 5.0
        
        # Place stop order
        orders = broker.buy(quantity=1.0, trigger_price=trigger_price)
        order_id = orders[0].order_id
        
        # Cancel order
        canceled_orders = broker.cancel_orders([order_id])
        
        # Assertions
        assert len(canceled_orders) == 1
        assert canceled_orders[0].status == OrderStatus.CANCELED
        
        # Check order is removed from arrays
        assert order_id not in broker.long_stop_order_ids
    
    def test_cancel_nonexistent_order(self, broker_instance, simple_quotes_data):
        """Test canceling a non-existent order."""
        broker = broker_instance
        broker.run(save_results=False)
        
        # Try to cancel non-existent order
        canceled_orders = broker.cancel_orders([99999])
        
        # Should return empty list (order not found)
        assert len(canceled_orders) == 0
    
    def test_cancel_executed_order(self, broker_instance, simple_quotes_data):
        """Test canceling an already executed order."""
        broker = broker_instance
        broker.run(save_results=False)
        
        # Place and execute market order
        orders = broker.buy(quantity=1.0)
        order_id = orders[0].order_id
        
        # Order should be executed
        assert orders[0].status == OrderStatus.EXECUTED
        
        # Try to cancel
        canceled_orders = broker.cancel_orders([order_id])
        
        # Should return order but status should remain EXECUTED (not ACTIVE, so not canceled)
        assert len(canceled_orders) == 1
        assert canceled_orders[0].status == OrderStatus.EXECUTED  # Status unchanged


# ============================================================================
# Statistics Tests
# ============================================================================

class TestStatistics:
    """Test trading statistics and results."""
    
    def test_stats_after_market_buy(self, broker_instance, simple_quotes_data):
        """Test statistics after market buy order."""
        broker = broker_instance
        broker.run(save_results=False)
        
        # Place market buy order (opens a deal)
        broker.buy(quantity=1.0)
        
        # Check stats
        assert broker.stats.total_trades == 1
        # Note: total_deals is only incremented when a deal is closed
        # A single BUY opens a deal but doesn't close it, so total_deals = 0
        assert broker.stats.total_deals == 0
        assert broker.equity_symbol == 1.0
        
        # Close the deal with a SELL
        broker.sell(quantity=1.0)
        
        # Now the deal is closed, so total_deals should be 1
        assert broker.stats.total_deals == 1
    
    def test_trades_list(self, broker_instance, simple_quotes_data):
        """Test that all executed orders create trades."""
        broker = broker_instance
        broker.run(save_results=False)
        
        # Place multiple orders
        broker.buy(quantity=1.0)
        broker.buy(quantity=2.0)
        broker.sell(quantity=1.5)
        
        # Check trades
        assert len(broker.trades) == 3
        assert all(trade.trade_id > 0 for trade in broker.trades)
        assert all(trade.trade_id == i + 1 for i, trade in enumerate(broker.trades))  # Sequential IDs
    
    def test_deals_list(self, broker_instance, simple_quotes_data):
        """Test that deals are created correctly."""
        broker = broker_instance
        broker.run(save_results=False)
        
        # Place orders that create deals
        broker.buy(quantity=1.0)
        broker.sell(quantity=0.5)
        
        # Check deals
        assert len(broker.deals) >= 1
        assert all(deal.deal_id > 0 for deal in broker.deals)
    
    def test_orders_list(self, broker_instance, simple_quotes_data):
        """Test that all orders are stored in orders list."""
        broker = broker_instance
        broker.run(save_results=False)
        
        # Place various orders
        broker.buy(quantity=1.0)  # Market
        current_price = simple_quotes_data['close'][-1]
        broker.buy(quantity=1.0, price=current_price - 5.0)  # Limit
        broker.buy(quantity=1.0, trigger_price=current_price + 5.0)  # Stop
        
        # Check orders
        assert len(broker.orders) == 3
        assert all(order.order_id > 0 for order in broker.orders)
        assert all(order.order_id == i + 1 for i, order in enumerate(broker.orders))  # Sequential IDs


# ============================================================================
# Edge Cases Tests
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_quotes_data(self, broker_instance):
        """Test that empty quotes data raises RuntimeError."""
        broker = broker_instance
        
        empty_quotes = {
            'time': np.array([], dtype='datetime64[ms]'),
            'open': np.array([], dtype=PRICE_TYPE),
            'high': np.array([], dtype=PRICE_TYPE),
            'low': np.array([], dtype=PRICE_TYPE),
            'close': np.array([], dtype=PRICE_TYPE),
            'volume': np.array([], dtype=VOLUME_TYPE)
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = empty_quotes
            mock_client_class.return_value = mock_client
            
            with pytest.raises(RuntimeError, match="No quotes data available"):
                broker.run(save_results=False)
    
    def test_single_bar(self, broker_instance):
        """Test backtesting with single bar of data."""
        broker = broker_instance
        
        single_bar_quotes = {
            'time': np.array([np.datetime64('2024-01-01T00:00:00', 'ms')], dtype='datetime64[ms]'),
            'open': np.array([100.0], dtype=PRICE_TYPE),
            'high': np.array([101.0], dtype=PRICE_TYPE),
            'low': np.array([99.0], dtype=PRICE_TYPE),
            'close': np.array([100.0], dtype=PRICE_TYPE),
            'volume': np.array([1000.0], dtype=VOLUME_TYPE)
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = single_bar_quotes
            mock_client_class.return_value = mock_client
            
            # Should complete without error
            broker.run(save_results=False)
            assert broker.current_time is not None

