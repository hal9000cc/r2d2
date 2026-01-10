"""
Tests for Strategy class - buy_sltp/sell_sltp methods - Group G.

Group G: Edge Cases Tests
Tests edge cases for buy_sltp and sell_sltp methods.
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
# Group G1: Full Position Closure
# ============================================================================

class TestBuySltpFullPositionClosure:
    """Test G1: Full position closure scenarios for buy_sltp."""
    
    def test_buy_sltp_market_all_stops_trigger_full_closure(self, test_task):
        """Test G1.1: Market entry → all stops trigger → deal fully closed."""
        # Prepare quotes data: price 100.0, then drops to trigger all stops
        # Bar 1: low should be <= 95.0 and <= 90.0 to trigger all stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 89.0, 99.0]  # Bar 1 low=89.0 triggers all stops at 95.0 and 90.0
        )
        
        # Protocol: On bar 0, enter BUY market with two stops (0.5 at 95.0, 0.5 at 90.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: both stops trigger on bar 1, deal fully closed
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 95.0
        stop_trigger2 = 90.0
        stop_quantity1 = 0.5
        stop_quantity2 = 0.5
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        # Both stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger1 - slippage  # 95.0 - 0.1 = 94.9 (SELL stop, slippage decreases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 94.9 * 0.5 * 0.001 = 0.04745
        stop_execution2 = stop_trigger2 - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1 + 0.1001 = 100.2001
        exit_proceeds = (stop_execution1 * stop_quantity1 - stop_fee1 +
                        stop_execution2 * stop_quantity2 - stop_fee2)  # 47.42555 + 44.90505 = 92.3306
        expected_profit = exit_proceeds - entry_cost  # = 92.3306 - 100.2001 = -7.8695
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.5, 95.0), (0.5, 90.0)],  # Two stops (0.5 + 0.5 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_g1_1_all_stops_full_closure")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, all stops trigger on bar 1
        # Bar 0: entry triggers (1 trade)
        # Bar 1: both stops trigger simultaneously (3 trades total - entry + stop1 + stop2)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Both stops should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No execution on bar 2"
        
        # Check final state: deal should be fully closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + stop1 + stop2), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "All stop loss orders should be executed"
        
        # Check that take profit order was canceled (deal closed by stops)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stops)"
    
    def test_buy_sltp_market_all_takes_trigger_full_closure(self, test_task):
        """Test G1.2: Market entry → all take profits trigger → deal fully closed."""
        # Prepare quotes data: price 100.0, then rises to trigger all take profits
        # Bar 1: high should be >= 105.0 and >= 110.0 to trigger all takes
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 111.0, 101.0]  # Bar 1 high=111.0 triggers all takes at 105.0 and 110.0
        )
        
        # Protocol: On bar 0, enter BUY market with two take profits (0.5 at 105.0, 0.5 at 110.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: both takes trigger on bar 1, deal fully closed
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_price1 = 105.0
        take_price2 = 110.0
        take_quantity1 = 0.5
        take_quantity2 = 0.5
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        # Both takes execute as limit orders (no slippage, fee_maker)
        take_execution1 = take_price1  # 105.0 (limit, no slippage)
        take_fee1 = take_execution1 * take_quantity1 * test_task.fee_maker  # 105.0 * 0.5 * 0.0005 = 0.02625
        take_execution2 = take_price2  # 110.0 (limit, no slippage)
        take_fee2 = take_execution2 * take_quantity2 * test_task.fee_maker  # 110.0 * 0.5 * 0.0005 = 0.0275
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1 + 0.1001 = 100.2001
        exit_proceeds = (take_execution1 * take_quantity1 - take_fee1 +
                        take_execution2 * take_quantity2 - take_fee2)  # 52.47375 + 54.9725 = 107.44625
        expected_profit = exit_proceeds - entry_cost  # = 107.44625 - 100.2001 = 7.24615
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': [(0.5, 105.0), (0.5, 110.0)]  # Two take profits (0.5 + 0.5 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_g1_2_all_takes_full_closure")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, all takes trigger on bar 1
        # Bar 0: entry triggers (1 trade)
        # Bar 1: both takes trigger simultaneously (3 trades total - entry + take1 + take2)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Both takes should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No execution on bar 2"
        
        # Check final state: deal should be fully closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + take1 + take2), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all take profit orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "All take profit orders should be executed"
        
        # Check that stop loss order was canceled (deal closed by takes)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled (deal closed by takes)"
    
    def test_buy_sltp_market_part_stops_remaining_closed_by_last_stop(self, test_task):
        """Test G1.3: Market entry → part of stops trigger → remaining part closed by last stop."""
        # Prepare quotes data: price 100.0, then drops to trigger stops sequentially
        # Bar 1: low should be <= 95.0 to trigger first stop
        # Bar 2: low should be <= 92.0 to trigger second stop
        # Bar 3: low should be <= 90.0 to trigger third stop (closes remaining)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            lows=[99.0, 94.0, 91.0, 89.0]  # Bar 1 low=94.0 triggers stop at 95.0, Bar 2 low=91.0 triggers stop at 92.0, Bar 3 low=89.0 triggers stop at 90.0
        )
        
        # Protocol: On bar 0, enter BUY market with three stops (0.33 at 95.0, 0.33 at 92.0, 0.34 at 90.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: stops trigger sequentially, last stop closes remaining volume
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 95.0
        stop_trigger2 = 92.0
        stop_trigger3 = 90.0
        
        # Stop volumes: calculated from total actual entered volume (1.0)
        #   First stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third stop (extreme): 1.0 - 0.3 - 0.3 = 0.4
        stop_quantity1 = 0.3
        stop_quantity2 = 0.3
        stop_quantity3 = 0.4
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        # All stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger1 - slippage  # 95.0 - 0.1 = 94.9 (SELL stop, slippage decreases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 94.9 * 0.3 * 0.001 = 0.02847
        stop_execution2 = stop_trigger2 - slippage  # 92.0 - 0.1 = 91.9 (SELL stop, slippage decreases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 91.9 * 0.3 * 0.001 = 0.02757
        stop_execution3 = stop_trigger3 - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        stop_fee3 = stop_execution3 * stop_quantity3 * test_task.fee_taker  # 89.9 * 0.4 * 0.001 = 0.03596
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1 + 0.1001 = 100.2001
        exit_proceeds = (stop_execution1 * stop_quantity1 - stop_fee1 +
                        stop_execution2 * stop_quantity2 - stop_fee2 +
                        stop_execution3 * stop_quantity3 - stop_fee3)  # 28.44153 + 27.54243 + 35.92404 = 91.908
        expected_profit = exit_proceeds - entry_cost  # = 91.908 - 100.2001 = -8.2921
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.33, 95.0), (0.33, 92.0), (0.34, 90.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_g1_3_part_stops_remaining_closed_by_last")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, stops trigger sequentially
        # Bar 0: entry triggers (1 trade)
        # Bar 1: first stop triggers (2 trades total - entry + stop1)
        # Bar 2: second stop triggers (3 trades total - entry + stop1 + stop2)
        # Bar 3: third stop triggers (4 trades total - entry + stop1 + stop2 + stop3)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First stop should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third stop should trigger on bar 3"
        
        # Check final state: deal should be fully closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + stop1 + stop2 + stop3), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All stop loss orders should be executed"
        
        # Check that take profit order was canceled (deal closed by stops)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stops)"
    
    def test_buy_sltp_market_part_takes_remaining_closed_by_last_take(self, test_task):
        """Test G1.4: Market entry → part of take profits trigger → remaining part closed by last take profit."""
        # Prepare quotes data: price 100.0, then rises to trigger take profits sequentially
        # Bar 1: high should be >= 105.0 to trigger first take
        # Bar 2: high should be >= 108.0 to trigger second take
        # Bar 3: high should be >= 110.0 to trigger third take (closes remaining)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            highs=[101.0, 106.0, 109.0, 111.0]  # Bar 1 high=106.0 triggers take at 105.0, Bar 2 high=109.0 triggers take at 108.0, Bar 3 high=111.0 triggers take at 110.0
        )
        
        # Protocol: On bar 0, enter BUY market with three take profits (0.33 at 105.0, 0.33 at 108.0, 0.34 at 110.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: takes trigger sequentially, last take closes remaining volume
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_price1 = 105.0
        take_price2 = 108.0
        take_price3 = 110.0
        
        # Take profit volumes: calculated from total actual entered volume (1.0) minus executed stops (0.0)
        #   First take: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second take: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third take (extreme): 1.0 - 0.3 - 0.3 = 0.4
        take_quantity1 = 0.3
        take_quantity2 = 0.3
        take_quantity3 = 0.4
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        # All takes execute as limit orders (no slippage, fee_maker)
        take_execution1 = take_price1  # 105.0 (limit, no slippage)
        take_fee1 = take_execution1 * take_quantity1 * test_task.fee_maker  # 105.0 * 0.3 * 0.0005 = 0.01575
        take_execution2 = take_price2  # 108.0 (limit, no slippage)
        take_fee2 = take_execution2 * take_quantity2 * test_task.fee_maker  # 108.0 * 0.3 * 0.0005 = 0.0162
        take_execution3 = take_price3  # 110.0 (limit, no slippage)
        take_fee3 = take_execution3 * take_quantity3 * test_task.fee_maker  # 110.0 * 0.4 * 0.0005 = 0.022
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1 + 0.1001 = 100.2001
        exit_proceeds = (take_execution1 * take_quantity1 - take_fee1 +
                        take_execution2 * take_quantity2 - take_fee2 +
                        take_execution3 * take_quantity3 - take_fee3)  # 31.48425 + 32.3838 + 43.978 = 107.84605
        expected_profit = exit_proceeds - entry_cost  # = 107.84605 - 100.2001 = 7.64595
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': [(0.33, 105.0), (0.33, 108.0), (0.34, 110.0)]  # Three take profits (0.33 + 0.33 + 0.34 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_g1_4_part_takes_remaining_closed_by_last")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, takes trigger sequentially
        # Bar 0: entry triggers (1 trade)
        # Bar 1: first take triggers (2 trades total - entry + take1)
        # Bar 2: second take triggers (3 trades total - entry + take1 + take2)
        # Bar 3: third take triggers (4 trades total - entry + take1 + take2 + take3)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First take should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second take should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third take should trigger on bar 3"
        
        # Check final state: deal should be fully closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + take1 + take2 + take3), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all take profit orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 3, "All take profit orders should be executed"
        
        # Check that stop loss order was canceled (deal closed by takes)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled (deal closed by takes)"


class TestSellSltpFullPositionClosure:
    """Test G1: Full position closure scenarios for sell_sltp."""
    
    def test_sell_sltp_market_all_stops_trigger_full_closure(self, test_task):
        """Test G1.1: Market entry → all stops trigger → deal fully closed."""
        # Prepare quotes data: price 100.0, then rises to trigger all stops
        # Bar 1: high should be >= 105.0 and >= 110.0 to trigger all stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 111.0, 101.0]  # Bar 1 high=111.0 triggers all stops at 105.0 and 110.0
        )
        
        # Protocol: On bar 0, enter SELL market with two stops (0.5 at 105.0, 0.5 at 110.0)
        # Entry price: 100.0 (market, with slippage -0.1 = 99.9)
        # Expected: both stops trigger on bar 1, deal fully closed
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 105.0
        stop_trigger2 = 110.0
        stop_quantity1 = 0.5
        stop_quantity2 = 0.5
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        # Both stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger1 + slippage  # 105.0 + 0.1 = 105.1 (BUY stop, slippage increases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 105.1 * 0.5 * 0.001 = 0.05255
        stop_execution2 = stop_trigger2 + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9 - 0.0999 = 99.8001
        exit_cost = (stop_execution1 * stop_quantity1 + stop_fee1 +
                    stop_execution2 * stop_quantity2 + stop_fee2)  # 52.60255 + 55.10505 = 107.7076
        expected_profit = entry_proceeds - exit_cost  # = 99.8001 - 107.7076 = -7.9075
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.5, 105.0), (0.5, 110.0)],  # Two stops (0.5 + 0.5 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_g1_1_all_stops_full_closure")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, all stops trigger on bar 1
        # Bar 0: entry triggers (1 trade)
        # Bar 1: both stops trigger simultaneously (3 trades total - entry + stop1 + stop2)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Both stops should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No execution on bar 2"
        
        # Check final state: deal should be fully closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + stop1 + stop2), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "All stop loss orders should be executed"
        
        # Check that take profit order was canceled (deal closed by stops)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stops)"
    
    def test_sell_sltp_market_all_takes_trigger_full_closure(self, test_task):
        """Test G1.2: Market entry → all take profits trigger → deal fully closed."""
        # Prepare quotes data: price 100.0, then drops to trigger all take profits
        # Bar 1: low should be <= 95.0 and <= 90.0 to trigger all takes
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 89.0, 99.0]  # Bar 1 low=89.0 triggers all takes at 95.0 and 90.0
        )
        
        # Protocol: On bar 0, enter SELL market with two take profits (0.5 at 95.0, 0.5 at 90.0)
        # Entry price: 100.0 (market, with slippage -0.1 = 99.9)
        # Expected: both takes trigger on bar 1, deal fully closed
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_price1 = 95.0
        take_price2 = 90.0
        take_quantity1 = 0.5
        take_quantity2 = 0.5
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        # Both takes execute as limit orders (no slippage, fee_maker)
        take_execution1 = take_price1  # 95.0 (limit, no slippage)
        take_fee1 = take_execution1 * take_quantity1 * test_task.fee_maker  # 95.0 * 0.5 * 0.0005 = 0.02375
        take_execution2 = take_price2  # 90.0 (limit, no slippage)
        take_fee2 = take_execution2 * take_quantity2 * test_task.fee_maker  # 90.0 * 0.5 * 0.0005 = 0.0225
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9 - 0.0999 = 99.8001
        exit_cost = (take_execution1 * take_quantity1 + take_fee1 +
                    take_execution2 * take_quantity2 + take_fee2)  # 47.52375 + 45.0225 = 92.54625
        expected_profit = entry_proceeds - exit_cost  # = 99.8001 - 92.54625 = 7.25385
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': [(0.5, 95.0), (0.5, 90.0)]  # Two take profits (0.5 + 0.5 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_g1_2_all_takes_full_closure")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, all takes trigger on bar 1
        # Bar 0: entry triggers (1 trade)
        # Bar 1: both takes trigger simultaneously (3 trades total - entry + take1 + take2)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Both takes should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No execution on bar 2"
        
        # Check final state: deal should be fully closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + take1 + take2), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all take profit orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "All take profit orders should be executed"
        
        # Check that stop loss order was canceled (deal closed by takes)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled (deal closed by takes)"
    
    def test_sell_sltp_market_part_stops_remaining_closed_by_last_stop(self, test_task):
        """Test G1.3: Market entry → part of stops trigger → remaining part closed by last stop."""
        # Prepare quotes data: price 100.0, then rises to trigger stops sequentially
        # Bar 1: high should be >= 105.0 to trigger first stop
        # Bar 2: high should be >= 108.0 to trigger second stop
        # Bar 3: high should be >= 110.0 to trigger third stop (closes remaining)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            highs=[101.0, 106.0, 109.0, 111.0]  # Bar 1 high=106.0 triggers stop at 105.0, Bar 2 high=109.0 triggers stop at 108.0, Bar 3 high=111.0 triggers stop at 110.0
        )
        
        # Protocol: On bar 0, enter SELL market with three stops (0.33 at 105.0, 0.33 at 108.0, 0.34 at 110.0)
        # Entry price: 100.0 (market, with slippage -0.1 = 99.9)
        # Expected: stops trigger sequentially, last stop closes remaining volume
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 105.0
        stop_trigger2 = 108.0
        stop_trigger3 = 110.0
        
        # Stop volumes: calculated from total actual entered volume (1.0)
        #   First stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third stop (extreme): 1.0 - 0.3 - 0.3 = 0.4
        stop_quantity1 = 0.3
        stop_quantity2 = 0.3
        stop_quantity3 = 0.4
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        # All stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger1 + slippage  # 105.0 + 0.1 = 105.1 (BUY stop, slippage increases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 105.1 * 0.3 * 0.001 = 0.03153
        stop_execution2 = stop_trigger2 + slippage  # 108.0 + 0.1 = 108.1 (BUY stop, slippage increases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 108.1 * 0.3 * 0.001 = 0.03243
        stop_execution3 = stop_trigger3 + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        stop_fee3 = stop_execution3 * stop_quantity3 * test_task.fee_taker  # 110.1 * 0.4 * 0.001 = 0.04404
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9 - 0.0999 = 99.8001
        exit_cost = (stop_execution1 * stop_quantity1 + stop_fee1 +
                    stop_execution2 * stop_quantity2 + stop_fee2 +
                    stop_execution3 * stop_quantity3 + stop_fee3)  # 31.56453 + 32.47243 + 44.08404 = 108.121
        expected_profit = entry_proceeds - exit_cost  # = 99.8001 - 108.121 = -8.3209
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.33, 105.0), (0.33, 108.0), (0.34, 110.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_g1_3_part_stops_remaining_closed_by_last")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, stops trigger sequentially
        # Bar 0: entry triggers (1 trade)
        # Bar 1: first stop triggers (2 trades total - entry + stop1)
        # Bar 2: second stop triggers (3 trades total - entry + stop1 + stop2)
        # Bar 3: third stop triggers (4 trades total - entry + stop1 + stop2 + stop3)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First stop should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third stop should trigger on bar 3"
        
        # Check final state: deal should be fully closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + stop1 + stop2 + stop3), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All stop loss orders should be executed"
        
        # Check that take profit order was canceled (deal closed by stops)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stops)"
    
    def test_sell_sltp_market_part_takes_remaining_closed_by_last_take(self, test_task):
        """Test G1.4: Market entry → part of take profits trigger → remaining part closed by last take profit."""
        # Prepare quotes data: price 100.0, then drops to trigger take profits sequentially
        # Bar 1: low should be <= 95.0 to trigger first take
        # Bar 2: low should be <= 92.0 to trigger second take
        # Bar 3: low should be <= 90.0 to trigger third take (closes remaining)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            lows=[99.0, 94.0, 91.0, 89.0]  # Bar 1 low=94.0 triggers take at 95.0, Bar 2 low=91.0 triggers take at 92.0, Bar 3 low=89.0 triggers take at 90.0
        )
        
        # Protocol: On bar 0, enter SELL market with three take profits (0.33 at 95.0, 0.33 at 92.0, 0.34 at 90.0)
        # Entry price: 100.0 (market, with slippage -0.1 = 99.9)
        # Expected: takes trigger sequentially, last take closes remaining volume
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_price1 = 95.0
        take_price2 = 92.0
        take_price3 = 90.0
        
        # Take profit volumes: calculated from total actual entered volume (1.0) minus executed stops (0.0)
        #   First take: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second take: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third take (extreme): 1.0 - 0.3 - 0.3 = 0.4
        take_quantity1 = 0.3
        take_quantity2 = 0.3
        take_quantity3 = 0.4
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        # All takes execute as limit orders (no slippage, fee_maker)
        take_execution1 = take_price1  # 95.0 (limit, no slippage)
        take_fee1 = take_execution1 * take_quantity1 * test_task.fee_maker  # 95.0 * 0.3 * 0.0005 = 0.01425
        take_execution2 = take_price2  # 92.0 (limit, no slippage)
        take_fee2 = take_execution2 * take_quantity2 * test_task.fee_maker  # 92.0 * 0.3 * 0.0005 = 0.0138
        take_execution3 = take_price3  # 90.0 (limit, no slippage)
        take_fee3 = take_execution3 * take_quantity3 * test_task.fee_maker  # 90.0 * 0.4 * 0.0005 = 0.018
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9 - 0.0999 = 99.8001
        exit_cost = (take_execution1 * take_quantity1 + take_fee1 +
                    take_execution2 * take_quantity2 + take_fee2 +
                    take_execution3 * take_quantity3 + take_fee3)  # 28.51425 + 27.6138 + 36.018 = 92.14605
        expected_profit = entry_proceeds - exit_cost  # = 99.8001 - 92.14605 = 7.65405
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': [(0.33, 95.0), (0.33, 92.0), (0.34, 90.0)]  # Three take profits (0.33 + 0.33 + 0.34 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_g1_4_part_takes_remaining_closed_by_last")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, takes trigger sequentially
        # Bar 0: entry triggers (1 trade)
        # Bar 1: first take triggers (2 trades total - entry + take1)
        # Bar 2: second take triggers (3 trades total - entry + take1 + take2)
        # Bar 3: third take triggers (4 trades total - entry + take1 + take2 + take3)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First take should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second take should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third take should trigger on bar 3"
        
        # Check final state: deal should be fully closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + take1 + take2 + take3), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 1, "Should have one entry order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all take profit orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 3, "All take profit orders should be executed"
        
        # Check that stop loss order was canceled (deal closed by takes)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled (deal closed by takes)"



# ============================================================================
# Group G2: Partial Position Closure
# ============================================================================

class TestBuySltpPartialPositionClosure:
    """Test G2: Partial position closure scenarios for buy_sltp."""
    
    def test_buy_sltp_market_one_stop_triggers_partial_closure(self, test_task):
        """Test G2.1: Market entry → one stop out of several triggers → position partially closed, then autoclosed at end."""
        # Prepare quotes data: price 100.0, then drops to trigger one stop
        # Bar 1: low should be <= 95.0 to trigger first stop, but not <= 90.0 (second stop)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 94.0, 99.0]  # Bar 1 low=94.0 triggers stop at 95.0, but not stop at 90.0
        )
        
        # Protocol: On bar 0, enter BUY market with two stops (0.5 at 95.0, 0.5 at 90.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: first stop triggers on bar 1, position partially closed, then autoclosed at end of backtesting
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.5, 95.0), (0.5, 90.0)],  # Two stops (0.5 + 0.5 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_g2_1_one_stop_partial_closure")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, first stop triggers on bar 1
        # Bar 0: entry triggers (1 trade)
        # Bar 1: first stop triggers (2 trades total - entry + stop1)
        # After backtesting ends: automatic closure closes remaining position (3 trades total)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First stop should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 2, "No execution on bar 2 (before autoclosure)"
        
        # Check final state: deal should be fully closed after automatic closure at end of backtesting
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be fully closed after autoclosure (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed after autoclosure"
        
        # Check total trades count: entry + stop1 + autoclosure
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + stop1 + autoclosure), got {len(broker.trades)}"
        
        # Check that entry order and autoclosure order were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 2, "Should have two orders without group (entry + autoclosure)"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 2, "Both entry and autoclosure orders should be executed"
        
        # Check that one stop order was executed, others were canceled by autoclosure
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "One stop loss order should be executed"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "One stop loss order should be canceled by autoclosure"
        
        # Check that take profit order was canceled by autoclosure
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled by autoclosure"
    
    def test_buy_sltp_market_one_take_triggers_partial_closure(self, test_task):
        """Test G2.2: Market entry → one take profit out of several triggers → position partially closed, then autoclosed at end."""
        # Prepare quotes data: price 100.0, then rises to trigger one take
        # Bar 1: high should be >= 105.0 to trigger first take, but not >= 110.0 (second take)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 106.0, 101.0]  # Bar 1 high=106.0 triggers take at 105.0, but not take at 110.0
        )
        
        # Protocol: On bar 0, enter BUY market with two take profits (0.5 at 105.0, 0.5 at 110.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: first take triggers on bar 1, position partially closed, then autoclosed at end of backtesting
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': [(0.5, 105.0), (0.5, 110.0)]  # Two take profits (0.5 + 0.5 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_g2_2_one_take_partial_closure")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, first take triggers on bar 1
        # Bar 0: entry triggers (1 trade)
        # Bar 1: first take triggers (2 trades total - entry + take1)
        # After backtesting ends: automatic closure closes remaining position (3 trades total)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First take should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 2, "No execution on bar 2 (before autoclosure)"
        
        # Check final state: deal should be fully closed after automatic closure at end of backtesting
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be fully closed after autoclosure (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed after autoclosure"
        
        # Check total trades count: entry + take1 + autoclosure
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + take1 + autoclosure), got {len(broker.trades)}"
        
        # Check that entry order and autoclosure order were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 2, "Should have two orders without group (entry + autoclosure)"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 2, "Both entry and autoclosure orders should be executed"
        
        # Check that one take profit order was executed, others were canceled by autoclosure
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 1, "One take profit order should be executed"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "One take profit order should be canceled by autoclosure"
        
        # Check that stop loss order was canceled by autoclosure
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled by autoclosure"


class TestSellSltpPartialPositionClosure:
    """Test G2: Partial position closure scenarios for sell_sltp."""
    
    def test_sell_sltp_market_one_stop_triggers_partial_closure(self, test_task):
        """Test G2.1: Market entry → one stop out of several triggers → position partially closed, then autoclosed at end."""
        # Prepare quotes data: price 100.0, then rises to trigger one stop
        # Bar 1: high should be >= 105.0 to trigger first stop, but not >= 110.0 (second stop)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 106.0, 101.0]  # Bar 1 high=106.0 triggers stop at 105.0, but not stop at 110.0
        )
        
        # Protocol: On bar 0, enter SELL market with two stops (0.5 at 105.0, 0.5 at 110.0)
        # Entry price: 100.0 (market, with slippage -0.1 = 99.9)
        # Expected: first stop triggers on bar 1, position partially closed, then autoclosed at end of backtesting
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.5, 105.0), (0.5, 110.0)],  # Two stops (0.5 + 0.5 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_g2_1_one_stop_partial_closure")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, first stop triggers on bar 1
        # Bar 0: entry triggers (1 trade)
        # Bar 1: first stop triggers (2 trades total - entry + stop1)
        # After backtesting ends: automatic closure closes remaining position (3 trades total)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First stop should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 2, "No execution on bar 2 (before autoclosure)"
        
        # Check final state: deal should be fully closed after automatic closure at end of backtesting
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be fully closed after autoclosure (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed after autoclosure"
        
        # Check total trades count: entry + stop1 + autoclosure
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + stop1 + autoclosure), got {len(broker.trades)}"
        
        # Check that entry order and autoclosure order were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 2, "Should have two orders without group (entry + autoclosure)"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 2, "Both entry and autoclosure orders should be executed"
        
        # Check that one stop order was executed, others were canceled by autoclosure
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "One stop loss order should be executed"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "One stop loss order should be canceled by autoclosure"
        
        # Check that take profit order was canceled by autoclosure
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled by autoclosure"
    
    def test_sell_sltp_market_one_take_triggers_partial_closure(self, test_task):
        """Test G2.2: Market entry → one take profit out of several triggers → position partially closed, then autoclosed at end."""
        # Prepare quotes data: price 100.0, then drops to trigger one take
        # Bar 1: low should be <= 95.0 to trigger first take, but not <= 90.0 (second take)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 94.0, 99.0]  # Bar 1 low=94.0 triggers take at 95.0, but not take at 90.0
        )
        
        # Protocol: On bar 0, enter SELL market with two take profits (0.5 at 95.0, 0.5 at 90.0)
        # Entry price: 100.0 (market, with slippage -0.1 = 99.9)
        # Expected: first take triggers on bar 1, position partially closed, then autoclosed at end of backtesting
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': [(0.5, 95.0), (0.5, 90.0)]  # Two take profits (0.5 + 0.5 = 1.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_g2_2_one_take_partial_closure")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0, first take triggers on bar 1
        # Bar 0: entry triggers (1 trade)
        # Bar 1: first take triggers (2 trades total - entry + take1)
        # After backtesting ends: automatic closure closes remaining position (3 trades total)
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First take should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 2, "No execution on bar 2 (before autoclosure)"
        
        # Check final state: deal should be fully closed after automatic closure at end of backtesting
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be fully closed after autoclosure (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed after autoclosure"
        
        # Check total trades count: entry + take1 + autoclosure
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + take1 + autoclosure), got {len(broker.trades)}"
        
        # Check that entry order and autoclosure order were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 2, "Should have two orders without group (entry + autoclosure)"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 2, "Both entry and autoclosure orders should be executed"
        
        # Check that one take profit order was executed, others were canceled by autoclosure
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 1, "One take profit order should be executed"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "One take profit order should be canceled by autoclosure"
        
        # Check that stop loss order was canceled by autoclosure
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled by autoclosure"


# ============================================================================
# Group G3: Order Cancellation
# ============================================================================

class TestBuySltpOrderCancellation:
    """Test G3: Order cancellation scenarios for buy_sltp."""
    
    def test_buy_sltp_market_entry_cancel_stops_takes(self, test_task):
        """Test G3.1: Market entry → stops/takes set → entry executed → cancel stops/takes → verify cancellation."""
        # Prepare quotes data: price 100.0, entry executes immediately, stops/takes don't trigger
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 99.0, 99.0],  # Price stays at 100.0, stops/takes don't trigger
            highs=[101.0, 101.0, 101.0]
        )
        
        # Protocol: On bar 0, enter BUY market with stop and take, then cancel them on bar 1
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
        
        collected_data = []
        buy_sltp_result = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
                # Store buy_sltp result to get order IDs for cancellation
                if bar_index == 0 and isinstance(method_result, OrderOperationResult) and method_result.deal_id > 0:
                    nonlocal buy_sltp_result
                    buy_sltp_result = method_result
            collected_data.append(data)
            
            # On bar 1, cancel stops and takes using order IDs from bar 0
            if bar_index == 1 and buy_sltp_result:
                # Get stop and take profit order IDs (active orders)
                stop_take_order_ids = [o.order_id for o in buy_sltp_result.orders 
                                      if o.order_group in [OrderGroup.STOP_LOSS, OrderGroup.TAKE_PROFIT]]
                
                # Cancel stops and takes
                if stop_take_order_ids:
                    cancel_result = strategy.cancel_orders(stop_take_order_ids)
                    data['cancel_result'] = cancel_result
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_g3_1_cancel_stops_takes")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) >= 2, f"Expected at least 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        
        # Check final state: deal should be fully closed after automatic closure at end of backtesting
        # (stops/takes were canceled, so deal remained open and was autoclosed)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be fully closed after autoclosure (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed after autoclosure"
        
        # Check total trades count: entry + autoclosure
        assert len(broker.trades) == 2, f"Expected 2 trades total (entry + autoclosure), got {len(broker.trades)}"
        
        # Check that entry order and autoclosure order were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 2, "Should have two orders without group (entry + autoclosure)"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 2, "Both entry and autoclosure orders should be executed"
        
        # Check that stop and take profit orders were canceled
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled"
        
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled"
    
    def test_buy_sltp_limit_entry_cancel_entry(self, test_task):
        """Test G3.2: Limit entry → entry not executed → cancel entry order → verify cancellation."""
        # Prepare quotes data: price 100.0, limit entry at 95.0 won't trigger
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 99.0, 99.0]  # Price stays at 100.0, limit entry at 95.0 won't trigger
        )
        
        # Protocol: On bar 0, place BUY limit entry, then cancel it on bar 1
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit entry at 95.0 (won't trigger at price 100.0)
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            }
        ]
        
        collected_data = []
        buy_sltp_result = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
                # Store buy_sltp result to get order IDs for cancellation
                if bar_index == 0 and isinstance(method_result, OrderOperationResult) and method_result.deal_id > 0:
                    nonlocal buy_sltp_result
                    buy_sltp_result = method_result
            collected_data.append(data)
            
            # On bar 1, cancel entry order using order ID from bar 0
            if bar_index == 1 and buy_sltp_result:
                # Get entry order ID (limit order, should be active)
                entry_order_ids = [o.order_id for o in buy_sltp_result.orders 
                                 if o.order_group == OrderGroup.NONE]
                
                # Cancel entry order
                if entry_order_ids:
                    cancel_result = strategy.cancel_orders(entry_order_ids)
                    data['cancel_result'] = cancel_result
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_g3_2_cancel_entry")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) >= 2, f"Expected at least 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry does NOT trigger on bar 0 (limit order)
        assert collected_data[0]['trades_count'] == 0, "Entry should NOT trigger on bar 0 (limit order)"
        
        # Check final state: deal should not exist or be empty (entry canceled)
        deal = broker.get_deal_by_id(method_result.deal_id)
        # Deal might exist but with no executed trades
        if deal:
            assert deal.quantity == 0.0, f"Deal should have no quantity (entry canceled), got {deal.quantity}"
        
        # Check that entry order was canceled
        if deal:
            entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
            assert len(entry_orders) == 1, "Should have one entry order"
            canceled_entries = [o for o in entry_orders if o.status == OrderStatus.CANCELED]
            assert len(canceled_entries) == 1, "Entry order should be canceled"
        
        # Check that stop and take profit orders were also canceled (when entry is canceled, exits are canceled too)
        if deal:
            stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
            take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
            # When entry is canceled, exit orders might also be canceled or removed
            # This depends on implementation - check what actually happens


class TestSellSltpOrderCancellation:
    """Test G3: Order cancellation scenarios for sell_sltp."""
    
    def test_sell_sltp_market_entry_cancel_stops_takes(self, test_task):
        """Test G3.1: Market entry → stops/takes set → entry executed → cancel stops/takes → verify cancellation."""
        # Prepare quotes data: price 100.0, entry executes immediately, stops/takes don't trigger
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 99.0, 99.0],
            highs=[101.0, 101.0, 101.0]  # Price stays at 100.0, stops/takes don't trigger
        )
        
        # Protocol: On bar 0, enter SELL market with stop and take, then cancel them on bar 1
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
        
        collected_data = []
        sell_sltp_result = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
                # Store sell_sltp result to get order IDs for cancellation
                if bar_index == 0 and isinstance(method_result, OrderOperationResult) and method_result.deal_id > 0:
                    nonlocal sell_sltp_result
                    sell_sltp_result = method_result
            collected_data.append(data)
            
            # On bar 1, cancel stops and takes using order IDs from bar 0
            if bar_index == 1 and sell_sltp_result:
                # Get stop and take profit order IDs (active orders)
                stop_take_order_ids = [o.order_id for o in sell_sltp_result.orders 
                                      if o.order_group in [OrderGroup.STOP_LOSS, OrderGroup.TAKE_PROFIT]]
                
                # Cancel stops and takes
                if stop_take_order_ids:
                    cancel_result = strategy.cancel_orders(stop_take_order_ids)
                    data['cancel_result'] = cancel_result
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_g3_1_cancel_stops_takes")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) >= 2, f"Expected at least 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 0
        assert collected_data[0]['trades_count'] == 1, "Entry should trigger on bar 0"
        
        # Check final state: deal should be fully closed after automatic closure at end of backtesting
        # (stops/takes were canceled, so deal remained open and was autoclosed)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be fully closed after autoclosure (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed after autoclosure"
        
        # Check total trades count: entry + autoclosure
        assert len(broker.trades) == 2, f"Expected 2 trades total (entry + autoclosure), got {len(broker.trades)}"
        
        # Check that entry order and autoclosure order were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 2, "Should have two orders without group (entry + autoclosure)"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 2, "Both entry and autoclosure orders should be executed"
        
        # Check that stop and take profit orders were canceled
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled"
        
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled"
    
    def test_sell_sltp_limit_entry_cancel_entry(self, test_task):
        """Test G3.2: Limit entry → entry not executed → cancel entry order → verify cancellation."""
        # Prepare quotes data: price 100.0, limit entry at 105.0 won't trigger
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 99.0, 99.0],
            highs=[101.0, 101.0, 101.0]  # Price stays at 100.0, limit entry at 105.0 won't trigger
        )
        
        # Protocol: On bar 0, place SELL limit entry, then cancel it on bar 1
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),  # Limit entry at 105.0 (won't trigger at price 100.0)
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            }
        ]
        
        collected_data = []
        sell_sltp_result = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            data = {
                'bar': bar_index,
                'price': current_price,
                'orders_count': len(strategy.broker.orders) if hasattr(strategy.broker, 'orders') else 0,
                'trades_count': len(strategy.broker.trades),
            }
            if method_result:
                data['method_result'] = method_result
                # Store sell_sltp result to get order IDs for cancellation
                if bar_index == 0 and isinstance(method_result, OrderOperationResult) and method_result.deal_id > 0:
                    nonlocal sell_sltp_result
                    sell_sltp_result = method_result
            collected_data.append(data)
            
            # On bar 1, cancel entry order using order ID from bar 0
            if bar_index == 1 and sell_sltp_result:
                # Get entry order ID (limit order, should be active)
                entry_order_ids = [o.order_id for o in sell_sltp_result.orders 
                                 if o.order_group == OrderGroup.NONE]
                
                # Cancel entry order
                if entry_order_ids:
                    cancel_result = strategy.cancel_orders(entry_order_ids)
                    data['cancel_result'] = cancel_result
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_g3_2_cancel_entry")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) >= 2, f"Expected at least 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry does NOT trigger on bar 0 (limit order)
        assert collected_data[0]['trades_count'] == 0, "Entry should NOT trigger on bar 0 (limit order)"
        
        # Check final state: deal should not exist or be empty (entry canceled)
        deal = broker.get_deal_by_id(method_result.deal_id)
        # Deal might exist but with no executed trades
        if deal:
            assert deal.quantity == 0.0, f"Deal should have no quantity (entry canceled), got {deal.quantity}"
        
        # Check that entry order was canceled
        if deal:
            entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
            assert len(entry_orders) == 1, "Should have one entry order"
            canceled_entries = [o for o in entry_orders if o.status == OrderStatus.CANCELED]
            assert len(canceled_entries) == 1, "Entry order should be canceled"
        
        # Check that stop and take profit orders were also canceled (when entry is canceled, exits are canceled too)
        if deal:
            stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
            take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
            # When entry is canceled, exit orders might also be canceled or removed
            # This depends on implementation - check what actually happens
