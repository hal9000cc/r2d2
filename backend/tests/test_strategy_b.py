"""
Tests for Strategy class - buy_sltp/sell_sltp methods - Group B.

Group B: Order Execution - Simple Cases
Tests simple order execution scenarios:
- B1: Single order execution
- B2: Multiple same-type orders execution on same bar
- B3: Partial execution of same-type orders
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
# Group B1: Single Order Execution - BUY
# ============================================================================

class TestBuySltpSingleExecution:
    """Test B1: Single order execution scenarios for buy_sltp."""
    
    def test_buy_sltp_market_stop_triggers(self, test_task):
        """Test B1.1: Market entry → stop triggers (price hits only stop)."""
        # Prepare quotes data: price 100.0, then drops to trigger stop
        # Bar 1: no trigger (price 98.0, stop at 90.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_b1_1_market_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0 (market order)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        
        # Check that stop triggered on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: stop triggered (2 trades - entry + stop)
        assert collected_data[2]['trades_count'] == 2, "Stop should trigger on bar 2"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that take profit did NOT trigger (only stop triggered)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        if take_orders:
            # Take profit order should be canceled or still active, not executed
            assert take_orders[0].status != OrderStatus.EXECUTED, "Take profit should not execute when stop triggers first"
    
    def test_buy_sltp_market_take_triggers(self, test_task):
        """Test B1.2: Market entry → take profit triggers (price hits only take profit)."""
        # Prepare quotes data: price 100.0, then rises to trigger take profit
        # Bar 1: no trigger (price 105.0, take profit at 110.0)
        # Bar 2: high should be >= 110.0 to trigger take profit
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 110.0, 115.0],
            highs=[101.0, 106.0, 111.0, 116.0]  # Bar 2 high=111.0 triggers take profit at 110.0
        )
        
        # Protocol: On bar 0, enter market with stop loss 90.0 and take profit 110.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_b1_2_market_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0 (market order)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        
        # Check that take profit triggered on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: take profit triggered (2 trades - entry + take profit)
        assert collected_data[2]['trades_count'] == 2, "Take profit should trigger on bar 2"
        
        # Check final state: deal should be closed (take profit triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that stop loss did NOT trigger (only take profit triggered)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        if stop_orders:
            # Stop order should be canceled or still active, not executed
            assert stop_orders[0].status != OrderStatus.EXECUTED, "Stop loss should not execute when take profit triggers first"
    
    def test_buy_sltp_limit_entry_stop_triggers(self, test_task):
        """Test B1.3: Limit entry → entry triggers → stop triggers."""
        # Prepare quotes data: price 100.0, then drops to 95.0 (triggers limit entry), then to 90.0 (triggers stop)
        # Bar 1: low=97.0, limit=95.0 - limit does NOT trigger (97.0 > 95.0)
        # Bar 2: low=94.0, limit=95.0 - limit triggers (94.0 <= 95.0)
        # Bar 3: low=89.0, stop=90.0 - stop triggers (89.0 <= 90.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 95.0, 90.0],
            lows=[99.0, 97.0, 94.0, 89.0]  # Bar 2 low=94.0 triggers limit at 95.0, Bar 3 low=89.0 triggers stop
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stop loss 90.0 and take profit 110.0
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Expected limit trigger: bar 2 at price 95.0 (when low=94.0 <= 95.0)
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
            
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_b1_3_limit_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 2 (limit order)
        # Bar 0: no execution (0 trades)
        # Bar 1: no execution (0 trades) - limit not triggered (low=97.0 > limit=95.0)
        # Bar 2: entry executed (1 trade) - limit triggered (low=94.0 <= limit=95.0)
        assert collected_data[1]['trades_count'] == 0, "Entry limit order should NOT execute on bar 1 (low=97.0 > limit=95.0)"
        assert collected_data[2]['trades_count'] == 1, "Entry limit order should execute on bar 2"
        
        # Check that stop triggered on bar 3
        # Bar 3: stop triggered (2 trades - entry + stop)
        assert collected_data[3]['trades_count'] == 2, "Stop should trigger on bar 3"
        
        # Check final state: deal should be closed (stop triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
    
    def test_buy_sltp_limit_entry_take_triggers(self, test_task):
        """Test B1.4: Limit entry → entry triggers → take profit triggers."""
        # Prepare quotes data: price 100.0, then drops to 95.0 (triggers limit entry), then rises to 110.0 (triggers take profit)
        # Bar 1: low=97.0, limit=95.0 - limit does NOT trigger (97.0 > 95.0)
        # Bar 2: low=94.0, limit=95.0 - limit triggers (94.0 <= 95.0)
        # Bar 3: high=111.0, take=110.0 - take profit triggers (111.0 >= 110.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 98.0, 95.0, 110.0],
            lows=[99.0, 97.0, 94.0, 109.0],  # Bar 2 low=94.0 triggers limit at 95.0
            highs=[101.0, 99.0, 96.0, 111.0]  # Bar 3 high=111.0 triggers take profit at 110.0
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stop loss 90.0 and take profit 110.0
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Expected limit trigger: bar 2 at price 95.0 (when low=94.0 <= 95.0)
        # Expected take profit trigger: bar 3 at price 110.0 (limit order, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 95.0
        quantity = 1.0
        take_profit_price = 110.0
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        exit_execution = take_profit_price  # 110.0 (limit, no slippage)
        exit_fee = exit_execution * quantity * test_task.fee_maker  # 110.0 * 1.0 * 0.0005 = 0.055
        expected_profit = exit_execution * quantity - exit_fee - (entry_execution * quantity + entry_fee)  # = 14.8975
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_b1_4_limit_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 2 (limit order)
        # Bar 0: no execution (0 trades)
        # Bar 1: no execution (0 trades) - limit not triggered (low=97.0 > limit=95.0)
        # Bar 2: entry executed (1 trade) - limit triggered (low=94.0 <= limit=95.0)
        assert collected_data[1]['trades_count'] == 0, "Entry limit order should NOT execute on bar 1 (low=97.0 > limit=95.0)"
        assert collected_data[2]['trades_count'] == 1, "Entry limit order should execute on bar 2"
        
        # Check that take profit triggered on bar 3
        # Bar 3: take profit triggered (2 trades - entry + take profit)
        assert collected_data[3]['trades_count'] == 2, "Take profit should trigger on bar 3"
        
        # Check final state: deal should be closed (take profit triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"

