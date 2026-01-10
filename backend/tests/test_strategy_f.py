"""
Tests for Strategy class - buy_sltp/sell_sltp methods - Group F.

Group F: Validation and Errors Tests
Tests validation logic for buy_sltp and sell_sltp methods.
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
# Group F1: Price Validation
# ============================================================================

class TestBuySltpPriceValidation:
    """Test F1: Price validation scenarios for buy_sltp."""
    
    def test_buy_sltp_stop_loss_above_current_price(self, test_task):
        """Test F1.1: BUY stop loss above current price → validation error."""
        # Current price: 100.0
        # Stop loss: 110.0 (above current price - invalid for BUY)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': 110.0,  # Stop at 110.0 (above current 100.0 - invalid)
                    'take_profit': 120.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f1_1_stop_loss_above_current_price")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop loss" in msg.lower() and "above" in msg.lower() for msg in method_result.error_messages), \
            f"Should have error about stop loss above current price, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_buy_sltp_take_profit_below_current_price(self, test_task):
        """Test F1.2: BUY take profit below current price → validation error."""
        # Current price: 100.0
        # Take profit: 90.0 (below current price - invalid for BUY)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': 80.0,  # Valid stop
                    'take_profit': 90.0  # Take at 90.0 (below current 100.0 - invalid)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f1_2_take_profit_below_current_price")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("take profit" in msg.lower() and "below" in msg.lower() for msg in method_result.error_messages), \
            f"Should have error about take profit below current price, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_buy_sltp_limit_entry_above_current_price(self, test_task):
        """Test F1.5: BUY limit entry above current price → validation error."""
        # Current price: 100.0
        # Limit entry: 110.0 (above current price - invalid for BUY)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 110.0),  # Limit entry at 110.0 (above current 100.0 - invalid)
                    'stop_loss': 90.0,
                    'take_profit': 120.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f1_5_limit_entry_above_current_price")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("limit" in msg.lower() and ("above" in msg.lower() or "current" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about limit entry above current price, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"


class TestSellSltpPriceValidation:
    """Test F1: Price validation scenarios for sell_sltp."""
    
    def test_sell_sltp_stop_loss_below_current_price(self, test_task):
        """Test F1.3: SELL stop loss below current price → validation error."""
        # Current price: 100.0
        # Stop loss: 90.0 (below current price - invalid for SELL)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': 90.0,  # Stop at 90.0 (below current 100.0 - invalid)
                    'take_profit': 80.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f1_3_stop_loss_below_current_price")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop loss" in msg.lower() and "below" in msg.lower() for msg in method_result.error_messages), \
            f"Should have error about stop loss below current price, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_sell_sltp_take_profit_above_current_price(self, test_task):
        """Test F1.4: SELL take profit above current price → validation error."""
        # Current price: 100.0
        # Take profit: 110.0 (above current price - invalid for SELL)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': 120.0,  # Valid stop
                    'take_profit': 110.0  # Take at 110.0 (above current 100.0 - invalid)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f1_4_take_profit_above_current_price")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("take profit" in msg.lower() and "above" in msg.lower() for msg in method_result.error_messages), \
            f"Should have error about take profit above current price, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_sell_sltp_limit_entry_below_current_price(self, test_task):
        """Test F1.6: SELL limit entry below current price → validation error."""
        # Current price: 100.0
        # Limit entry: 90.0 (below current price - invalid for SELL)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 90.0),  # Limit entry at 90.0 (below current 100.0 - invalid)
                    'stop_loss': 110.0,
                    'take_profit': 80.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f1_6_limit_entry_below_current_price")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("limit" in msg.lower() and ("below" in msg.lower() or "current" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about limit entry below current price, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"


# ============================================================================
# Group F2: Entry Limit Protection by Stop Loss
# ============================================================================

class TestBuySltpEntryLimitProtection:
    """Test F2: Entry limit protection by stop loss scenarios for buy_sltp."""
    
    def test_buy_sltp_single_limit_entry_below_min_stop(self, test_task):
        """Test F2.1: BUY single limit entry below minimum stop price → validation error (entry not protected)."""
        # Current price: 100.0
        # Limit entry: 95.0
        # Stop loss: 90.0 (minimum stop)
        # Entry at 95.0 is NOT protected by stop at 90.0 (entry should be above stop for BUY)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit entry at 95.0
                    'stop_loss': 90.0,  # Stop at 90.0 (entry 95.0 is NOT protected - should be above stop)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f2_1_single_limit_entry_below_min_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop loss" in msg.lower() and ("below" in msg.lower() or "protect" in msg.lower() or "minimum" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about entry not protected by stop loss, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_buy_sltp_multiple_limits_one_entry_below_min_stop(self, test_task):
        """Test F2.3: BUY multiple limit entries, one entry below minimum stop price → validation error."""
        # Current price: 100.0
        # Limit entries: 97.0, 95.0, 93.0
        # Stop loss: 90.0 (minimum stop)
        # Entry at 93.0 is NOT protected by stop at 90.0 (entry should be above stop for BUY)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.33, 97.0), (0.33, 95.0), (0.34, 93.0)],  # Three limit entries
                    'stop_loss': 90.0,  # Stop at 90.0 (entry 93.0 is NOT protected)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f2_3_multiple_limits_one_entry_below_min_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop loss" in msg.lower() and ("below" in msg.lower() or "protect" in msg.lower() or "minimum" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about entry not protected by stop loss, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_buy_sltp_limit_entry_equal_to_min_stop(self, test_task):
        """Test F2.5: BUY limit entry equal to minimum stop price → validation error (entry not protected, stop must be strictly below)."""
        # Current price: 100.0
        # Limit entry: 90.0
        # Stop loss: 90.0 (equal to entry - invalid, stop must be strictly below)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 90.0),  # Limit entry at 90.0
                    'stop_loss': 90.0,  # Stop at 90.0 (equal to entry - invalid, must be strictly below)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f2_5_limit_entry_equal_to_min_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop loss" in msg.lower() and ("below" in msg.lower() or "protect" in msg.lower() or "strictly" in msg.lower() or "minimum" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about entry not protected by stop loss (stop must be strictly below), got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"


class TestSellSltpEntryLimitProtection:
    """Test F2: Entry limit protection by stop loss scenarios for sell_sltp."""
    
    def test_sell_sltp_single_limit_entry_above_max_stop(self, test_task):
        """Test F2.2: SELL single limit entry above maximum stop price → validation error (entry not protected)."""
        # Current price: 100.0
        # Limit entry: 105.0
        # Stop loss: 110.0 (maximum stop)
        # Entry at 105.0 is NOT protected by stop at 110.0 (entry should be below stop for SELL)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 105.0),  # Limit entry at 105.0
                    'stop_loss': 110.0,  # Stop at 110.0 (entry 105.0 is NOT protected - should be below stop)
                    'take_profit': 90.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f2_2_single_limit_entry_above_max_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop loss" in msg.lower() and ("above" in msg.lower() or "protect" in msg.lower() or "maximum" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about entry not protected by stop loss, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_sell_sltp_multiple_limits_one_entry_above_max_stop(self, test_task):
        """Test F2.4: SELL multiple limit entries, one entry above maximum stop price → validation error."""
        # Current price: 100.0
        # Limit entries: 103.0, 105.0, 107.0
        # Stop loss: 110.0 (maximum stop)
        # Entry at 107.0 is NOT protected by stop at 110.0 (entry should be below stop for SELL)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.33, 103.0), (0.33, 105.0), (0.34, 107.0)],  # Three limit entries
                    'stop_loss': 110.0,  # Stop at 110.0 (entry 107.0 is NOT protected)
                    'take_profit': 90.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f2_4_multiple_limits_one_entry_above_max_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop loss" in msg.lower() and ("above" in msg.lower() or "protect" in msg.lower() or "maximum" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about entry not protected by stop loss, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_sell_sltp_limit_entry_equal_to_max_stop(self, test_task):
        """Test F2.6: SELL limit entry equal to maximum stop price → validation error (entry not protected, stop must be strictly above)."""
        # Current price: 100.0
        # Limit entry: 110.0
        # Stop loss: 110.0 (equal to entry - invalid, stop must be strictly above)
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': (1.0, 110.0),  # Limit entry at 110.0
                    'stop_loss': 110.0,  # Stop at 110.0 (equal to entry - invalid, must be strictly above)
                    'take_profit': 90.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f2_6_limit_entry_equal_to_max_stop")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop loss" in msg.lower() and ("above" in msg.lower() or "protect" in msg.lower() or "strictly" in msg.lower() or "maximum" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about entry not protected by stop loss (stop must be strictly above), got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"


# ============================================================================
# Group F3: Structure Validation
# ============================================================================

class TestBuySltpStructureValidation:
    """Test F3: Structure validation scenarios for buy_sltp."""
    
    def test_buy_sltp_stop_shares_sum_not_one(self, test_task):
        """Test F3.1: Sum of stop shares != 1.0 → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': [(0.5, 90.0), (0.4, 88.0)],  # Sum = 0.9 (should be 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f3_1_stop_shares_sum_not_one")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop" in msg.lower() and ("sum" in msg.lower() or "share" in msg.lower() or "1.0" in msg) for msg in method_result.error_messages), \
            f"Should have error about stop shares sum not equal to 1.0, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_buy_sltp_take_shares_sum_not_one(self, test_task):
        """Test F3.2: Sum of take profit shares != 1.0 → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': 90.0,
                    'take_profit': [(0.5, 110.0), (0.4, 112.0)]  # Sum = 0.9 (should be 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f3_2_take_shares_sum_not_one")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("take" in msg.lower() and ("sum" in msg.lower() or "share" in msg.lower() or "1.0" in msg) for msg in method_result.error_messages), \
            f"Should have error about take profit shares sum not equal to 1.0, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_buy_sltp_entry_shares_sum_not_one(self, test_task):
        """Test F3.3: Sum of entry order shares != 1.0 → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(0.5, 95.0), (0.4, 93.0)],  # Sum = 0.9 (should be 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f3_3_entry_shares_sum_not_one")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("enter" in msg.lower() or "entry" in msg.lower() and ("sum" in msg.lower() or "share" in msg.lower() or "1.0" in msg) for msg in method_result.error_messages), \
            f"Should have error about entry shares sum not equal to 1.0, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_buy_sltp_negative_shares(self, test_task):
        """Test F3.4: Negative shares → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': [(-0.5, 90.0), (1.5, 88.0)],  # Negative share -0.5
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f3_4_negative_shares")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("negative" in msg.lower() or "share" in msg.lower() and "0" in msg for msg in method_result.error_messages), \
            f"Should have error about negative shares, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_buy_sltp_shares_greater_than_one(self, test_task):
        """Test F3.5: Shares > 1.0 → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': [(0.5, 90.0), (0.6, 88.0)],  # Sum = 1.1 (> 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_f3_5_shares_greater_than_one")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop" in msg.lower() and ("sum" in msg.lower() or "share" in msg.lower() or "1.0" in msg or "greater" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about shares sum greater than 1.0, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"


