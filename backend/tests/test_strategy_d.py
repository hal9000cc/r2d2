"""
Tests for Strategy class - buy_sltp/sell_sltp methods - Group D.

Group D: Order Execution - Complex Cases (Entries + Takes Simultaneously)
Tests scenarios where entry orders and take profit orders trigger:
- D1: One entry, one take profit
- D2: One entry, multiple take profits
- D3: Multiple entries, all take profits
- D4: Multiple entries, part of take profits

IMPORTANT: Rules for simultaneous order execution:
1. After placing all orders (entry, stop, take): entry and stop are ACTIVE, take is NEW (not active)
2. On the same bar, entry and stop can trigger simultaneously
3. Take profit CANNOT trigger on the same bar as entry - it activates only after entry executes
4. Take profit can trigger on the next bar (or later) after entry has executed
5. Therefore, in tests where entry and take are both hit by price on the same bar:
   - Entry triggers on bar N
   - Take profit activates after entry executes
   - Take profit triggers on bar N+1 (or later) if price conditions are met
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
# Group D1: One Entry, One Take Profit - BUY
# ============================================================================

class TestBuySltpOneEntryOneTake:
    """Test D1: One entry, one take profit scenarios for buy_sltp."""
    
    def test_buy_sltp_limit_entry_take_simultaneous(self, test_task):
        """Test D1.1: Limit entry and take profit hit on same bar → entry triggers on bar 1, take triggers on bar 2."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry on bar 1, take profit on bar 2
        # Bar 0: high=101.0, low=99.0, limit=95.0, take=110.0 - won't trigger (99.0 > 95.0 for limit, 101.0 < 110.0 for take)
        # Bar 1: high=112.0, low=94.0, limit=95.0, take=110.0 - entry triggers (94.0 <= 95.0), take activates but doesn't trigger yet
        #   Entry limit (BUY, triggers when low <= price): 94.0 <= 95.0 ✓
        #   Take profit (SELL limit, triggers when high >= price): 112.0 >= 110.0 ✓, but take is NEW, activates after entry executes
        # Bar 2: high=112.0, take=110.0 - take profit triggers (112.0 >= 110.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 103.0, 112.0],
            highs=[101.0, 112.0, 112.0],  # Bar 1 high=112.0 (entry triggers), Bar 2 high=112.0 triggers take profit at 110.0 (112.0 >= 110.0)
            lows=[99.0, 94.0, 111.0]  # Bar 1 low=94.0 triggers entry limit at 95.0 (94.0 <= 95.0)
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stop loss 90.0 and take profit 110.0
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Take trigger: 110.0 (take executes as limit, no slippage, fee_maker)
        # Expected: limit entry triggers on bar 1, take profit activates and triggers on bar 2
        # Expected profit calculation:
        entry_price = 95.0
        quantity = 1.0
        take_price = 110.0
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        exit_execution = take_price  # 110.0 (limit, no slippage)
        exit_fee = exit_execution * quantity * test_task.fee_maker  # 110.0 * 1.0 * 0.0005 = 0.055
        
        entry_cost = entry_execution * quantity + entry_fee  # 95.0*1.0 + 0.0475 = 95.0475
        exit_proceeds = exit_execution * quantity - exit_fee  # 110.0*1.0 - 0.055 = 109.945
        expected_profit = exit_proceeds - entry_cost  # = 109.945 - 95.0475 = 14.8975
        
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_d1_1_limit_entry_take_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 1, take profit triggers on bar 2
        # Bar 0: no execution (0 trades)
        # Bar 1: entry triggers (1 trade - entry), take profit activates but doesn't trigger yet
        # Bar 2: take profit triggers (2 trades total - entry + take)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 1, "Entry should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 2, "Take profit should trigger on bar 2"
        
        # Check final state: deal should be closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 2, f"Expected 2 trades total (entry + take), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that take profit order was executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 1, "Take profit order should be executed"


