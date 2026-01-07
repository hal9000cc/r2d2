"""
Tests for Strategy class - buy_sltp/sell_sltp methods - Group A.

Group A: Basic Order Placement Tests
Tests basic order placement scenarios for buy_sltp and sell_sltp methods.
"""
import pytest
from unittest.mock import Mock, patch

from app.services.tasks.strategy import OrderOperationResult
from app.services.tasks.broker import OrderSide, OrderType, OrderStatus

# Import helpers from test_strategy_helpers
from tests.test_strategy_helpers import (
    TestStrategy,
    create_broker_and_strategy,
    create_custom_quotes_data,
    test_task
)

# ============================================================================
# Group A: Basic Order Placement Tests
# ============================================================================

class TestBuySltpBasicPlacement:
    # Additional tests for Group A2 and A3
    """Test basic buy_sltp order placement scenarios."""
    
    def test_buy_sltp_market_one_stop_one_take(self, test_task):
        """Test A1.1: Market entry, one stop, one take profit."""
        # Prepare quotes data: price 100.0, then drops to trigger stop
        # Bar 2: low should be <= 90.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 90.0, 95.0],
            lows=[99.0, 97.0, 89.0, 94.0]  # Bar 2 low=89.0 triggers stop at 90.0
        )
        
        # Protocol: On bar 0, enter market with stop loss 90.0 and take profit 110.0
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected stop trigger: bar 2 at price 90.0 (stop executes as market, with slippage -0.1 = 89.9)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 90.0
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        exit_execution = stop_trigger - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        expected_profit = exit_execution * quantity - exit_fee - (entry_execution * quantity + entry_fee)  # = -10.29

        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            }
        ]
        
        # Collect data from callback
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id and isRunning=True
            # This is needed because broker_backtesting checks result_id and isRunning in update_state()
            # Ensure isRunning is True before patching
            test_task.isRunning = True
            # Patch Task.load method on the class level
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_market_stop_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check orders: 1 entry (market) + 1 stop + 1 take profit = 3 orders
        # But market order executes immediately, so we should have 1 executed entry + 2 active exit orders
        assert len(method_result.orders) == 3, f"Expected 3 orders, got {len(method_result.orders)}"
        
        # Check entry order (market, should be executed)
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.MARKET]
        assert len(entry_orders) == 1, "Should have one market entry order"
        assert entry_orders[0].status == OrderStatus.EXECUTED, "Market entry should be executed"
        
        # Check exit orders (stop and take profit, should be active initially)
        exit_orders = [o for o in method_result.orders if o.order_type != OrderType.MARKET]
        assert len(exit_orders) == 2, "Should have two exit orders (stop + take profit)"
        
        # Check that stop loss order is SELL STOP
        stop_orders = [o for o in exit_orders if o.order_type == OrderType.STOP]
        assert len(stop_orders) == 1, "Should have one stop order"
        assert stop_orders[0].side == OrderSide.SELL, "Stop order for BUY position should be SELL"
        assert stop_orders[0].trigger_price == 90.0, "Stop trigger price should be 90.0"
        
        # Check that take profit order is SELL LIMIT
        take_orders = [o for o in exit_orders if o.order_type == OrderType.LIMIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        assert take_orders[0].side == OrderSide.SELL, "Take profit for BUY position should be SELL"
        assert take_orders[0].price == 110.0, "Take profit price should be 110.0"
        
        # Check that stop was triggered on bar 2 (price 90.0)
        # After broker.run(), we should check if stop was executed
        # The stop should trigger when low <= trigger_price (90.0)
        # Bar 2 has low around 90.0 (with spread), so stop should trigger
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        # Deal should be closed after stop triggers
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_limit_one_stop_one_take(self, test_task):
        """Test A1.2: Limit entry, one stop, one take profit."""
        # Prepare quotes data: price 100.0, then drops to 95.0 (triggers limit entry), then to 90.0 (triggers stop)
        # Bar 2: low should be <= 95.0 to trigger limit entry
        # Bar 3: low should be <= 90.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 95.0, 90.0],
            lows=[99.0, 97.0, 94.0, 89.0]  # Bar 2 low=94.0 triggers limit at 95.0, Bar 3 low=89.0 triggers stop
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stop loss 90.0 and take profit 110.0
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Expected limit trigger: bar 2 at price 95.0
        # Expected stop trigger: bar 3 at price 90.0 (stop executes as market, with slippage -0.1 = 89.9)
        # Expected profit calculation:
        entry_price = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 90.0
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        exit_execution = stop_trigger - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        expected_profit = exit_execution * quantity - exit_fee - (entry_execution * quantity + entry_fee)  # = -5.1374
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit order at 95.0
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_limit_stop_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4
        
        # Check method result
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert method_result.deal_id > 0
        
        # Check orders: 1 limit entry + 1 stop + 1 take profit = 3 orders
        assert len(method_result.orders) == 3
        
        # Entry order should be LIMIT and initially ACTIVE
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.BUY]
        assert len(entry_orders) == 1
        # Initially active, but should execute on bar 2 when price reaches 95.0
        # After broker.run(), check if it executed
        
        # Check that entry executed on bar 2 (price 95.0)
        # Entry limit at 95.0 should execute when price reaches 95.0
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        # Entry should have executed, so deal should have quantity > 0 initially
        # Then stop should trigger, closing the deal
        assert deal.quantity == 0.0, "Deal should be closed after stop triggers"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"


    def test_buy_sltp_multiple_limits_one_stop_one_take(self, test_task):
        """Test A1.3: Multiple limit entries, one stop, one take profit."""
        # Prepare quotes data: price 100.0, then drops to trigger both limit entries, then to trigger stop
        # Bar 1: low should be <= 99.0 to trigger first limit
        # Bar 2: low should be <= 95.0 to trigger second limit
        # Bar 3: low should be <= 90.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 99.0, 95.0, 90.0],
            lows=[99.0, 98.0, 94.0, 89.0]  # Bar 1 low=98.0 triggers limit at 99.0, Bar 2 low=94.0 triggers limit at 95.0, Bar 3 low=89.0 triggers stop
        )
        
        # Protocol: On bar 0, enter with two limit orders (0.5 at 99.0, 0.5 at 95.0) with stop loss 90.0 and take profit 110.0
        # Entry prices: 99.0 and 95.0 (limits, no slippage, fee_maker)
        # Expected limit triggers: bar 1 at 99.0, bar 2 at 95.0
        # Expected stop trigger: bar 3 at price 90.0 (stop executes as market, with slippage -0.1 = 89.9)
        # Expected profit calculation:
        entry_price1 = 99.0
        entry_price2 = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = quantity1 + quantity2  # 1.0
        stop_trigger = 90.0
        entry_execution1 = entry_price1  # 99.0 (limit, no slippage)
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 99.0 * 0.5 * 0.0005 = 0.02475
        entry_execution2 = entry_price2  # 95.0 (limit, no slippage)
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 95.0 * 0.5 * 0.0005 = 0.02375
        total_entry_cost = entry_execution1 * quantity1 + entry_fee1 + entry_execution2 * quantity2 + entry_fee2  # 99.0*0.5 + 0.02475 + 95.0*0.5 + 0.02375 = 97.0485
        exit_execution = stop_trigger - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee = exit_execution * total_quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        exit_proceeds = exit_execution * total_quantity - exit_fee  # 89.9 * 1.0 - 0.0899 = 89.8101
        expected_profit = exit_proceeds - total_entry_cost  # 89.8101 - 97.0485 = -7.2384
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.5, 99.0), (0.5, 95.0)],  # Two limit orders
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_multiple_limits_stop_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4
        
        # Check method result
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert method_result.deal_id > 0
        
        # Check orders: 2 limit entries + 1 stop + 1 take profit = 4 orders
        assert len(method_result.orders) == 4
        
        # Check entry orders (both should be LIMIT)
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.BUY]
        assert len(entry_orders) == 2, "Should have two limit entry orders"
        
        # Check exit orders
        exit_orders = [o for o in method_result.orders if o.order_type != OrderType.LIMIT or o.side != OrderSide.BUY]
        assert len(exit_orders) == 2, "Should have two exit orders (stop + take profit)"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0, "Deal should be closed after stop triggers"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_market_only_stops(self, test_task):
        """Test A3.1: Market entry, only stop losses (no take profit)."""
        # Prepare quotes data: price 100.0, then drops to trigger stop
        # Bar 2: low should be <= 90.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 90.0, 95.0],
            lows=[99.0, 97.0, 89.0, 94.0]  # Bar 2 low=89.0 triggers stop at 90.0
        )
        
        # Protocol: On bar 0, enter market with stop loss 90.0 (no take profit)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected stop trigger: bar 2 at price 90.0 (stop executes as market, with slippage -0.1 = 89.9)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 90.0
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        exit_execution = stop_trigger - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        expected_profit = exit_execution * quantity - exit_fee - (entry_execution * quantity + entry_fee)  # = -10.29
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0
                    # No take_profit
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_market_only_stops")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4
        
        # Check method result
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert method_result.deal_id > 0
        
        # Check orders: 1 entry (market) + 1 stop = 2 orders (no take profit)
        assert len(method_result.orders) == 2
        
        # Check entry order (market, should be executed)
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.MARKET]
        assert len(entry_orders) == 1
        assert entry_orders[0].status == OrderStatus.EXECUTED
        
        # Check exit orders (only stop, no take profit)
        exit_orders = [o for o in method_result.orders if o.order_type != OrderType.MARKET]
        assert len(exit_orders) == 1
        assert exit_orders[0].order_type == OrderType.STOP
        assert exit_orders[0].trigger_price == 90.0
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0, "Deal should be closed after stop triggers"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_market_only_takes(self, test_task):
        """Test A3.2: Market entry, only take profits (no stop loss)."""
        # Prepare quotes data: price 100.0, then rises to trigger take profit
        # Bar 2: high should be >= 110.0 to trigger take profit
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 110.0, 115.0],
            highs=[101.0, 106.0, 111.0, 116.0]  # Bar 2 high=111.0 triggers take profit at 110.0
        )
        
        # Protocol: On bar 0, enter market with take profit 110.0 (no stop loss)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected take profit trigger: bar 2 at price 110.0 (limit order, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_profit_price = 110.0
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        exit_execution = take_profit_price  # 110.0 (limit, no slippage)
        exit_fee = exit_execution * quantity * test_task.fee_maker  # 110.0 * 1.0 * 0.0005 = 0.055
        expected_profit = exit_execution * quantity - exit_fee - (entry_execution * quantity + entry_fee)  # = 9.7449
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'take_profit': 110.0
                    # No stop_loss
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_market_only_takes")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4
        
        # Check method result
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert method_result.deal_id > 0
        
        # Check orders: 1 entry (market) + 1 take profit = 2 orders (no stop)
        assert len(method_result.orders) == 2
        
        # Check entry order (market, should be executed)
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.MARKET]
        assert len(entry_orders) == 1
        assert entry_orders[0].status == OrderStatus.EXECUTED
        
        # Check exit orders (only take profit, no stop)
        exit_orders = [o for o in method_result.orders if o.order_type != OrderType.MARKET]
        assert len(exit_orders) == 1
        assert exit_orders[0].order_type == OrderType.LIMIT
        assert exit_orders[0].price == 110.0
        
        # Check final state: deal should be closed (take profit triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0, "Deal should be closed after take profit triggers"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"



