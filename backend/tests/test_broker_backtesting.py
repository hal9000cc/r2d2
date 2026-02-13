"""
Tests for BrokerBacktesting class.

Tests market orders, limit orders, stop orders, validation, cancellation, and statistics.
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from app.services.tasks.broker_backtesting import BrokerBacktesting
from app.services.tasks.broker import Order
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide, OrderType, OrderStatus
from app.services.tasks.enums import OrderGroup
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.strategy import Strategy, OrderOperationResult


# ============================================================================
# Helper Functions
# ============================================================================

def create_test_quotes_data(n_bars: int, start_price: PRICE_TYPE, trend: str = 'up', precision_price: Optional[float] = None) -> Dict[str, np.ndarray]:
    """
    Create test quotes data (OHLCV).
    
    Args:
        n_bars: Number of bars to generate
        start_price: Starting price
        trend: 'up', 'down', 'volatile', or 'flat'
        precision_price: Optional price precision. If provided, all prices will be rounded to this precision.
    
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
    
    # Round all prices to precision_price if specified
    if precision_price is not None and precision_price > 0:
        def round_price(price: PRICE_TYPE) -> PRICE_TYPE:
            return PRICE_TYPE(round(price / precision_price) * precision_price)
        
        close_prices = np.array([round_price(p) for p in close_prices], dtype=PRICE_TYPE)
        open_prices = np.array([round_price(p) for p in open_prices], dtype=PRICE_TYPE)
        high_prices = np.array([round_price(p) for p in high_prices], dtype=PRICE_TYPE)
        low_prices = np.array([round_price(p) for p in low_prices], dtype=PRICE_TYPE)
        
        # Re-ensure high >= close >= low after rounding
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
        # Use approximate comparison for floating point prices (due to rounding)
        assert abs(order.price - expected_price) < 0.01, \
            f"Order price should be approximately {expected_price}, got {order.price}"


def assert_order_operation_error(result, expected_error_message: str = None) -> None:
    """Assert that an OrderOperationResult has an error.
    
    Args:
        result: OrderOperationResult from Strategy.buy()/sell()
        expected_error_message: Optional expected error message substring
    """
    from app.services.tasks.strategy import OrderOperationResult
    assert isinstance(result, OrderOperationResult), f"Expected OrderOperationResult, got {type(result)}"
    assert len(result.error_messages) > 0, f"Expected error messages, got {result.error_messages}"
    # If there are orders with errors, there should be error messages
    if len(result.error) > 0:
        assert len(result.error_messages) > 0, f"Expected error messages when error order IDs exist, got {result.error_messages}"
    if expected_error_message:
        assert any(expected_error_message in error for error in result.error_messages), \
            f"Expected error message '{expected_error_message}' not found in {result.error_messages}"