# ============================================================================
# Group D1: One Entry, One Take Profit - SELL
# ============================================================================

class TestSellSltpOneEntryOneTake:
    """Test D1: One entry, one take profit scenarios for sell_sltp."""
    
    def test_sell_sltp_limit_entry_take_simultaneous(self, test_task):
        """Test D1.1: Limit entry and take profit hit on same bar → entry triggers on bar 1, take triggers on bar 2."""
        # Prepare quotes data: price 100.0, then price moves to trigger limit entry on bar 1, take profit on bar 2
        # Bar 0: high=101.0, low=99.0, limit=105.0, take=90.0 - won't trigger (101.0 < 105.0 for limit, 99.0 > 90.0 for take)
        # Bar 1: high=106.0, low=89.0, limit=105.0, take=90.0 - entry triggers (106.0 >= 105.0), take activates but doesn't trigger yet
        #   Entry limit (SELL, triggers when high >= price): 106.0 >= 105.0 ✓
        #   Take profit (BUY limit, triggers when low <= price): 89.0 <= 90.0 ✓, but take is NEW, activates after entry executes
        # Bar 2: low=89.0, take=90.0 - take profit triggers (89.0 <= 90.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 97.0, 89.0],
            highs=[101.0, 106.0, 92.0],  # Bar 1 high=106.0 triggers entry limit at 105.0 (106.0 >= 105.0)
            lows=[99.0, 89.0, 89.0]  # Bar 1 low=89.0 (entry triggers), Bar 2 low=89.0 triggers take profit at 90.0 (89.0 <= 90.0)
        )
        
        # Protocol: On bar 0, enter limit at 105.0 with stop loss 110.0 and take profit 90.0
        # Entry price: 105.0 (limit, no slippage, fee_maker)
        # Take trigger: 90.0 (take executes as limit, no slippage, fee_maker)
        # Expected: limit entry triggers on bar 1, take profit activates and triggers on bar 2
        # Expected profit calculation:
        entry_price = 105.0
        quantity = 1.0
        take_price = 90.0
        
        entry_execution = entry_price  # 105.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 105.0 * 1.0 * 0.0005 = 0.0525
        
        exit_execution = take_price  # 90.0 (limit, no slippage)
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_sell_d1_1_limit_entry_take_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 1, take profit triggers on bar 2
        # Bar 0: no execution (0 trades)
        # Bar 1: entry triggers (1 trade - entry), take profit activates but doesn't trigger yet
        # Bar 2: take profit triggers (2 trades total - entry + take)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 1, "Entry should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 2, "Take profit should trigger on bar 2"
        
        # Check final state: deal should be closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 2, f"Expected 2 trades total (entry + take), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that take profit order was executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 1, "Should have one take profit order"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 1, "Take profit order should be executed"


# ============================================================================
# Group D2: One Entry, Multiple Take Profits - BUY
# ============================================================================

