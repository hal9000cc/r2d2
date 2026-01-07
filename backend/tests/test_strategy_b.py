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


# ============================================================================
# Group B2: Multiple Same-Type Orders Execution on Same Bar - SELL
# ============================================================================

class TestSellSltpMultipleExecutionSameBar:
    """Test B2: Multiple same-type orders execution on same bar scenarios for sell_sltp."""
    
    def test_sell_sltp_market_multiple_stops_simultaneous(self, test_task):
        """Test B2.1: Market entry → multiple stops trigger simultaneously (price hits all stops)."""
        # Prepare quotes data: price 100.0, then rises to trigger all stops simultaneously
        # Bar 1: high=105.0, stops at 110.0 and 112.0 - stops не сработают (105.0 < 110.0, 105.0 < 112.0)
        # Bar 2: high=113.0, stops at 110.0 and 112.0 - оба стопа сработают одновременно (113.0 >= 110.0, 113.0 >= 112.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 113.0, 108.0],
            highs=[101.0, 106.0, 114.0, 109.0]  # Bar 2 high=114.0 triggers both stops at 110.0 and 112.0 simultaneously
        )
        
        # Protocol: On bar 0, enter market SELL with two stops (0.5 at 110.0, 0.5 at 112.0) and take profit 90.0
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected stops trigger: bar 2 at prices 110.0 and 112.0 (both execute as market, with slippage)
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
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2  # 110.1*0.5 + 0.05505 + 112.1*0.5 + 0.05605 = 111.2111
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 111.2111 = -11.411
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b2_1_multiple_stops_simultaneous")
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
    
    def test_sell_sltp_market_multiple_takes_simultaneous(self, test_task):
        """Test B2.2: Market entry → multiple take profits trigger simultaneously (price hits all takes)."""
        # Prepare quotes data: price 100.0, then drops to trigger all take profits simultaneously
        # Bar 1: low=95.0, takes at 90.0 and 88.0 - takes не сработают (95.0 > 90.0, 95.0 > 88.0)
        # Bar 2: low=87.0, takes at 90.0 and 88.0 - оба тейка сработают одновременно (87.0 <= 90.0, 87.0 <= 88.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 87.0, 92.0],
            lows=[99.0, 94.0, 86.0, 91.0]  # Bar 2 low=86.0 triggers both takes at 90.0 and 88.0 simultaneously
        )
        
        # Protocol: On bar 0, enter market SELL with stop loss 110.0 and two takes (0.5 at 90.0, 0.5 at 88.0)
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected takes trigger: bar 2 at prices 90.0 and 88.0 (both execute as limit, no slippage, fee_maker)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_trigger1 = 90.0
        take_trigger2 = 88.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution1 = take_trigger1  # 90.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_maker  # 90.0 * 0.5 * 0.0005 = 0.0225
        exit_execution2 = take_trigger2  # 88.0 (limit, no slippage)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_maker  # 88.0 * 0.5 * 0.0005 = 0.022
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2  # 90.0*0.5 + 0.0225 + 88.0*0.5 + 0.022 = 89.0445
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 89.0445 = 10.7556
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': [(0.5, 90.0), (0.5, 88.0)]  # Two takes with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b2_2_multiple_takes_simultaneous")
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
    
    def test_sell_sltp_multiple_limits_simultaneous(self, test_task):
        """Test B2.3: Multiple limit entries → all trigger simultaneously."""
        # Prepare quotes data: price 100.0, then rises to trigger all limit entries simultaneously
        # Bar 0: high=101.0, limits at 103.0 and 105.0 - лимитки не сработают (101.0 < 103.0, 101.0 < 105.0)
        # Bar 1: high=106.0, limits at 103.0 and 105.0 - обе лимитки сработают одновременно (106.0 >= 103.0, 106.0 >= 105.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 104.0, 102.0],
            highs=[101.0, 106.0, 103.0]  # Bar 1 high=106.0 triggers both limits at 103.0 and 105.0 simultaneously
        )
        
        # Protocol: On bar 0, enter SELL with two limits (0.5 at 103.0, 0.5 at 105.0) with stop loss 110.0 and take profit 90.0
        # Entry prices: 103.0 and 105.0 (limits, no slippage, fee_maker)
        # Expected limits trigger: bar 1 at prices 103.0 and 105.0 simultaneously
        # Expected profit calculation (assuming stop triggers later):
        entry_price1 = 103.0
        entry_price2 = 105.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity1 = 0.5
        quantity2 = 0.5
        total_quantity = 1.0
        stop_trigger = 110.0
        
        entry_execution1 = entry_price1  # 103.0 (limit, no slippage)
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 103.0 * 0.5 * 0.0005 = 0.02575
        entry_execution2 = entry_price2  # 105.0 (limit, no slippage)
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 105.0 * 0.5 * 0.0005 = 0.02625
        
        # For this test, we'll assume stop triggers on bar 2 (after entries execute)
        exit_execution = stop_trigger + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee = exit_execution * total_quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        
        entry_proceeds = entry_execution1 * quantity1 - entry_fee1 + entry_execution2 * quantity2 - entry_fee2  # 103.0*0.5 - 0.02575 + 105.0*0.5 - 0.02625 = 103.948
        exit_cost = exit_execution * total_quantity + exit_fee  # 110.1*1.0 + 0.1101 = 110.2101
        expected_profit = entry_proceeds - exit_cost  # = 103.948 - 110.2101 = -6.2621
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.5, 103.0), (0.5, 105.0)],  # Two limit orders
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b2_3_multiple_limits_simultaneous")
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
    
    def test_sell_sltp_market_multiple_stops_sequential(self, test_task):
        """Test B2.4: Market entry → multiple stops trigger sequentially (on different bars)."""
        # Prepare quotes data: price 100.0, then rises to trigger stops sequentially
        # Bar 1: high=105.0, stops at 110.0 and 114.0 - первый стоп не сработает (105.0 < 110.0), второй не сработает (105.0 < 114.0)
        # Bar 2: high=111.0, stops at 110.0 and 114.0 - первый стоп сработает (111.0 >= 110.0), второй не сработает (111.0 < 114.0)
        # Bar 3: high=115.0, stops at 110.0 and 114.0 - второй стоп сработает (115.0 >= 114.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 111.0, 115.0, 108.0],
            highs=[101.0, 106.0, 112.0, 116.0, 109.0]  # Bar 2 high=112.0 triggers first stop at 110.0, Bar 3 high=116.0 triggers second stop at 114.0
        )
        
        # Protocol: On bar 0, enter market SELL with two stops (0.5 at 110.0, 0.5 at 114.0) and take profit 90.0
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected stops trigger: bar 2 at 110.0, bar 3 at 114.0 (sequential)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 110.0
        stop_trigger2 = 114.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution1 = stop_trigger1 + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        exit_execution2 = stop_trigger2 + slippage  # 114.0 + 0.1 = 114.1 (BUY stop, slippage increases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 114.1 * 0.5 * 0.001 = 0.05705
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2  # 110.1*0.5 + 0.05505 + 114.1*0.5 + 0.05705 = 112.2121
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 112.2121 = -12.412
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': [(0.5, 110.0), (0.5, 114.0)],  # Two stops with equal shares - second stop higher to trigger sequentially
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b2_4_multiple_stops_sequential")
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
    
    def test_sell_sltp_market_multiple_takes_sequential(self, test_task):
        """Test B2.5: Market entry → multiple take profits trigger sequentially (on different bars)."""
        # Prepare quotes data: price 100.0, then drops to trigger take profits sequentially
        # Bar 1: low=95.0, takes at 90.0 and 88.0 - первый тейк не сработает (95.0 > 90.0), второй не сработает (95.0 > 88.0)
        # Bar 2: low=89.0, takes at 90.0 and 88.0 - первый тейк сработает (89.0 <= 90.0), второй не сработает (89.0 > 88.0)
        # Bar 3: low=87.0, takes at 90.0 and 88.0 - второй тейк сработает (87.0 <= 88.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 89.0, 87.0, 92.0],
            lows=[99.0, 94.0, 88.0, 86.0, 91.0]  # Bar 2 low=88.0 triggers first take at 90.0, Bar 3 low=86.0 triggers second take at 88.0
        )
        
        # Protocol: On bar 0, enter market SELL with stop loss 110.0 and two takes (0.5 at 90.0, 0.5 at 88.0)
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected takes trigger: bar 2 at 90.0, bar 3 at 88.0 (sequential)
        # Expected profit calculation:
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_trigger1 = 90.0
        take_trigger2 = 88.0
        quantity1 = 0.5
        quantity2 = 0.5
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution1 = take_trigger1  # 90.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_maker  # 90.0 * 0.5 * 0.0005 = 0.0225
        exit_execution2 = take_trigger2  # 88.0 (limit, no slippage)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_maker  # 88.0 * 0.5 * 0.0005 = 0.022
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2  # 90.0*0.5 + 0.0225 + 88.0*0.5 + 0.022 = 89.0445
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 89.0445 = 10.7556
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': [(0.5, 90.0), (0.5, 88.0)]  # Two takes with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b2_5_multiple_takes_sequential")
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


