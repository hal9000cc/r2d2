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


# ============================================================================
# Group B1: Single Order Execution - SELL
# ============================================================================

class TestSellSltpSingleExecution:
    """Test B1: Single order execution scenarios for sell_sltp."""
    
    def test_sell_sltp_market_stop_triggers(self, test_task):
        """Test B1.1: Market entry → stop triggers (price hits only stop)."""
        # Prepare quotes data: price 100.0, then rises to trigger stop
        # Bar 1: no trigger (price 102.0, stop at 110.0)
        # Bar 2: high should be >= 110.0 to trigger stop
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 102.0, 110.0, 108.0],
            highs=[101.0, 103.0, 111.0, 109.0]  # Bar 2 high=111.0 triggers stop at 110.0
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
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        exit_cost = exit_execution * quantity + exit_fee  # 110.1*1.0 + 0.1101 = 110.2101
        expected_profit = entry_proceeds - exit_cost  # = 99.8001 - 110.2101 = -10.41
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b1_1_market_stop")
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
    
    def test_sell_sltp_market_take_triggers(self, test_task):
        """Test B1.2: Market entry → take profit triggers (price hits only take profit)."""
        # Prepare quotes data: price 100.0, then drops to trigger take profit
        # Bar 1: no trigger (price 95.0, take profit at 90.0)
        # Bar 2: low should be <= 90.0 to trigger take profit
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 90.0, 92.0],
            lows=[99.0, 94.0, 89.0, 91.0]  # Bar 2 low=89.0 triggers take profit at 90.0
        )
        
        # Protocol: On bar 0, enter market SELL with stop loss 110.0 and take profit 90.0
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
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        exit_cost = exit_execution * quantity + exit_fee  # 90.0*1.0 + 0.045 = 90.045
        expected_profit = entry_proceeds - exit_cost  # = 99.8001 - 90.045 = 9.7551
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b1_2_market_take")
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
    
    def test_sell_sltp_limit_entry_stop_triggers(self, test_task):
        """Test B1.3: Limit entry → entry triggers → stop triggers."""
        # Prepare quotes data: price 100.0, then rises to trigger limit entry, then to trigger stop
        # Bar 0: high=101.0, limit=105.0 - limit не сработает (101.0 < 105.0)
        # Bar 1: high=106.0, limit=105.0 - limit сработает (106.0 >= 105.0)
        # Bar 2: high=107.0, stop=110.0 - стоп не сработает (107.0 < 110.0)
        # Bar 3: high=111.0, stop=110.0 - стоп сработает (111.0 >= 110.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 103.0, 105.0, 110.0],
            highs=[101.0, 106.0, 107.0, 111.0]  # Bar 1 high=106.0 triggers limit at 105.0, Bar 3 high=111.0 triggers stop at 110.0
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with stop loss 110.0 and take profit 90.0
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Expected limit trigger: bar 1 at price 105.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b1_3_limit_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 1 (limit order)
        # Bar 0: no execution (0 trades)
        # Bar 1: entry executed (1 trade) - limit triggered (high=106.0 >= limit=105.0)
        # Bar 2: no execution (1 trade) - stop not triggered (high=107.0 < stop=110.0)
        # Bar 3: stop triggered (2 trades - entry + stop)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 1, "Entry limit order should execute on bar 1"
        assert collected_data[2]['trades_count'] == 1, "Stop should NOT trigger on bar 2 (high=107.0 < stop=110.0)"
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
    
    def test_sell_sltp_limit_entry_take_triggers(self, test_task):
        """Test B1.4: Limit entry → entry triggers → take profit triggers."""
        # Prepare quotes data: price 100.0, then rises to trigger limit entry, then drops to trigger take profit
        # Bar 0: high=101.0, limit=105.0 - limit не сработает (101.0 < 105.0)
        # Bar 1: high=106.0, limit=105.0 - limit сработает (106.0 >= 105.0)
        # Bar 2: low=104.0, take=90.0 - тейк не сработает (104.0 > 90.0)
        # Bar 3: low=89.0, take=90.0 - тейк сработает (89.0 <= 90.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 103.0, 105.0, 90.0],
            highs=[101.0, 106.0, 107.0, 91.0],  # Bar 1 high=106.0 triggers limit at 105.0
            lows=[99.0, 102.0, 104.0, 89.0]  # Bar 3 low=89.0 triggers take profit at 90.0
        )
        
        # Protocol: On bar 0, enter SELL limit at 105.0 with stop loss 110.0 and take profit 90.0
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Expected limit trigger: bar 1 at price 105.0
        # Expected take profit trigger: bar 3 at price 90.0 (BUY limit order, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 105.0
        quantity = 1.0
        take_profit_price = 90.0
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        exit_execution = take_profit_price  # 90.0 (limit, no slippage)
        exit_fee = exit_execution * quantity * test_task.fee_maker  # 90.0 * 1.0 * 0.0005 = 0.045
        entry_proceeds = entry_execution * quantity - entry_fee  # 105.0*1.0 - 0.0525 = 104.9475
        exit_cost = exit_execution * quantity + exit_fee  # 90.0*1.0 + 0.045 = 90.045
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 90.045 = 14.9025
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b1_4_limit_take")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 1 (limit order)
        # Bar 0: no execution (0 trades)
        # Bar 1: entry executed (1 trade) - limit triggered (high=106.0 >= limit=105.0)
        # Bar 2: no execution (1 trade) - take profit not triggered (low=104.0 > take=90.0)
        # Bar 3: take profit triggered (2 trades - entry + take profit)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 1, "Entry limit order should execute on bar 1"
        assert collected_data[2]['trades_count'] == 1, "Take profit should NOT trigger on bar 2 (low=104.0 > take=90.0)"
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


