"""
Tests for Strategy class - modify_deal method - Group I.

Group I: modify_deal Tests
Tests for the modify_deal() method that modifies existing deals by canceling active orders and placing new ones.
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
# Group I1: modify_deal Validation
# ============================================================================

class TestModifyDealValidation:
    """Test I1: Validation scenarios for modify_deal."""
    
    def test_modify_deal_deal_not_found(self, test_task):
        """Test I1.1: modify_deal - deal not found (invalid deal_id) → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'modify_deal',
                'args': {
                    'deal_id': 999,  # Non-existent deal_id
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
                'method_result': method_result
            }
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_1_deal_not_found")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("not found" in msg.lower() for msg in method_result.error_messages), \
            f"Should have error about deal not found, got: {method_result.error_messages}"
        
        # Should not create orders
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 999, "Should return the requested deal_id"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_modify_deal_deal_already_closed(self, test_task):
        """Test I1.2: modify_deal - deal already closed (quantity == 0) → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 110.0],  # Price rises to trigger take profit
            highs=[101.0, 111.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,
                    'stop_loss': 90.0,
                    'take_profit': 110.0  # Will trigger on bar 1
                }
            },
            {
                'bar_index': 1,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'stop_loss': 95.0,
                    'take_profit': 115.0
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_2_deal_already_closed")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("already closed" in msg.lower() for msg in method_result.error_messages), \
            f"Should have error about deal already closed, got: {method_result.error_messages}"
        
        # Should not create orders
        assert len(method_result.orders) == 0, "Should not create any orders"
    
    def test_modify_deal_negative_volume_exceeds_position(self, test_task):
        """Test I1.3: modify_deal - negative volume exceeds current position volume → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Position will be 1.0
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 0,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'enter': -1.5,  # Trying to close 1.5 when position is only 1.0
                    'stop_loss': 90.0,
                    'take_profit': 110.0
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
            
            # Get deal_id from first result
            if method_result and method_result.deal_id > 0 and deal_id is None:
                deal_id = method_result.deal_id
                # Update protocol for modify_deal
                for action in strategy.test_protocol:
                    if action.get('method') == 'modify_deal':
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_3_negative_volume_exceeds_position")
                broker.run(save_results=False)
        
        # Check results - should have 2 method results (buy_sltp and modify_deal)
        modify_results = [d['method_result'] for d in collected_data if d.get('method_result')]
        assert len(modify_results) >= 2, f"Expected at least 2 method results, got {len(modify_results)}"
        
        # Find modify_deal result
        modify_result = None
        for result in modify_results:
            if result and len(result.error_messages) > 0:
                modify_result = result
                break
        
        assert modify_result is not None, "Should have modify_deal result with errors"
        
        # Should have validation errors
        assert len(modify_result.error_messages) > 0, "Should have validation errors"
        assert any("exceeds" in msg.lower() and "current position volume" in msg.lower() for msg in modify_result.error_messages), \
            f"Should have error about negative volume exceeding position, got: {modify_result.error_messages}"
    
    def test_modify_deal_long_buy_limit_above_current_price(self, test_task):
        """Test I1.4: modify_deal LONG - buy limit order price above current price → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],
            highs=[101.0, 101.0]
        )
        
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
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'enter': (0.5, 105.0),  # Buy limit at 105.0 (above current 100.0 - invalid)
                    'stop_loss': 90.0,
                    'take_profit': 110.0
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_4_long_buy_limit_above_current")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("LONG buy limit" in msg and "must be below" in msg for msg in method_result.error_messages), \
            f"Should have error about buy limit above current price, got: {method_result.error_messages}"
    
    def test_modify_deal_short_sell_limit_below_current_price(self, test_task):
        """Test I1.5: modify_deal SHORT - sell limit order price below current price → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],
            lows=[99.0, 99.0]
        )
        
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
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'enter': (0.5, 95.0),  # Sell limit at 95.0 (below current 100.0 - invalid)
                    'stop_loss': 110.0,
                    'take_profit': 90.0
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_5_short_sell_limit_below_current")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("SHORT sell limit" in msg and "must be above" in msg for msg in method_result.error_messages), \
            f"Should have error about sell limit below current price, got: {method_result.error_messages}"
    
    def test_modify_deal_long_stop_loss_above_current_price(self, test_task):
        """Test I1.6: modify_deal LONG - stop loss trigger price above current price → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],
            lows=[99.0, 99.0]
        )
        
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
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'stop_loss': 105.0,  # Stop at 105.0 (above current 100.0 - invalid for LONG)
                    'take_profit': 110.0
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_6_long_stop_loss_above_current")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("LONG stop loss" in msg and "must be below" in msg for msg in method_result.error_messages), \
            f"Should have error about stop loss above current price, got: {method_result.error_messages}"
    
    def test_modify_deal_short_stop_loss_below_current_price(self, test_task):
        """Test I1.7: modify_deal SHORT - stop loss trigger price below current price → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],
            highs=[101.0, 101.0]
        )
        
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
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'stop_loss': 95.0,  # Stop at 95.0 (below current 100.0 - invalid for SHORT)
                    'take_profit': 90.0
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_7_short_stop_loss_below_current")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("SHORT stop loss" in msg and "must be above" in msg for msg in method_result.error_messages), \
            f"Should have error about stop loss below current price, got: {method_result.error_messages}"
    
    def test_modify_deal_long_take_profit_below_current_price(self, test_task):
        """Test I1.8: modify_deal LONG - take profit price below current price → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],
            highs=[101.0, 101.0]
        )
        
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
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'stop_loss': 90.0,
                    'take_profit': 95.0  # Take at 95.0 (below current 100.0 - invalid for LONG)
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_8_long_take_profit_below_current")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("LONG take profit" in msg and "must be above" in msg for msg in method_result.error_messages), \
            f"Should have error about take profit below current price, got: {method_result.error_messages}"
    
    def test_modify_deal_short_take_profit_above_current_price(self, test_task):
        """Test I1.9: modify_deal SHORT - take profit price above current price → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],
            lows=[99.0, 99.0]
        )
        
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
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'stop_loss': 110.0,
                    'take_profit': 105.0  # Take at 105.0 (above current 100.0 - invalid for SHORT)
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_9_short_take_profit_above_current")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("SHORT take profit" in msg and "must be below" in msg for msg in method_result.error_messages), \
            f"Should have error about take profit above current price, got: {method_result.error_messages}"
    
    def test_modify_deal_long_limit_entry_not_protected_by_stop(self, test_task):
        """Test I1.10: modify_deal LONG - buy limit entry not protected by stop loss → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],
            lows=[99.0, 99.0]
        )
        
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
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'enter': (0.5, 85.0),  # Buy limit at 85.0
                    'stop_loss': 90.0  # Stop at 90.0 (above entry - not protected)
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_10_long_limit_entry_not_protected")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("not protected by stop loss" in msg for msg in method_result.error_messages), \
            f"Should have error about entry not protected by stop loss, got: {method_result.error_messages}"
    
    def test_modify_deal_short_limit_entry_not_protected_by_stop(self, test_task):
        """Test I1.11: modify_deal SHORT - sell limit entry not protected by stop loss → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],
            highs=[101.0, 101.0]
        )
        
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
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'enter': (0.5, 115.0),  # Sell limit at 115.0
                    'stop_loss': 110.0  # Stop at 110.0 (below entry - not protected)
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
            
            # Get deal_id from first result
            if bar_index == 0 and method_result and method_result.deal_id > 0:
                deal_id = method_result.deal_id
                # Update protocol for next bar
                for action in strategy.test_protocol:
                    if action.get('bar_index') == 1:
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i1_11_short_limit_entry_not_protected")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check method result on bar 1 (modify_deal)
        assert collected_data[1]['method_result'] is not None
        method_result = collected_data[1]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("not protected by stop loss" in msg for msg in method_result.error_messages), \
            f"Should have error about entry not protected by stop loss, got: {method_result.error_messages}"