class TestSellSltpStructureValidation:
    """Test F3: Structure validation scenarios for sell_sltp."""
    
    def test_sell_sltp_stop_shares_sum_not_one(self, test_task):
        """Test F3.1: Sum of stop shares != 1.0 → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': [(0.5, 110.0), (0.4, 112.0)],  # Sum = 0.9 (should be 1.0)
                    'take_profit': 90.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f3_1_stop_shares_sum_not_one")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop" in msg.lower() and ("sum" in msg.lower() or "share" in msg.lower() or "1.0" in msg) for msg in method_result.error_messages), \
            f"Should have error about stop shares sum not equal to 1.0, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_sell_sltp_take_shares_sum_not_one(self, test_task):
        """Test F3.2: Sum of take profit shares != 1.0 → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            lows=[99.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': 110.0,
                    'take_profit': [(0.5, 90.0), (0.4, 88.0)]  # Sum = 0.9 (should be 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f3_2_take_shares_sum_not_one")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("take" in msg.lower() and ("sum" in msg.lower() or "share" in msg.lower() or "1.0" in msg) for msg in method_result.error_messages), \
            f"Should have error about take profit shares sum not equal to 1.0, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_sell_sltp_entry_shares_sum_not_one(self, test_task):
        """Test F3.3: Sum of entry order shares != 1.0 → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(0.5, 105.0), (0.4, 107.0)],  # Sum = 0.9 (should be 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f3_3_entry_shares_sum_not_one")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("enter" in msg.lower() or "entry" in msg.lower() and ("sum" in msg.lower() or "share" in msg.lower() or "1.0" in msg) for msg in method_result.error_messages), \
            f"Should have error about entry shares sum not equal to 1.0, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_sell_sltp_negative_shares(self, test_task):
        """Test F3.4: Negative shares → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': [(-0.5, 110.0), (1.5, 112.0)],  # Negative share -0.5
                    'take_profit': 90.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f3_4_negative_shares")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("negative" in msg.lower() or "share" in msg.lower() and "0" in msg for msg in method_result.error_messages), \
            f"Should have error about negative shares, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
    
    def test_sell_sltp_shares_greater_than_one(self, test_task):
        """Test F3.5: Shares > 1.0 → validation error."""
        quotes_data = create_custom_quotes_data(
            prices=[100.0],
            highs=[101.0]
        )
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': 1.0,  # Market entry
                    'stop_loss': [(0.5, 110.0), (0.6, 112.0)],  # Sum = 1.1 (> 1.0)
                    'take_profit': 90.0
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_f3_5_shares_greater_than_one")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 1, f"Expected 1 bar, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        
        # Should have validation errors
        assert len(method_result.error_messages) > 0, "Should have validation errors"
        assert any("stop" in msg.lower() and ("sum" in msg.lower() or "share" in msg.lower() or "1.0" in msg or "greater" in msg.lower()) for msg in method_result.error_messages), \
            f"Should have error about shares sum greater than 1.0, got: {method_result.error_messages}"
        
        # Should not create orders or deal
        assert len(method_result.orders) == 0, "Should not create any orders"
        assert method_result.deal_id == 0, "Should not create deal (deal_id should be 0)"
        assert method_result.volume == 0.0, "Should have zero volume"