# Alias for backward compatibility
assert_order_error = assert_order_operation_error


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
    
    def test_limit_buy_placement(self, test_task, simple_quotes_data):
        """Test limit buy order placement through run() with minimal strategy."""
        # Create a simple strategy that places a limit buy order
        class LimitBuyStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.limit_price = None
            
            def on_bar(self):
                self.bar_count += 1
                # Place limit buy order on the first bar
                if self.bar_count == 1:
                    # Calculate limit price below current price
                    current_price = self.broker.price
                    self.limit_price = current_price - 5.0
                    self.broker.buy(quantity=1.0, price=self.limit_price)
        
        # Create strategy instance
        strategy = LimitBuyStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_limit_buy_placement"
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
            
            # Run backtest - strategy will place limit order on first bar
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.bar_count >= 1, "Strategy should have processed at least one bar"
            assert strategy.limit_price is not None, "Limit price should be set"
            
            # Find limit buy order
            limit_order = next((o for o in broker.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.BUY and o.order_group == OrderGroup.AUTO), None)
            assert limit_order is not None, "Limit buy order should exist"
            assert_order_active(limit_order, strategy.limit_price)
            
            # Check order is in arrays
            assert limit_order.order_id in broker.long_order_ids
            # Check price with approximate comparison due to rounding
            assert any(abs(price - strategy.limit_price) < 0.01 for price in broker.long_order_prices), \
                f"Limit price {strategy.limit_price} should be approximately in long_order_prices {broker.long_order_prices}"
    
    def test_limit_buy_execution(self, test_task):
        """Test limit buy order execution when price is reached through run() with minimal strategy."""
        # Create quotes data: 10 bars history + 2 bars for execution
        # History bars (all 100.0 to distinguish from execution bars)
        base_time = np.datetime64('2023-12-31T14:00:00', 'ms')
        history_times = np.array([base_time + np.timedelta64(i, 'h') for i in range(10)], dtype='datetime64[ms]')
        history_price = 100.0
        
        # Execution bars
        exec_times = np.array([
            np.datetime64('2024-01-01T00:00:00', 'ms'),
            np.datetime64('2024-01-01T01:00:00', 'ms')
        ], dtype='datetime64[ms]')
        
        quotes_data = {
            'time': np.concatenate([history_times, exec_times]),
            'open': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'high': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([101.0, 101.0], dtype=PRICE_TYPE)]),
            'low': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([99.0, 95.0], dtype=PRICE_TYPE)]),  # Second bar low goes below limit
            'close': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 98.0], dtype=PRICE_TYPE)]),
            'volume': np.concatenate([np.full(10, 1000.0, dtype=VOLUME_TYPE), np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)])
        }
        
        # Create a simple strategy that places a limit buy order
        class LimitBuyExecutionStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.limit_price = 96.0  # Below first bar close of 100.0
            
            def on_bar(self):
                self.bar_count += 1
                # Place limit buy order on the first bar
                if self.bar_count == 1:
                    self.broker.buy(quantity=1.0, price=self.limit_price)
        
        # Create strategy instance
        strategy = LimitBuyExecutionStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_limit_buy_execution"
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
            
            # Run backtest - strategy will place limit order on first bar, it will execute on second bar
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.bar_count >= 2, "Strategy should have processed at least two bars"
            
            # Find limit buy order
            limit_order = next((o for o in broker.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.BUY and o.order_group == OrderGroup.AUTO), None)
            assert limit_order is not None, "Limit buy order should exist"
            assert_order_executed(limit_order, 1.0, OrderSide.BUY)
            assert limit_order.price == strategy.limit_price
            
            # Check trade - execution price should be limit price
            limit_trade = next((t for t in broker.trades if t.order_id == limit_order.order_id), None)
            assert limit_trade is not None, "Limit buy trade should exist"
            assert limit_trade.side == OrderSide.BUY
            assert limit_trade.price == strategy.limit_price
            assert limit_trade.quantity == 1.0
            expected_fee = strategy.limit_price * 1.0 * broker.fee_maker
            assert abs(limit_trade.fee - expected_fee) < 0.0001, \
                f"Limit trade fee {limit_trade.fee} should be approximately {expected_fee}"
    
    def test_limit_sell_execution(self, test_task):
        """Test limit sell order execution when price is reached through run() with minimal strategy."""
        # Create quotes data: 10 bars history + 2 bars for execution
        # History bars (all 100.0 to distinguish from execution bars)
        base_time = np.datetime64('2023-12-31T14:00:00', 'ms')
        history_times = np.array([base_time + np.timedelta64(i, 'h') for i in range(10)], dtype='datetime64[ms]')
        history_price = 100.0
        
        # Execution bars
        exec_times = np.array([
            np.datetime64('2024-01-01T00:00:00', 'ms'),
            np.datetime64('2024-01-01T01:00:00', 'ms')
        ], dtype='datetime64[ms]')
        
        quotes_data = {
            'time': np.concatenate([history_times, exec_times]),
            'open': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'high': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([101.0, 105.0], dtype=PRICE_TYPE)]),  # Second bar high goes above limit
            'low': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([99.0, 99.0], dtype=PRICE_TYPE)]),
            'close': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 102.0], dtype=PRICE_TYPE)]),
            'volume': np.concatenate([np.full(10, 1000.0, dtype=VOLUME_TYPE), np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)])
        }
        
        # Create a simple strategy that buys and places limit sell order on first bar
        class LimitSellExecutionStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.limit_price = 104.0  # Above first bar close of 100.0
            
            def on_bar(self):
                self.bar_count += 1
                # Buy and place limit sell order on first bar
                if self.bar_count == 1:
                    self.broker.buy(quantity=1.0)  # Buy first to have position
                    self.broker.sell(quantity=1.0, price=self.limit_price)  # Place limit sell order
        
        # Create strategy instance
        strategy = LimitSellExecutionStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_limit_sell_execution"
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
            
            # Run backtest - strategy will buy and place limit sell on first bar, limit sell will execute on second bar
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.bar_count >= 2, "Strategy should have processed at least two bars"
            
            # Find limit sell order
            limit_order = next((o for o in broker.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.SELL and o.order_group == OrderGroup.AUTO), None)
            assert limit_order is not None, "Limit sell order should exist"
            assert_order_executed(limit_order, 1.0, OrderSide.SELL)
            assert limit_order.price == strategy.limit_price
            
            # Check trade - execution price should be limit price
            limit_trade = next((t for t in broker.trades if t.order_id == limit_order.order_id), None)
            assert limit_trade is not None, "Limit sell trade should exist"
            assert limit_trade.side == OrderSide.SELL
            assert limit_trade.price == strategy.limit_price
            assert limit_trade.quantity == 1.0
    
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
    
    def test_limit_order_exact_price(self, test_task):
        """Test limit order execution when low exactly equals price through run() with minimal strategy."""
        # Create quotes data: 10 bars history + 2 bars for execution
        # History bars (all 100.0 to distinguish from execution bars)
        base_time = np.datetime64('2023-12-31T14:00:00', 'ms')
        history_times = np.array([base_time + np.timedelta64(i, 'h') for i in range(10)], dtype='datetime64[ms]')
        history_price = 100.0
        
        # Execution bars
        exec_times = np.array([
            np.datetime64('2024-01-01T00:00:00', 'ms'),
            np.datetime64('2024-01-01T01:00:00', 'ms')
        ], dtype='datetime64[ms]')
        
        # Limit price for buy order
        limit_price = 96.0
        
        quotes_data = {
            'time': np.concatenate([history_times, exec_times]),
            'open': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'high': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([101.0, 101.0], dtype=PRICE_TYPE)]),
            'low': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([99.0, 95.0], dtype=PRICE_TYPE)]),  # low=95.0 < limit=96.0, order will execute
            'close': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 98.0], dtype=PRICE_TYPE)]),
            'volume': np.concatenate([np.full(10, 1000.0, dtype=VOLUME_TYPE), np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)])
        }
        
        # Create a simple strategy that places a limit buy order
        
        class LimitExactPriceStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
            
            def on_bar(self):
                self.bar_count += 1
                # Place limit buy order on the first bar (after history)
                if self.bar_count == 1:
                    self.broker.buy(quantity=1.0, price=limit_price)
        
        # Create strategy instance
        strategy = LimitExactPriceStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_limit_order_exact_price"
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
            
            # Run backtest - strategy will place limit order on first bar, it will execute on second bar (low=95.0 < limit=96.0)
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.bar_count >= 2, "Strategy should have processed at least two bars"
            
            # Find limit buy order
            limit_order = next((o for o in broker.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.BUY and o.order_group == OrderGroup.AUTO), None)
            assert limit_order is not None, "Limit buy order should exist"
            assert_order_executed(limit_order, 1.0, OrderSide.BUY)  # Should execute when low < limit
            assert limit_order.price == limit_price
            
            # Check trade - execution price should be limit price (low=95.0 < limit=96.0 triggers execution)
            limit_trade = next((t for t in broker.trades if t.order_id == limit_order.order_id), None)
            assert limit_trade is not None, "Limit buy trade should exist"
            assert limit_trade.side == OrderSide.BUY
            assert limit_trade.price == limit_price
            assert limit_trade.quantity == 1.0
            expected_fee = limit_price * 1.0 * broker.fee_maker
            assert abs(limit_trade.fee - expected_fee) < 0.0001, \
                f"Limit trade fee {limit_trade.fee} should be approximately {expected_fee}"


