"""
Tests for Strategy class - buy_sltp/sell_sltp methods - Group E.

Group E: Order Execution - Most Complex Cases (Entries + Stops + Takes Simultaneously)
Tests scenarios where entry orders, stop loss orders, and take profit orders trigger:
- E1: One entry, one stop, one take profit
- E2: One entry, multiple stops, one take profit
- E3: One entry, one stop, multiple take profits
- E4: One entry, multiple stops, multiple take profits
- E5: Multiple entries, stops, take profits

IMPORTANT RULES for simultaneous order execution:
1. When price hits both stops and take profits simultaneously, ONLY STOPS are considered
2. Take profits do NOT trigger on the same bar as stops
3. Take profits may trigger on subsequent bars if the deal is not fully closed
4. After placing all orders: entry and stop are ACTIVE, take is NEW (not active)
5. Take profit activates only after entry executes
6. On the same bar, entry and stop can trigger simultaneously
7. Take profit CANNOT trigger on the same bar as entry - it activates only after entry executes
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
# Group E1: One Entry, One Stop, One Take Profit - BUY
# ============================================================================

class TestBuySltpOneEntryOneStopOneTake:
    """Test E1: One entry, one stop, one take profit scenarios for buy_sltp."""
    
    def test_buy_sltp_limit_entry_stop_take_simultaneous_stop_priority(self, test_task):
        """Test E1.1: Limit entry, stop and take profit hit simultaneously → entry + stop trigger, take profit does NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, stop, and take profit simultaneously
        # Bar 0: high=101.0, low=99.0, limit=95.0, stop=90.0, take=110.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 101.0 < 110.0)
        # Bar 1: high=112.0, low=88.0, limit=95.0, stop=90.0, take=110.0 - entry and stop trigger simultaneously, take does NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 88.0 <= 95.0 ✓
        #   Stop loss (BUY stop, triggers when low <= trigger_price): 88.0 <= 90.0 ✓
        #   Take profit (SELL limit, triggers when high >= price): 112.0 >= 110.0 ✓, but take is NEW, and stops have priority
        # Bar 2: high=112.0, take=110.0 - take profit does NOT trigger (deal already closed by stop)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 112.0, 112.0],  # Bar 1 high=112.0 hits take profit at 110.0, but stops have priority
            lows=[99.0, 88.0, 100.0]  # Bar 1 low=88.0 triggers limit entry at 95.0 and stop at 90.0 simultaneously
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with stop loss 90.0 and take profit 110.0
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop trigger: 90.0 (stop executes as market, with slippage, fee_taker)
        # Expected: limit entry triggers on bar 1, stop triggers on bar 1, take profit does NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volume: 1.0 (closes entire position)
        # Take profit does NOT trigger
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price = 90.0
        stop_quantity = 1.0  # Closes entire position
        take_price = 110.0  # Does NOT trigger
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # Stop executes as market order (with slippage, fee_taker)
        stop_execution = stop_trigger_price - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee = stop_execution * stop_quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = stop_execution * stop_quantity - stop_fee  # 89.9 * 1.0 - 0.0899 = 89.8101
        expected_profit = exit_proceeds - entry_cost  # = 89.8101 - 95.0475 = -5.2374
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': 90.0,
                    'take_profit': [(1.0, 110.0)]  # One take profit
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e1_1_limit_entry_stop_take_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and stop trigger on bar 1, take profit does NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and stop trigger simultaneously (2 trades - entry + stop), take profit does NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 2, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stop
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 2, f"Expected 2 trades total (entry + stop), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that stop order was executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Stop loss order should be executed"
        
        # Check that take profit order was NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "Take profit order should NOT be executed (stops have priority)"
        # Take profit should be CANCELED (deal closed by stop)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stop)"
    
    def test_buy_sltp_limit_entry_stop_take_simultaneous_take_next_bar(self, test_task):
        """Test E1.2: Limit entry, stop and take profit hit simultaneously → entry + stop trigger, take profit triggers on next bar (if deal didn't close completely)."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry and stop simultaneously, but stop only closes part of position
        # Bar 0: high=101.0, low=99.0, limit=95.0, stop=90.0, take=110.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 101.0 < 110.0)
        # Bar 1: high=112.0, low=88.0, limit=95.0, stop=90.0, take=110.0 - entry and stop trigger simultaneously, take does NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 88.0 <= 95.0 ✓
        #   Stop loss (BUY stop, triggers when low <= trigger_price): 88.0 <= 90.0 ✓
        #   Take profit (SELL limit, triggers when high >= price): 112.0 >= 110.0 ✓, but take is NEW, and stops have priority
        # Bar 2: high=112.0, take=110.0 - take profit triggers (112.0 >= 110.0) for remaining position
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 112.0, 112.0],  # Bar 1 high=112.0 hits take profit at 110.0, but stops have priority; Bar 2 high=112.0 triggers take
            lows=[99.0, 88.0, 100.0]  # Bar 1 low=88.0 triggers limit entry at 95.0 and stop at 90.0 simultaneously
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with two stops (0.5 at 90.0, 0.5 at 85.0) and two take profits (0.5 at 110.0, 0.5 at 115.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 (first stop executes as market, with slippage, fee_taker) - closes 0.5; 85.0 does NOT trigger (low=88.0 > 85.0)
        # Take triggers: 110.0 (first take executes as limit, no slippage, fee_maker) - closes remaining 0.5 on bar 2; 115.0 does NOT trigger (high=112.0 < 115.0)
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1 (closes 0.5), first take profit triggers on bar 2 (closes remaining 0.5)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5 (but doesn't trigger)
        # Take volumes: calculated from CURRENT POSITION at the time of take activation/execution, NOT from entry volume
        #   After stop closes 0.5 on bar 1, remaining position is 0.5
        #   On bar 2, take volumes are recalculated from current position (0.5)
        #   First take: round(0.5 * 0.5 / 0.1) * 0.1 = round(2.5) * 0.1 = 2 * 0.1 = 0.2 (banking rounding: round(2.5) = 2)
        #   Second take (extreme): 0.5 - 0.2 = 0.3 (but doesn't trigger)
        #   Remaining position after take: 0.5 - 0.2 = 0.3 (will be auto-closed at end of test)
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price1 = 90.0
        stop_quantity1 = 0.5  # First stop closes half position
        stop_trigger_price2 = 85.0  # Does NOT trigger (low=88.0 > 85.0)
        take_price1 = 110.0
        take_price2 = 115.0  # Does NOT trigger (high=112.0 < 115.0)
        # IMPORTANT: Take profit volumes are calculated from CURRENT POSITION (0.5 after stop), NOT from entry volume (1.0)
        # Fraction: 0.5
        # Current position after stop: 0.5
        # First take: round(0.5 * 0.5 / 0.1) * 0.1 = round(2.5) * 0.1 = 2 * 0.1 = 0.2
        take_quantity1 = 0.2  # round(0.5 * 0.5 / 0.1) * 0.1 = 0.2
        remaining_quantity = 0.3  # 0.5 - 0.2 = 0.3 (will be auto-closed)
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # Stop executes as market order (with slippage, fee_taker)
        stop_execution = stop_trigger_price1 - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee = stop_execution * stop_quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        
        # Take executes as limit order (no slippage, fee_maker)
        take_execution = take_price1  # 110.0 (limit, no slippage)
        # Take fee recalculated with correct volume: 110.0 * 0.2 * 0.0005 = 0.011
        take_fee = take_execution * take_quantity1 * test_task.fee_maker  # 110.0 * 0.2 * 0.0005 = 0.011
        
        # Auto-close: remaining 0.3 position closed at last bar closing price (100.0) as market order (with slippage, fee_taker)
        auto_close_price = 100.0  # Last bar closing price
        # Auto-close is SELL market order (closing BUY position), slippage decreases price
        auto_close_execution = auto_close_price - test_task.slippage_in_steps * test_task.price_step  # 100.0 - 0.1 = 99.9
        auto_close_fee = auto_close_execution * remaining_quantity * test_task.fee_taker  # 99.9 * 0.3 * 0.001 = 0.02997
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = stop_execution * stop_quantity1 - stop_fee + take_execution * take_quantity1 - take_fee + auto_close_execution * remaining_quantity - auto_close_fee  # 89.9*0.5 - 0.04495 + 110.0*0.2 - 0.011 + 99.9*0.3 - 0.02997 = 44.90505 + 21.989 + 29.87003 = 96.76408
        expected_profit = exit_proceeds - entry_cost  # = 96.76408 - 95.0475 = 1.71658
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': [(0.5, 90.0), (0.5, 85.0)],  # Two stops (0.5 + 0.5 = 1.0), only first triggers
                    'take_profit': [(0.5, 110.0), (0.5, 115.0)]  # Two take profits (0.5 + 0.5 = 1.0), only first triggers
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e1_2_limit_entry_stop_take_simultaneous_take_next_bar")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and stop trigger on bar 1, take profit triggers on bar 2
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and stop trigger simultaneously (2 trades - entry + stop), take profit does NOT trigger
        # Bar 2: take profit triggers (3 trades total - entry + stop + take)
        # After bar 2: auto-close of remaining position (4 trades total - entry + stop + take + auto-close)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Take profit should trigger on bar 2"
        
        # Check final state: deal should be closed (auto-closed at end of test)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count (including auto-close)
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + stop + take + auto-close), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that first stop order was executed, second does NOT trigger
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "First stop loss order should be executed"
        active_stops = [o for o in stop_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_stops) == 0, "No stop orders should remain active after deal closes"
        
        # Check that first take profit order was executed (on bar 2), second does NOT trigger
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 1, "First take profit order should be executed on bar 2"
        active_takes = [o for o in take_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_takes) == 0, "No take profit orders should remain active after deal closes"


# ============================================================================
# Group E1: One Entry, One Stop, One Take Profit - SELL
# ============================================================================

class TestSellSltpOneEntryOneStopOneTake:
    """Test E1: One entry, one stop, one take profit scenarios for sell_sltp."""
    
    def test_sell_sltp_limit_entry_stop_take_simultaneous_stop_priority(self, test_task):
        """Test E1.1: Limit entry, stop and take profit hit simultaneously → entry + stop trigger, take profit does NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, stop, and take profit simultaneously
        # Bar 0: high=101.0, low=99.0, limit=105.0, stop=110.0, take=90.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 99.0 > 90.0)
        # Bar 1: high=112.0, low=88.0, limit=105.0, stop=110.0, take=90.0 - entry and stop trigger simultaneously, take does NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 112.0 >= 105.0 ✓
        #   Stop loss (SELL stop, triggers when high >= trigger_price): 112.0 >= 110.0 ✓
        #   Take profit (BUY limit, triggers when low <= price): 88.0 <= 90.0 ✓, but take is NEW, and stops have priority
        # Bar 2: low=88.0, take=90.0 - take profit does NOT trigger (deal already closed by stop)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 112.0, 100.0],  # Bar 1 high=112.0 triggers limit entry at 105.0 and stop at 110.0 simultaneously
            lows=[99.0, 88.0, 100.0]  # Bar 1 low=88.0 hits take profit at 90.0, but stops have priority
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with stop loss 110.0 and take profit 90.0
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop trigger: 110.0 (stop executes as market, with slippage, fee_taker)
        # Expected: limit entry triggers on bar 1, stop triggers on bar 1, take profit does NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volume: 1.0 (closes entire position)
        # Take profit does NOT trigger
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price = 110.0
        stop_quantity = 1.0  # Closes entire position
        take_price = 90.0  # Does NOT trigger
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # Stop executes as market order (with slippage, fee_taker)
        stop_execution = stop_trigger_price + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee = stop_execution * stop_quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = stop_execution * stop_quantity + stop_fee  # 110.1 * 1.0 + 0.1101 = 110.2101
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 110.2101 = -5.2626
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': 110.0,
                    'take_profit': [(1.0, 90.0)]  # One take profit
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e1_1_limit_entry_stop_take_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and stop trigger on bar 1, take profit does NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and stop trigger simultaneously (2 trades - entry + stop), take profit does NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 2, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stop
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 2, f"Expected 2 trades total (entry + stop), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that stop order was executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Stop loss order should be executed"
        
        # Check that take profit order was NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "Take profit order should NOT be executed (stops have priority)"
        # Take profit should be CANCELED (deal closed by stop)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stop)"
    
    def test_sell_sltp_limit_entry_stop_take_simultaneous_take_next_bar(self, test_task):
        """Test E1.2: Limit entry, stop and take profit hit simultaneously → entry + stop trigger, take profit triggers on next bar (if deal didn't close completely)."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry and stop simultaneously, but stop only closes part of position
        # Bar 0: high=101.0, low=99.0, limit=105.0, stop=110.0, take=90.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 99.0 > 90.0)
        # Bar 1: high=112.0, low=88.0, limit=105.0, stop=110.0, take=90.0 - entry and stop trigger simultaneously, take does NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 112.0 >= 105.0 ✓
        #   Stop loss (SELL stop, triggers when high >= trigger_price): 112.0 >= 110.0 ✓
        #   Take profit (BUY limit, triggers when low <= price): 88.0 <= 90.0 ✓, but take is NEW, and stops have priority
        # Bar 2: low=88.0, take=90.0 - take profit triggers (88.0 <= 90.0) for remaining position
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 112.0, 100.0],  # Bar 1 high=112.0 triggers limit entry at 105.0 and stop at 110.0 simultaneously
            lows=[99.0, 88.0, 88.0]  # Bar 1 low=88.0 hits take profit at 90.0, but stops have priority; Bar 2 low=88.0 triggers take
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with two stops (0.5 at 110.0, 0.5 at 115.0) and two take profits (0.5 at 90.0, 0.5 at 85.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 (first stop executes as market, with slippage, fee_taker) - closes 0.5; 115.0 does NOT trigger (high=112.0 < 115.0)
        # Take triggers: 90.0 (first take executes as limit, no slippage, fee_maker) - closes remaining 0.5 on bar 2; 85.0 does NOT trigger (low=88.0 > 85.0)
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1 (closes 0.5), first take profit triggers on bar 2 (closes remaining 0.5)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5 (but doesn't trigger)
        # Take volumes: calculated from CURRENT POSITION at the time of take activation/execution, NOT from entry volume
        #   After stop closes 0.5 on bar 1, remaining position is 0.5 (SELL position, negative quantity: -0.5, but we use abs)
        #   On bar 2, take volumes are recalculated from current position (0.5)
        #   First take: round(0.5 * 0.5 / 0.1) * 0.1 = round(2.5) * 0.1 = 2 * 0.1 = 0.2 (banking rounding: round(2.5) = 2)
        #   Second take (extreme): 0.5 - 0.2 = 0.3 (but doesn't trigger)
        #   Remaining position after take: 0.5 - 0.2 = 0.3 (will be auto-closed at end of test)
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price1 = 110.0
        stop_quantity1 = 0.5  # First stop closes half position
        stop_trigger_price2 = 115.0  # Does NOT trigger (high=112.0 < 115.0)
        take_price1 = 90.0
        take_price2 = 85.0  # Does NOT trigger (low=88.0 > 85.0)
        # IMPORTANT: Take profit volumes are calculated from CURRENT POSITION (0.5 after stop), NOT from entry volume (1.0)
        # Fraction: 0.5
        # Current position after stop: 0.5 (SELL position, but we use abs for calculation)
        # First take: round(0.5 * 0.5 / 0.1) * 0.1 = round(2.5) * 0.1 = 2 * 0.1 = 0.2
        take_quantity1 = 0.2  # round(0.5 * 0.5 / 0.1) * 0.1 = 0.2
        remaining_quantity = 0.3  # 0.5 - 0.2 = 0.3 (will be auto-closed)
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # Stop executes as market order (with slippage, fee_taker)
        stop_execution = stop_trigger_price1 + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee = stop_execution * stop_quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        
        # Take executes as limit order (no slippage, fee_maker)
        take_execution = take_price1  # 90.0 (limit, no slippage)
        # Take fee recalculated with correct volume: 90.0 * 0.2 * 0.0005 = 0.009
        take_fee = take_execution * take_quantity1 * test_task.fee_maker  # 90.0 * 0.2 * 0.0005 = 0.009
        
        # Auto-close: remaining 0.3 position closed at last bar closing price (100.0) as market order (with slippage, fee_taker)
        auto_close_price = 100.0  # Last bar closing price
        # Auto-close is BUY market order (closing SELL position), slippage increases price
        auto_close_execution = auto_close_price + test_task.slippage_in_steps * test_task.price_step  # 100.0 + 0.1 = 100.1
        auto_close_fee = auto_close_execution * remaining_quantity * test_task.fee_taker  # 100.1 * 0.3 * 0.001 = 0.03003
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = stop_execution * stop_quantity1 + stop_fee + take_execution * take_quantity1 + take_fee + auto_close_execution * remaining_quantity + auto_close_fee  # 110.1*0.5 + 0.05505 + 90.0*0.2 + 0.009 + 100.1*0.3 + 0.03003 = 55.05505 + 18.009 + 30.03003 = 103.09408
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 103.09408 = 1.85342
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': [(0.5, 110.0), (0.5, 115.0)],  # Two stops (0.5 + 0.5 = 1.0), only first triggers
                    'take_profit': [(0.5, 90.0), (0.5, 85.0)]  # Two take profits (0.5 + 0.5 = 1.0), only first triggers
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e1_2_limit_entry_stop_take_simultaneous_take_next_bar")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and stop trigger on bar 1, take profit triggers on bar 2
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and stop trigger simultaneously (2 trades - entry + stop), take profit does NOT trigger
        # Bar 2: take profit triggers (3 trades total - entry + stop + take)
        # After bar 2: auto-close of remaining position (4 trades total - entry + stop + take + auto-close)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Take profit should trigger on bar 2"
        
        # Check final state: deal should be closed (auto-closed at end of test)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count (including auto-close)
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + stop + take + auto-close), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that first stop order was executed, second does NOT trigger
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "First stop loss order should be executed"
        active_stops = [o for o in stop_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_stops) == 0, "No stop orders should remain active after deal closes"
        
        # Check that first take profit order was executed (on bar 2), second does NOT trigger
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 1, "First take profit order should be executed on bar 2"
        active_takes = [o for o in take_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_takes) == 0, "No take profit orders should remain active after deal closes"

# ============================================================================
# Group E2: One Entry, Multiple Stops, One Take Profit - BUY
# ============================================================================

class TestBuySltpOneEntryMultipleStopsOneTake:
    """Test E2: One entry, multiple stops, one take profit scenarios for buy_sltp."""
    
    def test_buy_sltp_limit_entry_all_stops_take_simultaneous_stop_priority(self, test_task):
        """Test E2.1: Limit entry, all stops and take profit hit simultaneously → entry + all stops trigger, take profit does NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, all stops, and take profit simultaneously
        # Bar 0: high=101.0, low=99.0, limit=95.0, stops=(90.0, 88.0), take=110.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 99.0 > 88.0, 101.0 < 110.0)
        # Bar 1: high=112.0, low=87.0, limit=95.0, stops=(90.0, 88.0), take=110.0 - entry and all stops trigger simultaneously, take does NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 87.0 <= 95.0 ✓
        #   Stop loss 1 (BUY stop, triggers when low <= trigger_price): 87.0 <= 90.0 ✓
        #   Stop loss 2 (BUY stop, triggers when low <= trigger_price): 87.0 <= 88.0 ✓
        #   Take profit (SELL limit, triggers when high >= price): 112.0 >= 110.0 ✓, but take is NEW, and stops have priority
        # Bar 2: high=112.0, take=110.0 - take profit does NOT trigger (deal already closed by stops)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 112.0, 100.0],  # Bar 1 high=112.0 hits take profit at 110.0, but stops have priority
            lows=[99.0, 87.0, 100.0]  # Bar 1 low=87.0 triggers limit entry at 95.0 and both stops at 90.0 and 88.0 simultaneously
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with two stops (0.5 at 90.0, 0.5 at 88.0) and one take profit (1.0 at 110.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 and 88.0 (both stops execute as market, with slippage, fee_taker) - close entire position
        # Expected: limit entry triggers on bar 1, both stops trigger on bar 1, take profit does NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5
        # Take profit does NOT trigger
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price1 = 90.0
        stop_trigger_price2 = 88.0
        stop_quantity1 = 0.5  # First stop closes half position
        stop_quantity2 = 0.5  # Second stop closes remaining half position
        take_price = 110.0  # Does NOT trigger
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # Both stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        stop_execution2 = stop_trigger_price2 - test_task.slippage_in_steps * test_task.price_step  # 88.0 - 0.1 = 87.9 (SELL market, slippage decreases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 87.9 * 0.5 * 0.001 = 0.04395
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = stop_execution1 * stop_quantity1 - stop_fee1 + stop_execution2 * stop_quantity2 - stop_fee2  # 89.9*0.5 - 0.04495 + 87.9*0.5 - 0.04395 = 44.90505 + 43.90605 = 88.8111
        expected_profit = exit_proceeds - entry_cost  # = 88.8111 - 95.0475 = -6.2364
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': [(0.5, 90.0), (0.5, 88.0)],  # Two stops (0.5 + 0.5 = 1.0), both trigger
                    'take_profit': [(1.0, 110.0)]  # One take profit
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e2_1_limit_entry_all_stops_take_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and all stops trigger on bar 1, take profit does NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and both stops trigger simultaneously (3 trades - entry + stop1 + stop2), take profit does NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and both stops should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that both stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop loss orders should be executed"
        active_stops = [o for o in stop_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_stops) == 0, "No stop orders should remain active after deal closes"
        
        # Check that take profit order was NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "Take profit order should NOT be executed (stops have priority)"
        # Take profit should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stops)"

    def test_buy_sltp_limit_entry_part_stops_take_simultaneous_stop_priority(self, test_task):
        """Test E2.2: Limit entry, part of stops and take profit hit simultaneously → entry + part of stops trigger, take profit does NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, part of stops, and take profit simultaneously
        # Bar 0: high=101.0, low=99.0, limit=95.0, stops=(90.0, 88.0, 86.0), take=110.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 99.0 > 88.0, 99.0 > 86.0, 101.0 < 110.0)
        # Bar 1: high=112.0, low=89.0, limit=95.0, stops=(90.0, 88.0, 86.0), take=110.0 - entry and first stop trigger simultaneously, take does NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 89.0 <= 95.0 ✓
        #   Stop loss 1 (BUY stop, triggers when low <= trigger_price): 89.0 <= 90.0 ✓
        #   Stop loss 2 (BUY stop, triggers when low <= trigger_price): 89.0 > 88.0 ✗ (does NOT trigger)
        #   Stop loss 3 (BUY stop, triggers when low <= trigger_price): 89.0 > 86.0 ✗ (does NOT trigger)
        #   Take profit (SELL limit, triggers when high >= price): 112.0 >= 110.0 ✓, but take is NEW, and stops have priority
        # Bar 2: low=87.0, stop2=88.0, stop3=86.0 - second stop triggers (87.0 <= 88.0), third stop does NOT trigger (87.0 > 86.0)
        # Bar 3: low=85.0, stop3=86.0 - third stop triggers (85.0 <= 86.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            highs=[101.0, 112.0, 100.0, 100.0],  # Bar 1 high=112.0 hits take profit at 110.0, but stops have priority
            lows=[99.0, 89.0, 87.0, 85.0]  # Bar 1 low=89.0 triggers limit entry at 95.0 and first stop at 90.0; Bar 2 low=87.0 triggers second stop at 88.0; Bar 3 low=85.0 triggers third stop at 86.0
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with three stops (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0) and one take profit (1.0 at 110.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 (first stop executes as market, with slippage, fee_taker) - closes 0.3; 88.0 (second stop) - closes 0.3 on bar 2; 86.0 (third stop) - closes remaining 0.4 on bar 3
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, take profit does NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third stop (extreme): 1.0 - 0.3 - 0.3 = 0.4
        # Take profit does NOT trigger
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price1 = 90.0
        stop_trigger_price2 = 88.0
        stop_trigger_price3 = 86.0
        stop_quantity1 = 0.3  # First stop closes 0.3 position
        stop_quantity2 = 0.3  # Second stop closes 0.3 position
        stop_quantity3 = 0.4  # Third stop closes remaining 0.4 position
        take_price = 110.0  # Does NOT trigger
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # All stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 89.9 * 0.3 * 0.001 = 0.02697
        stop_execution2 = stop_trigger_price2 - test_task.slippage_in_steps * test_task.price_step  # 88.0 - 0.1 = 87.9 (SELL market, slippage decreases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 87.9 * 0.3 * 0.001 = 0.02637
        stop_execution3 = stop_trigger_price3 - test_task.slippage_in_steps * test_task.price_step  # 86.0 - 0.1 = 85.9 (SELL market, slippage decreases price)
        stop_fee3 = stop_execution3 * stop_quantity3 * test_task.fee_taker  # 85.9 * 0.4 * 0.001 = 0.03436
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = stop_execution1 * stop_quantity1 - stop_fee1 + stop_execution2 * stop_quantity2 - stop_fee2 + stop_execution3 * stop_quantity3 - stop_fee3  # 89.9*0.3 - 0.02697 + 87.9*0.3 - 0.02637 + 85.9*0.4 - 0.03436 = 26.93603 + 26.34363 + 34.32564 = 87.6053
        expected_profit = exit_proceeds - entry_cost  # = 87.6053 - 95.0475 = -7.4422
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0), all trigger sequentially
                    'take_profit': [(1.0, 110.0)]  # One take profit
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e2_2_limit_entry_part_stops_take_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and first stop trigger on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, take profit does NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and first stop trigger simultaneously (2 trades - entry + stop1), take profit does NOT trigger
        # Bar 2: second stop triggers (3 trades total - entry + stop1 + stop2)
        # Bar 3: third stop triggers (4 trades total - entry + stop1 + stop2 + stop3)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and first stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third stop should trigger on bar 3"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all three stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All three stop loss orders should be executed"
        active_stops = [o for o in stop_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_stops) == 0, "No stop orders should remain active after deal closes"
        
        # Check that take profit order was NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "Take profit order should NOT be executed (stops have priority)"
        # Take profit should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stops)"


# ============================================================================
# Group E2: One Entry, Multiple Stops, One Take Profit - SELL
# ============================================================================

class TestSellSltpOneEntryMultipleStopsOneTake:
    """Test E2: One entry, multiple stops, one take profit scenarios for sell_sltp."""
    
    def test_sell_sltp_limit_entry_all_stops_take_simultaneous_stop_priority(self, test_task):
        """Test E2.1: Limit entry, all stops and take profit hit simultaneously → entry + all stops trigger, take profit does NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, all stops, and take profit simultaneously
        # Bar 0: high=101.0, low=99.0, limit=105.0, stops=(110.0, 112.0), take=90.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 101.0 < 112.0, 99.0 > 90.0)
        # Bar 1: high=113.0, low=88.0, limit=105.0, stops=(110.0, 112.0), take=90.0 - entry and all stops trigger simultaneously, take does NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 113.0 >= 105.0 ✓
        #   Stop loss 1 (SELL stop, triggers when high >= trigger_price): 113.0 >= 110.0 ✓
        #   Stop loss 2 (SELL stop, triggers when high >= trigger_price): 113.0 >= 112.0 ✓
        #   Take profit (BUY limit, triggers when low <= price): 88.0 <= 90.0 ✓, but take is NEW, and stops have priority
        # Bar 2: low=88.0, take=90.0 - take profit does NOT trigger (deal already closed by stops)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 113.0, 100.0],  # Bar 1 high=113.0 triggers limit entry at 105.0 and both stops at 110.0 and 112.0 simultaneously
            lows=[99.0, 88.0, 100.0]  # Bar 1 low=88.0 hits take profit at 90.0, but stops have priority
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with two stops (0.5 at 110.0, 0.5 at 112.0) and one take profit (1.0 at 90.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 and 112.0 (both stops execute as market, with slippage, fee_taker) - close entire position
        # Expected: limit entry triggers on bar 1, both stops trigger on bar 1, take profit does NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5
        # Take profit does NOT trigger
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price1 = 110.0
        stop_trigger_price2 = 112.0
        stop_quantity1 = 0.5  # First stop closes half position
        stop_quantity2 = 0.5  # Second stop closes remaining half position
        take_price = 90.0  # Does NOT trigger
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # Both stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        stop_execution2 = stop_trigger_price2 + test_task.slippage_in_steps * test_task.price_step  # 112.0 + 0.1 = 112.1 (BUY market, slippage increases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 112.1 * 0.5 * 0.001 = 0.05605
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = stop_execution1 * stop_quantity1 + stop_fee1 + stop_execution2 * stop_quantity2 + stop_fee2  # 110.1*0.5 + 0.05505 + 112.1*0.5 + 0.05605 = 55.05505 + 56.05605 = 111.1111
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 111.1111 = -6.1636
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': [(0.5, 110.0), (0.5, 112.0)],  # Two stops (0.5 + 0.5 = 1.0), both trigger
                    'take_profit': [(1.0, 90.0)]  # One take profit
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e2_1_limit_entry_all_stops_take_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and all stops trigger on bar 1, take profit does NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and both stops trigger simultaneously (3 trades - entry + stop1 + stop2), take profit does NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and both stops should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that both stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop loss orders should be executed"
        active_stops = [o for o in stop_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_stops) == 0, "No stop orders should remain active after deal closes"
        
        # Check that take profit order was NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "Take profit order should NOT be executed (stops have priority)"
        # Take profit should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stops)"
    
    def test_sell_sltp_limit_entry_part_stops_take_simultaneous_stop_priority(self, test_task):
        """Test E2.2: Limit entry, part of stops and take profit hit simultaneously → entry + part of stops trigger, take profit does NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, part of stops, and take profit simultaneously
        # Bar 0: high=101.0, low=99.0, limit=105.0, stops=(110.0, 112.0, 114.0), take=90.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 101.0 < 112.0, 101.0 < 114.0, 99.0 > 90.0)
        # Bar 1: high=111.0, low=88.0, limit=105.0, stops=(110.0, 112.0, 114.0), take=90.0 - entry and first stop trigger simultaneously, take does NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 111.0 >= 105.0 ✓
        #   Stop loss 1 (SELL stop, triggers when high >= trigger_price): 111.0 >= 110.0 ✓
        #   Stop loss 2 (SELL stop, triggers when high >= trigger_price): 111.0 < 112.0 ✗ (does NOT trigger)
        #   Stop loss 3 (SELL stop, triggers when high >= trigger_price): 111.0 < 114.0 ✗ (does NOT trigger)
        #   Take profit (BUY limit, triggers when low <= price): 88.0 <= 90.0 ✓, but take is NEW, and stops have priority
        # Bar 2: high=113.0, stop2=112.0, stop3=114.0 - second stop triggers (113.0 >= 112.0), third stop does NOT trigger (113.0 < 114.0)
        # Bar 3: high=115.0, stop3=114.0 - third stop triggers (115.0 >= 114.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            highs=[101.0, 111.0, 113.0, 115.0],  # Bar 1 high=111.0 triggers limit entry at 105.0 and first stop at 110.0; Bar 2 high=113.0 triggers second stop at 112.0; Bar 3 high=115.0 triggers third stop at 114.0
            lows=[99.0, 88.0, 100.0, 100.0]  # Bar 1 low=88.0 hits take profit at 90.0, but stops have priority
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with three stops (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0) and one take profit (1.0 at 90.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 (first stop executes as market, with slippage, fee_taker) - closes 0.3; 112.0 (second stop) - closes 0.3 on bar 2; 114.0 (third stop) - closes remaining 0.4 on bar 3
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, take profit does NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third stop (extreme): 1.0 - 0.3 - 0.3 = 0.4
        # Take profit does NOT trigger
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price1 = 110.0
        stop_trigger_price2 = 112.0
        stop_trigger_price3 = 114.0
        stop_quantity1 = 0.3  # First stop closes 0.3 position
        stop_quantity2 = 0.3  # Second stop closes 0.3 position
        stop_quantity3 = 0.4  # Third stop closes remaining 0.4 position
        take_price = 90.0  # Does NOT trigger
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # All stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 110.1 * 0.3 * 0.001 = 0.03303
        stop_execution2 = stop_trigger_price2 + test_task.slippage_in_steps * test_task.price_step  # 112.0 + 0.1 = 112.1 (BUY market, slippage increases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 112.1 * 0.3 * 0.001 = 0.03363
        stop_execution3 = stop_trigger_price3 + test_task.slippage_in_steps * test_task.price_step  # 114.0 + 0.1 = 114.1 (BUY market, slippage increases price)
        stop_fee3 = stop_execution3 * stop_quantity3 * test_task.fee_taker  # 114.1 * 0.4 * 0.001 = 0.04564
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = stop_execution1 * stop_quantity1 + stop_fee1 + stop_execution2 * stop_quantity2 + stop_fee2 + stop_execution3 * stop_quantity3 + stop_fee3  # 110.1*0.3 + 0.03303 + 112.1*0.3 + 0.03363 + 114.1*0.4 + 0.04564 = 33.03303 + 33.63363 + 45.68564 = 112.3523
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 112.3523 = -7.4048
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0), all trigger sequentially
                    'take_profit': [(1.0, 90.0)]  # One take profit
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e2_2_limit_entry_part_stops_take_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and first stop trigger on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, take profit does NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and first stop trigger simultaneously (2 trades - entry + stop1), take profit does NOT trigger
        # Bar 2: second stop triggers (3 trades total - entry + stop1 + stop2)
        # Bar 3: third stop triggers (4 trades total - entry + stop1 + stop2 + stop3)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and first stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third stop should trigger on bar 3"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all three stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All three stop loss orders should be executed"
        active_stops = [o for o in stop_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_stops) == 0, "No stop orders should remain active after deal closes"
        
        # Check that take profit order was NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "Take profit order should NOT be executed (stops have priority)"
        # Take profit should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 1, "Take profit order should be canceled (deal closed by stops)"
# ============================================================================
# Group E3: One Entry, One Stop, Multiple Take Profits - BUY
# ============================================================================

class TestBuySltpOneEntryOneStopMultipleTakes:
    """Test E3: One entry, one stop, multiple take profits scenarios for buy_sltp."""
    
    def test_buy_sltp_limit_entry_stop_all_takes_simultaneous_stop_priority(self, test_task):
        """Test E3.1: Limit entry, stop and all take profits hit simultaneously → entry + stop trigger, all takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, stop, and all take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=95.0, stop=90.0, takes=110.0, 112.0, 114.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 101.0 < 110.0)
        # Bar 1: high=115.0, low=88.0, limit=95.0, stop=90.0, takes=110.0, 112.0, 114.0 - entry and stop trigger simultaneously, all takes do NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 88.0 <= 95.0 ✓
        #   Stop loss (BUY stop, triggers when low <= trigger_price): 88.0 <= 90.0 ✓
        #   Take profits (SELL limits, trigger when high >= price): 115.0 >= 110.0 ✓, 115.0 >= 112.0 ✓, 115.0 >= 114.0 ✓, but takes are NEW, and stops have priority
        # Bar 2: high=115.0, takes=110.0, 112.0, 114.0 - take profits do NOT trigger (deal already closed by stop)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 115.0, 115.0],  # Bar 1 high=115.0 hits all take profits at 110.0, 112.0, 114.0, but stops have priority
            lows=[99.0, 88.0, 100.0]  # Bar 1 low=88.0 triggers limit entry at 95.0 and stop at 90.0 simultaneously
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with stop loss 90.0 and three take profits (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop trigger: 90.0 (stop executes as market, with slippage, fee_taker) - closes entire position
        # Expected: limit entry triggers on bar 1, stop triggers on bar 1, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volume: 1.0 (closes entire position)
        # Take profits do NOT trigger
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price = 90.0
        stop_quantity = 1.0  # Closes entire position
        take_prices = [110.0, 112.0, 114.0]  # All do NOT trigger
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # Stop executes as market order (with slippage, fee_taker)
        stop_execution = stop_trigger_price - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee = stop_execution * stop_quantity * test_task.fee_taker  # 89.9 * 1.0 * 0.001 = 0.0899
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = stop_execution * stop_quantity - stop_fee  # 89.9 * 1.0 - 0.0899 = 89.8101
        expected_profit = exit_proceeds - entry_cost  # = 89.8101 - 95.0475 = -5.2374
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': 90.0,
                    'take_profit': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)]  # Three take profits
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e3_1_limit_entry_stop_all_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and stop trigger on bar 1, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and stop trigger simultaneously (2 trades - entry + stop), all take profits do NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 2, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stop
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 2, f"Expected 2 trades total (entry + stop), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that stop order was executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Stop loss order should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stop)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 3, "All take profit orders should be canceled (deal closed by stop)"
    
    def test_buy_sltp_limit_entry_stop_all_takes_simultaneous_part_takes_next_bar(self, test_task):
        """Test E3.2: Limit entry, stop and all take profits hit simultaneously → entry + stop trigger, part of takes trigger on next bar (if deal didn't close completely)."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry and first stop simultaneously, but stop only closes part of position
        # Bar 0: high=101.0, low=99.0, limit=95.0, stops=90.0, 85.0, takes=110.0, 112.0, 114.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 101.0 < 110.0)
        # Bar 1: high=115.0, low=88.0, limit=95.0, stops=90.0, 85.0, takes=110.0, 112.0, 114.0 - entry and first stop trigger simultaneously, all takes do NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 88.0 <= 95.0 ✓
        #   First stop loss (BUY stop, triggers when low <= trigger_price): 88.0 <= 90.0 ✓
        #   Second stop loss (BUY stop): 88.0 > 85.0 ✗ (does NOT trigger)
        #   Take profits (SELL limits, trigger when high >= price): 115.0 >= 110.0 ✓, 115.0 >= 112.0 ✓, 115.0 >= 114.0 ✓, but takes are NEW, and stops have priority
        # Bar 2: high=113.0, takes=110.0, 112.0, 114.0 - first two take profits trigger (113.0 >= 110.0, 113.0 >= 112.0), third does NOT trigger (113.0 < 114.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 115.0, 113.0],  # Bar 1 high=115.0 hits all take profits, but stops have priority; Bar 2 high=113.0 triggers first two takes at 110.0 and 112.0
            lows=[99.0, 88.0, 100.0]  # Bar 1 low=88.0 triggers limit entry at 95.0 and first stop at 90.0 simultaneously; second stop at 85.0 does NOT trigger
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with two stops (0.5 at 90.0, 0.5 at 85.0) and three take profits (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 (first stop executes as market, with slippage, fee_taker) - closes 0.5; 85.0 does NOT trigger (low=88.0 > 85.0)
        # Take triggers: 110.0 and 112.0 (first two takes execute as limits, no slippage, fee_maker) - close part of remaining position on bar 2; 114.0 does NOT trigger (high=113.0 < 114.0)
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1 (closes 0.5), first two take profits trigger on bar 2 (close part of remaining 0.5)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5 (but doesn't trigger)
        # IMPORTANT: Take profit volumes are calculated from FULL ENTRY VOLUME (deal.enter_volume = 1.0), 
        # MINUS executed stop volumes (0.5), NOT from current position (0.5)
        # Target volume for takes: 1.0 - 0.5 = 0.5
        # Fractions: 0.33, 0.33, 0.34
        # First take: round(0.33 * 0.5 / 0.1) * 0.1 = round(1.65) * 0.1 = 2 * 0.1 = 0.2
        # Second take: round(0.33 * 0.5 / 0.1) * 0.1 = round(1.65) * 0.1 = 2 * 0.1 = 0.2
        # Third take (extreme, gets remainder from current position): 0.5 - 0.2 - 0.2 = 0.1 (but doesn't trigger)
        # Only first two takes trigger, closing 0.2 + 0.2 = 0.4 of remaining position (0.5)
        # Remaining position after takes: 0.5 - 0.4 = 0.1 (will be auto-closed at end of test)
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price1 = 90.0
        stop_trigger_price2 = 85.0  # Does NOT trigger (low=88.0 > 85.0)
        stop_quantity1 = 0.5  # First stop closes half position
        take_price1 = 110.0
        take_price2 = 112.0
        take_price3 = 114.0  # Does NOT trigger (high=113.0 < 114.0)
        # IMPORTANT: Take profit volumes are calculated from FULL ENTRY VOLUME (deal.enter_volume = 1.0), 
        # MINUS executed stop volumes (0.5), NOT from current position (0.5)
        # Target volume for takes: 1.0 - 0.5 = 0.5
        # Fractions: 0.33, 0.33, 0.34
        # First take: round(0.33 * 0.5 / 0.1) * 0.1 = round(1.65) * 0.1 = 2 * 0.1 = 0.2
        # Second take: round(0.33 * 0.5 / 0.1) * 0.1 = round(1.65) * 0.1 = 2 * 0.1 = 0.2
        # Third take (extreme, gets remainder from current position): 0.5 - 0.2 - 0.2 = 0.1 (but doesn't trigger)
        take_quantity1 = 0.2  # round(0.33 * 0.5 / 0.1) * 0.1 = 0.2
        take_quantity2 = 0.2  # round(0.33 * 0.5 / 0.1) * 0.1 = 0.2
        remaining_quantity = 0.5 - take_quantity1 - take_quantity2  # 0.5 - 0.2 - 0.2 = 0.1 (will be auto-closed)
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # Stop executes as market order (with slippage, fee_taker)
        stop_execution = stop_trigger_price1 - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee = stop_execution * stop_quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        
        # Takes execute as limit orders (no slippage, fee_maker)
        take_execution1 = take_price1  # 110.0 (limit, no slippage)
        take_fee1 = take_execution1 * take_quantity1 * test_task.fee_maker  # 110.0 * 0.2 * 0.0005 = 0.011
        take_execution2 = take_price2  # 112.0 (limit, no slippage)
        take_fee2 = take_execution2 * take_quantity2 * test_task.fee_maker  # 112.0 * 0.2 * 0.0005 = 0.0112
        
        # Auto-close: remaining 0.1 position closed at last bar closing price (100.0) as market order (with slippage, fee_taker)
        auto_close_price = 100.0  # Last bar closing price
        auto_close_execution = auto_close_price - test_task.slippage_in_steps * test_task.price_step  # 100.0 - 0.1 = 99.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * remaining_quantity * test_task.fee_taker  # 99.9 * 0.1 * 0.001 = 0.00999
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = (stop_execution * stop_quantity1 - stop_fee +
                         take_execution1 * take_quantity1 - take_fee1 +
                         take_execution2 * take_quantity2 - take_fee2 +
                         auto_close_execution * remaining_quantity - auto_close_fee)  # 44.90505 + 21.989 + 22.3888 + 9.98001 = 99.26286
        expected_profit = exit_proceeds - entry_cost  # = 99.26286 - 95.0475 = 4.21536
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': [(0.5, 90.0), (0.5, 85.0)],  # Two stops (0.5 + 0.5 = 1.0), only first triggers
                    'take_profit': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)]  # Three take profits
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e3_2_limit_entry_stop_all_takes_simultaneous_part_takes_next_bar")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and stop trigger on bar 1, part of take profits trigger on bar 2
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and stop trigger simultaneously (2 trades - entry + stop), all take profits do NOT trigger
        # Bar 2: first two take profits trigger (4 trades total - entry + stop + take1 + take2)
        # After bar 2: auto-close of remaining position (5 trades total - entry + stop + take1 + take2 + auto-close)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 4, "First two take profits should trigger on bar 2"
        
        # Check final state: deal should be closed (auto-closed at end of test)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count (including auto-close)
        assert len(broker.trades) == 5, f"Expected 5 trades total (entry + stop + take1 + take2 + auto-close), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that first stop order was executed, second does NOT trigger
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "First stop loss order should be executed"
        active_stops = [o for o in stop_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_stops) == 0, "No stop orders should remain active after deal closes"
        
        # Check that first two take profit orders were executed (on bar 2), third does NOT trigger
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "First two take profit orders should be executed on bar 2"
        active_takes = [o for o in take_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_takes) == 0, "No take profit orders should remain active after deal closes"


# ============================================================================
# Group E3: One Entry, One Stop, Multiple Take Profits - SELL
# ============================================================================

class TestSellSltpOneEntryOneStopMultipleTakes:
    """Test E3: One entry, one stop, multiple take profits scenarios for sell_sltp."""
    
    def test_sell_sltp_limit_entry_stop_all_takes_simultaneous_stop_priority(self, test_task):
        """Test E3.1: Limit entry, stop and all take profits hit simultaneously → entry + stop trigger, all takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, stop, and all take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=105.0, stop=110.0, takes=90.0, 88.0, 86.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 99.0 > 90.0)
        # Bar 1: high=112.0, low=85.0, limit=105.0, stop=110.0, takes=90.0, 88.0, 86.0 - entry and stop trigger simultaneously, all takes do NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 112.0 >= 105.0 ✓
        #   Stop loss (SELL stop, triggers when high >= trigger_price): 112.0 >= 110.0 ✓
        #   Take profits (BUY limits, trigger when low <= price): 85.0 <= 90.0 ✓, 85.0 <= 88.0 ✓, 85.0 <= 86.0 ✓, but takes are NEW, and stops have priority
        # Bar 2: low=85.0, takes=90.0, 88.0, 86.0 - take profits do NOT trigger (deal already closed by stop)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 112.0, 100.0],  # Bar 1 high=112.0 triggers limit entry at 105.0 and stop at 110.0 simultaneously
            lows=[99.0, 85.0, 100.0]  # Bar 1 low=85.0 hits all take profits at 90.0, 88.0, 86.0, but stops have priority
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with stop loss 110.0 and three take profits (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop trigger: 110.0 (stop executes as market, with slippage, fee_taker) - closes entire position
        # Expected: limit entry triggers on bar 1, stop triggers on bar 1, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volume: 1.0 (closes entire position)
        # Take profits do NOT trigger
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price = 110.0
        stop_quantity = 1.0  # Closes entire position
        take_prices = [90.0, 88.0, 86.0]  # All do NOT trigger
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # Stop executes as market order (with slippage, fee_taker)
        stop_execution = stop_trigger_price + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee = stop_execution * stop_quantity * test_task.fee_taker  # 110.1 * 1.0 * 0.001 = 0.1101
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = stop_execution * stop_quantity + stop_fee  # 110.1 * 1.0 + 0.1101 = 110.2101
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 110.2101 = -5.2626
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': 110.0,
                    'take_profit': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)]  # Three take profits
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e3_1_limit_entry_stop_all_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and stop trigger on bar 1, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and stop trigger simultaneously (2 trades - entry + stop), all take profits do NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 2, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stop
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 2, f"Expected 2 trades total (entry + stop), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that stop order was executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 1, "Should have one stop loss order"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "Stop loss order should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stop)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 3, "All take profit orders should be canceled (deal closed by stop)"
    
    def test_sell_sltp_limit_entry_stop_all_takes_simultaneous_part_takes_next_bar(self, test_task):
        """Test E3.2: Limit entry, stop and all take profits hit simultaneously → entry + stop trigger, part of takes trigger on next bar (if deal didn't close completely)."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry and first stop simultaneously, but stop only closes part of position
        # Bar 0: high=101.0, low=99.0, limit=105.0, stops=110.0, 115.0, takes=90.0, 88.0, 86.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 99.0 > 90.0)
        # Bar 1: high=112.0, low=85.0, limit=105.0, stops=110.0, 115.0, takes=90.0, 88.0, 86.0 - entry and first stop trigger simultaneously, all takes do NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 112.0 >= 105.0 ✓
        #   First stop loss (SELL stop, triggers when high >= trigger_price): 112.0 >= 110.0 ✓
        #   Second stop loss (SELL stop): 112.0 < 115.0 ✗ (does NOT trigger)
        #   Take profits (BUY limits, trigger when low <= price): 85.0 <= 90.0 ✓, 85.0 <= 88.0 ✓, 85.0 <= 86.0 ✓, but takes are NEW, and stops have priority
        # Bar 2: low=87.0, takes=90.0, 88.0, 86.0 - first two take profits trigger (87.0 <= 90.0, 87.0 <= 88.0), third does NOT trigger (87.0 > 86.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 112.0, 100.0],  # Bar 1 high=112.0 triggers limit entry at 105.0 and first stop at 110.0 simultaneously; second stop at 115.0 does NOT trigger
            lows=[99.0, 85.0, 87.0]  # Bar 1 low=85.0 hits all take profits, but stops have priority; Bar 2 low=87.0 triggers first two takes at 90.0 and 88.0
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with two stops (0.5 at 110.0, 0.5 at 115.0) and three take profits (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 (first stop executes as market, with slippage, fee_taker) - closes 0.5; 115.0 does NOT trigger (high=112.0 < 115.0)
        # Take triggers: 90.0 and 88.0 (first two takes execute as limits, no slippage, fee_maker) - close part of remaining position on bar 2; 86.0 does NOT trigger (low=87.0 > 86.0)
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1 (closes 0.5), first two take profits trigger on bar 2 (close part of remaining 0.5)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5 (but doesn't trigger)
        # IMPORTANT: Take profit volumes are calculated from FULL ENTRY VOLUME (deal.enter_volume = 1.0), 
        # MINUS executed stop volumes (0.5), NOT from current position (0.5)
        # Target volume for takes: 1.0 - 0.5 = 0.5
        # Fractions: 0.33, 0.33, 0.34
        # First take: round(0.33 * 0.5 / 0.1) * 0.1 = round(1.65) * 0.1 = 2 * 0.1 = 0.2
        # Second take: round(0.33 * 0.5 / 0.1) * 0.1 = round(1.65) * 0.1 = 2 * 0.1 = 0.2
        # Third take (extreme, gets remainder from current position): 0.5 - 0.2 - 0.2 = 0.1 (but doesn't trigger)
        # Only first two takes trigger, closing 0.2 + 0.2 = 0.4 of remaining position (0.5)
        # Remaining position after takes: 0.5 - 0.4 = 0.1 (will be auto-closed at end of test)
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price1 = 110.0
        stop_trigger_price2 = 115.0  # Does NOT trigger (high=112.0 < 115.0)
        stop_quantity1 = 0.5  # First stop closes half position
        take_price1 = 90.0
        take_price2 = 88.0
        take_price3 = 86.0  # Does NOT trigger (low=87.0 > 86.0)
        # IMPORTANT: Take profit volumes are calculated from FULL ENTRY VOLUME (deal.enter_volume = 1.0), 
        # MINUS executed stop volumes (0.5), NOT from current position (0.5)
        # Target volume for takes: 1.0 - 0.5 = 0.5
        # Fractions: 0.33, 0.33, 0.34
        # First take: round(0.33 * 0.5 / 0.1) * 0.1 = round(1.65) * 0.1 = 2 * 0.1 = 0.2
        # Second take: round(0.33 * 0.5 / 0.1) * 0.1 = round(1.65) * 0.1 = 2 * 0.1 = 0.2
        # Third take (extreme, gets remainder from current position): 0.5 - 0.2 - 0.2 = 0.1 (but doesn't trigger)
        take_quantity1 = 0.2  # round(0.33 * 0.5 / 0.1) * 0.1 = 0.2
        take_quantity2 = 0.2  # round(0.33 * 0.5 / 0.1) * 0.1 = 0.2
        remaining_quantity = 0.5 - take_quantity1 - take_quantity2  # 0.5 - 0.2 - 0.2 = 0.1 (will be auto-closed)
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # Stop executes as market order (with slippage, fee_taker)
        stop_execution = stop_trigger_price1 + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee = stop_execution * stop_quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        
        # Takes execute as limit orders (no slippage, fee_maker)
        take_execution1 = take_price1  # 90.0 (limit, no slippage)
        take_fee1 = take_execution1 * take_quantity1 * test_task.fee_maker  # 90.0 * 0.2 * 0.0005 = 0.009
        take_execution2 = take_price2  # 88.0 (limit, no slippage)
        take_fee2 = take_execution2 * take_quantity2 * test_task.fee_maker  # 88.0 * 0.2 * 0.0005 = 0.0088
        
        # Auto-close: remaining 0.1 position closed at last bar closing price (100.0) as market order (with slippage, fee_taker)
        auto_close_price = 100.0  # Last bar closing price
        auto_close_execution = auto_close_price + test_task.slippage_in_steps * test_task.price_step  # 100.0 + 0.1 = 100.1 (BUY market, slippage increases price)
        auto_close_fee = auto_close_execution * remaining_quantity * test_task.fee_taker  # 100.1 * 0.1 * 0.001 = 0.01001
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = (stop_execution * stop_quantity1 + stop_fee +
                     take_execution1 * take_quantity1 + take_fee1 +
                     take_execution2 * take_quantity2 + take_fee2 +
                     auto_close_execution * remaining_quantity + auto_close_fee)  # 55.05505 + 18.009 + 17.6088 + 10.01001 = 100.68286
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 100.68286 = 4.26464
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': [(0.5, 110.0), (0.5, 115.0)],  # Two stops (0.5 + 0.5 = 1.0), only first triggers
                    'take_profit': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)]  # Three take profits
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e3_2_limit_entry_stop_all_takes_simultaneous_part_takes_next_bar")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and stop trigger on bar 1, part of take profits trigger on bar 2
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and stop trigger simultaneously (2 trades - entry + stop), all take profits do NOT trigger
        # Bar 2: first two take profits trigger (4 trades total - entry + stop + take1 + take2)
        # After bar 2: auto-close of remaining position (5 trades total - entry + stop + take1 + take2 + auto-close)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 4, "First two take profits should trigger on bar 2"
        
        # Check final state: deal should be closed (auto-closed at end of test)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count (including auto-close)
        assert len(broker.trades) == 5, f"Expected 5 trades total (entry + stop + take1 + take2 + auto-close), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that first stop order was executed, second does NOT trigger
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 1, "First stop loss order should be executed"
        active_stops = [o for o in stop_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_stops) == 0, "No stop orders should remain active after deal closes"
        
        # Check that first two take profit orders were executed (on bar 2), third does NOT trigger
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "First two take profit orders should be executed on bar 2"
        active_takes = [o for o in take_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_takes) == 0, "No take profit orders should remain active after deal closes"

# ============================================================================
# Group E4: One Entry, Multiple Stops, Multiple Take Profits - BUY
# ============================================================================

class TestBuySltpOneEntryMultipleStopsMultipleTakes:
    """Test E4: One entry, multiple stops, multiple take profits scenarios for buy_sltp."""
    
    def test_buy_sltp_limit_entry_all_stops_all_takes_simultaneous_stop_priority(self, test_task):
        """Test E4.1: Limit entry, all stops and all take profits hit simultaneously → entry + all stops trigger, all takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, all stops, and all take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=95.0, stops=90.0, 88.0, takes=110.0, 112.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 101.0 < 110.0)
        # Bar 1: high=115.0, low=87.0, limit=95.0, stops=90.0, 88.0, takes=110.0, 112.0 - entry and all stops trigger simultaneously, all takes do NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 87.0 <= 95.0 ✓
        #   First stop loss (BUY stop, triggers when low <= trigger_price): 87.0 <= 90.0 ✓
        #   Second stop loss (BUY stop): 87.0 <= 88.0 ✓
        #   Take profits (SELL limits, trigger when high >= price): 115.0 >= 110.0 ✓, 115.0 >= 112.0 ✓, but takes are NEW, and stops have priority
        # Bar 2: high=115.0, takes=110.0, 112.0 - take profits do NOT trigger (deal already closed by stops)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 115.0, 100.0],  # Bar 1 high=115.0 hits all take profits, but stops have priority
            lows=[99.0, 87.0, 100.0]  # Bar 1 low=87.0 triggers limit entry at 95.0 and both stops at 90.0 and 88.0 simultaneously
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with two stops (0.5 at 90.0, 0.5 at 88.0) and two take profits (0.5 at 110.0, 0.5 at 112.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 and 88.0 (both stops execute as market, with slippage, fee_taker) - close entire position
        # Expected: limit entry triggers on bar 1, both stops trigger on bar 1, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5
        # Take profits do NOT trigger
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price1 = 90.0
        stop_trigger_price2 = 88.0
        stop_quantity1 = 0.5  # First stop closes half position
        stop_quantity2 = 0.5  # Second stop closes remaining half position
        take_prices = [110.0, 112.0]  # All do NOT trigger
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # Stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        stop_execution2 = stop_trigger_price2 - test_task.slippage_in_steps * test_task.price_step  # 88.0 - 0.1 = 87.9 (SELL market, slippage decreases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 87.9 * 0.5 * 0.001 = 0.04395
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = (stop_execution1 * stop_quantity1 - stop_fee1 +
                         stop_execution2 * stop_quantity2 - stop_fee2)  # 44.90505 + 43.90605 = 88.8111
        expected_profit = exit_proceeds - entry_cost  # = 88.8111 - 95.0475 = -6.2364
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': [(0.5, 90.0), (0.5, 88.0)],  # Two stops (0.5 + 0.5 = 1.0)
                    'take_profit': [(0.5, 110.0), (0.5, 112.0)]  # Two take profits (0.5 + 0.5 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e4_1_limit_entry_all_stops_all_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and all stops trigger on bar 1, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and both stops trigger simultaneously (3 trades - entry + stop1 + stop2), all take profits do NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and both stops should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that both stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop loss orders should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 2, "All take profit orders should be canceled (deal closed by stops)"
    
    def test_buy_sltp_limit_entry_all_stops_part_takes_simultaneous_stop_priority(self, test_task):
        """Test E4.2: Limit entry, all stops and part of take profits hit simultaneously → entry + all stops trigger, part of takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, all stops, and part of take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=95.0, stops=90.0, 88.0, takes=110.0, 112.0, 114.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 101.0 < 110.0)
        # Bar 1: high=113.0, low=87.0, limit=95.0, stops=90.0, 88.0, takes=110.0, 112.0, 114.0 - entry and all stops trigger simultaneously, part of takes do NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 87.0 <= 95.0 ✓
        #   First stop loss (BUY stop, triggers when low <= trigger_price): 87.0 <= 90.0 ✓
        #   Second stop loss (BUY stop): 87.0 <= 88.0 ✓
        #   Take profits (SELL limits, trigger when high >= price): 113.0 >= 110.0 ✓, 113.0 >= 112.0 ✓, 113.0 < 114.0 ✗, but takes are NEW, and stops have priority
        # Bar 2: high=113.0, takes=110.0, 112.0, 114.0 - take profits do NOT trigger (deal already closed by stops)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 113.0, 100.0],  # Bar 1 high=113.0 hits first two take profits at 110.0 and 112.0, but stops have priority
            lows=[99.0, 87.0, 100.0]  # Bar 1 low=87.0 triggers limit entry at 95.0 and both stops at 90.0 and 88.0 simultaneously
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with two stops (0.5 at 90.0, 0.5 at 88.0) and three take profits (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 and 88.0 (both stops execute as market, with slippage, fee_taker) - close entire position
        # Expected: limit entry triggers on bar 1, both stops trigger on bar 1, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5
        # Take profits do NOT trigger
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price1 = 90.0
        stop_trigger_price2 = 88.0
        stop_quantity1 = 0.5  # First stop closes half position
        stop_quantity2 = 0.5  # Second stop closes remaining half position
        take_prices = [110.0, 112.0, 114.0]  # All do NOT trigger (stops have priority)
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # Stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 89.9 * 0.5 * 0.001 = 0.04495
        stop_execution2 = stop_trigger_price2 - test_task.slippage_in_steps * test_task.price_step  # 88.0 - 0.1 = 87.9 (SELL market, slippage decreases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 87.9 * 0.5 * 0.001 = 0.04395
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = (stop_execution1 * stop_quantity1 - stop_fee1 +
                         stop_execution2 * stop_quantity2 - stop_fee2)  # 44.90505 + 43.90605 = 88.8111
        expected_profit = exit_proceeds - entry_cost  # = 88.8111 - 95.0475 = -6.2364
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': [(0.5, 90.0), (0.5, 88.0)],  # Two stops (0.5 + 0.5 = 1.0)
                    'take_profit': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)]  # Three take profits (0.33 + 0.33 + 0.34 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e4_2_limit_entry_all_stops_part_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and all stops trigger on bar 1, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and both stops trigger simultaneously (3 trades - entry + stop1 + stop2), all take profits do NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and both stops should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that both stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop loss orders should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 3, "All take profit orders should be canceled (deal closed by stops)"
    
    def test_buy_sltp_limit_entry_part_stops_all_takes_simultaneous_stop_priority(self, test_task):
        """Test E4.3: Limit entry, part of stops and all take profits hit simultaneously → entry + part of stops trigger, all takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, part of stops, and all take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=95.0, stops=90.0, 88.0, 86.0, takes=110.0, 112.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 101.0 < 110.0)
        # Bar 1: high=115.0, low=89.0, limit=95.0, stops=90.0, 88.0, 86.0, takes=110.0, 112.0 - entry and first stop trigger simultaneously, all takes do NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 89.0 <= 95.0 ✓
        #   First stop loss (BUY stop, triggers when low <= trigger_price): 89.0 <= 90.0 ✓
        #   Second stop loss (BUY stop): 89.0 > 88.0 ✗ (does NOT trigger)
        #   Third stop loss (BUY stop): 89.0 > 86.0 ✗ (does NOT trigger)
        #   Take profits (SELL limits, trigger when high >= price): 115.0 >= 110.0 ✓, 115.0 >= 112.0 ✓, but takes are NEW, and stops have priority
        # Bar 2: low=87.0, stops=88.0, 86.0 - second stop triggers (87.0 <= 88.0), third stop does NOT trigger (87.0 > 86.0)
        # Bar 3: low=85.0, stop3=86.0 - third stop triggers (85.0 <= 86.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            highs=[101.0, 115.0, 100.0, 100.0],  # Bar 1 high=115.0 hits all take profits, but stops have priority
            lows=[99.0, 89.0, 87.0, 85.0]  # Bar 1 low=89.0 triggers limit entry at 95.0 and first stop at 90.0; Bar 2 low=87.0 triggers second stop at 88.0; Bar 3 low=85.0 triggers third stop at 86.0
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with three stops (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0) and two take profits (0.5 at 110.0, 0.5 at 112.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 (first stop executes as market, with slippage, fee_taker) - closes 0.3; 88.0 (second stop) - closes 0.3 on bar 2; 86.0 (third stop) - closes remaining 0.4 on bar 3
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third stop (extreme): 1.0 - 0.3 - 0.3 = 0.4
        # Take profits do NOT trigger
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price1 = 90.0
        stop_trigger_price2 = 88.0
        stop_trigger_price3 = 86.0
        stop_quantity1 = 0.3  # First stop closes 0.3 position
        stop_quantity2 = 0.3  # Second stop closes 0.3 position
        stop_quantity3 = 0.4  # Third stop closes remaining 0.4 position
        take_prices = [110.0, 112.0]  # All do NOT trigger (stops have priority)
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # All stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 89.9 * 0.3 * 0.001 = 0.02697
        stop_execution2 = stop_trigger_price2 - test_task.slippage_in_steps * test_task.price_step  # 88.0 - 0.1 = 87.9 (SELL market, slippage decreases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 87.9 * 0.3 * 0.001 = 0.02637
        stop_execution3 = stop_trigger_price3 - test_task.slippage_in_steps * test_task.price_step  # 86.0 - 0.1 = 85.9 (SELL market, slippage decreases price)
        stop_fee3 = stop_execution3 * stop_quantity3 * test_task.fee_taker  # 85.9 * 0.4 * 0.001 = 0.03436
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = (stop_execution1 * stop_quantity1 - stop_fee1 +
                         stop_execution2 * stop_quantity2 - stop_fee2 +
                         stop_execution3 * stop_quantity3 - stop_fee3)  # 26.93603 + 26.34363 + 34.32564 = 87.6053
        expected_profit = exit_proceeds - entry_cost  # = 87.6053 - 95.0475 = -7.4422
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0), all trigger sequentially
                    'take_profit': [(0.5, 110.0), (0.5, 112.0)]  # Two take profits (0.5 + 0.5 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e4_3_limit_entry_part_stops_all_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and first stop trigger on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and first stop trigger simultaneously (2 trades - entry + stop1), all take profits do NOT trigger
        # Bar 2: second stop triggers (3 trades total - entry + stop1 + stop2)
        # Bar 3: third stop triggers (4 trades total - entry + stop1 + stop2 + stop3)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and first stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third stop should trigger on bar 3"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all three stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All three stop loss orders should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 2, "All take profit orders should be canceled (deal closed by stops)"
    
    def test_buy_sltp_limit_entry_part_stops_part_takes_simultaneous_stop_priority(self, test_task):
        """Test E4.4: Limit entry, part of stops and part of take profits hit simultaneously → entry + part of stops trigger, part of takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, part of stops, and part of take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=95.0, stops=90.0, 88.0, 86.0, takes=110.0, 112.0, 114.0 - won't trigger (99.0 > 95.0, 99.0 > 90.0, 101.0 < 110.0)
        # Bar 1: high=113.0, low=89.0, limit=95.0, stops=90.0, 88.0, 86.0, takes=110.0, 112.0, 114.0 - entry and first stop trigger simultaneously, part of takes do NOT trigger
        #   Entry limit (BUY, triggers when low <= price): 89.0 <= 95.0 ✓
        #   First stop loss (BUY stop, triggers when low <= trigger_price): 89.0 <= 90.0 ✓
        #   Second stop loss (BUY stop): 89.0 > 88.0 ✗ (does NOT trigger)
        #   Third stop loss (BUY stop): 89.0 > 86.0 ✗ (does NOT trigger)
        #   Take profits (SELL limits, trigger when high >= price): 113.0 >= 110.0 ✓, 113.0 >= 112.0 ✓, 113.0 < 114.0 ✗, but takes are NEW, and stops have priority
        # Bar 2: low=87.0, stops=88.0, 86.0 - second stop triggers (87.0 <= 88.0), third stop does NOT trigger (87.0 > 86.0)
        # Bar 3: low=85.0, stop3=86.0 - third stop triggers (85.0 <= 86.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            highs=[101.0, 113.0, 100.0, 100.0],  # Bar 1 high=113.0 hits first two take profits at 110.0 and 112.0, but stops have priority
            lows=[99.0, 89.0, 87.0, 85.0]  # Bar 1 low=89.0 triggers limit entry at 95.0 and first stop at 90.0; Bar 2 low=87.0 triggers second stop at 88.0; Bar 3 low=85.0 triggers third stop at 86.0
        )
        
        # Protocol: On bar 0, enter BUY with limit (1.0 at 95.0) with three stops (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0) and three take profits (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Stop triggers: 90.0 (first stop executes as market, with slippage, fee_taker) - closes 0.3; 88.0 (second stop) - closes 0.3 on bar 2; 86.0 (third stop) - closes remaining 0.4 on bar 3
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third stop (extreme): 1.0 - 0.3 - 0.3 = 0.4
        # Take profits do NOT trigger
        entry_price = 95.0
        entry_quantity = 1.0
        stop_trigger_price1 = 90.0
        stop_trigger_price2 = 88.0
        stop_trigger_price3 = 86.0
        stop_quantity1 = 0.3  # First stop closes 0.3 position
        stop_quantity2 = 0.3  # Second stop closes 0.3 position
        stop_quantity3 = 0.4  # Third stop closes remaining 0.4 position
        take_prices = [110.0, 112.0, 114.0]  # All do NOT trigger (stops have priority)
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        # All stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 - test_task.slippage_in_steps * test_task.price_step  # 90.0 - 0.1 = 89.9 (SELL market, slippage decreases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 89.9 * 0.3 * 0.001 = 0.02697
        stop_execution2 = stop_trigger_price2 - test_task.slippage_in_steps * test_task.price_step  # 88.0 - 0.1 = 87.9 (SELL market, slippage decreases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 87.9 * 0.3 * 0.001 = 0.02637
        stop_execution3 = stop_trigger_price3 - test_task.slippage_in_steps * test_task.price_step  # 86.0 - 0.1 = 85.9 (SELL market, slippage decreases price)
        stop_fee3 = stop_execution3 * stop_quantity3 * test_task.fee_taker  # 85.9 * 0.4 * 0.001 = 0.03436
        
        entry_cost = entry_execution * entry_quantity + entry_fee  # 95.0 * 1.0 + 0.0475 = 95.0475
        exit_proceeds = (stop_execution1 * stop_quantity1 - stop_fee1 +
                         stop_execution2 * stop_quantity2 - stop_fee2 +
                         stop_execution3 * stop_quantity3 - stop_fee3)  # 26.93603 + 26.34363 + 34.32564 = 87.6053
        expected_profit = exit_proceeds - entry_cost  # = 87.6053 - 95.0475 = -7.4422
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': [(1.0, 95.0)],  # One limit order
                    'stop_loss': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0), all trigger sequentially
                    'take_profit': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)]  # Three take profits (0.33 + 0.33 + 0.34 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_e4_4_limit_entry_part_stops_part_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and first stop trigger on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and first stop trigger simultaneously (2 trades - entry + stop1), all take profits do NOT trigger
        # Bar 2: second stop triggers (3 trades total - entry + stop1 + stop2)
        # Bar 3: third stop triggers (4 trades total - entry + stop1 + stop2 + stop3)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and first stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third stop should trigger on bar 3"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all three stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All three stop loss orders should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 3, "All take profit orders should be canceled (deal closed by stops)"



# ============================================================================
# Group E4: One Entry, Multiple Stops, Multiple Take Profits - SELL
# ============================================================================

class TestSellSltpOneEntryMultipleStopsMultipleTakes:
    """Test E4: One entry, multiple stops, multiple take profits scenarios for sell_sltp."""
    
    def test_sell_sltp_limit_entry_all_stops_all_takes_simultaneous_stop_priority(self, test_task):
        """Test E4.1: Limit entry, all stops and all take profits hit simultaneously → entry + all stops trigger, all takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, all stops, and all take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=105.0, stops=110.0, 112.0, takes=90.0, 88.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 99.0 > 90.0)
        # Bar 1: high=113.0, low=87.0, limit=105.0, stops=110.0, 112.0, takes=90.0, 88.0 - entry and all stops trigger simultaneously, all takes do NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 113.0 >= 105.0 ✓
        #   First stop loss (SELL stop, triggers when high >= trigger_price): 113.0 >= 110.0 ✓
        #   Second stop loss (SELL stop): 113.0 >= 112.0 ✓
        #   Take profits (BUY limits, trigger when low <= price): 87.0 <= 90.0 ✓, 87.0 <= 88.0 ✓, but takes are NEW, and stops have priority
        # Bar 2: low=87.0, takes=90.0, 88.0 - take profits do NOT trigger (deal already closed by stops)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 113.0, 100.0],  # Bar 1 high=113.0 triggers limit entry at 105.0 and both stops at 110.0 and 112.0 simultaneously
            lows=[99.0, 87.0, 100.0]  # Bar 1 low=87.0 hits all take profits, but stops have priority
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with two stops (0.5 at 110.0, 0.5 at 112.0) and two take profits (0.5 at 90.0, 0.5 at 88.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 and 112.0 (both stops execute as market, with slippage, fee_taker) - close entire position
        # Expected: limit entry triggers on bar 1, both stops trigger on bar 1, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5
        # Take profits do NOT trigger
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price1 = 110.0
        stop_trigger_price2 = 112.0
        stop_quantity1 = 0.5  # First stop closes half position
        stop_quantity2 = 0.5  # Second stop closes remaining half position
        take_prices = [90.0, 88.0]  # All do NOT trigger
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # Stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        stop_execution2 = stop_trigger_price2 + test_task.slippage_in_steps * test_task.price_step  # 112.0 + 0.1 = 112.1 (BUY market, slippage increases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 112.1 * 0.5 * 0.001 = 0.05605
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = (stop_execution1 * stop_quantity1 + stop_fee1 +
                     stop_execution2 * stop_quantity2 + stop_fee2)  # 55.05505 + 56.05605 = 111.1111
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 111.1111 = -6.1636
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': [(0.5, 110.0), (0.5, 112.0)],  # Two stops (0.5 + 0.5 = 1.0)
                    'take_profit': [(0.5, 90.0), (0.5, 88.0)]  # Two take profits (0.5 + 0.5 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e4_1_limit_entry_all_stops_all_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and all stops trigger on bar 1, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and both stops trigger simultaneously (3 trades - entry + stop1 + stop2), all take profits do NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and both stops should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that both stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop loss orders should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 2, "All take profit orders should be canceled (deal closed by stops)"
    
    def test_sell_sltp_limit_entry_all_stops_part_takes_simultaneous_stop_priority(self, test_task):
        """Test E4.2: Limit entry, all stops and part of take profits hit simultaneously → entry + all stops trigger, part of takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, all stops, and part of take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=105.0, stops=110.0, 112.0, takes=90.0, 88.0, 86.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 99.0 > 90.0)
        # Bar 1: high=113.0, low=88.0, limit=105.0, stops=110.0, 112.0, takes=90.0, 88.0, 86.0 - entry and all stops trigger simultaneously, part of takes do NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 113.0 >= 105.0 ✓
        #   First stop loss (SELL stop, triggers when high >= trigger_price): 113.0 >= 110.0 ✓
        #   Second stop loss (SELL stop): 113.0 >= 112.0 ✓
        #   Take profits (BUY limits, trigger when low <= price): 88.0 <= 90.0 ✓, 88.0 <= 88.0 ✓, 88.0 > 86.0 ✗, but takes are NEW, and stops have priority
        # Bar 2: low=88.0, takes=90.0, 88.0, 86.0 - take profits do NOT trigger (deal already closed by stops)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0],
            highs=[101.0, 113.0, 100.0],  # Bar 1 high=113.0 triggers limit entry at 105.0 and both stops at 110.0 and 112.0 simultaneously
            lows=[99.0, 88.0, 100.0]  # Bar 1 low=88.0 hits first two take profits at 90.0 and 88.0, but stops have priority
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with two stops (0.5 at 110.0, 0.5 at 112.0) and three take profits (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 and 112.0 (both stops execute as market, with slippage, fee_taker) - close entire position
        # Expected: limit entry triggers on bar 1, both stops trigger on bar 1, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.5 * 1.0 / 0.1) * 0.1 = round(5.0) * 0.1 = 5 * 0.1 = 0.5
        #   Second stop (extreme): 1.0 - 0.5 = 0.5
        # Take profits do NOT trigger
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price1 = 110.0
        stop_trigger_price2 = 112.0
        stop_quantity1 = 0.5  # First stop closes half position
        stop_quantity2 = 0.5  # Second stop closes remaining half position
        take_prices = [90.0, 88.0, 86.0]  # All do NOT trigger (stops have priority)
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # Stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 110.1 * 0.5 * 0.001 = 0.05505
        stop_execution2 = stop_trigger_price2 + test_task.slippage_in_steps * test_task.price_step  # 112.0 + 0.1 = 112.1 (BUY market, slippage increases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 112.1 * 0.5 * 0.001 = 0.05605
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = (stop_execution1 * stop_quantity1 + stop_fee1 +
                     stop_execution2 * stop_quantity2 + stop_fee2)  # 55.05505 + 56.05605 = 111.1111
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 111.1111 = -6.1636
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': [(0.5, 110.0), (0.5, 112.0)],  # Two stops (0.5 + 0.5 = 1.0)
                    'take_profit': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)]  # Three take profits (0.33 + 0.33 + 0.34 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e4_2_limit_entry_all_stops_part_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and all stops trigger on bar 1, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and both stops trigger simultaneously (3 trades - entry + stop1 + stop2), all take profits do NOT trigger
        # Bar 2: no execution (deal already closed)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 3, "Entry and both stops should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "No additional trades on bar 2 (deal already closed)"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that both stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 2, "Should have two stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 2, "Both stop loss orders should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 3, "All take profit orders should be canceled (deal closed by stops)"
    
    def test_sell_sltp_limit_entry_part_stops_all_takes_simultaneous_stop_priority(self, test_task):
        """Test E4.3: Limit entry, part of stops and all take profits hit simultaneously → entry + part of stops trigger, all takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, part of stops, and all take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=105.0, stops=110.0, 112.0, 114.0, takes=90.0, 88.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 99.0 > 90.0)
        # Bar 1: high=111.0, low=99.0, limit=105.0, stops=110.0, 112.0, 114.0, takes=90.0, 88.0 - entry and first stop trigger simultaneously, all takes do NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 111.0 >= 105.0 ✓
        #   First stop loss (SELL stop, triggers when high >= trigger_price): 111.0 >= 110.0 ✓
        #   Second stop loss (SELL stop): 111.0 < 112.0 ✗ (does NOT trigger)
        #   Third stop loss (SELL stop): 111.0 < 114.0 ✗ (does NOT trigger)
        #   Take profits (BUY limits, trigger when low <= price): 99.0 > 90.0 ✗, 99.0 > 88.0 ✗, but takes are NEW, and stops have priority
        # Bar 2: high=113.0, low=99.0, stops=112.0, 114.0 - second stop triggers (113.0 >= 112.0), third stop does NOT trigger (113.0 < 114.0)
        # Bar 3: high=115.0, low=99.0, stop3=114.0 - third stop triggers (115.0 >= 114.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            highs=[101.0, 111.0, 113.0, 115.0],  # Bar 1 high=111.0 triggers limit entry at 105.0 and first stop at 110.0; Bar 2 high=113.0 triggers second stop at 112.0; Bar 3 high=115.0 triggers third stop at 114.0
            lows=[99.0, 99.0, 99.0, 99.0]  # Takes do NOT trigger (stops have priority)
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with three stops (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0) and two take profits (0.5 at 90.0, 0.5 at 88.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 (first stop executes as market, with slippage, fee_taker) - closes 0.3; 112.0 (second stop) - closes 0.3 on bar 2; 114.0 (third stop) - closes remaining 0.4 on bar 3
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third stop (extreme): 1.0 - 0.3 - 0.3 = 0.4
        # Take profits do NOT trigger
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price1 = 110.0
        stop_trigger_price2 = 112.0
        stop_trigger_price3 = 114.0
        stop_quantity1 = 0.3  # First stop closes 0.3 position
        stop_quantity2 = 0.3  # Second stop closes 0.3 position
        stop_quantity3 = 0.4  # Third stop closes remaining 0.4 position
        take_prices = [90.0, 88.0]  # All do NOT trigger (stops have priority)
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # All stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 110.1 * 0.3 * 0.001 = 0.03303
        stop_execution2 = stop_trigger_price2 + test_task.slippage_in_steps * test_task.price_step  # 112.0 + 0.1 = 112.1 (BUY market, slippage increases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 112.1 * 0.3 * 0.001 = 0.03363
        stop_execution3 = stop_trigger_price3 + test_task.slippage_in_steps * test_task.price_step  # 114.0 + 0.1 = 114.1 (BUY market, slippage increases price)
        stop_fee3 = stop_execution3 * stop_quantity3 * test_task.fee_taker  # 114.1 * 0.4 * 0.001 = 0.04564
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = (stop_execution1 * stop_quantity1 + stop_fee1 +
                     stop_execution2 * stop_quantity2 + stop_fee2 +
                     stop_execution3 * stop_quantity3 + stop_fee3)  # 33.03303 + 33.63363 + 45.64564 = 112.3123
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 112.3123 = -7.3648
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0), all trigger sequentially
                    'take_profit': [(0.5, 90.0), (0.5, 88.0)]  # Two take profits (0.5 + 0.5 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e4_3_limit_entry_part_stops_all_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and first stop trigger on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and first stop trigger simultaneously (2 trades - entry + stop1), all take profits do NOT trigger
        # Bar 2: second stop triggers (3 trades total - entry + stop1 + stop2)
        # Bar 3: third stop triggers (4 trades total - entry + stop1 + stop2 + stop3)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and first stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third stop should trigger on bar 3"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all three stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All three stop loss orders should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 2, "All take profit orders should be canceled (deal closed by stops)"
    
    def test_sell_sltp_limit_entry_part_stops_part_takes_simultaneous_stop_priority(self, test_task):
        """Test E4.4: Limit entry, part of stops and part of take profits hit simultaneously → entry + part of stops trigger, part of takes do NOT trigger."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry, part of stops, and part of take profits simultaneously
        # Bar 0: high=101.0, low=99.0, limit=105.0, stops=110.0, 112.0, 114.0, takes=90.0, 88.0, 86.0 - won't trigger (101.0 < 105.0, 101.0 < 110.0, 99.0 > 90.0)
        # Bar 1: high=111.0, low=99.0, limit=105.0, stops=110.0, 112.0, 114.0, takes=90.0, 88.0, 86.0 - entry and first stop trigger simultaneously, part of takes do NOT trigger
        #   Entry limit (SELL, triggers when high >= price): 111.0 >= 105.0 ✓
        #   First stop loss (SELL stop, triggers when high >= trigger_price): 111.0 >= 110.0 ✓
        #   Second stop loss (SELL stop): 111.0 < 112.0 ✗ (does NOT trigger)
        #   Third stop loss (SELL stop): 111.0 < 114.0 ✗ (does NOT trigger)
        #   Take profits (BUY limits, trigger when low <= price): 99.0 > 90.0 ✗, 99.0 > 88.0 ✗, 99.0 > 86.0 ✗, but takes are NEW, and stops have priority
        # Bar 2: high=113.0, low=99.0, stops=112.0, 114.0 - second stop triggers (113.0 >= 112.0), third stop does NOT trigger (113.0 < 114.0)
        # Bar 3: high=115.0, low=99.0, stop3=114.0 - third stop triggers (115.0 >= 114.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 100.0, 100.0, 100.0],
            highs=[101.0, 111.0, 113.0, 115.0],  # Bar 1 high=111.0 triggers limit entry at 105.0 and first stop at 110.0; Bar 2 high=113.0 triggers second stop at 112.0; Bar 3 high=115.0 triggers third stop at 114.0
            lows=[99.0, 99.0, 99.0, 99.0]  # Takes do NOT trigger (stops have priority)
        )
        
        # Protocol: On bar 0, enter SELL with limit (1.0 at 105.0) with three stops (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0) and three take profits (0.33 at 90.0, 0.33 at 88.0, 0.34 at 86.0)
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Stop triggers: 110.0 (first stop executes as market, with slippage, fee_taker) - closes 0.3; 112.0 (second stop) - closes 0.3 on bar 2; 114.0 (third stop) - closes remaining 0.4 on bar 3
        # Expected: limit entry triggers on bar 1, first stop triggers on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, all take profits do NOT trigger (stops have priority)
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Entry volume: 1.0 (no rounding needed)
        # Stop volumes: calculated from all requested entry volumes (1.0)
        #   First stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Second stop: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        #   Third stop (extreme): 1.0 - 0.3 - 0.3 = 0.4
        # Take profits do NOT trigger
        entry_price = 105.0
        entry_quantity = 1.0
        stop_trigger_price1 = 110.0
        stop_trigger_price2 = 112.0
        stop_trigger_price3 = 114.0
        stop_quantity1 = 0.3  # First stop closes 0.3 position
        stop_quantity2 = 0.3  # Second stop closes 0.3 position
        stop_quantity3 = 0.4  # Third stop closes remaining 0.4 position
        take_prices = [90.0, 88.0, 86.0]  # All do NOT trigger (stops have priority)
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * entry_quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        # All stops execute as market orders (with slippage, fee_taker)
        stop_execution1 = stop_trigger_price1 + test_task.slippage_in_steps * test_task.price_step  # 110.0 + 0.1 = 110.1 (BUY market, slippage increases price)
        stop_fee1 = stop_execution1 * stop_quantity1 * test_task.fee_taker  # 110.1 * 0.3 * 0.001 = 0.03303
        stop_execution2 = stop_trigger_price2 + test_task.slippage_in_steps * test_task.price_step  # 112.0 + 0.1 = 112.1 (BUY market, slippage increases price)
        stop_fee2 = stop_execution2 * stop_quantity2 * test_task.fee_taker  # 112.1 * 0.3 * 0.001 = 0.03363
        stop_execution3 = stop_trigger_price3 + test_task.slippage_in_steps * test_task.price_step  # 114.0 + 0.1 = 114.1 (BUY market, slippage increases price)
        stop_fee3 = stop_execution3 * stop_quantity3 * test_task.fee_taker  # 114.1 * 0.4 * 0.001 = 0.04564
        
        entry_proceeds = entry_execution * entry_quantity - entry_fee  # 105.0 * 1.0 - 0.0525 = 104.9475
        exit_cost = (stop_execution1 * stop_quantity1 + stop_fee1 +
                     stop_execution2 * stop_quantity2 + stop_fee2 +
                     stop_execution3 * stop_quantity3 + stop_fee3)  # 33.03303 + 33.63363 + 45.64564 = 112.3123
        expected_profit = entry_proceeds - exit_cost  # = 104.9475 - 112.3123 = -7.3648
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'sell_sltp',
                'args': {
                    'enter': [(1.0, 105.0)],  # One limit order
                    'stop_loss': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)],  # Three stops (0.33 + 0.33 + 0.34 = 1.0), all trigger sequentially
                    'take_profit': [(0.33, 90.0), (0.33, 88.0), (0.34, 86.0)]  # Three take profits (0.33 + 0.33 + 0.34 = 1.0)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_e4_4_limit_entry_part_stops_part_takes_simultaneous_stop_priority")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 4, f"Expected 4 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry and first stop trigger on bar 1, second stop triggers on bar 2, third stop triggers on bar 3, all take profits do NOT trigger
        # Bar 0: no execution (0 trades)
        # Bar 1: entry and first stop trigger simultaneously (2 trades - entry + stop1), all take profits do NOT trigger
        # Bar 2: second stop triggers (3 trades total - entry + stop1 + stop2)
        # Bar 3: third stop triggers (4 trades total - entry + stop1 + stop2 + stop3)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 2, "Entry and first stop should trigger simultaneously on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Second stop should trigger on bar 2"
        assert collected_data[3]['trades_count'] == 4, "Third stop should trigger on bar 3"
        
        # Check final state: deal should be closed by stops
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
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that all three stop orders were executed
        stop_orders = [o for o in deal.orders if o.order_group == OrderGroup.STOP_LOSS]
        assert len(stop_orders) == 3, "Should have three stop loss orders"
        executed_stops = [o for o in stop_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_stops) == 3, "All three stop loss orders should be executed"
        
        # Check that all take profit orders were NOT executed (stops have priority)
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 0, "All take profit orders should NOT be executed (stops have priority)"
        # All take profits should be CANCELED (deal closed by stops)
        canceled_takes = [o for o in take_orders if o.status == OrderStatus.CANCELED]
        assert len(canceled_takes) == 3, "All take profit orders should be canceled (deal closed by stops)"