class TestBuySltpOneEntryMultipleTakes:
    """Test D2: One entry, multiple take profits scenarios for buy_sltp."""
    
    def test_buy_sltp_limit_entry_all_takes_simultaneous(self, test_task):
        """Test D2.1: Limit entry and all take profits hit on same bar → entry triggers on bar 1, all takes trigger on bar 2."""
        # Prepare quotes data: price 100.0, then rises to trigger limit entry on bar 1, all take profits on bar 2
        # Bar 0: high=101.0, low=99.0, limit=95.0, takes at 110.0 and 112.0 - won't trigger (99.0 > 95.0 for limit, 101.0 < 110.0 for takes)
        # Bar 1: high=113.0, low=94.0, limit=95.0, takes at 110.0 and 112.0 - entry triggers (94.0 <= 95.0), takes activate but don't trigger yet
        #   Entry limit (BUY, triggers when low <= price): 94.0 <= 95.0 ✓
        #   Take profits (SELL limits, trigger when high >= price): 113.0 >= 110.0 ✓, 113.0 >= 112.0 ✓, but takes are NEW, activate after entry executes
        # Bar 2: high=113.0, takes at 110.0 and 112.0 - both take profits trigger (113.0 >= 110.0, 113.0 >= 112.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 103.0, 113.0],
            highs=[101.0, 113.0, 113.0],  # Bar 1 high=113.0 (entry triggers), Bar 2 high=113.0 triggers both take profits at 110.0 and 112.0 (113.0 >= 110.0, 113.0 >= 112.0)
            lows=[99.0, 94.0, 112.0]  # Bar 1 low=94.0 triggers entry limit at 95.0 (94.0 <= 95.0)
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stop loss 90.0 and two take profits (0.5 at 110.0, 0.5 at 112.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Take triggers: 110.0 and 112.0 (takes execute as limits, no slippage, fee_maker)
        # Expected: limit entry triggers on bar 1, both take profits activate and trigger on bar 2
        # Expected profit calculation:
        entry_price = 95.0
        quantity = 1.0
        take_price1 = 110.0
        take_price2 = 112.0
        take_quantity1 = 0.5
        take_quantity2 = 0.5
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        exit_execution1 = take_price1  # 110.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * take_quantity1 * test_task.fee_maker  # 110.0 * 0.5 * 0.0005 = 0.0275
        exit_execution2 = take_price2  # 112.0 (limit, no slippage)
        exit_fee2 = exit_execution2 * take_quantity2 * test_task.fee_maker  # 112.0 * 0.5 * 0.0005 = 0.028
        
        entry_cost = entry_execution * quantity + entry_fee  # 95.0*1.0 + 0.0475 = 95.0475
        total_exit_proceeds = exit_execution1 * take_quantity1 - exit_fee1 + exit_execution2 * take_quantity2 - exit_fee2  # 110.0*0.5 - 0.0275 + 112.0*0.5 - 0.028 = 110.9445
        expected_profit = total_exit_proceeds - entry_cost  # = 110.9445 - 95.0475 = 15.897
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit order at 95.0
                    'stop_loss': 90.0,
                    'take_profit': [(0.5, 110.0), (0.5, 112.0)]  # Two take profits with equal shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_d2_1_limit_entry_all_takes_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 1, both take profits trigger on bar 2
        # Bar 0: no execution (0 trades)
        # Bar 1: entry triggers (1 trade - entry), take profits activate but don't trigger yet
        # Bar 2: both take profits trigger (3 trades total - entry + take1 + take2)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 1, "Entry should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 3, "Both take profits should trigger on bar 2"
        
        # Check final state: deal should be closed
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count
        assert len(broker.trades) == 3, f"Expected 3 trades total (entry + take1 + take2), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that both take profit orders were executed
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 2, "Should have two take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "Both take profit orders should be executed"
    
    def test_buy_sltp_limit_entry_part_takes_simultaneous(self, test_task):
        """Test D2.2: Limit entry and part of take profits hit on same bar → entry triggers on bar 1, part of takes trigger on bar 2."""
        # Prepare quotes data: price 100.0, then rises to trigger limit entry on bar 1, part of take profits on bar 2
        # Bar 0: high=101.0, low=99.0, limit=95.0, takes at 110.0, 112.0, 114.0 - won't trigger (99.0 > 95.0 for limit, 101.0 < 110.0 for takes)
        # Bar 1: high=113.0, low=94.0, limit=95.0, takes at 110.0, 112.0, 114.0 - entry triggers (94.0 <= 95.0), takes activate but don't trigger yet
        #   Entry limit (BUY, triggers when low <= price): 94.0 <= 95.0 ✓
        #   Take profits (SELL limits, trigger when high >= price): 113.0 >= 110.0 ✓, 113.0 >= 112.0 ✓, 113.0 < 114.0 ✗, but takes are NEW, activate after entry executes
        # Bar 2: high=113.0, takes at 110.0, 112.0, 114.0 - first two take profits trigger (113.0 >= 110.0, 113.0 >= 112.0), third doesn't trigger (113.0 < 114.0)
        quotes_data = create_custom_quotes_data(
            prices=[100.0, 103.0, 113.0],
            highs=[101.0, 113.0, 113.0],  # Bar 1 high=113.0 (entry triggers), Bar 2 high=113.0 triggers first two take profits at 110.0 and 112.0 (113.0 >= 110.0, 113.0 >= 112.0) but not third at 114.0 (113.0 < 114.0)
            lows=[99.0, 94.0, 112.0]  # Bar 1 low=94.0 triggers entry limit at 95.0 (94.0 <= 95.0)
        )
        
        # Protocol: On bar 0, enter limit at 95.0 with stop loss 90.0 and three take profits (0.33 at 110.0, 0.33 at 112.0, 0.34 at 114.0)
        # Entry price: 95.0 (limit, no slippage, fee_maker)
        # Take triggers: 110.0 and 112.0 (takes execute as limits, no slippage, fee_maker)
        # Expected: limit entry triggers on bar 1, first two take profits activate and trigger on bar 2, third take remains active
        # Expected profit calculation (with volume rounding to precision_amount=0.1):
        # Volume calculation rules:
        # 1. Entry volumes are rounded DOWN (floor_to_precision) independently for each order
        # 2. Take profit volumes are calculated from TOTAL actual rounded-down entry volumes (sum of all rounded entries), not from requested volumes
        # 3. Last take profit (extreme) always closes all remaining volume
        # Entry volume (rounded down):
        # Quantity: 1.0 (no rounding needed, already at precision)
        # Total actual rounded entry volume: 1.0 (for take calculation)
        entry_price = 95.0
        quantity = 1.0
        total_rounded_entry_volume = 1.0  # For take calculation
        take_price1 = 110.0
        take_price2 = 112.0
        # Takes are calculated from TOTAL actual rounded-down entry volumes (1.0)
        # Fractions: 0.33, 0.33, 0.34
        # First take: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        # Second take: round(0.33 * 1.0 / 0.1) * 0.1 = round(3.3) * 0.1 = 3 * 0.1 = 0.3
        # Third take (extreme, gets remainder): 1.0 - 0.3 - 0.3 = 0.4 (but doesn't trigger)
        # First two takes trigger, closing 0.3 + 0.3 = 0.6 of 1.0
        take_quantity1 = 0.3  # round(0.33 * 1.0 / 0.1) * 0.1 = 0.3
        take_quantity2 = 0.3  # round(0.33 * 1.0 / 0.1) * 0.1 = 0.3
        remaining_quantity = quantity - take_quantity1 - take_quantity2  # 1.0 - 0.3 - 0.3 = 0.4
        
        entry_execution = entry_price  # 95.0 (limit, no slippage)
        entry_fee = entry_execution * quantity * test_task.fee_maker  # 95.0 * 1.0 * 0.0005 = 0.0475
        
        exit_execution1 = take_price1  # 110.0 (limit, no slippage)
        exit_fee1 = exit_execution1 * take_quantity1 * test_task.fee_maker  # 110.0 * 0.3 * 0.0005 = 0.0165
        exit_execution2 = take_price2  # 112.0 (limit, no slippage)
        exit_fee2 = exit_execution2 * take_quantity2 * test_task.fee_maker  # 112.0 * 0.3 * 0.0005 = 0.0168
        
        # Remaining position (0.4) will be auto-closed at end of test at bar 2 closing price (113.0)
        auto_close_price = 113.0  # Price close of last bar (bar 2)
        auto_close_execution = auto_close_price - test_task.slippage_in_steps * test_task.price_step  # 113.0 - 0.1 = 112.9 (SELL market, slippage decreases price)
        auto_close_fee = auto_close_execution * remaining_quantity * test_task.fee_taker  # 112.9 * 0.4 * 0.001 = 0.04516
        
        entry_cost = entry_execution * quantity + entry_fee  # 95.0*1.0 + 0.0475 = 95.0475
        total_exit_proceeds = exit_execution1 * take_quantity1 - exit_fee1 + exit_execution2 * take_quantity2 - exit_fee2 + auto_close_execution * remaining_quantity - auto_close_fee  # 110.0*0.3 - 0.0165 + 112.0*0.3 - 0.0168 + 112.9*0.4 - 0.04516 = 32.9835 + 33.5832 + 45.11484 = 111.68154
        expected_profit = total_exit_proceeds - entry_cost  # = 111.68154 - 95.0475 = 16.63404
        
        protocol = [
            {
                'bar_index': 0,
                'method': 'buy_sltp',
                'args': {
                    'enter': (1.0, 95.0),  # Limit order at 95.0
                    'stop_loss': 90.0,
                    'take_profit': [(0.33, 110.0), (0.33, 112.0), (0.34, 114.0)]  # Three take profits with shares
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
                broker, strategy = create_broker_and_strategy(test_task, quotes_data, "test_buy_d2_2_limit_entry_part_takes_simultaneous")
                broker.run(save_results=False)
        
        # Check results
        assert len(collected_data) == 3, f"Expected 3 bars, got {len(collected_data)}"
        
        # Check method result on bar 0
        assert collected_data[0]['method_result'] is not None
        method_result = collected_data[0]['method_result']
        assert isinstance(method_result, OrderOperationResult)
        assert len(method_result.error_messages) == 0, f"Unexpected errors: {method_result.error_messages}"
        assert method_result.deal_id > 0
        
        # Check that entry triggers on bar 1, first two take profits trigger on bar 2
        # Bar 0: no execution (0 trades)
        # Bar 1: entry triggers (1 trade - entry), take profits activate but don't trigger yet
        # Bar 2: first two take profits trigger (3 trades total - entry + take1 + take2)
        assert collected_data[0]['trades_count'] == 0, "No execution on bar 0"
        assert collected_data[1]['trades_count'] == 1, "Entry should trigger on bar 1"
        assert collected_data[2]['trades_count'] == 3, "First two take profits should trigger on bar 2"
        
        # Check final state: deal should be closed (auto-closed at end)
        deal = broker.get_deal_by_id(method_result.deal_id)
        assert deal is not None, "Deal should exist"
        assert deal.quantity == 0.0, f"Deal should be closed (quantity=0), got {deal.quantity}"
        assert deal.is_closed, "Deal should be closed"
        assert deal.profit is not None, "Deal profit should be calculated"
        
        # Check total trades count (including auto-close)
        assert len(broker.trades) == 4, f"Expected 4 trades total (entry + take1 + take2 + auto_close), got {len(broker.trades)}"
        
        # Check actual profit matches expected calculation
        assert abs(deal.profit - expected_profit) < 0.01, \
            f"Expected profit {expected_profit}, got {deal.profit}"
        
        # Check that entry order was executed
        entry_orders = [o for o in deal.orders if o.order_group == OrderGroup.NONE and o.order_type == OrderType.LIMIT]
        assert len(entry_orders) == 1, "Should have one entry limit order"
        executed_entries = [o for o in entry_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_entries) == 1, "Entry order should be executed"
        
        # Check that first two take profit orders were executed, third remains active
        take_orders = [o for o in deal.orders if o.order_group == OrderGroup.TAKE_PROFIT]
        assert len(take_orders) == 3, "Should have three take profit orders"
        executed_takes = [o for o in take_orders if o.status == OrderStatus.EXECUTED]
        assert len(executed_takes) == 2, "First two take profit orders should be executed"
        active_takes = [o for o in take_orders if o.status == OrderStatus.ACTIVE]
        assert len(active_takes) == 0, "No take profit orders should remain active after auto-close"