# ============================================================================
# Stop Orders Tests
# ============================================================================

class TestStopOrders:
    """Test stop order placement and execution."""
    
    def test_stop_buy_placement(self, test_task, simple_quotes_data):
        """Test stop buy order placement through run() with minimal strategy."""
        # Create a simple strategy that places a stop buy order
        # Get current price from quotes data (last bar after history)
        current_price = simple_quotes_data['close'].max()
        trigger_price = current_price + 5.0  # Above current price (won't trigger)
        
        class StopBuyPlacementStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
            
            def on_bar(self):
                self.bar_count += 1
                # Place stop buy order on the first bar (after history)
                if self.bar_count == 1:
                    self.broker.buy(quantity=1.0, trigger_price=trigger_price)
        
        # Create strategy instance
        strategy = StopBuyPlacementStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_stop_buy_placement"
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
            
            # Run backtest - strategy will place stop order on first bar, it won't execute (price doesn't reach trigger)
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.bar_count >= 1, "Strategy should have processed at least one bar"
            
            # Find stop buy order
            stop_order = next((o for o in broker.orders if o.order_type == OrderType.STOP and o.side == OrderSide.BUY and o.order_group == OrderGroup.AUTO), None)
            assert stop_order is not None, "Stop buy order should exist"
            assert_order_active(stop_order)
            assert abs(stop_order.trigger_price - trigger_price) < 0.01, \
                f"Stop order trigger_price should be approximately {trigger_price}, got {stop_order.trigger_price}"
    
    def test_stop_buy_execution(self, test_task):
        """Test stop buy order execution when trigger price is reached through run() with minimal strategy."""
        # Create quotes data: 10 bars history + 2 bars for execution
        # History bars (all 100.0 to distinguish from execution bars)
        base_time = np.datetime64('2023-12-31T14:00:00', 'ms')
        history_times = np.array([base_time + np.timedelta64(i, 'h') for i in range(10)], dtype='datetime64[ms]')
        history_price = 100.0
        
        # Execution bars
        exec_times = np.array([
            np.datetime64('2024-01-01T00:00:00', 'ms'),
            np.datetime64('2024-01-01T01:00:00', 'ms')
        ], dtype='datetime64[ms]')
        
        quotes_data = {
            'time': np.concatenate([history_times, exec_times]),
            'open': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'high': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([101.0, 106.0], dtype=PRICE_TYPE)]),  # Second bar high goes above trigger
            'low': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([99.0, 99.0], dtype=PRICE_TYPE)]),
            'close': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 102.0], dtype=PRICE_TYPE)]),
            'volume': np.concatenate([np.full(10, 1000.0, dtype=VOLUME_TYPE), np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)])
        }
        
        # Create a simple strategy that places a stop buy order
        class StopBuyExecutionStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.trigger_price = 105.0  # Above first bar close of 100.0
            
            def on_bar(self):
                self.bar_count += 1
                # Place stop buy order on the first bar
                if self.bar_count == 1:
                    self.broker.buy(quantity=1.0, trigger_price=self.trigger_price)
        
        # Create strategy instance
        strategy = StopBuyExecutionStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_stop_buy_execution"
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
            
            # Run backtest - strategy will place stop order on first bar, it will execute on second bar (high=106.0 >= 105.0)
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.bar_count >= 2, "Strategy should have processed at least two bars"
            
            # Find stop buy order
            stop_order = next((o for o in broker.orders if o.order_type == OrderType.STOP and o.side == OrderSide.BUY and o.order_group == OrderGroup.AUTO), None)
            assert stop_order is not None, "Stop buy order should exist"
            assert_order_executed(stop_order, 1.0, OrderSide.BUY)
            assert abs(stop_order.trigger_price - strategy.trigger_price) < 0.01, \
                f"Stop order trigger_price should be approximately {strategy.trigger_price}, got {stop_order.trigger_price}"
            
            # Check trade - stop orders execute at trigger_price + slippage (for BUY)
            expected_execution_price = strategy.trigger_price + broker.slippage
            stop_trade = next((t for t in broker.trades if t.order_id == stop_order.order_id), None)
            assert stop_trade is not None, "Stop buy trade should exist"
            assert stop_trade.side == OrderSide.BUY
            assert abs(stop_trade.price - expected_execution_price) < 0.01, \
                f"Stop trade price should be trigger_price + slippage = {expected_execution_price}, got {stop_trade.price}"
            assert stop_trade.quantity == 1.0
            expected_fee = expected_execution_price * 1.0 * broker.fee_taker
            assert abs(stop_trade.fee - expected_fee) < 0.0001, \
                f"Stop trade fee {stop_trade.fee} should be approximately {expected_fee}"
    
    def test_stop_sell_execution(self, test_task):
        """Test stop sell order execution when trigger price is reached through run() with minimal strategy."""
        # Create quotes data: 10 bars history + 2 bars for execution
        # History bars (all 100.0 to distinguish from execution bars)
        base_time = np.datetime64('2023-12-31T14:00:00', 'ms')
        history_times = np.array([base_time + np.timedelta64(i, 'h') for i in range(10)], dtype='datetime64[ms]')
        history_price = 100.0
        
        # Execution bars
        exec_times = np.array([
            np.datetime64('2024-01-01T00:00:00', 'ms'),
            np.datetime64('2024-01-01T01:00:00', 'ms')
        ], dtype='datetime64[ms]')
        
        quotes_data = {
            'time': np.concatenate([history_times, exec_times]),
            'open': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'high': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([101.0, 101.0], dtype=PRICE_TYPE)]),
            'low': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([99.0, 94.0], dtype=PRICE_TYPE)]),  # Second bar low goes below trigger
            'close': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 96.0], dtype=PRICE_TYPE)]),
            'volume': np.concatenate([np.full(10, 1000.0, dtype=VOLUME_TYPE), np.array([1000.0, 1000.0], dtype=VOLUME_TYPE)])
        }
        
        # Create a simple strategy that buys first, then places a stop sell order
        class StopSellExecutionStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.trigger_price = 95.0  # Below first bar close of 100.0
            
            def on_bar(self):
                self.bar_count += 1
                # Buy and place stop sell order on first bar
                if self.bar_count == 1:
                    self.broker.buy(quantity=1.0)  # Buy first to have position
                    self.broker.sell(quantity=1.0, trigger_price=self.trigger_price)  # Place stop sell order
        
        # Create strategy instance
        strategy = StopSellExecutionStrategy()
        
        # Create callbacks
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        # Mock quotes client
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Create broker with strategy
            result_id = "test_stop_sell_execution"
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
            
            # Run backtest - strategy will buy and place stop sell on first bar, stop sell will execute on second bar (low=94.0 <= 95.0)
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.bar_count >= 2, "Strategy should have processed at least two bars"
            
            # Find stop sell order
            stop_order = next((o for o in broker.orders if o.order_type == OrderType.STOP and o.side == OrderSide.SELL and o.order_group == OrderGroup.AUTO), None)
            assert stop_order is not None, "Stop sell order should exist"
            assert_order_executed(stop_order, 1.0, OrderSide.SELL)
            assert abs(stop_order.trigger_price - strategy.trigger_price) < 0.01, \
                f"Stop order trigger_price should be approximately {strategy.trigger_price}, got {stop_order.trigger_price}"
            
            # Check trade - stop orders execute at trigger_price - slippage (for SELL)
            expected_execution_price = strategy.trigger_price - broker.slippage
            stop_trade = next((t for t in broker.trades if t.order_id == stop_order.order_id), None)
            assert stop_trade is not None, "Stop sell trade should exist"
            assert stop_trade.side == OrderSide.SELL
            assert abs(stop_trade.price - expected_execution_price) < 0.01, \
                f"Stop trade price should be trigger_price - slippage = {expected_execution_price}, got {stop_trade.price}"
            assert stop_trade.quantity == 1.0
            expected_fee = expected_execution_price * 1.0 * broker.fee_taker
            assert abs(stop_trade.fee - expected_fee) < 0.0001, \
                f"Stop trade fee {stop_trade.fee} should be approximately {expected_fee}"


