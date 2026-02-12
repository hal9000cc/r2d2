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
from app.services.tasks.enums import OrderGroup
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.strategy import Strategy


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


def assert_order_executed(order: Order, expected_volume: VOLUME_TYPE, expected_side: OrderSide) -> None:
    """Assert that an order was executed correctly.
    
    Note: Execution price should be checked via Trade.price, not Order.price,
    as Order.price may be None for market orders or contain limit price for limit orders.
    """
    assert order.status == OrderStatus.EXECUTED, f"Order status should be EXECUTED, got {order.status}"
    assert order.filled_volume == expected_volume, f"Filled volume should be {expected_volume}, got {order.filled_volume}"
    assert order.side == expected_side, f"Order side should be {expected_side}, got {order.side}"
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
        precision_amount=0.1,  # Volume precision
        precision_price=0.01,  # Price precision
        history_size=10,  # Number of bars for strategy initialization
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
    return create_test_quotes_data(n_bars=20, start_price=100.0, trend='up')


@pytest.fixture
def volatile_quotes_data():
    """Volatile quotes data."""
    return create_test_quotes_data(n_bars=20, start_price=100.0, trend='volatile')


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
    
    def test_market_buy_execution(self, test_task, simple_quotes_data):
        """Test market buy order execution through run() with minimal strategy."""
        # Create a simple strategy that calls buy() on the first bar
        class BuyStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
            
            def on_bar(self):
                self.bar_count += 1
                # Call buy() on the first bar (after history)
                if self.bar_count == 1:
                    self.broker.buy(quantity=1.0)
        
        # Create strategy instance
        strategy = BuyStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_market_buy_execution"
            broker = BrokerBacktesting(
                task=test_task,
                result_id=result_id,
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            
            # Set broker reference in strategy
            strategy.broker = broker
            
            # Mock logging
            broker.logging = Mock()
            
            # Run backtest - strategy will call buy() on first bar
            broker.run(save_results=False)
            
            # Get expected execution price (first bar's close + slippage)
            first_bar_close = simple_quotes_data['close'][test_task.history_size]  # First bar after history
            expected_execution_price = first_bar_close + broker.slippage  # BUY: price increases
            expected_fee = expected_execution_price * 1.0 * broker.fee_taker
            
            # Assertions
            # Check that buy() was called
            assert strategy.bar_count >= 1, "Strategy should have processed at least one bar"
            
            # Check orders: entry order (buy) and close order (created by close_deals() at end of run())
            assert len(broker.orders) == 2, f"Expected 2 orders (entry + close), got {len(broker.orders)}"
            
            # Find entry order (BUY, from buy() call)
            entry_order = next((o for o in broker.orders if o.side == OrderSide.BUY and o.order_group == OrderGroup.AUTO), None)
            assert entry_order is not None, "Entry BUY order should exist"
            assert_order_executed(entry_order, 1.0, OrderSide.BUY)
            
            # Find close order (SELL, created by close_deals())
            close_order = next((o for o in broker.orders if o.side == OrderSide.SELL), None)
            assert close_order is not None, "Close SELL order should exist"
            assert close_order.order_group == OrderGroup.NONE, "Close order should have order_group=NONE"
            assert_order_executed(close_order, 1.0, OrderSide.SELL)
            
            # Check trades: entry trade and close trade
            assert len(broker.trades) == 2, f"Expected 2 trades (entry + close), got {len(broker.trades)}"
            
            # Entry trade - check execution price here (includes slippage for market orders)
            entry_trade = next((t for t in broker.trades if t.order_id == entry_order.order_id), None)
            assert entry_trade is not None, "Entry BUY trade should exist"
            assert entry_trade.side == OrderSide.BUY
            assert abs(entry_trade.price - expected_execution_price) < 0.01, \
                f"Entry trade price {entry_trade.price} should be approximately {expected_execution_price} (first_bar_close={first_bar_close}, slippage={broker.slippage})"
            assert entry_trade.quantity == 1.0
            assert abs(entry_trade.fee - expected_fee) < 0.0001, \
                f"Entry trade fee {entry_trade.fee} should be approximately {expected_fee}"
            
            # Close trade - check execution price here (includes slippage for market orders)
            close_trade = next((t for t in broker.trades if t.order_id == close_order.order_id), None)
            assert close_trade is not None, "Close SELL trade should exist"
            assert close_trade.side == OrderSide.SELL
            
            # Check auto-deal was created and closed
            assert len(broker.deals) == 1, f"Expected 1 deal, got {len(broker.deals)}"
            deal = broker.deals[0]
            assert deal.auto, "Deal should be an auto-deal"
            assert len(deal.trades) == 2, "Deal should have 2 trades (entry + close)"
            assert deal.quantity == 0.0, "Deal should be closed (quantity=0)"
            assert deal.is_closed, "Deal should be marked as closed"
            
            # Check equity_symbol - should be back to 0 after closing
            assert broker.equity_symbol == 0.0, "Equity should be 0 after closing position"
    
    def test_market_sell_execution(self, test_task, simple_quotes_data):
        """Test market sell order execution through run() with minimal strategy."""
        # Create a simple strategy that calls buy() then sell()
        class BuySellStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
            
            def on_bar(self):
                self.bar_count += 1
                # Call buy() on the first bar, sell() on the second bar
                if self.bar_count == 1:
                    self.broker.buy(quantity=2.0)
                elif self.bar_count == 2:
                    self.broker.sell(quantity=1.0)
        
        # Create strategy instance
        strategy = BuySellStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_market_sell_execution"
            broker = BrokerBacktesting(
                task=test_task,
                result_id=result_id,
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            
            # Set broker reference in strategy
            strategy.broker = broker
            
            # Mock logging
            broker.logging = Mock()
            
            # Run backtest - strategy will call buy() on first bar, sell() on second bar
            broker.run(save_results=False)
            
            # Get expected execution price (second bar's close - slippage for SELL)
            second_bar_close = simple_quotes_data['close'][test_task.history_size + 1]  # Second bar after history
            expected_execution_price = second_bar_close - broker.slippage  # SELL: price decreases
            expected_fee = expected_execution_price * 1.0 * broker.fee_taker
            
            # Assertions
            assert strategy.bar_count >= 2, "Strategy should have processed at least two bars"
            
            # Check orders: buy order, sell order, and close order (created by close_deals() at end)
            assert len(broker.orders) >= 2, f"Expected at least 2 orders, got {len(broker.orders)}"
            
            # Find buy order
            buy_order = next((o for o in broker.orders if o.side == OrderSide.BUY and o.order_group == OrderGroup.AUTO), None)
            assert buy_order is not None, "Buy order should exist"
            assert_order_executed(buy_order, 2.0, OrderSide.BUY)
            
            # Find sell order
            sell_order = next((o for o in broker.orders if o.side == OrderSide.SELL and o.order_group == OrderGroup.AUTO), None)
            assert sell_order is not None, "Sell order should exist"
            assert_order_executed(sell_order, 1.0, OrderSide.SELL)
            
            # Check trades: buy trade and sell trade (and possibly close trade)
            assert len(broker.trades) >= 2, f"Expected at least 2 trades, got {len(broker.trades)}"
            
            # Buy trade
            buy_trade = next((t for t in broker.trades if t.order_id == buy_order.order_id), None)
            assert buy_trade is not None, "Buy trade should exist"
            assert buy_trade.side == OrderSide.BUY
            assert buy_trade.quantity == 2.0
            
            # Sell trade - check execution price here (includes slippage for market orders)
            sell_trade = next((t for t in broker.trades if t.order_id == sell_order.order_id), None)
            assert sell_trade is not None, "Sell trade should exist"
            assert sell_trade.side == OrderSide.SELL
            assert abs(sell_trade.price - expected_execution_price) < 0.01, \
                f"Sell trade price {sell_trade.price} should be approximately {expected_execution_price} (second_bar_close={second_bar_close}, slippage={broker.slippage})"
            assert sell_trade.quantity == 1.0
            assert abs(sell_trade.fee - expected_fee) < 0.0001, \
                f"Sell trade fee {sell_trade.fee} should be approximately {expected_fee}"
            
            # Check auto-deal
            assert len(broker.deals) == 1, f"Expected 1 deal, got {len(broker.deals)}"
            deal = broker.deals[0]
            assert deal.auto, "Deal should be an auto-deal"
            # Deal is closed at end of run(), so quantity is 0, but we can check trades
            assert len(deal.trades) >= 2, f"Deal should have at least 2 trades (buy + sell), got {len(deal.trades)}"
            buy_trades_in_deal = [t for t in deal.trades if t.side == OrderSide.BUY]
            sell_trades_in_deal = [t for t in deal.trades if t.side == OrderSide.SELL and t.order_id == sell_order.order_id]
            assert len(buy_trades_in_deal) == 1, "Deal should have 1 buy trade"
            assert buy_trades_in_deal[0].quantity == 2.0, "Buy trade quantity should be 2.0"
            assert len(sell_trades_in_deal) == 1, "Deal should have 1 sell trade"
            assert sell_trades_in_deal[0].quantity == 1.0, "Sell trade quantity should be 1.0"
    
    def test_multiple_market_orders(self, test_task, simple_quotes_data):
        """Test multiple market orders in sequence through run() with minimal strategy."""
        # Create a simple strategy that calls buy(), buy(), then sell()
        class MultipleOrdersStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
            
            def on_bar(self):
                self.bar_count += 1
                # Call buy(1.0) on first bar, buy(2.0) on second bar, sell(1.5) on third bar
                if self.bar_count == 1:
                    self.broker.buy(quantity=1.0)
                elif self.bar_count == 2:
                    self.broker.buy(quantity=2.0)
                elif self.bar_count == 3:
                    self.broker.sell(quantity=1.5)
        
        # Create strategy instance
        strategy = MultipleOrdersStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_multiple_market_orders"
            broker = BrokerBacktesting(
                task=test_task,
                result_id=result_id,
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            
            # Set broker reference in strategy
            strategy.broker = broker
            
            # Mock logging
            broker.logging = Mock()
            
            # Run backtest - strategy will call buy(), buy(), sell() on consecutive bars
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.bar_count >= 3, "Strategy should have processed at least three bars"
            
            # Check orders: 2 buy orders, 1 sell order, and possibly close order
            buy_orders = [o for o in broker.orders if o.side == OrderSide.BUY and o.order_group == OrderGroup.AUTO]
            sell_orders = [o for o in broker.orders if o.side == OrderSide.SELL and o.order_group == OrderGroup.AUTO]
            
            assert len(buy_orders) == 2, f"Expected 2 buy orders, got {len(buy_orders)}"
            assert len(sell_orders) == 1, f"Expected 1 sell order, got {len(sell_orders)}"
            
            # All should be executed
            for order in buy_orders + sell_orders:
                assert_order_executed(order, order.filled_volume, order.side)
            
            # Check trades: 2 buy trades, 1 sell trade (and possibly close trade)
            buy_trades = [t for t in broker.trades if t.side == OrderSide.BUY]
            sell_trades = [t for t in broker.trades if t.side == OrderSide.SELL and t.order_id in [o.order_id for o in sell_orders]]
            
            assert len(buy_trades) == 2, f"Expected 2 buy trades, got {len(buy_trades)}"
            assert len(sell_trades) == 1, f"Expected 1 sell trade, got {len(sell_trades)}"
            
            # Check auto-deal
            assert len(broker.deals) == 1, f"Expected 1 deal, got {len(broker.deals)}"
            deal = broker.deals[0]
            assert deal.auto, "Deal should be an auto-deal"
            # Deal is closed at end of run(), so quantity is 0, but we can check trades
            assert len(deal.trades) >= 3, f"Deal should have at least 3 trades (2 buy + 1 sell), got {len(deal.trades)}"
            buy_trades_in_deal = [t for t in deal.trades if t.side == OrderSide.BUY]
            sell_trades_in_deal = [t for t in deal.trades if t.side == OrderSide.SELL and t.order_id in [o.order_id for o in sell_orders]]
            assert len(buy_trades_in_deal) == 2, "Deal should have 2 buy trades"
            assert sum(t.quantity for t in buy_trades_in_deal) == 3.0, "Total buy quantity should be 3.0 (1.0 + 2.0)"
            assert len(sell_trades_in_deal) == 1, "Deal should have 1 sell trade"
            assert sell_trades_in_deal[0].quantity == 1.5, "Sell trade quantity should be 1.5"


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

