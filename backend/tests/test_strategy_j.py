"""
Tests for Strategy class - modify_deal method - Group J.

Group J: modify_deal - Order Modification Scenarios (Limit Entry)
Tests for modify_deal() with limit entry that doesn't execute, testing order modification scenarios.
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
# Group J: modify_deal - Order Modification Scenarios (Limit Entry)
# ============================================================================

class TestModifyDealOrderModification:
    """Test J: modify_deal scenarios with limit entry that doesn't execute."""
    
    def test_modify_deal_long_take_profit_farther(self, test_task):
        """Test J1: LONG - modify_deal with limit entry, take profit moved farther (110 -> 115)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],  # Three bars
            highs=[101.0, 101.0, 101.0],
            lows=[99.5, 99.5, 99.5]  # Low is above limit entry (99.0), so it doesn't trigger
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 99.0),  # Limit entry at 99.0
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 2,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'take_profit': 115.0  # Move take profit farther (110 -> 115)
                }
            }
        ]
        
        collected_data = []
        deal_id = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {
                'bar': bar_index,
                'price': current_price,
                'method_result': method_result
            }
            collected_data.append(data)
            
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_j1_long_take_farther")
                broker.run(save_results=False)
        
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        buy_result = collected_data[0]['method_result']
        assert isinstance(buy_result, OrderOperationResult)
        assert len(buy_result.error_messages) == 0, f"Should not have errors, got: {buy_result.error_messages}"
        assert buy_result.deal_id > 0
        
        modify_result = collected_data[2]['method_result']
        assert isinstance(modify_result, OrderOperationResult)
        assert len(modify_result.error_messages) == 0, \
            f"modify_deal should not have errors, got: {modify_result.error_messages}"
        
        deal = broker.get_deal_by_id(deal_id)
        assert deal is not None, "Deal should exist"
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        new_take = [o for o in take_orders if o.price == 115.0]
        assert len(new_take) > 0, "Should have new take profit order at 115.0"
    
    def test_modify_deal_long_take_profit_closer(self, test_task):
        """Test J2: LONG - modify_deal with limit entry, take profit moved closer (115 -> 110)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[99.5, 99.5, 99.5]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 99.0),
                    'stop_loss': 90.0,
                    'take_profit': 115.0
                }
            },
            {
                'bar_index': 2,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,
                    'take_profit': 110.0  # Move take profit closer (115 -> 110)
                }
            }
        ]
        
        collected_data = []
        deal_id = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {'bar': bar_index, 'price': current_price, 'method_result': method_result}
            collected_data.append(data)
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_j2_long_take_closer")
                broker.run(save_results=False)
        
        assert len(collected_data) == 3
        assert len(collected_data[0]['method_result'].error_messages) == 0
        assert len(collected_data[2]['method_result'].error_messages) == 0
        deal = broker.get_deal_by_id(deal_id)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        new_take = [o for o in take_orders if o.price == 110.0]
        assert len(new_take) > 0, "Should have new take profit order at 110.0"
    
    def test_modify_deal_long_stop_loss_farther(self, test_task):
        """Test J3: LONG - modify_deal with limit entry, stop loss moved farther (90 -> 85)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[99.5, 99.5, 99.5]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 99.0),
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 2,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,
                    'stop_loss': 85.0  # Move stop loss farther (90 -> 85)
                }
            }
        ]
        
        collected_data = []
        deal_id = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {'bar': bar_index, 'price': current_price, 'method_result': method_result}
            collected_data.append(data)
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_j3_long_stop_farther")
                broker.run(save_results=False)
        
        assert len(collected_data) == 3
        assert len(collected_data[0]['method_result'].error_messages) == 0
        assert len(collected_data[2]['method_result'].error_messages) == 0
        deal = broker.get_deal_by_id(deal_id)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        new_stop = [o for o in stop_orders if o.trigger_price == 85.0]
        assert len(new_stop) > 0, "Should have new stop loss order at 85.0"
    
    def test_modify_deal_long_stop_loss_closer(self, test_task):
        """Test J4: LONG - modify_deal with limit entry, stop loss moved closer (85 -> 90)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],
            lows=[99.5, 99.5, 99.5]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 99.0),
                    'stop_loss': 85.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 2,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,
                    'stop_loss': 90.0  # Move stop loss closer (85 -> 90)
                }
            }
        ]
        
        collected_data = []
        deal_id = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {'bar': bar_index, 'price': current_price, 'method_result': method_result}
            collected_data.append(data)
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_j4_long_stop_closer")
                broker.run(save_results=False)
        
        assert len(collected_data) == 3
        assert len(collected_data[0]['method_result'].error_messages) == 0
        assert len(collected_data[2]['method_result'].error_messages) == 0
        deal = broker.get_deal_by_id(deal_id)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        new_stop = [o for o in stop_orders if o.trigger_price == 90.0]
        assert len(new_stop) > 0, "Should have new stop loss order at 90.0"
    
    def test_modify_deal_short_take_profit_farther(self, test_task):
        """Test J5: SHORT - modify_deal with limit entry, take profit moved farther (90 -> 85)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[100.5, 100.5, 100.5],  # High is below limit entry (101.0), so it doesn't trigger
            lows=[99.0, 99.0, 99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 101.0),  # Limit entry at 101.0
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 2,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,
                    'take_profit': 85.0  # Move take profit farther (90 -> 85)
                }
            }
        ]
        
        collected_data = []
        deal_id = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {'bar': bar_index, 'price': current_price, 'method_result': method_result}
            collected_data.append(data)
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_j5_short_take_farther")
                broker.run(save_results=False)
        
        assert len(collected_data) == 3
        assert len(collected_data[0]['method_result'].error_messages) == 0
        assert len(collected_data[2]['method_result'].error_messages) == 0
        deal = broker.get_deal_by_id(deal_id)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        new_take = [o for o in take_orders if o.price == 85.0]
        assert len(new_take) > 0, "Should have new take profit order at 85.0"
    
    def test_modify_deal_short_take_profit_closer(self, test_task):
        """Test J6: SHORT - modify_deal with limit entry, take profit moved closer (85 -> 90)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[100.5, 100.5, 100.5],
            lows=[99.0, 99.0, 99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 101.0),
                    'stop_loss': 110.0,
                    'take_profit': 85.0
                }
            },
            {
                'bar_index': 2,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,
                    'take_profit': 90.0  # Move take profit closer (85 -> 90)
                }
            }
        ]
        
        collected_data = []
        deal_id = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {'bar': bar_index, 'price': current_price, 'method_result': method_result}
            collected_data.append(data)
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_j6_short_take_closer")
                broker.run(save_results=False)
        
        assert len(collected_data) == 3
        assert len(collected_data[0]['method_result'].error_messages) == 0
        assert len(collected_data[2]['method_result'].error_messages) == 0
        deal = broker.get_deal_by_id(deal_id)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        new_take = [o for o in take_orders if o.price == 90.0]
        assert len(new_take) > 0, "Should have new take profit order at 90.0"
    
    def test_modify_deal_short_stop_loss_farther(self, test_task):
        """Test J7: SHORT - modify_deal with limit entry, stop loss moved farther (110 -> 115)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[100.5, 100.5, 100.5],
            lows=[99.0, 99.0, 99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 101.0),
                    'stop_loss': 110.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 2,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,
                    'stop_loss': 115.0  # Move stop loss farther (110 -> 115)
                }
            }
        ]
        
        collected_data = []
        deal_id = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {'bar': bar_index, 'price': current_price, 'method_result': method_result}
            collected_data.append(data)
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_j7_short_stop_farther")
                broker.run(save_results=False)
        
        assert len(collected_data) == 3
        assert len(collected_data[0]['method_result'].error_messages) == 0
        assert len(collected_data[2]['method_result'].error_messages) == 0
        deal = broker.get_deal_by_id(deal_id)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        new_stop = [o for o in stop_orders if o.trigger_price == 115.0]
        assert len(new_stop) > 0, "Should have new stop loss order at 115.0"
    
    def test_modify_deal_short_stop_loss_closer(self, test_task):
        """Test J8: SHORT - modify_deal with limit entry, stop loss moved closer (115 -> 110)."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[100.5, 100.5, 100.5],
            lows=[99.0, 99.0, 99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 101.0),
                    'stop_loss': 115.0,
                    'take_profit': 90.0
                }
            },
            {
                'bar_index': 2,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,
                    'stop_loss': 110.0  # Move stop loss closer (115 -> 110)
                }
            }
        ]
        
        collected_data = []
        deal_id = None
        
        def check_callback(strategy, bar_index, current_price, method_result=None):
            nonlocal deal_id
            data = {'bar': bar_index, 'price': current_price, 'method_result': method_result}
            collected_data.append(data)
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
                        action['args']['deal_id'] = deal_id
                        break
        
        test_task.parameters = {'test_protocol': protocol, 'test_callback': check_callback}
        
        with patch('app.services.tasks.broker_backtesting.QuotesClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_quotes.return_value = quotes_data
            mock_client_class.return_value = mock_client
            test_task.isRunning = True
            with patch('app.services.tasks.tasks.Task.load', return_value=test_task):
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_j8_short_stop_closer")
                broker.run(save_results=False)
        
        assert len(collected_data) == 3
        assert len(collected_data[0]['method_result'].error_messages) == 0
        assert len(collected_data[2]['method_result'].error_messages) == 0
        deal = broker.get_deal_by_id(deal_id)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        new_stop = [o for o in stop_orders if o.trigger_price == 110.0]
        assert len(new_stop) > 0, "Should have new stop loss order at 110.0"

