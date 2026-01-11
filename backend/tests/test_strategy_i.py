"""
Tests for Strategy class - modify_deal method - Group I.

Group I: modify_deal Tests
Tests for the modify_deal() method that modifies existing deals by canceling active orders and placing new ones.
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
            prices=[100.0, 100.0],  # Need 2 bars: one for buy_sltp, one for modify_deal
            highs=[101.0, 101.0]
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
                'bar_index': 1,  # On next bar after buy_sltp (TestStrategy executes only one action per bar)
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
            if bar_index == 0 and method_result and method_result.deal_id > 0:
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
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check buy_sltp result on bar 0
        assert collected_data[0]['method_result'] is not None
        buy_result = collected_data[0]['method_result']
        assert isinstance(buy_result, OrderOperationResult)
        assert buy_result.deal_id > 0
        
        # Check modify_deal result on bar 1
        assert collected_data[1]['method_result'] is not None
        modify_result = collected_data[1]['method_result']
        assert isinstance(modify_result, OrderOperationResult)
        
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


# ============================================================================
# Group I2: modify_deal - Basic Modification
# ============================================================================

class TestModifyDealBasicModification:
    """Test I2: Basic modification scenarios for modify_deal."""
    
    def test_modify_deal_basic_modification(self, test_task):
        """Test I2.1: A4.1 scenario → modify_deal to update stop loss and take profit."""
        # Prepare quotes data: price 100.0, drops to trigger limits, then modify_deal on bar 2
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 99.0, 95.0, 100.0],  # Bar 1 triggers first limit, Bar 2 triggers second limit, Bar 3 for modify_deal
            lows=[99.0, 98.0, 94.0, 99.0],  # Bar 1 triggers first limit, Bar 2 triggers second limit
            highs=[101.0, 100.0, 96.0, 101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.5, 99.0), (0.5, 95.0)],
                    'take_profit': 110.0
                    # No stop_loss initially
                }
            },
            {
                'bar_index': 2,  # After both entries execute
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'stop_loss': 90.0,  # Add stop loss
                    'take_profit': 115.0  # Update take profit
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i2_1_basic_modification")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check buy_sltp result on bar 0
        assert collected_data[0]['method_result'] is not None
        buy_result = collected_data[0]['method_result']
        assert isinstance(buy_result, OrderOperationResult)
        assert len(buy_result.error_messages) == 0, f"Should not have errors, got: {buy_result.error_messages}"
        assert buy_result.deal_id > 0
        
        # Check modify_deal result on bar 2
        assert collected_data[2]['method_result'] is not None
        modify_result = collected_data[2]['method_result']
        assert isinstance(modify_result, OrderOperationResult)
        assert len(modify_result.error_messages) == 0, f"Should not have errors, got: {modify_result.error_messages}"
        assert modify_result.deal_id == deal_id, "Should return the same deal_id"
        
        # Verify new orders are placed (stop loss + updated take profit)
        assert len(modify_result.orders) >= 2, "Should have at least stop loss and take profit orders"
        
        # Check that stop loss order is present
        stop_orders = [o for o in modify_result.orders if o.order_type == OrderType.STOP]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        assert stop_orders[0].trigger_price == 90.0, "Stop loss trigger price should be 90.0"
        
        # Check that new take profit order is created (modify_result.orders contains only new orders)
        take_orders = [o for o in modify_result.orders if o.order_type == OrderType.LIMIT and o.side == OrderSide.SELL]
        assert len(take_orders) == 1, "Should have one new take profit order in modify_result.orders"
        assert take_orders[0].price == 115.0, "New take profit price should be 115.0"
        
        # Verify deal exists and was closed after backtesting (close_deals is called at the end)
        deal = broker.get_deal_by_id(deal_id)
        assert deal is not None, "Deal should exist"
        # After broker.run() completes, all open deals are closed, so quantity should be 0
        assert deal.quantity == 0.0, f"Deal should be closed after backtesting (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be marked as closed after backtesting"
        
        # Verify old active orders are canceled and new ones are created
        # After close_deals(), all active orders are canceled, so we check that both orders exist
        # Check all take profit orders in the deal to see both old and new ones
        all_take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(all_take_orders) >= 2, "Should have at least 2 take profit orders (old + new)"
        
        # Find old take profit (110.0) - should be canceled (was canceled by modify_deal)
        old_take = [o for o in all_take_orders if o.price == 110.0]
        assert len(old_take) == 1, "Should have one old take profit order at 110.0"
        assert old_take[0].status == OrderStatus.CANCELED, "Old take profit at 110.0 should be canceled"
        
        # Find new take profit (115.0) - should be canceled (was canceled by close_deals at the end)
        new_take = [o for o in all_take_orders if o.price == 115.0]
        assert len(new_take) == 1, "Should have one new take profit order at 115.0"
        assert new_take[0].status == OrderStatus.CANCELED, "New take profit at 115.0 should be canceled (deal was closed at the end)"
        
        # Verify canceled list contains the old take profit order ID
        assert old_take[0].order_id in modify_result.canceled, "Old take profit order ID should be in canceled list"


# ============================================================================
# Group I7: modify_deal - Edge Cases
# ============================================================================

class TestModifyDealEdgeCases:
    """Test I7: Edge case scenarios for modify_deal."""
    
    def test_modify_deal_enter_none_only_update_exits(self, test_task):
        """Test I7.2: modify_deal with enter=None (only update exits)."""
        # Prepare quotes data: price 100.0, market entry executes immediately
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0],  # Bar 0: entry executes, Bar 1: modify_deal
            highs=[101.0, 101.0],
            lows=[99.0, 99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': 90.0,
                    'take_profit': 110.0
                }
            },
            {
                'bar_index': 1,
                'method': 'modify_deal',
                'args': {
                    'deal_id': None,  # Will be set from first result
                    'enter': None,  # No new entry orders
                    'stop_loss': 95.0,  # Update stop loss
                    'take_profit': 115.0  # Update take profit
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_modify_deal_i7_2_enter_none")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 2, f"Expected 2 bars, got {len(collected_data)}"
        
        # Check buy_sltp result on bar 0
        assert collected_data[0]['method_result'] is not None
        buy_result = collected_data[0]['method_result']
        assert isinstance(buy_result, OrderOperationResult)
        assert len(buy_result.error_messages) == 0, f"Should not have errors, got: {buy_result.error_messages}"
        assert buy_result.deal_id > 0
        
        # Check modify_deal result on bar 1
        assert collected_data[1]['method_result'] is not None
        modify_result = collected_data[1]['method_result']
        assert isinstance(modify_result, OrderOperationResult)
        assert len(modify_result.error_messages) == 0, f"Should not have errors, got: {modify_result.error_messages}"
        assert modify_result.deal_id == deal_id, "Should return the same deal_id"
        
        # Verify no new entry orders
        entry_orders = [o for o in modify_result.orders if o.order_type == OrderType.MARKET or 
                       (o.order_type == OrderType.LIMIT and o.side == OrderSide.BUY)]
        assert len(entry_orders) == 0, "Should not have any new entry orders"
        
        # Verify only exit orders are updated
        exit_orders = [o for o in modify_result.orders if o.side == OrderSide.SELL]
        assert len(exit_orders) == 2, "Should have two exit orders (stop loss + take profit)"
        
        # Check that stop loss order is updated
        stop_orders = [o for o in exit_orders if o.order_type == OrderType.STOP]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        assert stop_orders[0].trigger_price == 95.0, "Stop loss trigger price should be updated to 95.0"
        
        # Check that take profit order is updated
        take_orders = [o for o in exit_orders if o.order_type == OrderType.LIMIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        assert take_orders[0].price == 115.0, "Take profit price should be updated to 115.0"
        
        # Verify deal exists and was closed after backtesting (close_deals is called at the end)
        deal = broker.get_deal_by_id(deal_id)
        assert deal is not None, "Deal should exist"
        # After broker.run() completes, all open deals are closed, so quantity should be 0
        assert deal.quantity == 0.0, f"Deal should be closed after backtesting (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be marked as closed after backtesting"


# ============================================================================
# Group I8: No Order Execution
# ============================================================================

class TestNoOrderExecution:
    """Test I8: Scenarios where deal is opened but no orders are executed."""
    
    def test_buy_sltp_no_orders_executed(self, test_task):
        """Test I8.1: BUY - Deal opened with limit entries, stops, and takes, but no orders execute."""
        # Prepare quotes data: price 100.0, stays stable, never triggers any orders
        # Entries: 95.0, 90.0 (below current 100.0)
        # Stop: 85.0 (below entries)
        # Take: 110.0 (above current)
        # Price stays at 100.0, never reaches entry levels, stop, or take
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 99.0, 99.0],  # Never drops below 99.0 (entries at 95.0, 90.0 won't trigger)
            highs=[101.0, 101.0, 101.0]  # Never rises above 101.0 (take at 110.0 won't trigger)
        )
        
        # Protocol: On bar 0, enter BUY with limit entries, stop, and take
        # Expected: deal is created, orders are placed, but none execute
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.5, 95.0), (0.5, 90.0)],  # Two limit entries (both below 100.0)
                    'stop_loss': 85.0,  # Stop below entries
                    'take_profit': 110.0  # Take above current price
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_i8_1_no_orders_executed")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that no trades occurred (no orders executed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 0, "No execution on bar 1"
        assert collected_data[2]['trades_count'] == 0, "No execution on bar 2"
        
        # Check total trades count: should be 0 (no orders executed)
        assert len(broker.trades) == 0, f"Expected 0 trades (no orders executed), got {len(broker.trades)}"
        
        # Check final state: deal should exist but be closed by autoclosure at the end
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        # After broker.run() completes, all open deals are closed, so quantity should be 0
        assert deal.quantity == 0.0, f"Deal should be closed after backtesting (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be marked as closed after backtesting"
        
        # Check that entry orders were placed but not executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 2, "Should have two entry orders"
        # After autoclosure, entry orders should be canceled
        canceled_entries = [o for o in entry_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_entries) == 2, "Entry orders should be canceled after autoclosure"
        
        # Check that stop loss order was placed but not executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled after autoclosure"
        
        # Check that take profit order was placed but not executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled after autoclosure"
    
    def test_sell_sltp_no_orders_executed(self, test_task):
        """Test I8.2: SELL - Deal opened with limit entries, stops, and takes, but no orders execute."""
        # Prepare quotes data: price 100.0, stays stable, never triggers any orders
        # Entries: 105.0, 110.0 (above current 100.0)
        # Stop: 115.0 (above entries)
        # Take: 90.0 (below current)
        # Price stays at 100.0, never reaches entry levels, stop, or take
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 101.0, 101.0],  # Never rises above 101.0 (entries at 105.0, 110.0 won't trigger)
            lows=[99.0, 99.0, 99.0]  # Never drops below 99.0 (take at 90.0 won't trigger)
        )
        
        # Protocol: On bar 0, enter SELL with limit entries, stop, and take
        # Expected: deal is created, orders are placed, but none execute
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.5, 105.0), (0.5, 110.0)],  # Two limit entries (both above 100.0)
                    'stop_loss': 115.0,  # Stop above entries
                    'take_profit': 90.0  # Take below current price
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_i8_2_no_orders_executed")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that no trades occurred (no orders executed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 0, "No execution on bar 1"
        assert collected_data[2]['trades_count'] == 0, "No execution on bar 2"
        
        # Check total trades count: should be 0 (no orders executed)
        assert len(broker.trades) == 0, f"Expected 0 trades (no orders executed), got {len(broker.trades)}"
        
        # Check final state: deal should exist but be closed by autoclosure at the end
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        # After broker.run() completes, all open deals are closed, so quantity should be 0
        assert deal.quantity == 0.0, f"Deal should be closed after backtesting (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be marked as closed after backtesting"
        
        # Check that entry orders were placed but not executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 2, "Should have two entry orders"
        # After autoclosure, entry orders should be canceled
        canceled_entries = [o for o in entry_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_entries) == 2, "Entry orders should be canceled after autoclosure"
        
        # Check that stop loss order was placed but not executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled after autoclosure"
        
        # Check that take profit order was placed but not executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled after autoclosure"