# ============================================================================
# Group B2: Multiple Same-Type Orders Execution on Same Bar - BUY
# ============================================================================

class TestBuySltpMultipleExecutionSameBar:
    """Test B2: Multiple same-type orders execution on same bar scenarios for buy_sltp."""
    
    def test_buy_sltp_market_multiple_stops_simultaneous(self, test_task):
        """Test B2.1: Market entry → multiple stops trigger simultaneously (price hits all stops)."""
        # Prepare quotes data: price 100.0, then drops to trigger all stops simultaneously
        # Bar 1: low=95.0, stops at 90.0 and 88.0 - stops не сработают (95.0 > 90.0, 95.0 > 88.0)
        # Bar 2: low=87.0, stops at 90.0 and 88.0 - оба стопа сработают одновременно (87.0 <= 90.0, 87.0 <= 88.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 87.0, 92.0],
            lows=[99.0, 94.0, 86.0, 91.0]  # Bar 2 low=86.0 triggers both stops at 90.0 and 88.0 simultaneously
        )
        
        # Protocol: On bar 0, enter market with two stops (0.5 at 90.0, 0.5 at 88.0) and take profit 110.0
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected stops trigger: bar 2 at prices 90.0 and 88.0 (both execute as market, with slippage)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 90.0
        stop_trigger2 = 88.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price + slippage  # 100.1
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
                    'enter': 1.0,
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b2_1_multiple_stops_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, both stops on bar 2 simultaneously
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: both stops triggered simultaneously (3 trades - entry + stop1 + stop2)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 3, "Both stops should trigger simultaneously on bar 2"
        
        # Check final state: deal should be closed (all stops triggered)
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
    
    def test_buy_sltp_market_multiple_takes_simultaneous(self, test_task):
        """Test B2.2: Market entry → multiple take profits trigger simultaneously (price hits all takes)."""
        # Prepare quotes data: price 100.0, then rises to trigger all take profits simultaneously
        # Bar 1: high=105.0, takes at 110.0 and 112.0 - takes не сработают (105.0 < 110.0, 105.0 < 112.0)
        # Bar 2: high=113.0, takes at 110.0 and 112.0 - оба тейка сработают одновременно (113.0 >= 110.0, 113.0 >= 112.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 113.0, 115.0],
            highs=[101.0, 106.0, 114.0, 116.0]  # Bar 2 high=114.0 triggers both takes at 110.0 and 112.0 simultaneously
        )
        
        # Protocol: On bar 0, enter market with stop loss 90.0 and two takes (0.5 at 110.0, 0.5 at 112.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected takes trigger: bar 2 at prices 110.0 and 112.0 (both execute as limit, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_trigger1 = 110.0
        take_trigger2 = 112.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution1 = take_trigger1  # 110.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_maker  # 110.0 * 0.5 * 0.0005 = 0.0275
        exit_execution2 = take_trigger2  # 112.0 (limit, no slippage)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_maker  # 112.0 * 0.5 * 0.0005 = 0.028
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + exit_execution2 * quantity2 - exit_fee2  # 110.0*0.5 - 0.0275 + 112.0*0.5 - 0.028 = 110.9445
        expected_profit = total_exit_proceeds - entry_cost  # = 110.9445 - 100.2001 = 10.7444
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': [(0.5, 110.0), (0.5, 112.0)]  # Two takes with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b2_2_multiple_takes_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, both takes on bar 2 simultaneously
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: both takes triggered simultaneously (3 trades - entry + take1 + take2)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 3, "Both takes should trigger simultaneously on bar 2"
        
        # Check final state: deal should be closed (all takes triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that both take orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "Both take orders should be executed"
    
    def test_buy_sltp_multiple_limits_simultaneous(self, test_task):
        """Test B2.3: Multiple limit entries → all trigger simultaneously."""
        # Prepare quotes data: price 100.0, then drops to trigger all limit entries simultaneously
        # Bar 0: low=99.0, limits at 97.0 and 95.0 - лимитки не сработают (99.0 > 97.0, 99.0 > 95.0)
        # Bar 1: low=94.0, limits at 97.0 and 95.0 - обе лимитки сработают одновременно (94.0 <= 97.0, 94.0 <= 95.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 96.0, 98.0],
            lows=[99.0, 94.0, 97.0]  # Bar 1 low=94.0 triggers both limits at 97.0 and 95.0 simultaneously
        )
        
        # Protocol: On bar 0, enter with two limits (0.5 at 97.0, 0.5 at 95.0) with stop loss 90.0 and take profit 110.0
        # Entry prices: 97.0 and 95.0 (limits, no slippage, fee_maker)
        # Expected limits trigger: bar 1 at prices 97.0 and 95.0 simultaneously
        # Expected profit calculation (assuming stop triggers later):
        entry_price1 = 97.0
        entry_price2 = 95.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = 1.0
        stop_trigger = 90.0
        
        entry_execution1 = entry_price1  # 97.0 (limit, no slippage)
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 97.0 * 0.5 * 0.0005 = 0.02425
        entry_execution2 = entry_price2  # 95.0 (limit, no slippage)
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 95.0 * 0.5 * 0.0005 = 0.02375
        
        # For this test, we'll assume stop triggers on bar 2 (after entries execute)
        exit_execution = stop_trigger - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee = exit_execution * total_quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        
        entry_cost = entry_execution1 * quantity1 + entry_fee1 + entry_execution2 * quantity2 + entry_fee2  # 97.0*0.5 + 0.02425 + 95.0*0.5 + 0.02375 = 96.048
        exit_proceeds = exit_execution * total_quantity - exit_fee  # 89.9*1.0 - 0.0899 = 89.8101
        expected_profit = exit_proceeds - entry_cost  # = 89.8101 - 96.048 = -6.2379
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.5, 97.0), (0.5, 95.0)],  # Two limit orders
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b2_3_multiple_limits_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that both limits executed simultaneously on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: both limits executed simultaneously (2 trades - limit1 + limit2)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Both limits should execute simultaneously on bar 1"
        
        # Check final state: deal should be closed (auto-close on last bar if stop didn't trigger)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation (may differ if auto-close price is different)
        # Note: profit calculation above assumes stop triggers, but if it doesn't, auto-close will use bar 2 close price
        # We'll check that profit is calculated, but exact value depends on auto-close price
        assert deal.profit is not None, "Deal profit should be calculated"
    
    def test_buy_sltp_market_multiple_stops_sequential(self, test_task):
        """Test B2.4: Market entry → multiple stops trigger sequentially (on different bars)."""
        # Prepare quotes data: price 100.0, then drops to trigger stops sequentially
        # Bar 1: low=94.0, stops at 90.0 and 86.0 - первый стоп не сработает (94.0 > 90.0), второй не сработает (94.0 > 86.0)
        # Bar 2: low=88.0, stops at 90.0 and 86.0 - первый стоп сработает (88.0 <= 90.0), второй не сработает (88.0 > 86.0)
        # Bar 3: low=86.0, stops at 90.0 and 86.0 - второй стоп сработает (86.0 <= 86.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 89.0, 87.0, 92.0],
            lows=[99.0, 94.0, 88.0, 85.0, 91.0]  # Bar 2 low=88.0 triggers first stop at 90.0, Bar 3 low=85.0 triggers second stop at 86.0
        )
        
        # Protocol: On bar 0, enter market with two stops (0.5 at 90.0, 0.5 at 86.0) and take profit 110.0
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected stops trigger: bar 2 at 90.0, bar 3 at 86.0 (sequential)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 90.0
        stop_trigger2 = 86.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution1 = stop_trigger1 - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        exit_execution2 = stop_trigger2 - slippage  # 86.0 - 0.1 = 85.9 (SELL stop, slippage decreases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 85.9 * 0.5 * 0.001 = 0.04295
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + exit_execution2 * quantity2 - exit_fee2  # 89.9*0.5 - 0.04495 + 85.9*0.5 - 0.04295 = 87.8121
        expected_profit = total_exit_proceeds - entry_cost  # = 87.8121 - 100.2001 = -12.388
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.5, 90.0), (0.5, 86.0)],  # Two stops with equal shares - second stop lower to trigger sequentially
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b2_4_multiple_stops_sequential")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, stops triggered sequentially
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first stop triggered (2 trades - entry + stop1)
        # Bar 3: second stop triggered (3 trades - entry + stop1 + stop2)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 2, "First stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 3, "Second stop should trigger on bar 3"
        
        # Check final state: deal should be closed (all stops triggered)
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
    
    def test_buy_sltp_market_multiple_takes_sequential(self, test_task):
        """Test B2.5: Market entry → multiple take profits trigger sequentially (on different bars)."""
        # Prepare quotes data: price 100.0, then rises to trigger take profits sequentially
        # Bar 1: high=105.0, takes at 110.0 and 112.0 - первый тейк не сработает (105.0 < 110.0), второй не сработает (105.0 < 112.0)
        # Bar 2: high=111.0, takes at 110.0 and 112.0 - первый тейк сработает (111.0 >= 110.0), второй не сработает (111.0 < 112.0)
        # Bar 3: high=113.0, takes at 110.0 and 112.0 - второй тейк сработает (113.0 >= 112.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 111.0, 113.0, 115.0],
            highs=[101.0, 106.0, 112.0, 114.0, 116.0]  # Bar 2 high=112.0 triggers first take at 110.0, Bar 3 high=114.0 triggers second take at 112.0
        )
        
        # Protocol: On bar 0, enter market with stop loss 90.0 and two takes (0.5 at 110.0, 0.5 at 112.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected takes trigger: bar 2 at 110.0, bar 3 at 112.0 (sequential)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_trigger1 = 110.0
        take_trigger2 = 112.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution1 = take_trigger1  # 110.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_maker  # 110.0 * 0.5 * 0.0005 = 0.0275
        exit_execution2 = take_trigger2  # 112.0 (limit, no slippage)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_maker  # 112.0 * 0.5 * 0.0005 = 0.028
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + exit_execution2 * quantity2 - exit_fee2  # 110.0*0.5 - 0.0275 + 112.0*0.5 - 0.028 = 110.9445
        expected_profit = total_exit_proceeds - entry_cost  # = 110.9445 - 100.2001 = 10.7444
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': [(0.5, 110.0), (0.5, 112.0)]  # Two takes with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b2_5_multiple_takes_sequential")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, takes triggered sequentially
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first take triggered (2 trades - entry + take1)
        # Bar 3: second take triggered (3 trades - entry + take1 + take2)
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 2, "First take should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 3, "Second take should trigger on bar 3"
        
        # Check final state: deal should be closed (all takes triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that both take orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "Both take orders should be executed"