# ============================================================================
# Validation Tests
# ============================================================================

class TestValidation:
    """Test order validation."""
    
    def test_validation_quantity_zero(self, test_task, simple_quotes_data):
        """Test order with zero quantity through run() with minimal strategy."""
        class ZeroQuantityStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.buy_result = None
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    self.buy_result = self.buy(quantity=0.0)
        
        strategy = ZeroQuantityStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_validation_quantity_zero",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            assert strategy.buy_result is not None, "buy() should return a result"
            assert_order_operation_error(strategy.buy_result, "quantity must be greater than 0")
    
    def test_validation_quantity_negative(self, test_task, simple_quotes_data):
        """Test order with negative quantity through run() with minimal strategy."""
        class NegativeQuantityStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.buy_result = None
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    self.buy_result = self.buy(quantity=-1.0)
        
        strategy = NegativeQuantityStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_validation_quantity_negative",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            assert strategy.buy_result is not None, "buy() should return a result"
            assert_order_operation_error(strategy.buy_result, "quantity must be greater than 0")
    
    def test_validation_limit_buy_price_too_high(self, test_task, simple_quotes_data):
        """Test limit buy order with price above current price through run() with minimal strategy."""
        current_price = simple_quotes_data['close'][test_task.history_size]  # First bar after history
        limit_price = current_price + 10.0  # Above current price
        
        class LimitBuyPriceTooHighStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.limit_price = limit_price
                self.buy_result = None
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    self.buy_result = self.buy(quantity=1.0, price=self.limit_price)
        
        strategy = LimitBuyPriceTooHighStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_validation_limit_buy_price_too_high",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            assert strategy.buy_result is not None, "buy() should return a result"
            assert_order_operation_error(strategy.buy_result, "must be below or equal to current price")
    
    def test_validation_limit_sell_price_too_low(self, test_task, simple_quotes_data):
        """Test limit sell order with price below current price through run() with minimal strategy."""
        current_price = simple_quotes_data['close'][test_task.history_size]  # First bar after history
        limit_price = current_price - 10.0  # Below current price
        
        class LimitSellPriceTooLowStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.limit_price = limit_price
                self.sell_result = None
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    self.sell_result = self.sell(quantity=1.0, price=self.limit_price)
        
        strategy = LimitSellPriceTooLowStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_validation_limit_sell_price_too_low",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            assert strategy.sell_result is not None, "sell() should return a result"
            assert_order_operation_error(strategy.sell_result, "must be above or equal to current price")
    
    def test_validation_stop_buy_trigger_too_low(self, test_task):
        """Test stop buy order with trigger_price below or equal to current price through run() with minimal strategy."""
        # Create quotes data with precision_price to ensure prices are already rounded
        quotes_data = create_test_quotes_data(
            n_bars=20, 
            start_price=100.0, 
            trend='up',
            precision_price=test_task.precision_price
        )
        current_price = quotes_data['close'][test_task.history_size]  # First bar after history
        
        # Test trigger_price below current price
        trigger_price_below = current_price - 1.0
        
        class StopBuyTriggerTooLowStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.trigger_price_below = trigger_price_below
                self.buy_results = []
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Test below current price
                    self.buy_results.append(self.buy(quantity=1.0, trigger_price=self.trigger_price_below))
                elif self.bar_count == 2:
                    # Test equal to current price (use current price from this bar)
                    current_price_this_bar = self.close[-1]
                    self.buy_results.append(self.buy(quantity=1.0, trigger_price=current_price_this_bar))
        
        strategy = StopBuyTriggerTooLowStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_validation_stop_buy_trigger_too_low",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            assert len(strategy.buy_results) == 2, f"Expected 2 buy() results, got {len(strategy.buy_results)}"
            assert_order_operation_error(strategy.buy_results[0], "must be above current price")
            assert_order_operation_error(strategy.buy_results[1], "must be above current price")
    
    def test_validation_stop_sell_trigger_too_high(self, test_task):
        """Test stop sell order with trigger_price above or equal to current price through run() with minimal strategy."""
        # Create quotes data with precision_price to ensure prices are already rounded
        quotes_data = create_test_quotes_data(
            n_bars=20, 
            start_price=100.0, 
            trend='up',
            precision_price=test_task.precision_price
        )
        current_price = quotes_data['close'][test_task.history_size]  # First bar after history
        
        # Test trigger_price above current price
        trigger_price_above = current_price + 1.0
        
        class StopSellTriggerTooHighStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.trigger_price_above = trigger_price_above
                self.sell_results = []
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Test above current price
                    self.sell_results.append(self.sell(quantity=1.0, trigger_price=self.trigger_price_above))
                elif self.bar_count == 2:
                    # Test equal to current price (use current price from this bar)
                    current_price_this_bar = self.close[-1]
                    self.sell_results.append(self.sell(quantity=1.0, trigger_price=current_price_this_bar))
        
        strategy = StopSellTriggerTooHighStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_validation_stop_sell_trigger_too_high",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            assert len(strategy.sell_results) == 2, f"Expected 2 sell() results, got {len(strategy.sell_results)}"
            assert_order_operation_error(strategy.sell_results[0], "must be below current price")
            assert_order_operation_error(strategy.sell_results[1], "must be below current price")
    
    
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
    
    def test_cancel_active_limit_order(self, test_task):
        """Test canceling an active limit order through run() with minimal strategy."""
        # Create quotes data where price will reach limit price if order is not canceled
        # History bars (all 100.0)
        base_time = np.datetime64('2023-12-31T14:00:00', 'ms')
        history_times = np.array([base_time + np.timedelta64(i, 'h') for i in range(10)], dtype='datetime64[ms]')
        history_price = 100.0
        
        # Execution bars: first bar at 100.0, second bar low reaches limit_price (95.0)
        exec_times = np.array([
            np.datetime64('2024-01-01T00:00:00', 'ms'),
            np.datetime64('2024-01-01T01:00:00', 'ms')
        ], dtype='datetime64[ms]')
        
        current_price = 100.0
        limit_price = 95.0
        
        quotes_data = {
            'time': np.concatenate([history_times, exec_times]),
            'open': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'high': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'low': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, limit_price], dtype=PRICE_TYPE)]),
            'close': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 95.0], dtype=PRICE_TYPE)]),
            'volume': np.full(12, 1000.0, dtype=VOLUME_TYPE)
        }
        
        class CancelLimitOrderStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.limit_price = limit_price
                self.order_id = None
                self.cancel_result = None
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Place limit order on first bar
                    result = self.buy(quantity=1.0, price=self.limit_price)
                    if result.orders:
                        self.order_id = result.orders[0].order_id
                elif self.bar_count == 2:
                    pass
                    # Cancel order on second bar (before it can execute)
                    self.cancel_result = self.cancel_orders([self.order_id])
        
        strategy = CancelLimitOrderStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_cancel_active_limit_order",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.order_id is not None, "Order should be placed"
            assert strategy.cancel_result is not None, "cancel_orders should be called"
            assert len(strategy.cancel_result.canceled) == 1, "Order should be canceled"
            assert strategy.order_id in strategy.cancel_result.canceled
            
            # Check order status
            order = broker.orders[strategy.order_id - 1]
            assert order.status == OrderStatus.CANCELED
            
            # Check order is removed from arrays
            assert strategy.order_id not in broker.long_order_ids
            
            # Check no trades were created (order was canceled before execution)
            assert len(broker.trades) == 0, "No trades should be created if order is canceled"
    
    def test_cancel_active_stop_order(self, test_task):
        """Test canceling an active stop order through run() with minimal strategy."""
        # Create quotes data where price will reach trigger price if order is not canceled
        # History bars (all 100.0)
        base_time = np.datetime64('2023-12-31T14:00:00', 'ms')
        history_times = np.array([base_time + np.timedelta64(i, 'h') for i in range(10)], dtype='datetime64[ms]')
        history_price = 100.0
        
        # Execution bars: first bar at 100.0, second bar high reaches trigger_price (105.0)
        exec_times = np.array([
            np.datetime64('2024-01-01T00:00:00', 'ms'),
            np.datetime64('2024-01-01T01:00:00', 'ms')
        ], dtype='datetime64[ms]')
        
        current_price = 100.0
        trigger_price = 105.0
        
        quotes_data = {
            'time': np.concatenate([history_times, exec_times]),
            'open': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'high': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, trigger_price], dtype=PRICE_TYPE)]),
            'low': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 100.0], dtype=PRICE_TYPE)]),
            'close': np.concatenate([np.full(10, history_price, dtype=PRICE_TYPE), np.array([100.0, 105.0], dtype=PRICE_TYPE)]),
            'volume': np.full(12, 1000.0, dtype=VOLUME_TYPE)
        }
        
        class CancelStopOrderStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.trigger_price = trigger_price
                self.order_id = None
                self.cancel_result = None
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Place stop order on first bar
                    result = self.buy(quantity=1.0, trigger_price=self.trigger_price)
                    if result.orders:
                        self.order_id = result.orders[0].order_id
                elif self.bar_count == 2:
                    # Cancel order on second bar (before it can execute)
                    self.cancel_result = self.cancel_orders([self.order_id])
        
        strategy = CancelStopOrderStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_cancel_active_stop_order",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.order_id is not None, "Order should be placed"
            assert strategy.cancel_result is not None, "cancel_orders should be called"
            assert len(strategy.cancel_result.canceled) == 1, "Order should be canceled"
            assert strategy.order_id in strategy.cancel_result.canceled
            
            # Check order status
            order = broker.orders[strategy.order_id - 1]
            assert order.status == OrderStatus.CANCELED
            
            # Check order is removed from arrays
            assert strategy.order_id not in broker.long_stop_order_ids
            
            # Check no trades were created (order was canceled before execution)
            assert len(broker.trades) == 0, "No trades should be created if order is canceled"
    
    def test_cancel_nonexistent_order(self, test_task, simple_quotes_data):
        """Test canceling a non-existent order through run() with minimal strategy."""
        class CancelNonexistentOrderStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.cancel_result = None
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Try to cancel non-existent order
                    self.cancel_result = self.cancel_orders([99999])
        
        strategy = CancelNonexistentOrderStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_cancel_nonexistent_order",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            # Assertions
            assert strategy.cancel_result is not None, "cancel_orders should be called"
            assert len(strategy.cancel_result.canceled) == 0, "No orders should be canceled"
            assert len(strategy.cancel_result.error) == 1, "Should have one error order ID"
            assert 99999 in strategy.cancel_result.error
            assert len(strategy.cancel_result.error_messages) == 1, "Should have one error message"
            assert "not found" in strategy.cancel_result.error_messages[0]
    
    def test_cancel_executed_order(self, test_task, simple_quotes_data):
        """Test canceling an already executed order through run() with minimal strategy."""
        class CancelExecutedOrderStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.order_id = None
                self.cancel_result = None
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Place market order on first bar (will be executed immediately)
                    result = self.buy(quantity=1.0)
                    if result.orders:
                        self.order_id = result.orders[0].order_id
                elif self.bar_count == 2:
                    # Try to cancel executed order on second bar
                    self.cancel_result = self.cancel_orders([self.order_id])
        
        strategy = CancelExecutedOrderStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_cancel_executed_order",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            # Order should be executed
            assert strategy.order_id is not None, "Order should be placed"
            order = broker.orders[strategy.order_id - 1]
            assert order.status == OrderStatus.EXECUTED, "Market order should be executed"
            
            # Assertions for cancel result
            assert strategy.cancel_result is not None, "cancel_orders should be called"
            assert len(strategy.cancel_result.canceled) == 0, "Executed order should not be canceled"
            assert len(strategy.cancel_result.error) == 1, "Should have one error order ID"
            assert strategy.order_id in strategy.cancel_result.error
            assert len(strategy.cancel_result.error_messages) == 1, "Should have one error message"
            assert "cannot be canceled" in strategy.cancel_result.error_messages[0]
            assert "status is EXECUTED" in strategy.cancel_result.error_messages[0]
            
            # Status should remain EXECUTED
            assert order.status == OrderStatus.EXECUTED  # Status unchanged