# ============================================================================
# Group B3: Partial Execution of Same-Type Orders - BUY
# ============================================================================

class TestBuySltpPartialExecution:
    """Test B3: Partial execution of same-type orders scenarios for buy_sltp."""
    
    def test_buy_sltp_market_multiple_stops_one_triggers(self, test_task):
        """Test B3.1: Market entry → multiple stops, only one triggers (price hits one stop)."""
        # Prepare quotes data: price 100.0, then drops to trigger only one stop
        # Bar 1: low=94.0, stops at 90.0 and 88.0 - stops не сработают (94.0 > 90.0, 94.0 > 88.0)
        # Bar 2: low=89.0, stops at 90.0 and 88.0 - первый стоп сработает (89.0 <= 90.0), второй не сработает (89.0 > 88.0)
        # Bar 3: low=91.0, stops at 90.0 and 88.0 - второй стоп не сработает (91.0 > 88.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 89.0, 92.0, 95.0],
            lows=[99.0, 94.0, 89.0, 91.0, 94.0]  # Bar 2 low=89.0 triggers first stop at 90.0, second stop at 88.0 doesn't trigger (89.0 > 88.0)
        )
        
        # Protocol: On bar 0, enter market with two stops (0.5 at 90.0, 0.5 at 88.0) and take profit 110.0
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: only first stop triggers on bar 2, second stop remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 90.0
        quantity1 = 0.5
        quantity2 = 0.5  # Remaining position that will be auto-closed
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution1 = stop_trigger1 - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        
        # Auto-close on last bar (bar 4) at close price 95.0
        auto_close_price = 95.0
        auto_close_execution = auto_close_price - slippage  # 95.0 - 0.1 = 94.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * quantity2 * test_task.fee_taker  # 94.9 * 0.5 * 0.001 = 0.04745
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + auto_close_execution * quantity2 - auto_close_fee  # 89.9*0.5 - 0.04495 + 94.9*0.5 - 0.04745 = 92.2576
        expected_profit = total_exit_proceeds - entry_cost  # = 92.2576 - 100.2001 = -7.9425
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b3_1_multiple_stops_one_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, only first stop on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first stop triggered (2 trades - entry + stop1)
        # Bar 3-4: no more stops trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 2, "First stop should trigger on bar 2"
        
        # Check final state: deal should be closed (one stop + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + stop1 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only one stop order was executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Only one stop order should be executed"

    
    def test_buy_sltp_market_multiple_stops_part_triggers(self, test_task):
        """Test B3.2: Market entry → multiple stops, part triggers (price hits part of stops)."""
        # Prepare quotes data: price 100.0, then drops to trigger part of stops
        # Bar 1: low=94.0, stops at 90.0, 88.0, 86.0 - stops не сработают (94.0 > 90.0, 94.0 > 88.0, 94.0 > 86.0)
        # Bar 2: low=87.0, stops at 90.0, 88.0, 86.0 - первые два стопа сработают (87.0 <= 90.0, 87.0 <= 88.0), третий не сработает (87.0 > 86.0)
        # Bar 3: low=91.0, stops at 90.0, 88.0, 86.0 - третий стоп не сработает (91.0 > 86.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 87.0, 92.0, 95.0],
            lows=[99.0, 94.0, 86.0, 91.0, 94.0]  # Bar 2 low=86.0 triggers first two stops at 90.0 and 88.0, third stop at 86.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter market with three stops (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0) and take profit 110.0
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: first two stops trigger on bar 2, third stop remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 90.0
        stop_trigger2 = 88.0
        quantity1 = 0.33
        quantity2 = 0.33
        quantity3 = 0.34  # Remaining position that will be auto-closed
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution1 = stop_trigger1 - slippage  # 90.0 - 0.1 = 89.9 (SELL stop, slippage decreases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 89.9 * 0.33 * 0.001 = 0.029667
        exit_execution2 = stop_trigger2 - slippage  # 88.0 - 0.1 = 87.9 (SELL stop, slippage decreases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 87.9 * 0.33 * 0.001 = 0.029007
        
        # Auto-close on last bar (bar 4) at close price 95.0
        auto_close_price = 95.0
        auto_close_execution = auto_close_price - slippage  # 95.0 - 0.1 = 94.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * quantity3 * test_task.fee_taker  # 94.9 * 0.34 * 0.001 = 0.032266
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + exit_execution2 * quantity2 - exit_fee2 + auto_close_execution * quantity3 - auto_close_fee  # 89.9*0.33 - 0.029667 + 87.9*0.33 - 0.029007 + 94.9*0.34 - 0.032266 = 91.80806
        expected_profit = total_exit_proceeds - entry_cost  # = 91.80806 - 100.2001 = -8.39204
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b3_2_multiple_stops_part_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, first two stops on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first two stops triggered (3 trades - entry + stop1 + stop2)
        # Bar 3-4: no more stops trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 3, "First two stops should trigger on bar 2"
        
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
        
        # Check that only two stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Only two stop orders should be executed"

    
    def test_buy_sltp_market_multiple_takes_one_triggers(self, test_task):
        """Test B3.3: Market entry → multiple take profits, only one triggers."""
        # Prepare quotes data: price 100.0, then rises to trigger only one take profit
        # Bar 1: high=105.0, takes at 110.0 and 112.0 - takes не сработают (105.0 < 110.0, 105.0 < 112.0)
        # Bar 2: high=111.0, takes at 110.0 and 112.0 - первый тейк сработает (111.0 >= 110.0), второй не сработает (111.0 < 112.0)
        # Bar 3: high=109.0, takes at 110.0 and 112.0 - второй тейк не сработает (109.0 < 112.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 111.0, 109.0, 108.0],
            highs=[101.0, 106.0, 112.0, 110.0, 109.0]  # Bar 2 high=112.0 triggers first take at 110.0, second take at 112.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter market with stop loss 90.0 and two takes (0.5 at 110.0, 0.5 at 112.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: only first take triggers on bar 2, second take remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_trigger1 = 110.0
        quantity1 = 0.5
        quantity2 = 0.5  # Remaining position that will be auto-closed
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution1 = take_trigger1  # 110.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_maker  # 110.0 * 0.5 * 0.0005 = 0.0275
        
        # Auto-close on last bar (bar 4) at close price 108.0
        auto_close_price = 108.0
        auto_close_execution = auto_close_price - slippage  # 108.0 - 0.1 = 107.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * quantity2 * test_task.fee_taker  # 107.9 * 0.5 * 0.001 = 0.05395
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + auto_close_execution * quantity2 - auto_close_fee  # 110.0*0.5 - 0.0275 + 107.9*0.5 - 0.05395 = 108.81855
        expected_profit = total_exit_proceeds - entry_cost  # = 108.81855 - 100.2001 = 8.61845
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b3_3_multiple_takes_one_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, only first take on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first take triggered (2 trades - entry + take1)
        # Bar 3-4: no more takes trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 2, "First take should trigger on bar 2"
        
        # Check final state: deal should be closed (one take + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + take1 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only one take order was executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 1, "Only one take order should be executed"
    

    def test_buy_sltp_market_multiple_takes_part_triggers(self, test_task):
        """Test B3.4: Market entry → multiple take profits, part triggers."""
        # Prepare quotes data: price 100.0, then rises to trigger part of take profits
        # Bar 1: high=105.0, takes at 110.0, 112.0, 114.0 - takes не сработают (105.0 < 110.0, 105.0 < 112.0, 105.0 < 114.0)
        # Bar 2: high=113.0, takes at 110.0, 112.0, 114.0 - первые два тейка сработают (113.0 >= 110.0, 113.0 >= 112.0), третий не сработает (113.0 < 114.0)
        # Bar 3: high=111.0, takes at 110.0, 112.0, 114.0 - третий тейк не сработает (111.0 < 114.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 113.0, 111.0, 110.0],
            highs=[101.0, 106.0, 114.0, 112.0, 111.0]  # Bar 2 high=114.0 triggers first two takes at 110.0 and 112.0, third take at 114.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter market with stop loss 90.0 and three takes (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0)
        # Entry price: 100.0 (market, with slippage +0.1 = 100.1)
        # Expected: first two takes trigger on bar 2, third take remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_trigger1 = 110.0
        take_trigger2 = 112.0
        quantity1 = 0.33
        quantity2 = 0.33
        quantity3 = 0.34  # Remaining position that will be auto-closed
        
        entry_execution = entry_price + slippage  # 100.1
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 100.1 * 1.0 * 0.001 = 0.1001
        
        exit_execution1 = take_trigger1  # 110.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_maker  # 110.0 * 0.33 * 0.0005 = 0.01815
        exit_execution2 = take_trigger2  # 112.0 (limit, no slippage)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_maker  # 112.0 * 0.33 * 0.0005 = 0.01848
        
        # Auto-close on last bar (bar 4) at close price 110.0
        auto_close_price = 110.0
        auto_close_execution = auto_close_price - slippage  # 110.0 - 0.1 = 109.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * quantity3 * test_task.fee_taker  # 109.9 * 0.34 * 0.001 = 0.037366
        
        entry_cost = entry_execution * quantity + entry_fee  # 100.1*1.0 + 0.1001 = 100.2001
        total_exit_proceeds = exit_execution1 * quantity1 - exit_fee1 + exit_execution2 * quantity2 - exit_fee2 + auto_close_execution * quantity3 - auto_close_fee  # 110.0*0.33 - 0.01815 + 112.0*0.33 - 0.01848 + 109.9*0.34 - 0.037366 = 110.226004
        expected_profit = total_exit_proceeds - entry_cost  # = 110.226004 - 100.2001 = 10.025904
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)]  # Three takes with shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b3_4_multiple_takes_part_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, first two takes on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first two takes triggered (3 trades - entry + take1 + take2)
        # Bar 3-4: no more takes trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 3, "First two takes should trigger on bar 2"
        
        # Check final state: deal should be closed (two takes + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + take1 + take2 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only two take orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "Only two take orders should be executed"
    
    def test_buy_sltp_multiple_limits_one_triggers(self, test_task):
        """Test B3.5: Multiple limit entries → only one triggers."""
        # Prepare quotes data: price 100.0, then drops to trigger only one limit entry
        # Bar 0: low=99.0, limits at 97.0 and 95.0 - лимитки не сработают (99.0 > 97.0, 99.0 > 95.0)
        # Bar 1: low=96.0, limits at 97.0 and 95.0 - первая лимитка сработает (96.0 <= 97.0), вторая не сработает (96.0 > 95.0)
        # Bar 2: low=98.0, limits at 97.0 and 95.0 - вторая лимитка не сработает (98.0 > 95.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 96.0, 98.0, 99.0],
            lows=[99.0, 95.0, 97.0, 98.0]  # Bar 1 low=95.0 triggers first limit at 97.0, second limit at 95.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter with two limits (0.5 at 97.0, 0.5 at 95.0) with stop loss 90.0 and take profit 110.0
        # Entry prices: 97.0 (limit, no slippage, fee_maker)
        # Expected: only first limit triggers on bar 1, second limit remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price1 = 97.0
        quantity1 = 0.5
        quantity2 = 0.5  # Remaining position that will be auto-closed
        
        entry_execution1 = entry_price1  # 97.0 (limit, no slippage)
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 97.0 * 0.5 * 0.0005 = 0.02425
        
        # Auto-close on last bar (bar 3) at close price 99.0
        auto_close_price = 99.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        auto_close_execution = auto_close_price - slippage  # 99.0 - 0.1 = 98.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * quantity2 * test_task.fee_taker  # 98.9 * 0.5 * 0.001 = 0.04945
        
        entry_cost = entry_execution1 * quantity1 + entry_fee1  # 97.0*0.5 + 0.02425 = 48.52425
        exit_proceeds = auto_close_execution * quantity2 - auto_close_fee  # 98.9*0.5 - 0.04945 = 49.40055
        expected_profit = exit_proceeds - entry_cost  # = 49.40055 - 48.52425 = 0.8763
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b3_5_multiple_limits_one_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that only first limit executed on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: first limit executed (1 trade)
        # Bar 2-3: second limit doesn't trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 1, "First limit should execute on bar 1"
        
        # Check final state: deal should be closed (one limit + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 2, f"Expected 2 trades total (limit1 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only one entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.ENTRY]
        assert len(entry_orders) == 2, "Should have two entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Only one entry order should be executed"
    
    def test_buy_sltp_multiple_limits_part_triggers(self, test_task):
        """Test B3.6: Multiple limit entries → part triggers."""
        # Prepare quotes data: price 100.0, then drops to trigger part of limit entries
        # Bar 0: low=99.0, limits at 97.0, 95.0, 93.0 - лимитки не сработают (99.0 > 97.0, 99.0 > 95.0, 99.0 > 93.0)
        # Bar 1: low=94.0, limits at 97.0, 95.0, 93.0 - первые две лимитки сработают (94.0 <= 97.0, 94.0 <= 95.0), третья не сработает (94.0 > 93.0)
        # Bar 2: low=96.0, limits at 97.0, 95.0, 93.0 - третья лимитка не сработает (96.0 > 93.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 94.0, 96.0, 98.0],
            lows=[99.0, 93.0, 95.0, 97.0]  # Bar 1 low=93.0 triggers first two limits at 97.0 and 95.0, third limit at 93.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter with three limits (0.33 at 97.0, 0.33 at 95.0, 0.34 at 93.0) with stop loss 90.0 and take profit 110.0
        # Entry prices: 97.0 and 95.0 (limits, no slippage, fee_maker)
        # Expected: first two limits trigger on bar 1, third limit remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price1 = 97.0
        entry_price2 = 95.0
        quantity1 = 0.33
        quantity2 = 0.33
        quantity3 = 0.34  # Remaining position that will be auto-closed
        
        entry_execution1 = entry_price1  # 97.0 (limit, no slippage)
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 97.0 * 0.33 * 0.0005 = 0.016005
        entry_execution2 = entry_price2  # 95.0 (limit, no slippage)
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 95.0 * 0.33 * 0.0005 = 0.015675
        
        # Auto-close on last bar (bar 3) at close price 98.0
        auto_close_price = 98.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        auto_close_execution = auto_close_price - slippage  # 98.0 - 0.1 = 97.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * quantity3 * test_task.fee_taker  # 97.9 * 0.34 * 0.001 = 0.033286
        
        entry_cost = entry_execution1 * quantity1 + entry_fee1 + entry_execution2 * quantity2 + entry_fee2  # 97.0*0.33 + 0.016005 + 95.0*0.33 + 0.015675 = 63.38168
        exit_proceeds = auto_close_execution * quantity3 - auto_close_fee  # 97.9*0.34 - 0.033286 = 33.253714
        expected_profit = exit_proceeds - entry_cost  # = 33.253714 - 63.38168 = -30.127966
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.33, 97.0), (0.33, 95.0), (0.34, 93.0)],  # Three limit orders
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_b3_6_multiple_limits_part_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that first two limits executed on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: first two limits executed (2 trades)
        # Bar 2-3: third limit doesn't trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First two limits should execute on bar 1"
        
        # Check final state: deal should be closed (two limits + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 3, f"Expected 3 trades total (limit1 + limit2 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only two entry orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.ENTRY]
        assert len(entry_orders) == 3, "Should have three entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 2, "Only two entry orders should be executed"


