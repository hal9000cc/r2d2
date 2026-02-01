"""
Tests for Strategy class - close_deal method.

Tests close_deal functionality:
- Group 1: close_deal called on the same bar as deal creation (Bar 0) - 0 trades expected
- Group 2: close_deal called on the next bar after deal creation (Bar 1) - trades may occur
"""
import pytest
from unittest.mock import Mock, patch

from app.services.tasks.strategy import OrderOperationResult
from app.services.tasks.broker import OrderSide, OrderType, OrderStatus, OrderGroup

# Import helpers from test_strategy_helpers
from tests.test_strategy_helpers import (
    TestStrategy,
    create_broker_and_strategy,
    create_custom_quotes_data,
    test_task
)

# ============================================================================
# Group 1: close_deal on Same Bar (Bar 0) - BUY Tests
# ============================================================================

class TestCloseDealBuy:
    """Test close_deal method for BUY deals."""
    
    def test_close_deal_market_entry_same_bar_no_trigger(self, test_task):
        """Test 1: BUY market entry + close_deal on Bar 0, no stop/take trigger conditions.
        
        Scenario:
        - Bar 0: buy_sltp(market entry, stop=90, take=110) → close_deal()
        - Prices don't match stop/take conditions
        - All orders canceled before order_processing
        
        Expected:
        - 0 trades
        - Deal closed, quantity = 0
        - All orders CANCELED
        - Profit = 0
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 0,
                'method': 'close_deal',
                'args': {
                    'deal_id': None  # Will be set from first result
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            
            # Find or create data entry for this bar
            bar_data = None
            for data in collected_data:
                if data['bar'] == bar_index:
                    bar_data = data
                    break
            
            if bar_data is None:
                # Create new entry for this bar
                bar_data = {
                    'bar': bar_index,
                    'price': current_price,
                    'trades_count': len(strategy.broker.trades),
                }
                collected_data.append(bar_data)
            else:
                # Update existing entry
                bar_data['trades_count'] = len(strategy.broker.trades)
            
            # Always update method_result if provided
            if method_result:
                bar_data['method_result'] = method_result
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for close_deal
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_1")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check no trades on any bar
        assert collected_data[0]['trades_count'] == 0, "No trades on bar 0"
        assert collected_data[1]['trades_count'] == 0, "No trades on bar 1"
        assert collected_data[2]['trades_count'] == 0, "No trades on bar 2"
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        # Check deal state
        deal = broker.get_deal(deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, f"Expected profit None (no trades), got {deal.profit}"
        
        # Check order statuses
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        
        assert len(entry_orders) == 1, "Should have one entry order"
        assert entry_orders[0].status == OrderStatus.CANCELED, "Entry order should be CANCELED"
        
        assert len(stop_orders) == 1, "Should have one stop order"
        assert stop_orders[0].status == OrderStatus.CANCELED, "Stop order should be CANCELED"
        
        assert len(take_orders) == 1, "Should have one take profit order"
        assert take_orders[0].status == OrderStatus.CANCELED, "Take profit order should be CANCELED"
    
    def test_close_deal_market_entry_same_bar_take_could_trigger(self, test_task):
        """Test 2: BUY market entry + close_deal on Bar 0, take profit conditions met but canceled.
        
        Scenario:
        - Bar 0: buy_sltp(market entry, stop=90, take=110) → close_deal()
        - High=115.0 would trigger take profit, but close_deal cancels it first
        - All orders canceled before order_processing
        
        Expected:
        - 0 trades
        - Deal closed, quantity = 0
        - All orders CANCELED
        - Profit = 0
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[115.0, 101.0, 101.0],  # High enough for take profit on bar 0
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 0,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_2")
                broker.run(save_results=False)
        
        # Check results - same as test 1
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, "Expected profit None (no trades)"
        
        # All orders should be CANCELED
        for order in deal.orders:
            assert order.status == OrderStatus.CANCELED, f"Order {order.order_id} should be CANCELED"
    
    def test_close_deal_limit_entry_same_bar_entry_only(self, test_task):
        """Test 3: BUY limit entry + close_deal on Bar 0, only entry conditions met.
        
        Scenario:
        - Bar 0: buy_sltp(limit entry at 95, stop=90, take=110) → close_deal()
        - Low=94.0 would trigger limit entry, but close_deal cancels it first
        - All orders canceled before order_processing
        
        Expected:
        - 0 trades
        - Deal closed, quantity = 0
        - All orders CANCELED (including limit entry)
        - Profit = 0
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[94.0, 99.0, 99.0]  # Low enough for limit entry on bar 0
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit order at 95.0
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 0,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_3")
                broker.run(save_results=False)
        
        # Check results
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, "Expected profit None (no trades)"
        
        # Check that limit entry order is CANCELED
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        assert entry_orders[0].order_type == OrderType.LIMIT, "Entry should be LIMIT"
        assert entry_orders[0].status == OrderStatus.CANCELED, "Entry limit order should be CANCELED"
        
        # All orders should be CANCELED
        for order in deal.orders:
            assert order.status == OrderStatus.CANCELED, f"Order {order.order_id} should be CANCELED"
    
    def test_close_deal_limit_entry_same_bar_entry_take_could(self, test_task):
        """Test 4: BUY limit entry + close_deal on Bar 0, entry and take profit conditions met.
        
        Scenario:
        - Bar 0: buy_sltp(limit entry at 95, stop=90, take=110) → close_deal()
        - Low=94.0 for limit, High=115.0 for take - both would trigger
        - close_deal cancels all orders before order_processing
        
        Expected:
        - 0 trades
        - Deal closed, quantity = 0
        - All orders CANCELED
        - Profit = 0
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[115.0, 101.0, 101.0],  # High enough for take profit
            lows=[94.0, 99.0, 99.0]  # Low enough for limit entry
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 0,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_4")
                broker.run(save_results=False)
        
        # Check results - same as test 3
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, "Expected profit None (no trades)"
        
        for order in deal.orders:
            assert order.status == OrderStatus.CANCELED, f"Order {order.order_id} should be CANCELED"
    
    # ============================================================================
    # Group 2: close_deal on Next Bar (Bar 1) - BUY Tests
    # ============================================================================
    
    def test_close_deal_limit_entry_next_bar_before_entry_triggers(self, test_task):
        """Test 4.5: BUY limit entry on Bar 0, close_deal on Bar 1 before entry triggers.
        
        Scenario:
        - Bar 0: buy_sltp(limit entry at 95, stop=90, take=110)
          - Entry limit does NOT trigger (low=96.0 > 95.0)
          - Stop/Take don't trigger
        - Bar 1: close_deal() BEFORE entry limit can trigger
          - Entry limit would trigger (low=94.0 <= 95.0), but close_deal cancels it first
          - close_deal cancels all orders
          - No trades executed
        
        Expected:
        - 0 trades
        - Deal closed, quantity = 0
        - All orders CANCELED
        - Profit = None
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[96.0, 94.0, 99.0]  # Bar 0: low=96.0 > 95.0 (no trigger), Bar 1: low=94.0 <= 95.0 (would trigger)
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit order at 95.0
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            
            # Find or create data entry for this bar
            bar_data = None
            for data in collected_data:
                if data['bar'] == bar_index:
                    bar_data = data
                    break
            
            if bar_data is None:
                bar_data = {
                    'bar': bar_index,
                    'price': current_price,
                    'trades_count': len(strategy.broker.trades),
                }
                collected_data.append(bar_data)
            else:
                bar_data['trades_count'] = len(strategy.broker.trades)
            
            if method_result:
                bar_data['method_result'] = method_result
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_4_5")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check no trades on any bar
        assert collected_data[0]['trades_count'] == 0, "No trades on bar 0"
        assert collected_data[1]['trades_count'] == 0, "No trades on bar 1 (entry canceled before trigger)"
        assert collected_data[2]['trades_count'] == 0, "No trades on bar 2"
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        # Check deal state
        deal = broker.get_deal(deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, f"Expected profit None (no trades), got {deal.profit}"
        
        # Check order statuses - all should be CANCELED
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one limit entry order"
        assert entry_orders[0].status == OrderStatus.CANCELED, "Entry limit order should be CANCELED"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop order"
        assert stop_orders[0].status == OrderStatus.CANCELED, "Stop order should be CANCELED"
        
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        assert take_orders[0].status == OrderStatus.CANCELED, "Take profit order should be CANCELED"
    
    def test_close_deal_market_entry_next_bar_no_trigger(self, test_task):
        """Test 5: BUY market entry on Bar 0, close_deal on Bar 1, no stop/take trigger.
        
        Scenario:
        - Bar 0: buy_sltp(market entry, stop=90, take=110)
          - Entry market executes: BUY 1.0 @ 100.1 (100.0 + slippage)
          - Stop/Take don't trigger (high=101.0, low=99.0)
        - Bar 1: close_deal()
          - close_deal cancels stop/take
          - close_deal creates market SELL 1.0
          - Market SELL executes: @ 99.9 (100.0 - slippage)
        - Bar 2: 2 trades visible
        
        Expected profit:
        - Entry: BUY 1.0 @ 100.1, fee = 0.1001
        - Close: SELL 1.0 @ 99.9, fee = 0.0999
        - Entry cost = 100.2001
        - Exit proceeds = 99.8001
        - Profit = -0.4
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_5")
                broker.run(save_results=False)
        
        # Expected profit calculation
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 0.1
        quantity = 1.0
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 0.1001
        
        close_execution = entry_price - slippage  # 99.9
        close_fee = close_execution * quantity * test_task.fee_taker  # 0.0999
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.2001
        exit_proceeds = close_execution * quantity - close_fee  # 99.8001
        expected_profit = exit_proceeds - entry_cost  # -0.4
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check trade counts per bar
        assert collected_data[0]['trades_count'] == 0, "No trades visible on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry + close trades visible on bar 2"
        assert collected_data[2]['trades_count'] == 2, "Entry + close trades visible on bar 2"
        assert len(broker.trades) == 2, "Total 2 trades"
        
        # Check deal state
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert abs(deal.profit - expected_profit) < 1e-6, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check order statuses
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.MARKET]
        assert len(entry_orders) >= 1, "Should have entry market order"
        entry_order = entry_orders[0]
        assert entry_order.status == OrderStatus.EXECUTED, "Entry order should be EXECUTED"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop order"
        assert stop_orders[0].status == OrderStatus.CANCELED, "Stop order should be CANCELED"
        
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        assert take_orders[0].status == OrderStatus.CANCELED, "Take profit order should be CANCELED"
        
        # Check close market order exists
        close_orders = [o for o in entry_orders if o.side == OrderSide.SELL]
        assert len(close_orders) >= 1, "Should have close market order"
        assert close_orders[0].status == OrderStatus.EXECUTED, "Close order should be EXECUTED"
    
    def test_close_deal_market_entry_next_bar_take_triggered(self, test_task):
        """Test 6: BUY market entry on Bar 0, take profit triggers, close_deal on Bar 1.
        
        Scenario:
        - Bar 0: buy_sltp(market entry, stop=90, take=110)
          - Entry market executes: BUY 1.0 @ 100.1
          - Take profit triggers: SELL 1.0 @ 110.0 (high=115.0)
          - Deal closed, quantity = 0
        - Bar 1: close_deal() on already closed deal
          - close_deal does nothing (deal already closed)
        - Bar 2: still 2 trades
        
        Expected profit:
        - Entry: BUY 1.0 @ 100.1, fee_taker = 0.1001
        - Take: SELL 1.0 @ 110.0, fee_maker = 0.055
        - Entry cost = 100.2001
        - Exit proceeds = 109.945
        - Profit = 9.7449
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[115.0, 101.0, 101.0],  # High enough for take profit on bar 0
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_6")
                broker.run(save_results=False)
        
        # Expected profit calculation
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        take_price = 110.0
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 0.1001
        
        take_execution = take_price  # 110.0 (limit, no slippage)
        take_fee = take_execution * quantity * test_task.fee_maker  # 0.055
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.2001
        exit_proceeds = take_execution * quantity - take_fee  # 109.945
        expected_profit = exit_proceeds - entry_cost  # 9.7449
        
        # Check results
        assert collected_data[0]['trades_count'] == 0, "No trades visible on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry + take trades visible on bar 1"
        assert collected_data[2]['trades_count'] == 2, "Still 2 trades on bar 2"
        assert len(broker.trades) == 2, "Total 2 trades"
        
        # Check deal state
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert abs(deal.profit - expected_profit) < 1e-6, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check order statuses
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert entry_orders[0].status == OrderStatus.EXECUTED, "Entry order should be EXECUTED"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert stop_orders[0].status == OrderStatus.CANCELED, "Stop order should be CANCELED"
        
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert take_orders[0].status == OrderStatus.EXECUTED, "Take profit order should be EXECUTED"
        
        # No close market order should exist (deal closed by take profit)
        market_orders = [o for o in deal.orders if o.order_type == OrderType.MARKET]
        close_orders = [o for o in market_orders if o.side == OrderSide.SELL and o != entry_orders[0]]
        assert len(close_orders) == 0, "Should have no close market order"
    
    def test_close_deal_limit_entry_next_bar_entry_only(self, test_task):
        """Test 7: BUY limit entry on Bar 0, close_deal on Bar 1, only entry triggers.
        
        Scenario:
        - Bar 0: buy_sltp(limit entry at 95, stop=90, take=110)
          - Entry limit executes: BUY 1.0 @ 95.0 (low=94.0)
          - Stop/Take don't trigger
        - Bar 1: close_deal()
          - close_deal creates market SELL 1.0 @ 99.9
        
        Expected profit:
        - Entry: BUY 1.0 @ 95.0, fee_maker = 0.0475
        - Close: SELL 1.0 @ 99.9, fee_taker = 0.0999
        - Entry cost = 95.0475
        - Exit proceeds = 99.8001
        - Profit = 4.7526
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[94.0, 99.0, 99.0]  # Low enough for limit entry on bar 0
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_7")
                broker.run(save_results=False)
        
        # Expected profit calculation
        entry_price = 95.0
        close_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0475
        
        close_execution = close_price - slippage  # 99.9
        close_fee = close_execution * quantity * test_task.fee_taker  # 0.0999
        
        entry_cost = entry_execution * quantity + entry_fee  # 95.0475
        exit_proceeds = close_execution * quantity - close_fee  # 99.8001
        expected_profit = exit_proceeds - entry_cost  # 4.7526
        
        # Check results
        assert collected_data[1]['trades_count'] == 2, "Entry + close trades visible on bar 2"
        assert collected_data[2]['trades_count'] == 2, "Entry + close trades visible on bar 2"
        assert len(broker.trades) == 2, "Total 2 trades"
        
        # Check deal state
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert abs(deal.profit - expected_profit) < 1e-6, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check order statuses
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one limit entry order"
        assert entry_orders[0].status == OrderStatus.EXECUTED, "Entry limit order should be EXECUTED"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert stop_orders[0].status == OrderStatus.CANCELED, "Stop order should be CANCELED"
        
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert take_orders[0].status == OrderStatus.CANCELED, "Take profit order should be CANCELED"
        
        # Check close market order exists
        market_orders = [o for o in deal.orders if o.order_type == OrderType.MARKET]
        close_orders = [o for o in market_orders if o.side == OrderSide.SELL]
        assert len(close_orders) == 1, "Should have close market order"
        assert close_orders[0].status == OrderStatus.EXECUTED, "Close order should be EXECUTED"
    
    def test_close_deal_limit_entry_next_bar_entry_take_trigger(self, test_task):
        """Test 8: BUY limit entry on Bar 0, entry and take profit trigger, close_deal on Bar 1.
        
        Scenario:
        - Bar 0: buy_sltp(limit entry at 95, stop=90, take=110)
          - Entry limit executes: BUY 1.0 @ 95.0 (low=94.0)
          - Take profit triggers: SELL 1.0 @ 110.0 (high=115.0)
          - Deal closed
        - Bar 1: close_deal() on already closed deal
          - Does nothing
        
        Expected profit:
        - Entry: BUY 1.0 @ 95.0, fee_maker = 0.0475
        - Take: SELL 1.0 @ 110.0, fee_maker = 0.055
        - Entry cost = 95.0475
        - Exit proceeds = 109.945
        - Profit = 14.8975
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[115.0, 101.0, 101.0],  # High enough for take profit
            lows=[94.0, 99.0, 99.0]  # Low enough for limit entry
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_8")
                broker.run(save_results=False)
        
        # Expected profit calculation
        entry_price = 95.0
        take_price = 110.0
        quantity = 1.0
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0475
        
        take_execution = take_price  # 110.0 (limit, no slippage)
        take_fee = take_execution * quantity * test_task.fee_maker  # 0.055
        
        entry_cost = entry_execution * quantity + entry_fee  # 95.0475
        exit_proceeds = take_execution * quantity - take_fee  # 109.945
        expected_profit = exit_proceeds - entry_cost  # 14.8975
        
        # Check results
        assert collected_data[1]['trades_count'] == 2, "Entry + take trades visible on bar 1"
        assert collected_data[2]['trades_count'] == 2, "Still 2 trades on bar 2"
        assert len(broker.trades) == 2, "Total 2 trades"
        
        # Check deal state
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert abs(deal.profit - expected_profit) < 1e-6, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check order statuses
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert entry_orders[0].status == OrderStatus.EXECUTED, "Entry limit order should be EXECUTED"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert stop_orders[0].status == OrderStatus.CANCELED, "Stop order should be CANCELED"
        
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert take_orders[0].status == OrderStatus.EXECUTED, "Take profit order should be EXECUTED"
        
        # No close market order should exist
        market_orders = [o for o in deal.orders if o.order_type == OrderType.MARKET]
        assert len(market_orders) == 0, "Should have no market orders"


# ============================================================================
# SELL Tests - Mirror of BUY Tests
# ============================================================================

class TestCloseDealSell:
    """Test close_deal method for SELL deals."""
    
    def test_close_deal_market_entry_same_bar_no_trigger(self, test_task):
        """Test 1 SELL: SELL market entry + close_deal on Bar 0, no stop/take trigger conditions."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 0,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_1")
                broker.run(save_results=False)
        
        # Check results
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, "Expected profit None (no trades)"
        
        for order in deal.orders:
            assert order.status == OrderStatus.CANCELED, f"Order {order.order_id} should be CANCELED"
    
    def test_close_deal_market_entry_same_bar_take_could_trigger(self, test_task):
        """Test 2 SELL: SELL market entry + close_deal on Bar 0, take profit conditions met but canceled."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[85.0, 99.0, 99.0]  # Low enough for take profit on bar 0
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 0,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_2")
                broker.run(save_results=False)
        
        # Check results
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, "Expected profit None (no trades)"
        
        for order in deal.orders:
            assert order.status == OrderStatus.CANCELED, f"Order {order.order_id} should be CANCELED"
    
    def test_close_deal_limit_entry_same_bar_entry_only(self, test_task):
        """Test 3 SELL: SELL limit entry + close_deal on Bar 0, only entry conditions met."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[106.0, 101.0, 101.0],  # High enough for limit entry on bar 0
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),  # Limit order at 105.0
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 0,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_3")
                broker.run(save_results=False)
        
        # Check results
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, "Expected profit None (no trades)"
        
        for order in deal.orders:
            assert order.status == OrderStatus.CANCELED, f"Order {order.order_id} should be CANCELED"
    
    def test_close_deal_limit_entry_same_bar_entry_take_could(self, test_task):
        """Test 4 SELL: SELL limit entry + close_deal on Bar 0, entry and take profit conditions met."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[106.0, 101.0, 101.0],  # High enough for limit entry
            lows=[85.0, 99.0, 99.0]  # Low enough for take profit
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 0,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_4")
                broker.run(save_results=False)
        
        # Check results
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, "Expected profit None (no trades)"
        
        for order in deal.orders:
            assert order.status == OrderStatus.CANCELED, f"Order {order.order_id} should be CANCELED"
    
    # ============================================================================
    # Group 2: close_deal on Next Bar (Bar 1) - SELL Tests
    # ============================================================================
    
    def test_close_deal_limit_entry_next_bar_before_entry_triggers(self, test_task):
        """Test 4.5 SELL: SELL limit entry on Bar 0, close_deal on Bar 1 before entry triggers.
        
        Scenario:
        - Bar 0: sell_sltp(limit entry at 105, stop=110, take=90)
          - Entry limit does NOT trigger (high=104.0 < 105.0)
          - Stop/Take don't trigger
        - Bar 1: close_deal() BEFORE entry limit can trigger
          - Entry limit would trigger (high=106.0 >= 105.0), but close_deal cancels it first
          - close_deal cancels all orders
          - No trades executed
        
        Expected:
        - 0 trades
        - Deal closed, quantity = 0
        - All orders CANCELED
        - Profit = None
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[104.0, 106.0, 101.0],  # Bar 0: high=104.0 < 105.0 (no trigger), Bar 1: high=106.0 >= 105.0 (would trigger)
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),  # Limit order at 105.0
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            
            # Find or create data entry for this bar
            bar_data = None
            for data in collected_data:
                if data['bar'] == bar_index:
                    bar_data = data
                    break
            
            if bar_data is None:
                bar_data = {
                    'bar': bar_index,
                    'price': current_price,
                    'trades_count': len(strategy.broker.trades),
                }
                collected_data.append(bar_data)
            else:
                bar_data['trades_count'] = len(strategy.broker.trades)
            
            if method_result:
                bar_data['method_result'] = method_result
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_4_5")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check no trades on any bar
        assert collected_data[0]['trades_count'] == 0, "No trades on bar 0"
        assert collected_data[1]['trades_count'] == 0, "No trades on bar 1 (entry canceled before trigger)"
        assert collected_data[2]['trades_count'] == 0, "No trades on bar 2"
        assert len(broker.trades) == 0, "Total trades should be 0"
        
        # Check deal state
        deal = broker.get_deal(deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is None, f"Expected profit None (no trades), got {deal.profit}"
        
        # Check order statuses - all should be CANCELED
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one limit entry order"
        assert entry_orders[0].status == OrderStatus.CANCELED, "Entry limit order should be CANCELED"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop order"
        assert stop_orders[0].status == OrderStatus.CANCELED, "Stop order should be CANCELED"
        
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        assert take_orders[0].status == OrderStatus.CANCELED, "Take profit order should be CANCELED"
    
    def test_close_deal_market_entry_next_bar_no_trigger(self, test_task):
        """Test 5 SELL: SELL market entry on Bar 0, close_deal on Bar 1, no stop/take trigger.
        
        Expected profit:
        - Entry: SELL 1.0 @ 99.9 (100.0 - slippage), fee = 0.0999
        - Close: BUY 1.0 @ 100.1 (100.0 + slippage), fee = 0.1001
        - Entry proceeds = 99.8001
        - Exit cost = 100.2001
        - Profit = -0.4
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_5")
                broker.run(save_results=False)
        
        # Expected profit calculation
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        
        entry_execution = entry_price - slippage  # 99.9 (SELL market)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 0.0999
        
        close_execution = entry_price + slippage  # 100.1 (BUY market)
        close_fee = close_execution * quantity * test_task.fee_taker  # 0.1001
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.8001
        exit_cost = close_execution * quantity + close_fee  # 100.2001
        expected_profit = entry_proceeds - exit_cost  # -0.4
        
        # Check results
        assert collected_data[1]['trades_count'] == 2, "Entry + close trades visible on bar 2"
        assert collected_data[2]['trades_count'] == 2, "Entry + close trades visible on bar 2"
        assert len(broker.trades) == 2, "Total 2 trades"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert abs(deal.profit - expected_profit) < 1e-6, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_close_deal_market_entry_next_bar_take_triggered(self, test_task):
        """Test 6 SELL: SELL market entry on Bar 0, take profit triggers, close_deal on Bar 1.
        
        Expected profit:
        - Entry: SELL 1.0 @ 99.9, fee_taker = 0.0999
        - Take: BUY 1.0 @ 90.0, fee_maker = 0.045
        - Entry proceeds = 99.8001
        - Exit cost = 90.045
        - Profit = 9.7551
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[85.0, 99.0, 99.0]  # Low enough for take profit on bar 0
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_6")
                broker.run(save_results=False)
        
        # Expected profit calculation
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        take_price = 90.0
        
        entry_execution = entry_price - slippage  # 99.9
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 0.0999
        
        take_execution = take_price  # 90.0 (limit, no slippage)
        take_fee = take_execution * quantity * test_task.fee_maker  # 0.045
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.8001
        exit_cost = take_execution * quantity + take_fee  # 90.045
        expected_profit = entry_proceeds - exit_cost  # 9.7551
        
        # Check results
        assert collected_data[1]['trades_count'] == 2, "Entry + take trades visible on bar 1"
        assert collected_data[2]['trades_count'] == 2, "Still 2 trades on bar 2"
        assert len(broker.trades) == 2, "Total 2 trades"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert abs(deal.profit - expected_profit) < 1e-6, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_close_deal_limit_entry_next_bar_entry_only(self, test_task):
        """Test 7 SELL: SELL limit entry on Bar 0, close_deal on Bar 1, only entry triggers.
        
        Expected profit:
        - Entry: SELL 1.0 @ 105.0, fee_maker = 0.0525
        - Close: BUY 1.0 @ 100.1, fee_taker = 0.1001
        - Entry proceeds = 104.9475
        - Exit cost = 100.2001
        - Profit = 4.7474
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[106.0, 101.0, 101.0],  # High enough for limit entry on bar 0
            lows=[99.0, 99.0, 99.0]
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_7")
                broker.run(save_results=False)
        
        # Expected profit calculation
        entry_price = 105.0
        close_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0525
        
        close_execution = close_price + slippage  # 100.1 (BUY market)
        close_fee = close_execution * quantity * test_task.fee_taker  # 0.1001
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 104.9475
        exit_cost = close_execution * quantity + close_fee  # 100.2001
        expected_profit = entry_proceeds - exit_cost  # 4.7474
        
        # Check results
        assert collected_data[1]['trades_count'] == 2, "Entry + close trades visible on bar 2"
        assert collected_data[2]['trades_count'] == 2, "Entry + close trades visible on bar 2"
        assert len(broker.trades) == 2, "Total 2 trades"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert abs(deal.profit - expected_profit) < 1e-6, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_close_deal_limit_entry_next_bar_entry_take_trigger(self, test_task):
        """Test 8 SELL: SELL limit entry on Bar 0, entry and take profit trigger, close_deal on Bar 1.
        
        Expected profit:
        - Entry: SELL 1.0 @ 105.0, fee_maker = 0.0525
        - Take: BUY 1.0 @ 90.0, fee_maker = 0.045
        - Entry proceeds = 104.9475
        - Exit cost = 90.045
        - Profit = 14.9025
        """
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[106.0, 101.0, 101.0],  # High enough for limit entry
            lows=[85.0, 99.0, 99.0]  # Low enough for take profit
        )
        
        deal_id = None
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 1,
                'method': 'close_deal',
                'args': {
                    'deal_id': None
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'close_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_close_deal_sell_8")
                broker.run(save_results=False)
        
        # Expected profit calculation
        entry_price = 105.0
        take_price = 90.0
        quantity = 1.0
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0525
        
        take_execution = take_price  # 90.0 (limit, no slippage)
        take_fee = take_execution * quantity * test_task.fee_maker  # 0.045
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 104.9475
        exit_cost = take_execution * quantity + take_fee  # 90.045
        expected_profit = entry_proceeds - exit_cost  # 14.9025
        
        # Check results
        assert collected_data[1]['trades_count'] == 2, "Entry + take trades visible on bar 1"
        assert collected_data[2]['trades_count'] == 2, "Still 2 trades on bar 2"
        assert len(broker.trades) == 2, "Total 2 trades"
        
        deal = broker.get_deal(deal_id)
        assert deal.quantity == 0.0, "Deal should be closed"
        assert deal.is_closed, "Deal should be closed"
        assert abs(deal.profit - expected_profit) < 1e-6, \
            f"Expected profit {expected_profit}, got {deal.profit}"