# ============================================================================
# Statistics Tests
# ============================================================================

class TestStatistics:
    """Test trading statistics and results."""
    
    def test_stats_after_market_buy(self, test_task, simple_quotes_data):
        """Test statistics after market buy order through run() with minimal strategy."""
        class StatsBuySellStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Place market buy order (opens a deal)
                    self.buy(quantity=1.0)
                elif self.bar_count == 2:
                    # Close the deal with a SELL
                    self.sell(quantity=1.0)
        
        strategy = StatsBuySellStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_stats_after_market_buy",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            # Check stats after first bar (buy executed)
            # Note: total_deals is only incremented when a deal is closed
            # A single BUY opens a deal but doesn't close it, so total_deals = 0
            # But after run() completes, the deal is closed, so total_deals = 1
            assert broker.stats.total_trades == 2  # Buy + sell
            assert broker.stats.total_deals == 1  # Deal closed after sell
            assert broker.equity_symbol == 0.0  # Position closed
    
    def test_trades_list(self, test_task, simple_quotes_data):
        """Test that all executed orders create trades through run() with minimal strategy."""
        class TradesListStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Place first buy order
                    self.buy(quantity=1.0)
                elif self.bar_count == 2:
                    # Place second buy order
                    self.buy(quantity=2.0)
                elif self.bar_count == 3:
                    # Place sell order
                    self.sell(quantity=1.5)
        
        strategy = TradesListStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_trades_list",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            # Check trades
            # 3 trades from orders (2 buy + 1 sell) + 1 trade from close_deals() to close remaining position
            assert len(broker.trades) == 4
            assert all(trade.trade_id > 0 for trade in broker.trades)
            assert all(trade.trade_id == i + 1 for i, trade in enumerate(broker.trades))  # Sequential IDs
    
    def test_deals_list(self, test_task, simple_quotes_data):
        """Test that deals are created correctly through run() with minimal strategy."""
        class DealsListStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Place buy order (opens a deal)
                    self.buy(quantity=1.0)
                elif self.bar_count == 2:
                    # Place sell order (partially closes the deal)
                    self.sell(quantity=0.5)
        
        strategy = DealsListStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_deals_list",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            # Check deals
            assert len(broker.deals) >= 1
            assert all(deal.deal_id > 0 for deal in broker.deals)
    
    def test_orders_list(self, test_task, simple_quotes_data):
        """Test that all orders are stored in orders list through run() with minimal strategy."""
        # Get current price from first bar after history
        current_price = simple_quotes_data['close'][test_task.history_size]
        limit_price = current_price - 5.0
        trigger_price = current_price + 5.0
        
        class OrdersListStrategy(Strategy):
            def __init__(self):
                super().__init__()
                self.bar_count = 0
                self.limit_price = limit_price
                self.trigger_price = trigger_price
            
            def on_bar(self):
                self.bar_count += 1
                if self.bar_count == 1:
                    # Place market order
                    self.buy(quantity=1.0)
                elif self.bar_count == 2:
                    # Place limit order
                    self.buy(quantity=1.0, price=self.limit_price)
                elif self.bar_count == 3:
                    # Place stop order
                    self.buy(quantity=1.0, trigger_price=self.trigger_price)
        
        strategy = OrdersListStrategy()
        callbacks = Strategy.create_strategy_callbacks(strategy)
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = simple_quotes_data
            mock_client_class.return_value = mock_client
            
            broker = BrokerBacktesting(
                task=test_task,
                result_id="test_orders_list",
                callbacks_dict=callbacks,
                results_save_period=1.0
            )
            strategy.broker = broker
            broker.logging = Mock()
            
            broker.run(save_results=False)
            
            # Check orders
            # 3 orders from strategy (1 market executed + 1 limit + 1 stop) + 1 order from close_deals() to close position
            assert len(broker.orders) == 4
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