# ============================================================================
# Group A2: Multiple Stops/Takes Tests - BUY
# ============================================================================

    def test_buy_sltp_market_multiple_stops_equal_takes_equal(self, test_task):
        """Test A2.1: Market entry, multiple stops (equal parts), multiple takes (equal parts)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 90.0, 88.0],
            lows=[99.0, 97.0, 89.0, 87.0]
        )
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        entry_execution = entry_price + slippage
        entry_fee = entry_execution * quantity * test_task.fee_taker
        exit_execution1 = 90.0 - slippage
        exit_fee1 = exit_execution1 * 0.5 * test_task.fee_taker
        exit_execution2 = 88.0 - slippage
        exit_fee2 = exit_execution2 * 0.5 * test_task.fee_taker
        total_entry_cost = entry_execution * quantity + entry_fee
        total_exit_proceeds = exit_execution1 * 0.5 - exit_fee1 + exit_execution2 * 0.5 - exit_fee2
        expected_profit = total_exit_proceeds - total_entry_cost
        
        protocol = [{'bar_index': 0, 'method': 'buy_sltp', 'args': {'enter': 1.0, 'stop_loss': [90.0, 88.0], 'take_profit': [110.0, 112.0]}}]
        collected_data = []
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {'bar': bar_index, 'price': current_price, 'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0, 'trades_count': len(strategy.broker.trades)}
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_market_multiple_stops_takes")
                broker.run(save_results=False)
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert len(method_result.orders) == 5
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert abs(deal.profit - expected_profit) < 0.01, f"Expected profit {expected_profit}, got {deal.profit}"

    def test_buy_sltp_market_multiple_stops_custom_takes_custom(self, test_task):
        """Test A2.2: Market entry, multiple stops (custom fractions), multiple takes (custom fractions)."""
        # Prepare quotes data: price 100.0, then drops to trigger first stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 90.0, 88.0],
            lows=[99.0, 97.0, 89.0, 87.0]  # Bar 2 low=89.0 triggers first stop at 90.0, Bar 3 low=87.0 triggers second stop at 88.0
        )
        
        # Protocol: On bar 0, enter market with stops [(0.3, 90.0), (0.7, 88.0)] and takes [(0.4, 110.0), (0.6, 112.0)]
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 0.1001
        
        # First stop: 30% at 90.0
        stop1_trigger = 90.0
        stop1_qty = 0.3
        exit1_execution = stop1_trigger - slippage  # 89.9
        exit1_fee = exit1_execution * stop1_qty * test_task.fee_taker  # 89.9 * 0.3 * 0.001 = 0.02697
        
        # Second stop: 70% at 88.0
        stop2_trigger = 88.0
        stop2_qty = 0.7
        exit2_execution = stop2_trigger - slippage  # 87.9
        exit2_fee = exit2_execution * stop2_qty * test_task.fee_taker  # 87.9 * 0.7 * 0.001 = 0.06153
        
        total_entry_cost = entry_execution * quantity + entry_fee  # 100.2001
        total_exit_proceeds = exit1_execution * stop1_qty - exit1_fee + exit2_execution * stop2_qty - exit2_fee  # 89.9*0.3 - 0.02697 + 87.9*0.7 - 0.06153 = 88.6115
        expected_profit = total_exit_proceeds - total_entry_cost  # 88.6115 - 100.2001 = -11.5886
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.3, 90.0), (0.7, 88.0)],  # Custom fractions
                    'take_profit': [(0.4, 110.0), (0.6, 112.0)]  # Custom fractions
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_market_custom_stops_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 1 entry + 2 stops + 2 takes = 5 orders
        assert len(method_result.orders) == 5
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_limit_multiple_stops_takes(self, test_task):
        """Test A2.3: Limit entry, multiple stops, multiple takes."""
        # Prepare quotes data: price 100.0, drops to 95.0 (triggers limit), then to 90.0 and 88.0 (triggers stops)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 95.0, 90.0, 88.0],
            lows=[99.0, 97.0, 94.0, 89.0, 87.0]  # Bar 2 triggers limit, Bar 3 triggers first stop, Bar 4 triggers second stop
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stops [90.0, 88.0] and takes [110.0, 112.0]
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        entry_execution = entry_price  # 95.0
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0475
        
        # First stop: 50% at 90.0
        stop1_qty = 0.5
        exit1_execution = 90.0 - slippage  # 89.9
        exit1_fee = exit1_execution * stop1_qty * test_task.fee_taker  # 0.04495
        
        # Second stop: 50% at 88.0
        stop2_qty = 0.5
        exit2_execution = 88.0 - slippage  # 87.9
        exit2_fee = exit2_execution * stop2_qty * test_task.fee_taker  # 0.04395
        
        total_entry_cost = entry_execution * quantity + entry_fee  # 95.0475
        total_exit_proceeds = exit1_execution * stop1_qty - exit1_fee + exit2_execution * stop2_qty - exit2_fee  # 88.8111
        expected_profit = total_exit_proceeds - total_entry_cost  # -6.2364
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),
                    'stop_loss': [90.0, 88.0],
                    'take_profit': [110.0, 112.0]
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_limit_multiple_stops_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 1 limit entry + 2 stops + 2 takes = 5 orders
        assert len(method_result.orders) == 5
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_multiple_limits_multiple_stops_takes(self, test_task):
        """Test A2.4: Multiple limit entries, multiple stops, multiple takes."""
        # Prepare quotes data: price 100.0, drops to trigger limits, then stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 99.0, 95.0, 90.0, 88.0],
            lows=[99.0, 98.0, 94.0, 89.0, 87.0]  # Bar 1 triggers first limit, Bar 2 triggers second limit, Bar 3 triggers first stop, Bar 4 triggers second stop
        )
        
        # Protocol: On bar 0, enter with limits [(0.5, 99.0), (0.5, 95.0)] with stops [90.0, 88.0] and takes [110.0, 112.0]
        # Expected profit calculation:
        entry_price1 = 99.0
        entry_price2 = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = 1.0
        
        entry_execution1 = entry_price1  # 99.0
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 0.02475
        entry_execution2 = entry_price2  # 95.0
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 0.02375
        
        # Stops: 50% at 90.0, 50% at 88.0
        stop1_qty = 0.5
        exit1_execution = 90.0 - slippage  # 89.9
        exit1_fee = exit1_execution * stop1_qty * test_task.fee_taker  # 0.04495
        
        stop2_qty = 0.5
        exit2_execution = 88.0 - slippage  # 87.9
        exit2_fee = exit2_execution * stop2_qty * test_task.fee_taker  # 0.04395
        
        total_entry_cost = entry_execution1 * quantity1 + entry_fee1 + entry_execution2 * quantity2 + entry_fee2  # 97.0485
        total_exit_proceeds = exit1_execution * stop1_qty - exit1_fee + exit2_execution * stop2_qty - exit2_fee  # 88.8111
        expected_profit = total_exit_proceeds - total_entry_cost  # -8.2374
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.5, 99.0), (0.5, 95.0)],
                    'stop_loss': [90.0, 88.0],
                    'take_profit': [110.0, 112.0]
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_multiple_limits_stops_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 2 limit entries + 2 stops + 2 takes = 6 orders
        assert len(method_result.orders) == 6
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_limit_only_stops(self, test_task):
        """Test A3.3: Limit entry, only stop losses (no take profit)."""
        # Prepare quotes data: price 100.0, drops to 95.0 (triggers limit), then to 90.0 (triggers stop)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 95.0, 90.0],
            lows=[99.0, 97.0, 94.0, 89.0]  # Bar 2 triggers limit, Bar 3 triggers stop
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stop loss 90.0 (no take profit)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Expected stop trigger: bar 3 at price 90.0 (stop executes as market, with slippage -0.1 = 89.9)
        # Expected profit calculation:
        entry_price = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        stop_trigger = 90.0
        entry_execution = entry_price  # 95.0
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0475
        exit_execution = stop_trigger - slippage  # 89.9
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 0.0899
        expected_profit = exit_execution * quantity - exit_fee - (entry_execution * quantity + entry_fee)  # = -5.1374
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),
                    'stop_loss': 90.0
                    # No take_profit
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_limit_only_stops")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 1 limit entry + 1 stop = 2 orders
        assert len(method_result.orders) == 2
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_limit_only_takes(self, test_task):
        """Test A3.4: Limit entry, only take profits (no stop loss)."""
        # Prepare quotes data: price 100.0, drops to 95.0 (triggers limit), then rises to 110.0 (triggers take)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 95.0, 110.0],
            lows=[99.0, 97.0, 94.0, 109.0],  # Bar 2 triggers limit
            highs=[101.0, 99.0, 96.0, 111.0]  # Bar 3 high triggers take profit
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with take profit 110.0 (no stop loss)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Expected take profit trigger: bar 3 at price 110.0 (limit order, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 95.0
        quantity = 1.0
        take_profit_price = 110.0
        entry_execution = entry_price  # 95.0
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0475
        exit_execution = take_profit_price  # 110.0
        exit_fee = exit_execution * quantity * test_task.fee_maker  # 0.055
        expected_profit = exit_execution * quantity - exit_fee - (entry_execution * quantity + entry_fee)  # = 14.8975
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),
                    'take_profit': 110.0
                    # No stop_loss
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_limit_only_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 1 limit entry + 1 take profit = 2 orders
        assert len(method_result.orders) == 2
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_multiple_limits_only_stops(self, test_task):
        """Test A3.5: Multiple limit entries, only stop losses (no take profit)."""
        # Prepare quotes data: price 100.0, drops to trigger limits, then stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 99.0, 95.0, 90.0],
            lows=[99.0, 98.0, 94.0, 89.0]  # Bar 1 triggers first limit, Bar 2 triggers second limit, Bar 3 triggers stop
        )
        
        # Protocol: On bar 0, enter with limits [(0.5, 99.0), (0.5, 95.0)] with stop loss 90.0 (no take profit)
        # Expected profit calculation:
        entry_price1 = 99.0
        entry_price2 = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = 1.0
        stop_trigger = 90.0
        
        entry_execution1 = entry_price1  # 99.0
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 0.02475
        entry_execution2 = entry_price2  # 95.0
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 0.02375
        
        exit_execution = stop_trigger - slippage  # 89.9
        exit_fee = exit_execution * total_quantity * test_task.fee_taker  # 0.0899
        
        total_entry_cost = entry_execution1 * quantity1 + entry_fee1 + entry_execution2 * quantity2 + entry_fee2  # 97.0485
        exit_proceeds = exit_execution * total_quantity - exit_fee  # 89.8101
        expected_profit = exit_proceeds - total_entry_cost  # -7.2384
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.5, 99.0), (0.5, 95.0)],
                    'stop_loss': 90.0
                    # No take_profit
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_multiple_limits_only_stops")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 2 limit entries + 1 stop = 3 orders
        assert len(method_result.orders) == 3
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_multiple_limits_only_takes(self, test_task):
        """Test A3.6: Multiple limit entries, only take profits (no stop loss)."""
        # Prepare quotes data: price 100.0, drops to trigger limits, then rises to trigger take
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 99.0, 95.0, 110.0],
            lows=[99.0, 98.0, 94.0, 109.0],  # Bar 1 triggers first limit, Bar 2 triggers second limit
            highs=[101.0, 100.0, 96.0, 111.0]  # Bar 3 high triggers take profit
        )
        
        # Protocol: On bar 0, enter with limits [(0.5, 99.0), (0.5, 95.0)] with take profit 110.0 (no stop loss)
        # Expected profit calculation:
        entry_price1 = 99.0
        entry_price2 = 95.0
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = 1.0
        take_profit_price = 110.0
        
        entry_execution1 = entry_price1  # 99.0
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 0.02475
        entry_execution2 = entry_price2  # 95.0
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 0.02375
        
        exit_execution = take_profit_price  # 110.0
        exit_fee = exit_execution * total_quantity * test_task.fee_maker  # 0.055
        
        total_entry_cost = entry_execution1 * quantity1 + entry_fee1 + entry_execution2 * quantity2 + entry_fee2  # 97.0485
        exit_proceeds = exit_execution * total_quantity - exit_fee  # 109.945
        expected_profit = exit_proceeds - total_entry_cost  # 12.8965
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.5, 99.0), (0.5, 95.0)],
                    'take_profit': 110.0
                    # No stop_loss
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_multiple_limits_only_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 2 limit entries + 1 take profit = 3 orders
        assert len(method_result.orders) == 3
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"




# ============================================================================
# Group A: Basic Order Placement Tests - SELL
# ============================================================================

class TestSellSltpBasicPlacement:
    """Test basic sell_sltp order placement scenarios."""
    
    def test_sell_sltp_market_one_stop_one_take(self, test_task):
        """Test A1.1: Market entry, one stop, one take profit."""
        # Prepare quotes data: price 100.0, then rises to trigger stop
        # Bar 2: high should be >= 110.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 110.0, 108.0],
            highs=[101.0, 106.0, 111.0, 109.0]  # Bar 2 high=111.0 triggers stop at 110.0
        )
        
        # Protocol: On bar 0, enter market SELL with stop loss 110.0 and take profit 90.0
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected stop trigger: bar 2 at price 110.0 (BUY stop executes as market, with slippage +0.1 = 110.1)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 110.0
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        exit_execution = stop_trigger + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        expected_profit = entry_execution * quantity - entry_fee - (exit_execution * quantity + exit_fee)  # = -10.3101
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            }
        ]
        
        # Collect data from callback
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_market_stop_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check orders: 1 entry (market) + 1 stop + 1 take profit = 3 orders
        assert len(method_result.orders) == 3, f"Expected 3 orders, got {len(method_result.orders)}"
        
        # Check entry order (market, should be executed)
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.MARKET]
        assert len(entry_orders) == 1, "Should have one market entry order"
        assert entry_orders[0].status == OrderStatus.EXECUTED, "Market entry should be executed"
        assert entry_orders[0].side == OrderSide.SELL, "Entry order for SELL position should be SELL"
        
        # Check exit orders (stop and take profit, should be active initially)
        exit_orders = [o for o in method_result.orders if o.order_type != OrderType.MARKET]
        assert len(exit_orders) == 2, "Should have two exit orders (stop + take profit)"
        
        # Check that stop loss order is BUY STOP
        stop_orders = [o for o in exit_orders if o.order_type == OrderType.STOP]
        assert len(stop_orders) == 1, "Should have one stop order"
        assert stop_orders[0].side == OrderSide.BUY, "Stop order for SELL position should be BUY"
        assert stop_orders[0].trigger_price == 110.0, "Stop trigger price should be 110.0"
        
        # Check that take profit order is BUY LIMIT
        take_orders = [o for o in exit_orders if o.order_type == OrderType.LIMIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        assert take_orders[0].side == OrderSide.BUY, "Take profit for SELL position should be BUY"
        assert take_orders[0].price == 90.0, "Take profit price should be 90.0"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_limit_one_stop_one_take(self, test_task):
        """Test A1.2: Limit entry, one stop, one take profit."""
        # Prepare quotes data: price 100.0, then rises to 105.0 (triggers limit entry), then to 110.0 (triggers stop)
        # Bar 2: high should be >= 105.0 to trigger limit entry
        # Bar 3: high should be >= 110.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 103.0, 105.0, 110.0],
            highs=[101.0, 104.0, 106.0, 111.0]  # Bar 2 high=106.0 triggers limit at 105.0, Bar 3 high=111.0 triggers stop
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with stop loss 110.0 and take profit 90.0
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Expected limit trigger: bar 2 at price 105.0
        # Expected stop trigger: bar 3 at price 110.0 (BUY stop executes as market, with slippage +0.1 = 110.1)
        # Expected profit calculation:
        entry_price = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 110.0
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        exit_execution = stop_trigger + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        expected_profit = entry_execution * quantity - entry_fee - (exit_execution * quantity + exit_fee)  # = -5.1626
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),  # Limit order at 105.0
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_limit_stop_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4
        
        # Check method result
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert method_result.deal_id > 0
        
        # Check orders: 1 limit entry + 1 stop + 1 take profit = 3 orders
        assert len(method_result.orders) == 3
        
        # Entry order should be LIMIT and SELL
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.SELL]
        assert len(entry_orders) == 1
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0, "Deal should be closed after stop triggers"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_multiple_limits_one_stop_one_take(self, test_task):
        """Test A1.3: Multiple limit entries, one stop, one take profit."""
        # Prepare quotes data: price 100.0, then rises to trigger both limit entries, then to trigger stop
        # Bar 1: high should be >= 101.0 to trigger first limit
        # Bar 2: high should be >= 105.0 to trigger second limit
        # Bar 3: high should be >= 110.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 101.0, 105.0, 110.0],
            highs=[101.0, 102.0, 106.0, 111.0]  # Bar 1 high=102.0 triggers limit at 101.0, Bar 2 high=106.0 triggers limit at 105.0, Bar 3 high=111.0 triggers stop
        )
        
        # Protocol: On bar 0, enter with two SELL limit orders (0.5 at 101.0, 0.5 at 105.0) with stop loss 110.0 and take profit 90.0
        # Entry prices: 101.0 and 105.0 (limits, no slippage, fee_maker)
        # Expected limit triggers: bar 1 at 101.0, bar 2 at 105.0
        # Expected stop trigger: bar 3 at price 110.0 (BUY stop executes as market, with slippage +0.1 = 110.1)
        # Expected profit calculation:
        entry_price1 = 101.0
        entry_price2 = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = quantity1 + quantity2  # 1.0
        stop_trigger = 110.0
        entry_execution1 = entry_price1  # 101.0 (limit, no slippage)
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 101.0 * 0.5 * 0.0005 = 0.02525
        entry_execution2 = entry_price2  # 105.0 (limit, no slippage)
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 105.0 * 0.5 * 0.0005 = 0.02625
        total_entry_proceeds = entry_execution1 * quantity1 - entry_fee1 + entry_execution2 * quantity2 - entry_fee2  # 101.0*0.5 - 0.02525 + 105.0*0.5 - 0.02625 = 102.9485
        exit_execution = stop_trigger + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * total_quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        exit_cost = exit_execution * total_quantity + exit_fee  # 110.1 * 1.0 + 0.1101 = 110.2101
        expected_profit = total_entry_proceeds - exit_cost  # 102.9485 - 110.2101 = -7.2616
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.5, 101.0), (0.5, 105.0)],  # Two limit orders
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_multiple_limits_stop_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4
        
        # Check method result
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert method_result.deal_id > 0
        
        # Check orders: 2 limit entries + 1 stop + 1 take profit = 4 orders
        assert len(method_result.orders) == 4
        
        # Check entry orders (both should be LIMIT and SELL)
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.SELL]
        assert len(entry_orders) == 2, "Should have two limit entry orders"
        
        # Check exit orders
        exit_orders = [o for o in method_result.orders if o.order_type != OrderType.LIMIT or o.side != OrderSide.SELL]
        assert len(exit_orders) == 2, "Should have two exit orders (stop + take profit)"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0, "Deal should be closed after stop triggers"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_market_only_stops(self, test_task):
        """Test A3.1: Market entry, only stop losses (no take profit)."""
        # Prepare quotes data: price 100.0, then rises to trigger stop
        # Bar 2: high should be >= 110.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 110.0, 108.0],
            highs=[101.0, 106.0, 111.0, 109.0]  # Bar 2 high=111.0 triggers stop at 110.0
        )
        
        # Protocol: On bar 0, enter market SELL with stop loss 110.0 (no take profit)
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected stop trigger: bar 2 at price 110.0 (BUY stop executes as market, with slippage +0.1 = 110.1)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 110.0
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        exit_execution = stop_trigger + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        expected_profit = entry_execution * quantity - entry_fee - (exit_execution * quantity + exit_fee)  # = -10.3101
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0
                    # No take_profit
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_market_only_stops")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4
        
        # Check method result
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert method_result.deal_id > 0
        
        # Check orders: 1 entry (market) + 1 stop = 2 orders (no take profit)
        assert len(method_result.orders) == 2
        
        # Check entry order (market, should be executed)
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.MARKET]
        assert len(entry_orders) == 1
        assert entry_orders[0].status == OrderStatus.EXECUTED
        assert entry_orders[0].side == OrderSide.SELL
        
        # Check exit orders (only stop, no take profit)
        exit_orders = [o for o in method_result.orders if o.order_type != OrderType.MARKET]
        assert len(exit_orders) == 1
        assert exit_orders[0].order_type == OrderType.STOP
        assert exit_orders[0].side == OrderSide.BUY
        assert exit_orders[0].trigger_price == 110.0
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0, "Deal should be closed after stop triggers"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_market_only_takes(self, test_task):
        """Test A3.2: Market entry, only take profits (no stop loss)."""
        # Prepare quotes data: price 100.0, then drops to trigger take profit
        # Bar 2: low should be <= 90.0 to trigger take profit
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 90.0, 92.0],
            lows=[99.0, 94.0, 89.0, 91.0]  # Bar 2 low=89.0 triggers take profit at 90.0
        )
        
        # Protocol: On bar 0, enter market SELL with take profit 90.0 (no stop loss)
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected take profit trigger: bar 2 at price 90.0 (BUY limit order, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_profit_price = 90.0
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        exit_execution = take_profit_price  # 90.0 (limit, no slippage)
        exit_fee = exit_execution * quantity * test_task.fee_maker  # 90.0 * 1.0 * 0.0005 = 0.045
        expected_profit = entry_execution * quantity - entry_fee - (exit_execution * quantity + exit_fee)  # = 9.7551
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'take_profit': 90.0
                    # No stop_loss
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_market_only_takes")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4
        
        # Check method result
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        assert method_result.deal_id > 0
        
        # Check orders: 1 entry (market) + 1 take profit = 2 orders (no stop)
        assert len(method_result.orders) == 2
        
        # Check entry order (market, should be executed)
        entry_orders = [o for o in method_result.orders if o.order_type == OrderType.MARKET]
        assert len(entry_orders) == 1
        assert entry_orders[0].status == OrderStatus.EXECUTED
        assert entry_orders[0].side == OrderSide.SELL
        
        # Check exit orders (only take profit, no stop)
        exit_orders = [o for o in method_result.orders if o.order_type != OrderType.MARKET]
        assert len(exit_orders) == 1
        assert exit_orders[0].order_type == OrderType.LIMIT
        assert exit_orders[0].side == OrderSide.BUY
        assert exit_orders[0].price == 90.0
        
        # Check final state: deal should be closed (take profit triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0, "Deal should be closed after take profit triggers"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation from comment above
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"



# ============================================================================
# Group A2: Multiple Stops/Takes Tests - SELL
# ============================================================================

    def test_sell_sltp_market_multiple_stops_equal_takes_equal(self, test_task):
        """Test A2.1: Market entry, multiple stops (equal parts), multiple takes (equal parts)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 102.0, 110.0, 112.0],
            highs=[101.0, 103.0, 111.0, 113.0]
        )
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        entry_execution = entry_price - slippage
        entry_fee = entry_execution * quantity * test_task.fee_taker
        exit_execution1 = 110.0 + slippage
        exit_fee1 = exit_execution1 * 0.5 * test_task.fee_taker
        exit_execution2 = 112.0 + slippage
        exit_fee2 = exit_execution2 * 0.5 * test_task.fee_taker
        total_entry_proceeds = entry_execution * quantity - entry_fee
        total_exit_cost = exit_execution1 * 0.5 + exit_fee1 + exit_execution2 * 0.5 + exit_fee2
        expected_profit = total_entry_proceeds - total_exit_cost
        
        protocol = [{'bar_index': 0, 'method': 'sell_sltp', 'args': {'enter': 1.0, 'stop_loss': [110.0, 112.0], 'take_profit': [90.0, 88.0]}}]
        collected_data = []
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {'bar': bar_index, 'price': current_price, 'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0, 'trades_count': len(strategy.broker.trades)}
            if method_result: data['method_result'] = method_result
            collected_data.append(data)
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_market_multiple_stops_takes")
                broker.run(save_results=False)
        method_result = collected_data[0]['method_result']
        assert method_result is not None and len(method_result.error_messages) == 0
        assert len(method_result.orders) == 5
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None and deal.quantity == 0.0
        assert abs(deal.profit - expected_profit) < 0.01, f"Expected profit {expected_profit}, got {deal.profit}"

    def test_sell_sltp_market_multiple_stops_custom_takes_custom(self, test_task):
        """Test A2.2: Market entry, multiple stops (custom fractions), multiple takes (custom fractions)."""
        # Prepare quotes data: price 100.0, then rises to trigger first stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 102.0, 110.0, 112.0],
            highs=[101.0, 103.0, 111.0, 113.0]  # Bar 2 high=111.0 triggers first stop at 110.0, Bar 3 high=113.0 triggers second stop at 112.0
        )
        
        # Protocol: On bar 0, enter market SELL with stops [(0.3, 110.0), (0.7, 112.0)] and takes [(0.4, 90.0), (0.6, 88.0)]
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        # First stop: 30% at 110.0
        stop1_trigger = 110.0
        stop1_qty = 0.3
        exit1_execution = stop1_trigger + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit1_fee = exit1_execution * stop1_qty * test_task.fee_taker  # 110.1 * 0.3 * 0.001 = 0.03303
        
        # Second stop: 70% at 112.0
        stop2_trigger = 112.0
        stop2_qty = 0.7
        exit2_execution = stop2_trigger + slippage  # 112.0 + 0.1 = 112.1
        exit2_fee = exit2_execution * stop2_qty * test_task.fee_taker  # 112.1 * 0.7 * 0.001 = 0.07847
        
        total_entry_proceeds = entry_execution * quantity - entry_fee  # 99.9 - 0.0999 = 99.8001
        total_exit_cost = exit1_execution * stop1_qty + exit1_fee + exit2_execution * stop2_qty + exit2_fee  # 110.1*0.3 + 0.03303 + 112.1*0.7 + 0.07847 = 111.3115
        expected_profit = total_entry_proceeds - total_exit_cost  # 99.8001 - 111.3115 = -11.5114
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.3, 110.0), (0.7, 112.0)],  # Custom fractions (stops above for SELL)
                    'take_profit': [(0.4, 90.0), (0.6, 88.0)]  # Custom fractions (takes below for SELL)
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_market_custom_stops_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 1 entry + 2 stops + 2 takes = 5 orders
        assert len(method_result.orders) == 5
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_limit_multiple_stops_takes(self, test_task):
        """Test A2.3: Limit entry, multiple stops, multiple takes."""
        # Prepare quotes data: price 100.0, rises to 105.0 (triggers limit), then to 110.0 and 112.0 (triggers stops)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 102.0, 105.0, 110.0, 112.0],
            highs=[101.0, 103.0, 106.0, 111.0, 113.0]  # Bar 2 triggers limit, Bar 3 triggers first stop, Bar 4 triggers second stop
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with stops [110.0, 112.0] and takes [90.0, 88.0]
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        entry_execution = entry_price  # 105.0
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0525
        
        # First stop: 50% at 110.0
        stop1_qty = 0.5
        exit1_execution = 110.0 + slippage  # 110.1 (BUY stop, slippage increases price)
        exit1_fee = exit1_execution * stop1_qty * test_task.fee_taker  # 0.05505
        
        # Second stop: 50% at 112.0
        stop2_qty = 0.5
        exit2_execution = 112.0 + slippage  # 112.1
        exit2_fee = exit2_execution * stop2_qty * test_task.fee_taker  # 0.05605
        
        total_entry_proceeds = entry_execution * quantity - entry_fee  # 105.0 - 0.0525 = 104.9475
        total_exit_cost = exit1_execution * stop1_qty + exit1_fee + exit2_execution * stop2_qty + exit2_fee  # 110.1*0.5 + 0.05505 + 112.1*0.5 + 0.05605 = 111.2111
        expected_profit = total_entry_proceeds - total_exit_cost  # 104.9475 - 111.2111 = -6.2636
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),
                    'stop_loss': [110.0, 112.0],  # Stops above for SELL
                    'take_profit': [90.0, 88.0]  # Takes below for SELL
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_limit_multiple_stops_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 1 limit entry + 2 stops + 2 takes = 5 orders
        assert len(method_result.orders) == 5
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_multiple_limits_multiple_stops_takes(self, test_task):
        """Test A2.4: Multiple limit entries, multiple stops, multiple takes."""
        # Prepare quotes data: price 100.0, rises to trigger limits, then stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 101.0, 105.0, 110.0, 112.0],
            highs=[101.0, 102.0, 106.0, 111.0, 113.0]  # Bar 1 triggers first limit, Bar 2 triggers second limit, Bar 3 triggers first stop, Bar 4 triggers second stop
        )
        
        # Protocol: On bar 0, enter with SELL limits [(0.5, 101.0), (0.5, 105.0)] with stops [110.0, 112.0] and takes [90.0, 88.0]
        # Expected profit calculation:
        entry_price1 = 101.0
        entry_price2 = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = 1.0
        
        entry_execution1 = entry_price1  # 101.0
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 0.02525
        entry_execution2 = entry_price2  # 105.0
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 0.02625
        
        # Stops: 50% at 110.0, 50% at 112.0
        stop1_qty = 0.5
        exit1_execution = 110.0 + slippage  # 110.1 (BUY stop, slippage increases price)
        exit1_fee = exit1_execution * stop1_qty * test_task.fee_taker  # 0.05505
        
        stop2_qty = 0.5
        exit2_execution = 112.0 + slippage  # 112.1
        exit2_fee = exit2_execution * stop2_qty * test_task.fee_taker  # 0.05605
        
        total_entry_proceeds = entry_execution1 * quantity1 - entry_fee1 + entry_execution2 * quantity2 - entry_fee2  # 101.0*0.5 - 0.02525 + 105.0*0.5 - 0.02625 = 102.9485
        total_exit_cost = exit1_execution * stop1_qty + exit1_fee + exit2_execution * stop2_qty + exit2_fee  # 110.1*0.5 + 0.05505 + 112.1*0.5 + 0.05605 = 111.2111
        expected_profit = total_entry_proceeds - total_exit_cost  # 102.9485 - 111.2111 = -8.2626
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.5, 101.0), (0.5, 105.0)],
                    'stop_loss': [110.0, 112.0],  # Stops above for SELL
                    'take_profit': [90.0, 88.0]  # Takes below for SELL
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_multiple_limits_stops_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 2 limit entries + 2 stops + 2 takes = 6 orders
        assert len(method_result.orders) == 6
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_limit_only_stops(self, test_task):
        """Test A3.3: Limit entry, only stop losses (no take profit)."""
        # Prepare quotes data: price 100.0, rises to 105.0 (triggers limit), then to 110.0 (triggers stop)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 102.0, 105.0, 110.0],
            highs=[101.0, 103.0, 106.0, 111.0]  # Bar 2 triggers limit, Bar 3 triggers stop
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with stop loss 110.0 (no take profit)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Expected stop trigger: bar 3 at price 110.0 (BUY stop executes as market, with slippage +0.1 = 110.1)
        # Expected profit calculation:
        entry_price = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity = 1.0
        stop_trigger = 110.0
        entry_execution = entry_price  # 105.0
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0525
        exit_execution = stop_trigger + slippage  # 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 0.1101
        expected_profit = entry_execution * quantity - entry_fee - (exit_execution * quantity + exit_fee)  # = -5.1626
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),
                    'stop_loss': 110.0  # Stop above for SELL
                    # No take_profit
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_limit_only_stops")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 1 limit entry + 1 stop = 2 orders
        assert len(method_result.orders) == 2
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_limit_only_takes(self, test_task):
        """Test A3.4: Limit entry, only take profits (no stop loss)."""
        # Prepare quotes data: price 100.0, rises to 105.0 (triggers limit), then drops to 90.0 (triggers take)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 102.0, 105.0, 90.0],
            highs=[101.0, 103.0, 106.0, 91.0],  # Bar 2 triggers limit
            lows=[99.0, 101.0, 104.0, 89.0]  # Bar 3 low triggers take profit
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with take profit 90.0 (no stop loss)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Expected take profit trigger: bar 3 at price 90.0 (BUY limit order, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 105.0
        quantity = 1.0
        take_profit_price = 90.0
        entry_execution = entry_price  # 105.0
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 0.0525
        exit_execution = take_profit_price  # 90.0
        exit_fee = exit_execution * quantity * test_task.fee_maker  # 0.045
        expected_profit = entry_execution * quantity - entry_fee - (exit_execution * quantity + exit_fee)  # = 14.9025
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),
                    'take_profit': 90.0  # Take below for SELL
                    # No stop_loss
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_limit_only_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 1 limit entry + 1 take profit = 2 orders
        assert len(method_result.orders) == 2
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_multiple_limits_only_stops(self, test_task):
        """Test A3.5: Multiple limit entries, only stop losses (no take profit)."""
        # Prepare quotes data: price 100.0, rises to trigger limits, then stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 101.0, 105.0, 110.0],
            highs=[101.0, 102.0, 106.0, 111.0]  # Bar 1 triggers first limit, Bar 2 triggers second limit, Bar 3 triggers stop
        )
        
        # Protocol: On bar 0, enter with SELL limits [(0.5, 101.0), (0.5, 105.0)] with stop loss 110.0 (no take profit)
        # Expected profit calculation:
        entry_price1 = 101.0
        entry_price2 = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = 1.0
        stop_trigger = 110.0
        
        entry_execution1 = entry_price1  # 101.0
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 0.02525
        entry_execution2 = entry_price2  # 105.0
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 0.02625
        
        exit_execution = stop_trigger + slippage  # 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * total_quantity * test_task.fee_taker  # 0.1101
        
        total_entry_proceeds = entry_execution1 * quantity1 - entry_fee1 + entry_execution2 * quantity2 - entry_fee2  # 101.0*0.5 - 0.02525 + 105.0*0.5 - 0.02625 = 102.9485
        exit_cost = exit_execution * total_quantity + exit_fee  # 110.2101
        expected_profit = total_entry_proceeds - exit_cost  # 102.9485 - 110.2101 = -7.2616
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.5, 101.0), (0.5, 105.0)],
                    'stop_loss': 110.0  # Stop above for SELL
                    # No take_profit
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_multiple_limits_only_stops")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 2 limit entries + 1 stop = 3 orders
        assert len(method_result.orders) == 3
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_sell_sltp_multiple_limits_only_takes(self, test_task):
        """Test A3.6: Multiple limit entries, only take profits (no stop loss)."""
        # Prepare quotes data: price 100.0, rises to trigger limits, then drops to trigger take
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 101.0, 105.0, 90.0],
            highs=[101.0, 102.0, 106.0, 91.0],  # Bar 1 triggers first limit, Bar 2 triggers second limit
            lows=[99.0, 100.0, 104.0, 89.0]  # Bar 3 low triggers take profit
        )
        
        # Protocol: On bar 0, enter with SELL limits [(0.5, 101.0), (0.5, 105.0)] with take profit 90.0 (no stop loss)
        # Expected profit calculation:
        entry_price1 = 101.0
        entry_price2 = 105.0
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = 1.0
        take_profit_price = 90.0
        
        entry_execution1 = entry_price1  # 101.0
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 0.02525
        entry_execution2 = entry_price2  # 105.0
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 0.02625
        
        exit_execution = take_profit_price  # 90.0
        exit_fee = exit_execution * total_quantity * test_task.fee_maker  # 0.045
        
        total_entry_proceeds = entry_execution1 * quantity1 - entry_fee1 + entry_execution2 * quantity2 - entry_fee2  # 101.0*0.5 - 0.02525 + 105.0*0.5 - 0.02625 = 102.9485
        exit_cost = exit_execution * total_quantity + exit_fee  # 90.045
        expected_profit = total_entry_proceeds - exit_cost  # 102.9485 - 90.045 = 12.9035
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.5, 101.0), (0.5, 105.0)],
                    'take_profit': 90.0  # Take below for SELL
                    # No stop_loss
                }
            }
        ]
        
        collected_data = []
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
            collected_data.append(data)
        
        test_task.parameters = {
            'test_protocol': protocol,
            'test_callback': check_callback
        }
        
        # Create broker and run
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            
            # Mock task.load() to return task itself with correct result_id
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_multiple_limits_only_takes")
                broker.run(save_results=False)
        
        # Check results
        method_result = collected_data[0]['method_result']
        assert method_result is not None
        assert len(method_result.error_messages) == 0
        
        # Check orders: 2 limit entries + 1 take profit = 3 orders
        assert len(method_result.orders) == 3
        
        # Check final state
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None
        assert deal.quantity == 0.0
        assert deal.is_closed
        assert deal.profit is not None
        
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"


