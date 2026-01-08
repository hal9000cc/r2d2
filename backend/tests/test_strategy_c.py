"""
Tests for Strategy class - buy_sltp/sell_sltp methods - Group C.

Group C: Order Execution - Complex Cases (Entries + Stops Simultaneously)
Tests scenarios where entry orders and stop loss orders trigger simultaneously:
- C1: One entry, one stop
- C2: One entry, multiple stops
- C3: Multiple entries, all stops
- C4: Multiple entries, part of stops
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
# Group C1: One Entry, One Stop - BUY
# ============================================================================

class TestBuySltpOneEntryOneStop:
    """Test C1: One entry, one stop scenarios for buy_sltp."""
    
    def test_buy_sltp_limit_entry_stop_simultaneous(self, test_task):
        """Test C1.1: Limit entry and stop hit simultaneously → both trigger."""
        # Prepare quotes data: price 100.0, then drops to trigger both limit entry and stop simultaneously
        # Bar 0: low=99.0, limit=95.0, stop=90.0 - не сработают (99.0 > 95.0, 99.0 > 90.0)
        # Bar 1: low=88.0, limit=95.0, stop=90.0 - оба сработают одновременно (88.0 <= 95.0, 88.0 <= 90.0)
        # Bar 2: price recovers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 88.0, 95.0],
            lows=[99.0, 88.0, 94.0]  # Bar 1 low=88.0 triggers both limit at 95.0 and stop at 90.0 simultaneously
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stop loss 90.0 and take profit 110.0
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop trigger: 90.0 (stop executes as market, with slippage -0.1 = 89.9)
        # Expected: both limit entry and stop trigger simultaneously on bar 1
        # Expected profit calculation:
        entry_price = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 90.0
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        exit_execution = stop_trigger - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        
        entry_cost = entry_execution * quantity + entry_fee  # 95.0*1.0 + 0.0475 = 95.0475
        exit_proceeds = exit_execution * quantity - exit_fee  # 89.9*1.0 - 0.0899 = 89.8101
        expected_profit = exit_proceeds - entry_cost  # = 89.8101 - 95.0475 = -5.2374
        
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_c1_1_limit_stop_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that both entry and stop trigger simultaneously on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: both entry and stop trigger simultaneously (2 trades - entry + stop)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Both entry and stop should trigger simultaneously on bar 1"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that both entry and stop orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop order"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Stop order should be executed"
    
    def test_buy_sltp_market_entry_stop_next_bar(self, test_task):
        """Test C1.2: Market entry → on next bar stop triggers (entry already executed on bar 0)."""
        # Prepare quotes data: price 100.0, market entry on bar 0, then on bar 1 price drops to trigger stop
        # Bar 0: entry executed immediately (market order)
        # Bar 1: low=89.0, stop=90.0 - stop triggers (89.0 <= 90.0)
        # Note: entry already executed on bar 0, so on bar 1 only stop triggers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 90.0, 95.0],
            lows=[99.0, 89.0, 94.0]  # Bar 1 low=89.0 triggers stop at 90.0
        )
        
        # Protocol: On bar 0, enter market with stop loss 90.0 and take profit 110.0
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Stop trigger: 90.0 (stop executes as market, with slippage -0.1 = 89.9)
        # Expected: entry executes on bar 0, stop triggers on bar 1
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 90.0
        
        entry_execution = entry_price + slippage  # 100.0 + 0.1 = 100.1 (BUY market, slippage increases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution = stop_trigger - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        exit_proceeds = exit_execution * quantity - exit_fee  # 89.9*1.0 - 0.0899 = 89.8101
        expected_profit = exit_proceeds - entry_cost  # = 89.8101 - 100.2001 = -10.39
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market order
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_c1_2_market_stop_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, stop triggers on bar 1
        # Bar 0: entry executed (1 trade)
        # Bar 1: stop triggered (2 trades - entry + stop)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Stop should trigger on bar 1"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that stop order was executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop order"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Stop order should be executed"


# ============================================================================
# Group C1: One Entry, One Stop - SELL
# ============================================================================

class TestSellSltpOneEntryOneStop:
    """Test C1: One entry, one stop scenarios for sell_sltp."""
    
    def test_sell_sltp_limit_entry_stop_simultaneous(self, test_task):
        """Test C1.1: Limit entry and stop hit simultaneously → both trigger."""
        # Prepare quotes data: price 100.0, then rises to trigger both limit entry and stop simultaneously
        # Bar 0: high=101.0, limit=105.0, stop=110.0 - не сработают (101.0 < 105.0, 101.0 < 110.0)
        # Bar 1: high=112.0, limit=105.0, stop=110.0 - оба сработают одновременно (112.0 >= 105.0, 112.0 >= 110.0)
        # Bar 2: price recovers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 112.0, 108.0],
            highs=[101.0, 112.0, 109.0]  # Bar 1 high=112.0 triggers both limit at 105.0 and stop at 110.0 simultaneously
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with stop loss 110.0 and take profit 90.0
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop trigger: 110.0 (BUY stop executes as market, with slippage +0.1 = 110.1)
        # Expected: both limit entry and stop trigger simultaneously on bar 1
        # Expected profit calculation:
        entry_price = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 110.0
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        exit_execution = stop_trigger + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 105.0*1.0 - 0.0525 = 104.9475
        exit_cost = exit_execution * quantity + exit_fee  # 110.1*1.0 + 0.1101 = 110.2101
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 110.2101 = -5.2626
        
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_c1_1_limit_stop_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that both entry and stop trigger simultaneously on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: both entry and stop trigger simultaneously (2 trades - entry + stop)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Both entry and stop should trigger simultaneously on bar 1"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that both entry and stop orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop order"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Stop order should be executed"
    
    def test_sell_sltp_market_entry_stop_next_bar(self, test_task):
        """Test C1.2: Market entry → on next bar stop triggers (entry already executed on bar 0)."""
        # Prepare quotes data: price 100.0, market entry on bar 0, then on bar 1 price rises to trigger stop
        # Bar 0: entry executed immediately (market order)
        # Bar 1: high=111.0, stop=110.0 - stop triggers (111.0 >= 110.0)
        # Note: entry already executed on bar 0, so on bar 1 only stop triggers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 110.0, 108.0],
            highs=[101.0, 111.0, 109.0]  # Bar 1 high=111.0 triggers stop at 110.0
        )
        
        # Protocol: On bar 0, enter market SELL with stop loss 110.0 and take profit 90.0
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Stop trigger: 110.0 (BUY stop executes as market, with slippage +0.1 = 110.1)
        # Expected: entry executes on bar 0, stop triggers on bar 1
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger = 110.0
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution = stop_trigger + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        exit_cost = exit_execution * quantity + exit_fee  # 110.1*1.0 + 0.1101 = 110.2101
        expected_profit = entry_proceeds - exit_cost  # = 99.8001 - 110.2101 = -10.41
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,  # Market order
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_c1_2_market_stop_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, stop triggers on bar 1
        # Bar 0: entry executed (1 trade)
        # Bar 1: stop triggered (2 trades - entry + stop)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Stop should trigger on bar 1"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that stop order was executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop order"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Stop order should be executed"


# ============================================================================
# Group C2: One Entry, Multiple Stops - BUY
# ============================================================================

class TestBuySltpOneEntryMultipleStops:
    """Test C2: One entry, multiple stops scenarios for buy_sltp."""
    
    def test_buy_sltp_limit_entry_all_stops_simultaneous(self, test_task):
        """Test C2.1: Limit entry and all stops hit simultaneously → entry + all stops trigger."""
        # Prepare quotes data: price 100.0, then drops to trigger limit entry and all stops simultaneously
        # Bar 0: low=99.0, limit=95.0, stops at 90.0 and 88.0 - не сработают (99.0 > 95.0, 99.0 > 90.0, 99.0 > 88.0)
        # Bar 1: low=87.0, limit=95.0, stops at 90.0 and 88.0 - все сработают одновременно (87.0 <= 95.0, 87.0 <= 90.0, 87.0 <= 88.0)
        # Bar 2: price recovers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 87.0, 95.0],
            lows=[99.0, 87.0, 94.0]  # Bar 1 low=87.0 triggers limit at 95.0 and both stops at 90.0 and 88.0 simultaneously
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with two stops (0.5 at 90.0, 0.5 at 88.0) and take profit 110.0
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 and 88.0 (stops execute as market, with slippage -0.1)
        # Expected: limit entry and both stops trigger simultaneously on bar 1
        # Expected profit calculation:
        entry_price = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 90.0
        stop_trigger2 = 88.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        exit_execution1 = stop_trigger1 - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        exit_execution2 = stop_trigger2 - slippage  # 88.0 - 0.1 = 87.9 (SELL stop, slippage decreases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 87.9 * 0.5 * 0.001 = 0.04395
        
        entry_cost = entry_execution * quantity + entry_fee  # 95.0*1.0 + 0.0475 = 95.0475
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + exit_execution2 * quantity2 - exit_fee2  # 89.9*0.5 - 0.04495 + 87.9*0.5 - 0.04395 = 88.8111
        expected_profit = total_exit_proceeds - entry_cost  # = 88.8111 - 95.0475 = -6.2364
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit order at 95.0
                    'stop_loss': [(0.5, 90.0), (0.5, 88.0)],  # Two stops with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_c2_1_limit_all_stops_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and both stops trigger simultaneously on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and both stops trigger simultaneously (3 trades - entry + stop1 + stop2)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and both stops should trigger simultaneously on bar 1"
        
        # Check final state: deal should be closed (both stops triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry and both stop orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop orders should be executed"
    
    def test_buy_sltp_limit_entry_part_stops_simultaneous(self, test_task):
        """Test C2.2: Limit entry and part of stops hit simultaneously → entry + part of stops trigger."""
        # Prepare quotes data: price 100.0, then drops to trigger limit entry and part of stops simultaneously
        # Bar 0: low=99.0, limit=95.0, stops at 90.0, 88.0, 86.0 - не сработают (99.0 > 95.0, 99.0 > 90.0, 99.0 > 88.0, 99.0 > 86.0)
        # Bar 1: low=87.0, limit=95.0, stops at 90.0, 88.0, 86.0 - лимит и первые два стопа сработают (87.0 <= 95.0, 87.0 <= 90.0, 87.0 <= 88.0), третий не сработает (87.0 > 86.0)
        # Bar 2: price recovers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 87.0, 95.0],
            lows=[99.0, 87.0, 94.0]  # Bar 1 low=87.0 triggers limit at 95.0 and first two stops at 90.0 and 88.0, third stop at 86.0 doesn't trigger (87.0 > 86.0)
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with three stops (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0) and take profit 110.0
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 and 88.0 (stops execute as market, with slippage -0.1)
        # Expected: limit entry and first two stops trigger simultaneously on bar 1, third stop remains active
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Stop volumes are rounded to precision_amount=0.1: first two get rounded, third gets remainder
        # Fractions: 0.33, 0.33, 0.34
        # First stop: round(0.33 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        # Second stop: round(0.33 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        # Third stop (extreme, gets remainder): 1.0 - 0.3 - 0.3 = 0.4
        entry_price = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        entry_quantity = 1.0
        stop_trigger1 = 90.0
        stop_trigger2 = 88.0
        quantity1 = 0.3  # round(0.33 / 0.1) * 0.1 = 0.3
        quantity2 = 0.3  # round(0.33 / 0.1) * 0.1 = 0.3
        quantity3 = 0.4  # remainder: 1.0 - 0.3 - 0.3 = 0.4 (for third stop, which doesn't trigger)
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        exit_execution1 = stop_trigger1 - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 89.9 * 0.3 * 0.001 = 0.02697
        exit_execution2 = stop_trigger2 - slippage  # 88.0 - 0.1 = 87.9 (SELL stop, slippage decreases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 87.9 * 0.3 * 0.001 = 0.02637
        
        # Auto-close on last bar (bar 2) at close price 95.0
        auto_close_price = 95.0
        auto_close_execution = auto_close_price - slippage  # 95.0 - 0.1 = 94.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * quantity3 * test_task.fee_taker  # 94.9 * 0.4 * 0.001 = 0.03796
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0*1.0 + 0.0475 = 95.0475
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + exit_execution2 * quantity2 - exit_fee2 + auto_close_execution * quantity3 - auto_close_fee  # 89.9*0.3 - 0.02697 + 87.9*0.3 - 0.02637 + 94.9*0.4 - 0.03796 = 91.8087
        expected_profit = total_exit_proceeds - entry_cost  # = 91.8087 - 95.0475 = -3.2388
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit order at 95.0
                    'stop_loss': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)],  # Three stops with shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_c2_2_limit_part_stops_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and first two stops trigger simultaneously on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and first two stops trigger simultaneously (3 trades - entry + stop1 + stop2)
        # Bar 2: auto-close after last bar
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and first two stops should trigger simultaneously on bar 1"
        
        # Check final state: deal should be closed (two stops + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + stop1 + stop2 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry and first two stop orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Only first two stop orders should be executed"
    
    def test_buy_sltp_market_entry_all_stops_next_bar(self, test_task):
        """Test C2.3: Market entry → on next bar all stops hit simultaneously (entry already executed on bar 0)."""
        # Prepare quotes data: price 100.0, market entry on bar 0, then on bar 1 price drops to trigger all stops
        # Bar 0: entry executed immediately (market order)
        # Bar 1: low=87.0, stops at 90.0 and 88.0 - все стопы сработают (87.0 <= 90.0, 87.0 <= 88.0)
        # Bar 2: price recovers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 87.0, 95.0],
            lows=[99.0, 87.0, 94.0]  # Bar 1 low=87.0 triggers both stops at 90.0 and 88.0
        )
        
        # Protocol: On bar 0, enter market with two stops (0.5 at 90.0, 0.5 at 88.0) and take profit 110.0
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Stop triggers: 90.0 and 88.0 (stops execute as market, with slippage -0.1)
        # Expected: entry executes on bar 0, both stops trigger simultaneously on bar 1
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 90.0
        stop_trigger2 = 88.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price + slippage  # 100.0 + 0.1 = 100.1 (BUY market, slippage increases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution1 = stop_trigger1 - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        exit_execution2 = stop_trigger2 - slippage  # 88.0 - 0.1 = 87.9 (SELL stop, slippage decreases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 87.9 * 0.5 * 0.001 = 0.04395
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + exit_execution2 * quantity2 - exit_fee2  # 89.9*0.5 - 0.04495 + 87.9*0.5 - 0.04395 = 88.8111
        expected_profit = total_exit_proceeds - entry_cost  # = 88.8111 - 100.2001 = -11.389
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market order
                    'stop_loss': [(0.5, 90.0), (0.5, 88.0)],  # Two stops with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_c2_3_market_all_stops_next_bar")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, both stops trigger simultaneously on bar 1
        # Bar 0: entry executed (1 trade)
        # Bar 1: both stops triggered simultaneously (3 trades - entry + stop1 + stop2)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Both stops should trigger simultaneously on bar 1"
        
        # Check final state: deal should be closed (both stops triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that both stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop orders should be executed"


# ============================================================================
# Group C2: One Entry, Multiple Stops - SELL
# ============================================================================

class TestSellSltpOneEntryMultipleStops:
    """Test C2: One entry, multiple stops scenarios for sell_sltp."""
    
    def test_sell_sltp_limit_entry_all_stops_simultaneous(self, test_task):
        """Test C2.1: Limit entry and all stops hit simultaneously → entry + all stops trigger."""
        # Prepare quotes data: price 100.0, then rises to trigger limit entry and all stops simultaneously
        # Bar 0: high=101.0, limit=105.0, stops at 110.0 and 112.0 - не сработают (101.0 < 105.0, 101.0 < 110.0, 101.0 < 112.0)
        # Bar 1: high=113.0, limit=105.0, stops at 110.0 and 112.0 - все сработают одновременно (113.0 >= 105.0, 113.0 >= 110.0, 113.0 >= 112.0)
        # Bar 2: price recovers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 113.0, 108.0],
            highs=[101.0, 113.0, 109.0]  # Bar 1 high=113.0 triggers limit at 105.0 and both stops at 110.0 and 112.0 simultaneously
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with two stops (0.5 at 110.0, 0.5 at 112.0) and take profit 90.0
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 and 112.0 (BUY stops execute as market, with slippage +0.1)
        # Expected: limit entry and both stops trigger simultaneously on bar 1
        # Expected profit calculation:
        entry_price = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 110.0
        stop_trigger2 = 112.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        exit_execution1 = stop_trigger1 + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        exit_execution2 = stop_trigger2 + slippage  # 112.0 + 0.1 = 112.1 (BUY stop, slippage increases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 112.1 * 0.5 * 0.001 = 0.05605
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 105.0*1.0 - 0.0525 = 104.9475
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2  # 110.1*0.5 + 0.05505 + 112.1*0.5 + 0.05605 = 111.1611
        expected_profit = entry_proceeds - total_exit_cost  # = 104.9475 - 111.1611 = -6.2136
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),  # Limit order at 105.0
                    'stop_loss': [(0.5, 110.0), (0.5, 112.0)],  # Two stops with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_c2_1_limit_all_stops_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and both stops trigger simultaneously on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and both stops trigger simultaneously (3 trades - entry + stop1 + stop2)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and both stops should trigger simultaneously on bar 1"
        
        # Check final state: deal should be closed (both stops triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry and both stop orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop orders should be executed"
    
    def test_sell_sltp_limit_entry_part_stops_simultaneous(self, test_task):
        """Test C2.2: Limit entry and part of stops hit simultaneously → entry + part of stops trigger."""
        # Prepare quotes data: price 100.0, then rises to trigger limit entry and part of stops simultaneously
        # Bar 0: high=101.0, limit=105.0, stops at 110.0, 112.0, 114.0 - не сработают (101.0 < 105.0, 101.0 < 110.0, 101.0 < 112.0, 101.0 < 114.0)
        # Bar 1: high=113.0, limit=105.0, stops at 110.0, 112.0, 114.0 - лимит и первые два стопа сработают (113.0 >= 105.0, 113.0 >= 110.0, 113.0 >= 112.0), третий не сработает (113.0 < 114.0)
        # Bar 2: price recovers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 113.0, 108.0],
            highs=[101.0, 113.0, 109.0]  # Bar 1 high=113.0 triggers limit at 105.0 and first two stops at 110.0 and 112.0, third stop at 114.0 doesn't trigger (113.0 < 114.0)
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with three stops (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0) and take profit 90.0
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 and 112.0 (BUY stops execute as market, with slippage +0.1)
        # Expected: limit entry and first two stops trigger simultaneously on bar 1, third stop remains active
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Stop volumes are rounded to precision_amount=0.1: first two get rounded, third gets remainder
        # Fractions: 0.33, 0.33, 0.34
        # First stop: round(0.33 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        # Second stop: round(0.33 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        # Third stop (extreme, gets remainder): 1.0 - 0.3 - 0.3 = 0.4
        entry_price = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        entry_quantity = 1.0
        stop_trigger1 = 110.0
        stop_trigger2 = 112.0
        quantity1 = 0.3  # round(0.33 / 0.1) * 0.1 = 0.3
        quantity2 = 0.3  # round(0.33 / 0.1) * 0.1 = 0.3
        quantity3 = 0.4  # remainder: 1.0 - 0.3 - 0.3 = 0.4 (for third stop, which doesn't trigger)
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        exit_execution1 = stop_trigger1 + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 110.1 * 0.3 * 0.001 = 0.03303
        exit_execution2 = stop_trigger2 + slippage  # 112.0 + 0.1 = 112.1 (BUY stop, slippage increases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 112.1 * 0.3 * 0.001 = 0.03363
        
        # Auto-close on last bar (bar 2) at close price 108.0
        auto_close_price = 108.0
        auto_close_execution = auto_close_price + slippage  # 108.0 + 0.1 = 108.1 (BUY market, slippage increases price)
        auto_close_fee = auto_close_execution * quantity3 * test_task.fee_taker  # 108.1 * 0.4 * 0.001 = 0.04324
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0*1.0 - 0.0525 = 104.9475
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2 + auto_close_execution * quantity3 + auto_close_fee  # 110.1*0.3 + 0.03303 + 112.1*0.3 + 0.03363 + 108.1*0.4 + 0.04324 = 110.4107
        expected_profit = entry_proceeds - total_exit_cost  # = 104.9475 - 110.4107 = -5.4632
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),  # Limit order at 105.0
                    'stop_loss': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)],  # Three stops with shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_c2_2_limit_part_stops_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and first two stops trigger simultaneously on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and first two stops trigger simultaneously (3 trades - entry + stop1 + stop2)
        # Bar 2: auto-close after last bar
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and first two stops should trigger simultaneously on bar 1"
        
        # Check final state: deal should be closed (two stops + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + stop1 + stop2 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry and first two stop orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Only first two stop orders should be executed"
    
    def test_sell_sltp_market_entry_all_stops_next_bar(self, test_task):
        """Test C2.3: Market entry → on next bar all stops hit simultaneously (entry already executed on bar 0)."""
        # Prepare quotes data: price 100.0, market entry on bar 0, then on bar 1 price rises to trigger all stops
        # Bar 0: entry executed immediately (market order)
        # Bar 1: high=113.0, stops at 110.0 and 112.0 - все стопы сработают (113.0 >= 110.0, 113.0 >= 112.0)
        # Bar 2: price recovers
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 113.0, 108.0],
            highs=[101.0, 113.0, 109.0]  # Bar 1 high=113.0 triggers both stops at 110.0 and 112.0
        )
        
        # Protocol: On bar 0, enter market SELL with two stops (0.5 at 110.0, 0.5 at 112.0) and take profit 90.0
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Stop triggers: 110.0 and 112.0 (BUY stops execute as market, with slippage +0.1)
        # Expected: entry executes on bar 0, both stops trigger simultaneously on bar 1
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 110.0
        stop_trigger2 = 112.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution1 = stop_trigger1 + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        exit_execution2 = stop_trigger2 + slippage  # 112.0 + 0.1 = 112.1 (BUY stop, slippage increases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 112.1 * 0.5 * 0.001 = 0.05605
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2  # 110.1*0.5 + 0.05505 + 112.1*0.5 + 0.05605 = 111.1611
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 111.1611 = -11.361
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,  # Market order
                    'stop_loss': [(0.5, 110.0), (0.5, 112.0)],  # Two stops with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_c2_3_market_all_stops_next_bar")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, both stops trigger simultaneously on bar 1
        # Bar 0: entry executed (1 trade)
        # Bar 1: both stops triggered simultaneously (3 trades - entry + stop1 + stop2)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Both stops should trigger simultaneously on bar 1"
        
        # Check final state: deal should be closed (both stops triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that both stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop orders should be executed"
