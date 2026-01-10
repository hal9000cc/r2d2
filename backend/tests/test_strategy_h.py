"""
Tests for Strategy class - buy_sltp/sell_sltp methods - Group H.

Group H: Interleaved Entry and Exit Orders
Tests scenarios where exit orders (stops or take profits) are positioned between entry orders,
creating an interleaved structure. This tests the protection logic and execution order when
exit orders are not simply above/below all entries.
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
# Group H: Interleaved Entry and Exit Orders
# ============================================================================

class TestBuySltpInterleavedStopsBetweenEntries:
    """Test H1: Interleaved stops between entries for buy_sltp."""
    
    def test_buy_sltp_stops_between_entries_alternating_single(self, test_task):
        """Test H1.1: BUY - Multiple limit entries with stops between them (alternating pattern: entry, stop, entry, stop, entry)."""
        # Prepare quotes data: price 100.0, then drops to trigger entries and stops
        # Entries: 98.0, 95.0, 92.0 (all below current price 100.0)
        # Stops: 96.5 (between 98 and 95), 93.5 (between 95 and 92), 90.0 (below 92 for protection)
        # Bar 1: low=89.0 triggers all entries and stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 89.0, 99.0]  # Bar 1 low=89.0 triggers all entries (98.0, 95.0, 92.0) and all stops (96.5, 93.5, 90.0)
        )
        
        # Protocol: On bar 0, enter BUY with alternating entries and stops
        # Entry prices: 98.0, 95.0, 92.0 (all below current price 100.0)
        # Stop prices: 96.5, 93.5, 90.0 (90.0 is below min entry 92.0 for protection)
        # Expected: all entries and stops trigger on bar 1 simultaneously
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 98.0), (1.0, 95.0), (1.0, 92.0)],  # Three entries (all below 100.0)
                    'stop_loss': [(0.33, 96.5), (0.33, 93.5), (0.34, 90.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_h1_1_stops_between_entries")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that all entries and stops trigger on bar 1 (stops have priority, so all stops trigger, deal closes)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0 (limit entries)"
        assert collected_data[1]['trades_count'] == 6, "All entries (3) and all stops (3) should trigger - 6 trades total"
        assert collected_data[2]['trades_count'] == 6, "No execution on bar 2"
        
        # Check total trades count: 3 entries + 3 stops
        assert len(broker.trades) == 6, f"Expected 6 trades total (3 entries + 3 stops), got {len(broker.trades)}"
        
        # Check final state: deal should be closed (all stops triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        
        # Check that all entry orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 3, "Should have three entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 3, "All entry orders should be executed"
        
        # Check that all stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All stop loss orders should be executed"
        
        # Check that take profit order was canceled (deal closed by stops)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled"


class TestSellSltpInterleavedStopsBetweenEntries:
    """Test H1: Interleaved stops between entries for sell_sltp."""
    
    def test_sell_sltp_stops_between_entries_alternating_single(self, test_task):
        """Test H1.2: SELL - Multiple limit entries with stops between them (alternating pattern: entry, stop, entry, stop, entry)."""
        # Prepare quotes data: price 100.0, then rises to trigger entries and stops
        # Entries: 102.0, 105.0, 108.0 (all above current price 100.0)
        # Stops: 103.5 (between 102 and 105), 106.5 (between 105 and 108), 110.0 (above 108 for protection)
        # Bar 1: high=111.0 triggers all entries and stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 111.0, 101.0]  # Bar 1 high=111.0 triggers all entries (102.0, 105.0, 108.0) and all stops (103.5, 106.5, 110.0)
        )
        
        # Protocol: On bar 0, enter SELL with alternating entries and stops
        # Entry prices: 102.0, 105.0, 108.0 (all above current price 100.0)
        # Stop prices: 103.5, 106.5, 110.0 (110.0 is above max entry 108.0 for protection)
        # Expected: all entries and stops trigger on bar 1 simultaneously
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 102.0), (1.0, 105.0), (1.0, 108.0)],  # Three entries (all above 100.0)
                    'stop_loss': [(0.33, 103.5), (0.33, 106.5), (0.34, 110.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_h1_2_stops_between_entries")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that all entries and stops trigger on bar 1 (stops have priority, so all stops trigger, deal closes)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0 (limit entries)"
        assert collected_data[1]['trades_count'] == 6, "All entries (3) and all stops (3) should trigger - 6 trades total"
        assert collected_data[2]['trades_count'] == 6, "No execution on bar 2"
        
        # Check total trades count: 3 entries + 3 stops
        assert len(broker.trades) == 6, f"Expected 6 trades total (3 entries + 3 stops), got {len(broker.trades)}"
        
        # Check final state: deal should be closed (all stops triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        
        # Check that all entry orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 3, "Should have three entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 3, "All entry orders should be executed"
        
        # Check that all stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All stop loss orders should be executed"
        
        # Check that take profit order was canceled (deal closed by stops)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled"


class TestBuySltpInterleavedStopsBetweenEntriesMultiple:
    """Test H2: Interleaved multiple stops between entries for buy_sltp."""
    
    def test_buy_sltp_stops_between_entries_alternating_multiple(self, test_task):
        """Test H2.1: BUY - Multiple limit entries with multiple stops between them (alternating pattern: 2 entries, 2 stops, 2 entries, 2 stops)."""
        # Prepare quotes data: price 100.0, then drops to trigger entries and stops
        # Entries: 98.0, 96.0, 92.0, 90.0 (2 entries, then 2 entries)
        # Stops: 97.0, 94.0, 88.0 (between entries, last one below min entry 90.0 for protection)
        # Bar 1: low=87.0 triggers all entries and stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 87.0, 99.0]  # Bar 1 low=87.0 triggers all entries (98.0, 96.0, 92.0, 90.0) and all stops (97.0, 94.0, 88.0)
        )
        
        # Protocol: On bar 0, enter BUY with alternating multiple entries and stops
        # Entry prices: 98.0, 96.0, 92.0, 90.0 (all below current price 100.0)
        # Stop prices: 97.0, 94.0, 88.0 (88.0 is below min entry 90.0 for protection)
        # Pattern: 2 entries (98.0, 96.0), 2 stops (97.0, 94.0), 2 entries (92.0, 90.0), 1 stop (88.0)
        # Expected: all entries and stops trigger on bar 1 simultaneously
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 98.0), (1.0, 96.0), (1.0, 92.0), (1.0, 90.0)],  # Four entries (2+2 pattern)
                    'stop_loss': [(0.25, 97.0), (0.25, 94.0), (0.5, 88.0)],  # Three stops (0.25 + 0.25 + 0.5 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_h2_1_stops_between_entries_multiple")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that all entries and stops trigger on bar 1 (stops have priority, so all stops trigger, deal closes)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0 (limit entries)"
        assert collected_data[1]['trades_count'] == 7, "All entries (4) and all stops (3) should trigger - 7 trades total"
        assert collected_data[2]['trades_count'] == 7, "No execution on bar 2"
        
        # Check total trades count: 4 entries + 3 stops
        assert len(broker.trades) == 7, f"Expected 7 trades total (4 entries + 3 stops), got {len(broker.trades)}"
        
        # Check final state: deal should be closed (all stops triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        
        # Check that all entry orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 4, "Should have four entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 4, "All entry orders should be executed"
        
        # Check that all stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All stop loss orders should be executed"
        
        # Check that take profit order was canceled (deal closed by stops)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled"


class TestSellSltpInterleavedStopsBetweenEntriesMultiple:
    """Test H2: Interleaved multiple stops between entries for sell_sltp."""
    
    def test_sell_sltp_stops_between_entries_alternating_multiple(self, test_task):
        """Test H2.2: SELL - Multiple limit entries with multiple stops between them (alternating pattern: 2 entries, 2 stops, 2 entries, 2 stops)."""
        # Prepare quotes data: price 100.0, then rises to trigger entries and stops
        # Entries: 102.0, 104.0, 108.0, 110.0 (2 entries, then 2 entries)
        # Stops: 103.0, 106.0, 112.0 (between entries, last one above max entry 110.0 for protection)
        # Bar 1: high=113.0 triggers all entries and stops
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 113.0, 101.0]  # Bar 1 high=113.0 triggers all entries (102.0, 104.0, 108.0, 110.0) and all stops (103.0, 106.0, 112.0)
        )
        
        # Protocol: On bar 0, enter SELL with alternating multiple entries and stops
        # Entry prices: 102.0, 104.0, 108.0, 110.0 (all above current price 100.0)
        # Stop prices: 103.0, 106.0, 112.0 (112.0 is above max entry 110.0 for protection)
        # Pattern: 2 entries (102.0, 104.0), 2 stops (103.0, 106.0), 2 entries (108.0, 110.0), 1 stop (112.0)
        # Expected: all entries and stops trigger on bar 1 simultaneously
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 102.0), (1.0, 104.0), (1.0, 108.0), (1.0, 110.0)],  # Four entries (2+2 pattern)
                    'stop_loss': [(0.25, 103.0), (0.25, 106.0), (0.5, 112.0)],  # Three stops (0.25 + 0.25 + 0.5 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_h2_2_stops_between_entries_multiple")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that all entries and stops trigger on bar 1 (stops have priority, so all stops trigger, deal closes)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0 (limit entries)"
        assert collected_data[1]['trades_count'] == 7, "All entries (4) and all stops (3) should trigger - 7 trades total"
        assert collected_data[2]['trades_count'] == 7, "No execution on bar 2"
        
        # Check total trades count: 4 entries + 3 stops
        assert len(broker.trades) == 7, f"Expected 7 trades total (4 entries + 3 stops), got {len(broker.trades)}"
        
        # Check final state: deal should be closed (all stops triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        
        # Check that all entry orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 4, "Should have four entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 4, "All entry orders should be executed"
        
        # Check that all stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All stop loss orders should be executed"
        
        # Check that take profit order was canceled (deal closed by stops)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled"



class TestBuySltpInterleavedTakesBetweenEntries:
    """Test H3: Interleaved take profits between entries for buy_sltp."""
    
    def test_buy_sltp_takes_between_entries_alternating_single(self, test_task):
        """Test H3.1: BUY - Multiple limit entries with take profits between them (alternating pattern: entry, take, entry, take, entry)."""
        # Prepare quotes data: price 100.0, then drops to trigger entries, then rises to trigger takes
        # Entries: 98.0, 95.0, 92.0 (all below current price 100.0)
        # Takes: 101.0, 104.0, 107.0 (all above current price 100.0, above corresponding entries)
        # Stop: 90.0 (below min entry 92.0 for protection)
        # Bar 1: low=91.0 triggers all entries (98.0, 95.0, 92.0) but NOT stop (90.0) because low=91.0 > 90.0
        # Bar 2: high=108.0 triggers all takes (101.0, 104.0, 107.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            lows=[99.0, 91.0, 99.0],  # Bar 1 low=91.0 triggers all entries (98.0, 95.0, 92.0) but NOT stop 90.0
            highs=[101.0, 101.0, 108.0]  # Bar 2 high=108.0 triggers all takes (101.0, 104.0, 107.0)
        )
        
        # Protocol: On bar 0, enter BUY with alternating entries and takes
        # Entry prices: 98.0, 95.0, 92.0 (all below current price 100.0)
        # Take prices: 101.0, 104.0, 107.0 (all above current price 100.0, above corresponding entries)
        # Stop price: 90.0 (below min entry 92.0 for protection)
        # Expected: entries trigger on bar 1, takes trigger on bar 2
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 98.0), (1.0, 95.0), (1.0, 92.0)],  # Three entries (all below 100.0)
                    'stop_loss': 90.0,  # Single stop below min entry for protection
                    'take_profit': [(0.33, 101.0), (0.33, 104.0), (0.34, 107.0)]  # Three takes (0.33 + 0.33 + 0.34 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_h3_1_takes_between_entries")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entries trigger on bar 1, takes trigger on bar 2
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0 (limit entries)"
        assert collected_data[1]['trades_count'] == 3, "All entries (3) should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 6, "All takes (3) should trigger on bar 2 - 6 trades total"
        
        # Check total trades count: 3 entries + 3 takes
        assert len(broker.trades) == 6, f"Expected 6 trades total (3 entries + 3 takes), got {len(broker.trades)}"
        
        # Check final state: deal should be closed (all takes triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        
        # Check that all entry orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 3, "Should have three entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 3, "All entry orders should be executed"
        
        # Check that all take profit orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 3, "All take profit orders should be executed"
        
        # Check that stop loss order was canceled (deal closed by takes)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled"


class TestSellSltpInterleavedTakesBetweenEntries:
    """Test H3: Interleaved take profits between entries for sell_sltp."""
    
    def test_sell_sltp_takes_between_entries_alternating_single(self, test_task):
        """Test H3.2: SELL - Multiple limit entries with take profits between them (alternating pattern: entry, take, entry, take, entry)."""
        # Prepare quotes data: price 100.0, then rises to trigger entries, then drops to trigger takes
        # Entries: 102.0, 105.0, 108.0 (all above current price 100.0)
        # Takes: 99.0, 96.0, 93.0 (all below current price 100.0, below corresponding entries)
        # Stop: 110.0 (above max entry 108.0 for protection)
        # Bar 1: high=109.0 triggers all entries (102.0, 105.0, 108.0) but NOT stop (110.0) because high=109.0 < 110.0
        # Bar 2: low=92.0 triggers all takes (99.0, 96.0, 93.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 109.0, 101.0],  # Bar 1 high=109.0 triggers all entries (102.0, 105.0, 108.0) but NOT stop 110.0
            lows=[99.0, 99.0, 92.0]  # Bar 2 low=92.0 triggers all takes (99.0, 96.0, 93.0)
        )
        
        # Protocol: On bar 0, enter SELL with alternating entries and takes
        # Entry prices: 102.0, 105.0, 108.0 (all above current price 100.0)
        # Take prices: 99.0, 96.0, 93.0 (all below current price 100.0, below corresponding entries)
        # Stop price: 110.0 (above max entry 108.0 for protection)
        # Expected: entries trigger on bar 1, takes trigger on bar 2
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 102.0), (1.0, 105.0), (1.0, 108.0)],  # Three entries (all above 100.0)
                    'stop_loss': 110.0,  # Single stop above max entry for protection
                    'take_profit': [(0.33, 99.0), (0.33, 96.0), (0.34, 93.0)]  # Three takes (0.33 + 0.33 + 0.34 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_h3_2_takes_between_entries")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entries trigger on bar 1, takes trigger on bar 2
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0 (limit entries)"
        assert collected_data[1]['trades_count'] == 3, "All entries (3) should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 6, "All takes (3) should trigger on bar 2 - 6 trades total"
        
        # Check total trades count: 3 entries + 3 takes
        assert len(broker.trades) == 6, f"Expected 6 trades total (3 entries + 3 takes), got {len(broker.trades)}"
        
        # Check final state: deal should be closed (all takes triggered)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0.0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        
        # Check that all entry orders were executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE]
        assert len(entry_orders) == 3, "Should have three entry orders"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 3, "All entry orders should be executed"
        
        # Check that all take profit orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 3, "All take profit orders should be executed"
        
        # Check that stop loss order was canceled (deal closed by takes)
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        canceled_stops = [o for o in stop_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_stops) == 1, "Stop loss order should be canceled"