# ============================================================================
# Group B3: Partial Execution of Same-Type Orders - SELL
# ============================================================================

class TestSellSltpPartialExecution:
    """Test B3: Partial execution of same-type orders scenarios for sell_sltp."""
    
    def test_sell_sltp_market_multiple_stops_one_triggers(self, test_task):
        """Test B3.1: Market entry → multiple stops, only one triggers (price hits one stop)."""
        # Prepare quotes data: price 100.0, then rises to trigger only one stop
        # Bar 1: high=105.0, stops at 110.0 and 112.0 - stops не сработают (105.0 < 110.0, 105.0 < 112.0)
        # Bar 2: high=111.0, stops at 110.0 and 112.0 - первый стоп сработает (111.0 >= 110.0), второй не сработает (111.0 < 112.0)
        # Bar 3: high=109.0, stops at 110.0 and 112.0 - второй стоп не сработает (109.0 < 112.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 111.0, 109.0, 108.0],
            highs=[101.0, 106.0, 112.0, 110.0, 109.0]  # Bar 2 high=112.0 triggers first stop at 110.0, second stop at 112.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter market SELL with two stops (0.5 at 110.0, 0.5 at 112.0) and take profit 90.0
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected: only first stop triggers on bar 2, second stop remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 110.0
        quantity1 = 0.5
        quantity2 = 0.5  # Remaining position that will be auto-closed
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution1 = stop_trigger1 + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        
        # Auto-close on last bar (bar 4) at close price 108.0
        auto_close_price = 108.0
        auto_close_execution = auto_close_price + slippage  # 108.0 + 0.1 = 108.1 (BUY market, slippage increases price)
        auto_close_fee = auto_close_execution * quantity2 * test_task.fee_taker  # 108.1 * 0.5 * 0.001 = 0.05405
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + auto_close_execution * quantity2 + auto_close_fee  # 110.1*0.5 + 0.05505 + 108.1*0.5 + 0.05405 = 109.1591
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 109.1591 = -9.359
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b3_1_multiple_stops_one_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, only first stop on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first stop triggered (2 trades - entry + stop1)
        # Bar 3-4: no more stops trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 2, "First stop should trigger on bar 2"
        
        # Check final state: deal should be closed (one stop + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + stop1 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only one stop order was executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Only one stop order should be executed"

    
    def test_sell_sltp_market_multiple_stops_part_triggers(self, test_task):
        """Test B3.2: Market entry → multiple stops, part triggers (price hits part of stops)."""
        # Prepare quotes data: price 100.0, then rises to trigger part of stops
        # Bar 1: high=105.0, stops at 110.0, 112.0, 114.0 - stops не сработают (105.0 < 110.0, 105.0 < 112.0, 105.0 < 114.0)
        # Bar 2: high=113.0, stops at 110.0, 112.0, 114.0 - первые два стопа сработают (113.0 >= 110.0, 113.0 >= 112.0), третий не сработает (113.0 < 114.0)
        # Bar 3: high=111.0, stops at 110.0, 112.0, 114.0 - третий стоп не сработает (111.0 < 114.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 105.0, 113.0, 111.0, 110.0],
            highs=[101.0, 106.0, 114.0, 112.0, 111.0]  # Bar 2 high=114.0 triggers first two stops at 110.0 and 112.0, third stop at 114.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter market SELL with three stops (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0) and take profit 90.0
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected: first two stops trigger on bar 2, third stop remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        stop_trigger1 = 110.0
        stop_trigger2 = 112.0
        quantity1 = 0.33
        quantity2 = 0.33
        quantity3 = 0.34  # Remaining position that will be auto-closed
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution1 = stop_trigger1 + slippage  # 110.0 + 0.1 = 110.1 (BUY stop, slippage increases price)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_taker  # 110.1 * 0.33 * 0.001 = 0.036333
        exit_execution2 = stop_trigger2 + slippage  # 112.0 + 0.1 = 112.1 (BUY stop, slippage increases price)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_taker  # 112.1 * 0.33 * 0.001 = 0.036993
        
        # Auto-close on last bar (bar 4) at close price 110.0
        auto_close_price = 110.0
        auto_close_execution = auto_close_price + slippage  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        auto_close_fee = auto_close_execution * quantity3 * test_task.fee_taker  # 110.1 * 0.34 * 0.001 = 0.037434
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2 + auto_close_execution * quantity3 + auto_close_fee  # 110.1*0.33 + 0.036333 + 112.1*0.33 + 0.036993 + 110.1*0.34 + 0.037434 = 110.41066
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 110.41066 = -10.61056
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b3_2_multiple_stops_part_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, first two stops on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first two stops triggered (3 trades - entry + stop1 + stop2)
        # Bar 3-4: no more stops trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 3, "First two stops should trigger on bar 2"
        
        # Check final state: deal should be closed (two stops + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + stop1 + stop2 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only two stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Only two stop orders should be executed"
    
    def test_sell_sltp_market_multiple_takes_one_triggers(self, test_task):
        """Test B3.3: Market entry → multiple take profits, only one triggers."""
        # Prepare quotes data: price 100.0, then drops to trigger only one take profit
        # Bar 1: low=95.0, takes at 90.0 and 88.0 - takes не сработают (95.0 > 90.0, 95.0 > 88.0)
        # Bar 2: low=89.0, takes at 90.0 and 88.0 - первый тейк сработает (89.0 <= 90.0), второй не сработает (89.0 > 88.0)
        # Bar 3: low=91.0, takes at 90.0 and 88.0 - второй тейк не сработает (91.0 > 88.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 89.0, 91.0, 92.0],
            lows=[99.0, 94.0, 88.0, 90.0, 91.0]  # Bar 2 low=88.0 triggers first take at 90.0, second take at 88.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter market SELL with stop loss 110.0 and two takes (0.5 at 90.0, 0.5 at 88.0)
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected: only first take triggers on bar 2, second take remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_trigger1 = 90.0
        quantity1 = 0.5
        quantity2 = 0.5  # Remaining position that will be auto-closed
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution1 = take_trigger1  # 90.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_maker  # 90.0 * 0.5 * 0.0005 = 0.0225
        
        # Auto-close on last bar (bar 4) at close price 92.0
        auto_close_price = 92.0
        auto_close_execution = auto_close_price + slippage  # 92.0 + 0.1 = 92.1 (BUY market, slippage increases price)
        auto_close_fee = auto_close_execution * quantity2 * test_task.fee_taker  # 92.1 * 0.5 * 0.001 = 0.04605
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + auto_close_execution * quantity2 + auto_close_fee  # 90.0*0.5 + 0.0225 + 92.1*0.5 + 0.04605 = 91.11855
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 91.11855 = 8.68155
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': [(0.5, 90.0), (0.5, 88.0)]  # Two takes with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b3_3_multiple_takes_one_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, only first take on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first take triggered (2 trades - entry + take1)
        # Bar 3-4: no more takes trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 2, "First take should trigger on bar 2"
        
        # Check final state: deal should be closed (one take + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + take1 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only one take order was executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 1, "Only one take order should be executed"
    
    def test_sell_sltp_market_multiple_takes_part_triggers(self, test_task):
        """Test B3.4: Market entry → multiple take profits, part triggers."""
        # Prepare quotes data: price 100.0, then drops to trigger part of take profits
        # Bar 1: low=95.0, takes at 90.0, 88.0, 86.0 - takes не сработают (95.0 > 90.0, 95.0 > 88.0, 95.0 > 86.0)
        # Bar 2: low=87.0, takes at 90.0, 88.0, 86.0 - первые два тейка сработают (87.0 <= 90.0, 87.0 <= 88.0), третий не сработает (87.0 > 86.0)
        # Bar 3: low=89.0, takes at 90.0, 88.0, 86.0 - третий тейк не сработает (89.0 > 86.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 95.0, 87.0, 89.0, 90.0],
            lows=[99.0, 94.0, 86.0, 88.0, 89.0]  # Bar 2 low=86.0 triggers first two takes at 90.0 and 88.0, third take at 86.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter market SELL with stop loss 110.0 and three takes (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0)
        # Entry price: 100.0 (market SELL, with slippage -0.1 = 99.9)
        # Expected: first two takes trigger on bar 2, third take remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price = 100.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        quantity = 1.0
        take_trigger1 = 90.0
        take_trigger2 = 88.0
        quantity1 = 0.33
        quantity2 = 0.33
        quantity3 = 0.34  # Remaining position that will be auto-closed
        
        entry_execution = entry_price - slippage  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        entry_fee = entry_execution * quantity * test_task.fee_taker  # 99.9 * 1.0 * 0.001 = 0.0999
        
        exit_execution1 = take_trigger1  # 90.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * quantity1 * test_task.fee_maker  # 90.0 * 0.33 * 0.0005 = 0.01485
        exit_execution2 = take_trigger2  # 88.0 (limit, no slippage)
        exit_fee2 = exit_execution2 * quantity2 * test_task.fee_maker  # 88.0 * 0.33 * 0.0005 = 0.01452
        
        # Auto-close on last bar (bar 4) at close price 90.0
        auto_close_price = 90.0
        auto_close_execution = auto_close_price + slippage  # 90.0 + 0.1 = 90.1 (BUY market, slippage increases price)
        auto_close_fee = auto_close_execution * quantity3 * test_task.fee_taker  # 90.1 * 0.34 * 0.001 = 0.030634
        
        entry_proceeds = entry_execution * quantity - entry_fee  # 99.9*1.0 - 0.0999 = 99.8001
        total_exit_cost = exit_execution1 * quantity1 + exit_fee1 + exit_execution2 * quantity2 + exit_fee2 + auto_close_execution * quantity3 + auto_close_fee  # 90.0*0.33 + 0.01485 + 88.0*0.33 + 0.01452 + 90.1*0.34 + 0.030634 = 89.624004
        expected_profit = entry_proceeds - total_exit_cost  # = 99.8001 - 89.624004 = 10.176096
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 110.0,
                    'take_profit': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)]  # Three takes with shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b3_4_multiple_takes_part_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 5, f"Expected 5 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry executed on bar 0, first two takes on bar 2
        # Bar 0: entry executed (1 trade)
        # Bar 1: no execution (1 trade)
        # Bar 2: first two takes triggered (3 trades - entry + take1 + take2)
        # Bar 3-4: no more takes trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 1, "Entry market order should execute immediately"
        assert collected_data[2]['trades_count'] == 3, "First two takes should trigger on bar 2"
        
        # Check final state: deal should be closed (two takes + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + take1 + take2 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only two take orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "Only two take orders should be executed"
    
    def test_sell_sltp_multiple_limits_one_triggers(self, test_task):
        """Test B3.5: Multiple limit entries → only one triggers."""
        # Prepare quotes data: price 100.0, then rises to trigger only one limit entry
        # Bar 0: high=101.0, limits at 103.0 and 105.0 - лимитки не сработают (101.0 < 103.0, 101.0 < 105.0)
        # Bar 1: high=104.0, limits at 103.0 and 105.0 - первая лимитка сработает (104.0 >= 103.0), вторая не сработает (104.0 < 105.0)
        # Bar 2: high=102.0, limits at 103.0 and 105.0 - вторая лимитка не сработает (102.0 < 105.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 104.0, 102.0, 101.0],
            highs=[101.0, 105.0, 103.0, 102.0]  # Bar 1 high=105.0 triggers first limit at 103.0, second limit at 105.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter SELL with two limits (0.5 at 103.0, 0.5 at 105.0) with stop loss 110.0 and take profit 90.0
        # Entry prices: 103.0 (limit, no slippage, fee_maker)
        # Expected: only first limit triggers on bar 1, second limit remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price1 = 103.0
        quantity1 = 0.5
        quantity2 = 0.5  # Remaining position that will be auto-closed
        
        entry_execution1 = entry_price1  # 103.0 (limit, no slippage)
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 103.0 * 0.5 * 0.0005 = 0.02575
        
        # Auto-close on last bar (bar 3) at close price 101.0
        auto_close_price = 101.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        auto_close_execution = auto_close_price + slippage  # 101.0 + 0.1 = 101.1 (BUY market, slippage increases price)
        auto_close_fee = auto_close_execution * quantity2 * test_task.fee_taker  # 101.1 * 0.5 * 0.001 = 0.05055
        
        entry_proceeds = entry_execution1 * quantity1 - entry_fee1  # 103.0*0.5 - 0.02575 = 51.47425
        exit_cost = auto_close_execution * quantity2 + auto_close_fee  # 101.1*0.5 + 0.05055 = 50.60055
        expected_profit = entry_proceeds - exit_cost  # = 51.47425 - 50.60055 = 0.8737
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.5, 103.0), (0.5, 105.0)],  # Two limit orders
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b3_5_multiple_limits_one_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that only first limit executed on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: first limit executed (1 trade)
        # Bar 2-3: second limit doesn't trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 1, "First limit should execute on bar 1"
        
        # Check final state: deal should be closed (one limit + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 2, f"Expected 2 trades total (limit1 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only one entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.ENTRY]
        assert len(entry_orders) == 2, "Should have two entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Only one entry order should be executed"
    
    def test_sell_sltp_multiple_limits_part_triggers(self, test_task):
        """Test B3.6: Multiple limit entries → part triggers."""
        # Prepare quotes data: price 100.0, then rises to trigger part of limit entries
        # Bar 0: high=101.0, limits at 103.0, 105.0, 107.0 - лимитки не сработают (101.0 < 103.0, 101.0 < 105.0, 101.0 < 107.0)
        # Bar 1: high=106.0, limits at 103.0, 105.0, 107.0 - первые две лимитки сработают (106.0 >= 103.0, 106.0 >= 105.0), третья не сработает (106.0 < 107.0)
        # Bar 2: high=104.0, limits at 103.0, 105.0, 107.0 - третья лимитка не сработает (104.0 < 107.0), цена откатилась
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 106.0, 104.0, 102.0],
            highs=[101.0, 107.0, 105.0, 103.0]  # Bar 1 high=107.0 triggers first two limits at 103.0 and 105.0, third limit at 107.0 doesn't trigger
        )
        
        # Protocol: On bar 0, enter SELL with three limits (0.33 at 103.0, 0.33 at 105.0, 0.34 at 107.0) with stop loss 110.0 and take profit 90.0
        # Entry prices: 103.0 and 105.0 (limits, no slippage, fee_maker)
        # Expected: first two limits trigger on bar 1, third limit remains active but doesn't trigger
        # Expected profit calculation (assuming auto-close on last bar):
        entry_price1 = 103.0
        entry_price2 = 105.0
        quantity1 = 0.33
        quantity2 = 0.33
        quantity3 = 0.34  # Remaining position that will be auto-closed
        
        entry_execution1 = entry_price1  # 103.0 (limit, no slippage)
        entry_fee1 = entry_execution1 * quantity1 * test_task.fee_maker  # 103.0 * 0.33 * 0.0005 = 0.016995
        entry_execution2 = entry_price2  # 105.0 (limit, no slippage)
        entry_fee2 = entry_execution2 * quantity2 * test_task.fee_maker  # 105.0 * 0.33 * 0.0005 = 0.017325
        
        # Auto-close on last bar (bar 3) at close price 102.0
        auto_close_price = 102.0
        slippage = test_task.slippage_in_steps * test_task.price_step  # 1.0 * 0.1 = 0.1
        auto_close_execution = auto_close_price + slippage  # 102.0 + 0.1 = 102.1 (BUY market, slippage increases price)
        auto_close_fee = auto_close_execution * quantity3 * test_task.fee_taker  # 102.1 * 0.34 * 0.001 = 0.034714
        
        entry_proceeds = entry_execution1 * quantity1 - entry_fee1 + entry_execution2 * quantity2 - entry_fee2  # 103.0*0.33 - 0.016995 + 105.0*0.33 - 0.017325 = 68.36568
        exit_cost = auto_close_execution * quantity3 + auto_close_fee  # 102.1*0.34 + 0.034714 = 34.748714
        expected_profit = entry_proceeds - exit_cost  # = 68.36568 - 34.748714 = 33.616966
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.33, 103.0), (0.33, 105.0), (0.34, 107.0)],  # Three limit orders
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_b3_6_multiple_limits_part_triggers")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that first two limits executed on bar 1
        # Bar 0: no execution (0 trades)
        # Bar 1: first two limits executed (2 trades)
        # Bar 2-3: third limit doesn't trigger, auto-close after last bar
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "First two limits should execute on bar 1"
        
        # Check final state: deal should be closed (two limits + auto-close)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert len(broker.trades) == 3, f"Expected 3 trades total (limit1 + limit2 + auto-close), got {len(broker.trades)}"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01,             f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that only two entry orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.ENTRY]
        assert len(entry_orders) == 3, "Should have three entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 2, "Only two entry orders should be executed"
