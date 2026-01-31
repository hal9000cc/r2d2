from abc import ABC, abstractmethod
from enum import Enum, IntEnum
from typing import List, Optional, Set, Dict, Any, Tuple, Union, TYPE_CHECKING
import math
import sys
import time

import numpy as np
from pydantic import BaseModel, Field, ConfigDict, model_validator, PrivateAttr

from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.indicator_proxy import ta_proxy_talib
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType
from app.core.config import BAR_WAIT_INTERVAL, ORDER_WAIT_INTERVAL
from app.core.logger import get_logger
from app.core.datetime_utils import datetime64_to_iso
from app.services.tasks.enums import (
    OrderSide,
    OrderType,
    OrderStatus,
    OrderGroup,
    DealType,
    BarStatus
)
from app.services.tasks.trading_stats import TradingStats

if TYPE_CHECKING:
    from app.services.tasks.tasks import Task
    from app.services.tasks.task_results import TaskResults


logger = get_logger(__name__)


class Trade(BaseModel):
    """
    Represents a single trade (buy or sell operation).
    
    Note: deal_id may be assigned after creation.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        frozen=False  # Allow field modifications (deal_id may be set after creation)
    )

    trade_id: int = Field(gt=0, description="Trade ID, must be greater than 0")
    exchange_trade_id: str = Field(description="Exchange trade ID from exchange API")
    deal_id: int = Field(gt=0, description="Deal ID, must be greater than 0")
    order_id: int = Field(gt=0, description="Order ID, must be greater than 0")
    time: np.datetime64
    side: OrderSide
    price: PRICE_TYPE
    quantity: VOLUME_TYPE
    fee: PRICE_TYPE
    sum: PRICE_TYPE
    
    @model_validator(mode='after')
    def validate_trade(self):
        """Validate that all required fields are filled."""
        # Check that numeric fields are not None and have valid values
        if self.price is None:
            raise ValueError("price must be set")
        if self.quantity is None:
            raise ValueError("quantity must be set")
        if self.fee is None:
            raise ValueError("fee must be set")
        if self.sum is None:
            raise ValueError("sum must be set")
        if not self.exchange_trade_id:
            raise ValueError("exchange_trade_id must be set")
        
        return self


class Order(BaseModel):
    """
    Represents an order.
    
    Can be a limit order or a conditional order (stop order):
    - Limit order: only `price` is set. Executes when market price reaches limit price.
    - Stop order: `trigger_price` is set. Executes when market price reaches trigger price.
    - Stop-limit order: both `price` and `trigger_price` are set. When trigger_price is reached,
      a limit order at `price` is placed.
    
    Immutable fields (cannot be changed after creation): order_id, deal_id, order_type, create_time, side, price, trigger_price.
    """
    
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        frozen=False,  # Allow field modifications
        validate_assignment=True  # Validate on field assignment
    )
    
    # Immutable fields (set at creation, cannot be changed)
    order_id: int = Field(gt=0, description="Order ID, must be greater than 0")
    deal_id: int = Field(gt=0, description="Deal ID, must be greater than 0")
    order_type: OrderType
    create_time: np.datetime64
    side: OrderSide
    price: Optional[PRICE_TYPE] = None
    trigger_price: Optional[PRICE_TYPE] = None
    
    # Mutable fields
    modify_time: np.datetime64
    volume: VOLUME_TYPE
    filled_volume: VOLUME_TYPE = 0.0
    status: OrderStatus = OrderStatus.NEW
    order_group: OrderGroup = OrderGroup.NONE
    fraction: Optional[float] = None
    fraction_remain: Optional[float] = None
    exchange_order_id: Optional[Union[str, int]] = None
    actual: bool = False
    
    # Fields that require exchange synchronization when changed
    _sync_fields: Set[str] = {'status', 'volume', 'price'}

    @model_validator(mode='after')
    def validate_order(self):
        """Validate order fields.
        
        - order_id and deal_id must be greater than 0
        - Either price or trigger_price must be set (not both None)
        - If status is ACTIVE, volume must be greater than 0
        - fraction must be set for orders with order_group != NONE
        """
        # Validate order_id and deal_id (already checked by Field(gt=0), but double-check)
        if self.order_id <= 0:
            raise ValueError(f"order_id must be greater than 0, got {self.order_id}")
        if self.deal_id <= 0:
            raise ValueError(f"deal_id must be greater than 0, got {self.deal_id}")
        
        # Validate that either price or trigger_price is set (except for MARKET orders)
        if self.order_type != OrderType.MARKET and self.price is None and self.trigger_price is None:
            raise ValueError("Either 'price' or 'trigger_price' must be set (not both None) for non-MARKET orders")
        
        # Validate volume for ACTIVE orders
        if self.status == OrderStatus.ACTIVE and self.volume <= 0:
            raise ValueError(f"volume must be greater than 0 for orders with status ACTIVE, got {self.volume}")
        
        # Validate fraction for exit orders
        if self.order_group != OrderGroup.NONE and self.fraction is None:
            raise ValueError(f"fraction must be set for orders with order_group={self.order_group}")
        
        # Validate volume is non-negative
        if self.volume < 0:
            raise ValueError(f"volume must be greater than or equal to 0, got {self.volume}")
        
        return self
    
    def update_modify_time(self, broker: 'Broker') -> None:
        """
        Update modify_time to broker's current_time.
        
        Args:
            broker: Broker instance to get current_time from
        """
        assert broker.current_time is not None, "Broker's current_time must be set"
        self.modify_time = broker.current_time
    
    def _set_sync_field(self, field_name: str, new_value: Any) -> None:
        """
        Set field value and mark order as unsynced with exchange if value changed.
        
        Fields that affect exchange synchronization: status, volume, price.
        If field value changed, sets actual=False to indicate need for exchange synchronization.
        
        Args:
            field_name: Name of the field to set
            new_value: New value for the field
        """
        if field_name in self._sync_fields:
            old_value = getattr(self, field_name, None)
            if old_value != new_value:
                self.actual = False
        
        # Set the field value
        setattr(self, field_name, new_value)
    
    def cancel(self, broker: 'Broker') -> None:
        """
        Cancel this order.
        
        Updates order status based on filled_volume:
        - If filled_volume == 0, sets status to CANCELED
        - If filled_volume > 0, sets status to EXECUTED
        
        Resets actual flag if status changed.
        
        Args:
            broker: Broker instance to get current_time from
        
        Raises:
            AssertionError: If order status is not ACTIVE or NEW
        """
        # Check that order can be canceled
        assert self.status in (OrderStatus.ACTIVE, OrderStatus.NEW), \
            f"Cannot cancel order with status {self.status}"
        
        # Determine new status based on filled_volume
        if self.filled_volume == 0:
            new_status = OrderStatus.CANCELED
        else:
            new_status = OrderStatus.EXECUTED
        
        # Set status and mark as unsynced if changed
        self._set_sync_field('status', new_status)
        
        # Update modify_time
        self.update_modify_time(broker)


class Deal(BaseModel):
    """
    Trading deal that groups multiple trades and orders.

    - Accumulates trades belonging to a single logical deal.
    - Accumulates orders (entry and exit) belonging to a single logical deal.
    - Tracks average buy and sell prices across all trades.
    - Tracks current position quantity, total fees and profit.
    - Stores initial entry volume for deals created via buy_sltp/sell_sltp (used for calculating stop/take volumes).
    - Marks automatic deals (auto=True) created via Strategy.buy/sell methods.
    """

    deal_id: int = Field(gt=0)
    trades: List[Trade] = Field(default_factory=list)
    orders: List[Order] = Field(default_factory=list)  # List of orders (entry and exit) associated with this deal

    # Deal type (long/short) - determined by first trade
    type: Optional[DealType] = None

    # Average prices across all buy / sell trades in the deal
    avg_buy_price: Optional[PRICE_TYPE] = None
    avg_sell_price: Optional[PRICE_TYPE] = None

    # Current position quantity in symbol units; becomes 0 when fully closed
    quantity: VOLUME_TYPE = 0.0

    # Aggregated fees and realized profit for the deal
    fee: PRICE_TYPE = 0.0
    profit: Optional[PRICE_TYPE] = None
    
    # Deal closed status (set to True when quantity == 0 and no active entry orders)
    is_closed: bool = False
    
    # Emergency close flag (set to True if errors occurred during order cancellation when closing deal)
    need_emergency_close: bool = False
    
    # List of error messages for the deal
    errors: List[str] = Field(default_factory=list)
    
    # Type of deal closure (copied from last exit order's order_group, or NONE if closed via regular buy/sell)
    close_type: Optional[OrderGroup] = None
    
    # Internal accumulators for efficient incremental updates
    buy_quantity: VOLUME_TYPE = 0.0
    buy_cost: PRICE_TYPE = 0.0
    sell_quantity: VOLUME_TYPE = 0.0
    sell_proceeds: PRICE_TYPE = 0.0
    
    def add_trade(self, broker: 'Broker', trade: Trade, precision_amount: float) -> None:
        """
        Add trade to the deal and update aggregates incrementally.

        - Sets trade.deal_id to this deal_id.
        - Sets deal type (long/short) based on first trade if not set.
        - Updates quantity, avg_buy_price, avg_sell_price, fee and profit.
        
        Args:
            trade: Trade to add
            precision_amount: Precision for rounding quantity (default: 1e-8)
        """

        assert trade.quantity > 0, f"Trade quantity must be greater than 0, got {trade.quantity}"
        
        trade.deal_id = self.deal_id
        self.trades.append(trade)

        self.fee += trade.fee

        if trade.side == OrderSide.BUY:
            self.buy_quantity += trade.quantity
            self.buy_cost += trade.sum
            self.quantity = round((self.quantity + trade.quantity) / precision_amount) * precision_amount
        else:
            self.sell_quantity += trade.quantity
            self.sell_proceeds += trade.sum
            self.quantity = round((self.quantity - trade.quantity) / precision_amount) * precision_amount

        self.avg_buy_price = (
            self.buy_cost / self.buy_quantity if self.buy_quantity > 0 else None
        )
        self.avg_sell_price = (
            self.sell_proceeds / self.sell_quantity if self.sell_quantity > 0 else None
        )

        # Calculate profit when deal is closed (quantity == 0)
        if self.quantity == 0:
            self.profit = self.sell_proceeds - self.buy_cost - self.fee
        else:
            self.profit = None
        
        # Close the deal if quantity == 0 and no active entry orders
        if self.quantity == 0:
            has_active_entry_orders = any(
                order.status in (OrderStatus.ACTIVE, OrderStatus.NEW)
                and order.order_group == OrderGroup.NONE
                for order in self.orders
            )
            
            if not has_active_entry_orders:
                # Close the deal: cancel all active/new orders
                for order in self.orders:
                    if order.status in (OrderStatus.ACTIVE, OrderStatus.NEW):
                        order.cancel(broker)
                
                self.is_closed = True

    def unrealized_profit(self, broker: 'Broker') -> Optional[PRICE_TYPE]:
        """
        Calculate unrealized profit for an open position at current_price from broker.

        For closed positions, the result matches the realized profit.
        
        Args:
            broker: Broker instance to get current_price from
        
        Returns:
            Unrealized profit if current_price is available, None otherwise
        """
        current_price = broker.current_price
        
        # Value of current open position at market price
        current_value = self.quantity * current_price

        # Hypothetical total PnL if we closed the position now:
        # (all sells done + value of remaining position) - all buys - all fees
        return self.sell_proceeds + current_value - self.buy_cost - self.fee
    
    def cancel_orders(self, broker: 'Broker', group: Optional[OrderGroup] = None) -> List['Order']:
        """
        Cancel orders in this deal by specified group.
        
        Filters orders by group and status (ACTIVE or NEW), then cancels each one.
        Orders remain in deal's orders list for history tracking.
        
        Args:
            broker: Broker instance
            group: OrderGroup to filter by. If None, cancels all active/new orders.
        
        Returns:
            List of orders that were canceled (for information only).
        """
        # Filter orders by group and status
        if group is None:
            orders_to_cancel = [o for o in self.orders if o.status in (OrderStatus.ACTIVE, OrderStatus.NEW)]
        else:
            orders_to_cancel = [o for o in self.orders if o.order_group == group and o.status in (OrderStatus.ACTIVE, OrderStatus.NEW)]
        
        # Cancel each order
        for order in orders_to_cancel:
            order.cancel(broker)
        
        return orders_to_cancel
    
    def add_order(self, order: 'Order') -> None:
        """
        Add order to deal's orders list.
        
        Adds order to self.orders and sets order.deal_id to this deal_id.
        
        Args:
            order: Order to add
        """
        order.deal_id = self.deal_id
        self.orders.append(order)
    
    def calc_fraction_remain(self, broker: 'Broker', order_group: OrderGroup) -> None:
        """
        Calculate fraction_remain for orders of specified group.
        
        Sorts orders by price/trigger_price and calculates fraction_remain using
        cumulative remain algorithm. For stop losses: fraction must be set (assert).
        For take profits: fraction must be set (assert).
        
        Args:
            order_group: OrderGroup to process (STOP_LOSS or TAKE_PROFIT)
        """
        # Filter orders by group and status
        orders = [
            order for order in self.orders
            if order.order_group == order_group and order.status in (OrderStatus.ACTIVE, OrderStatus.NEW)
        ]
        
        if not orders:
            return
        
        # Determine sort direction based on deal type and order group
        if order_group == OrderGroup.STOP_LOSS:
            # For LONG: sort by trigger_price descending (farthest down first)
            # For SHORT: sort by trigger_price ascending (farthest up first)
            reverse = (self.type == DealType.LONG)
            # Sort by trigger_price
            orders.sort(key=lambda o: o.trigger_price if o.trigger_price is not None else float('-inf'), reverse=reverse)
        else:  # TAKE_PROFIT
            # For LONG: sort by price ascending (farthest up first)
            # For SHORT: sort by price descending (farthest down first)
            reverse = (self.type == DealType.SHORT)
            # Sort by price
            orders.sort(key=lambda o: o.price if o.price is not None else float('-inf'), reverse=reverse)
        
        # Initialize remain
        remain = 1.0
        
        # Process each order
        for order in orders:
            # Assert that fraction is set for stop/take orders
            assert order.fraction is not None, f"Order {order.order_id} must have fraction set for order_group {order_group}"
            
            # Calculate fraction_remain
            order.fraction_remain = order.fraction / remain
            order.update_modify_time(broker)
            
            # Update remain
            remain = remain - order.fraction
        
        # Assert that remain is 0 after processing all orders
        assert abs(remain) < 1e-10, f"Remain should be 0 after processing all orders, got {remain}"
    
    def update_order_volumes(self, broker: 'Broker') -> None:
        """
        Update volumes for stop loss and take profit orders.
        
        Calculates volumes based on simulated volume and fraction_remain.
        First updates stop losses, then take profits.
        
        Args:
            broker: Broker instance for format_volume
        """
        self.update_stop_loss_volumes(broker)
        self.update_take_profit_volumes(broker)
    
    def start(self, broker: 'Broker') -> List['Order']:
        """
        Start deal: update orders and activate entry and stop loss orders.
        
        First calls update_orders() to calculate volumes, then activates all entry orders,
        then all stop loss orders by changing their status to ACTIVE.
        
        Returns:
            List of orders that need to be sent to exchange (orders with actual=False)
        """
        # 1. Update orders
        self.update_order_volumes(broker)
        
        # 2. Collect entry and stop loss orders (NEW only, will be activated)
        entry_orders = [
            order for order in self.orders
            if order.order_group == OrderGroup.NONE
            and order.status == OrderStatus.NEW
        ]
        
        stop_orders = [
            order for order in self.orders
            if order.order_group == OrderGroup.STOP_LOSS
            and order.status == OrderStatus.NEW
        ]
        
        # 3. Activate orders and collect those that need exchange synchronization
        orders_to_sync = []
        
        # 3.1. Activate entry orders first
        for order in entry_orders:
            order._set_sync_field('status', OrderStatus.ACTIVE)
            order.update_modify_time(broker)
            if not order.actual:
                orders_to_sync.append(order)
        
        # 3.2. Activate stop loss orders
        for order in stop_orders:
            order._set_sync_field('status', OrderStatus.ACTIVE)
            order.update_modify_time(broker)
            if not order.actual:
                orders_to_sync.append(order)
        
        return orders_to_sync
    
    def update_stop_loss_volumes(self, broker: 'Broker') -> None:
        """
        Update volumes for stop loss orders.
        
        Calculates volumes based on:
        1. Current position volume in market (quantity)
        2. Sum of unexecuted entry orders (OrderGroup.NONE with status ACTIVE or NEW)
        3. Target volume = quantity + unexecuted entry orders volume
        4. Each stop loss order volume = fraction * target_volume (rounded)
        5. Last stop loss order (extreme) closes remaining volume
        """
        # 1. Get current position volume in market
        quantity = abs(self.quantity)
        
        # 2. Calculate unexecuted entry orders volume
        # Entry orders: OrderGroup.NONE with status ACTIVE or NEW (all types including MARKET)
        unexecuted_entry_volume = 0.0
        for order in self.orders:
            if (order.order_group == OrderGroup.NONE and 
                order.status in (OrderStatus.ACTIVE, OrderStatus.NEW)):
                unexecuted_entry_volume += order.volume
        
        # 3. Calculate target volume
        target_volume = quantity + unexecuted_entry_volume
        
        # 4. Get all stop loss orders
        stop_orders = [
            order for order in self.orders
            if order.order_group == OrderGroup.STOP_LOSS
            and order.status in (OrderStatus.ACTIVE, OrderStatus.NEW)
        ]
        
        if not stop_orders:
            return
        
        # 5. Sort stop orders
        # For LONG: descending by trigger_price (farthest down first)
        # For SHORT: ascending by trigger_price (farthest up first)
        reverse = (self.type == DealType.LONG)
        sorted_stop_orders = sorted(
            stop_orders,
            key=lambda o: o.trigger_price if o.trigger_price is not None else (float('-inf') if reverse else float('inf')),
            reverse=reverse
        )
        
        # 6. Calculate sum of fractions for active orders
        fraction_sum = sum(order.fraction for order in sorted_stop_orders if order.fraction is not None)
        if fraction_sum == 0:
            return
        
        # 7. Initialize accumulators
        exact_volume_sum = 0.0  # Accumulated exact (non-rounded) volume
        rounded_volume_sum = 0.0  # Accumulated rounded volume that went into orders
        
        # 8. Process all orders except last
        for order in sorted_stop_orders[:-1]:
            # Calculate exact volume for this order
            assert order.fraction is not None, f"Stop order {order.order_id} must have fraction set"
            exact_volume = order.fraction * target_volume / fraction_sum
            exact_volume_sum += exact_volume
            
            # Calculate order volume as difference between exact sum and rounded sum
            order_volume = exact_volume_sum - rounded_volume_sum
            formatted_volume = broker.format_volume_round(order_volume)
            rounded_volume_sum += formatted_volume
            
            # Update order immediately
            order._set_sync_field('volume', formatted_volume)
            order.update_modify_time(broker)
        
        # 9. Process last order (closes remaining volume)
        last_order = sorted_stop_orders[-1]
        last_order_volume = target_volume - rounded_volume_sum
        # Apply rounding to last order as well to ensure proper precision
        last_order._set_sync_field('volume', broker.format_volume_round(last_order_volume))
        last_order.update_modify_time(broker)
    
    def update_take_profit_volumes(self, broker: 'Broker') -> None:
        """
        Update volumes for take profit orders.
        
        Calculates volumes based on:
        1. Current position volume in market (quantity)
        2. Target volume = quantity
        3. Each take profit order volume = fraction * target_volume (rounded)
        4. Last take profit order (extreme) closes remaining volume
        """
        if self.quantity == 0:
            return

        # 1. Get current position volume in market
        quantity = abs(self.quantity)
        
        # 2. Calculate target volume
        target_volume = quantity
        
        # 4. Get all take profit orders
        take_orders = [
            order for order in self.orders
            if order.order_group == OrderGroup.TAKE_PROFIT
            and order.status in (OrderStatus.ACTIVE, OrderStatus.NEW)
        ]
        
        if not take_orders:
            return
        
        # 5. Sort take profit orders
        # For LONG: ascending by price (farthest up first)
        # For SHORT: descending by price (farthest down first)
        reverse = (self.type == DealType.SHORT)
        sorted_take_orders = sorted(
            take_orders,
            key=lambda o: o.price if o.price is not None else (float('-inf') if reverse else float('inf')),
            reverse=reverse
        )
        
        # 6. Calculate sum of fractions for active orders
        fraction_sum = sum(order.fraction for order in sorted_take_orders if order.fraction is not None)
        if fraction_sum == 0:
            return
        
        # 7. Initialize accumulators
        exact_volume_sum = 0.0  # Accumulated exact (non-rounded) volume
        rounded_volume_sum = 0.0  # Accumulated rounded volume that went into orders
        
        # 8. Process all orders except last
        for order in sorted_take_orders[:-1]:
            # Calculate exact volume for this order
            assert order.fraction is not None, f"Take profit order {order.order_id} must have fraction set"
            exact_volume = order.fraction * target_volume / fraction_sum
            exact_volume_sum += exact_volume
            
            # Calculate order volume as difference between exact sum and rounded sum
            order_volume = exact_volume_sum - rounded_volume_sum
            formatted_volume = broker.format_volume_round(order_volume)
            rounded_volume_sum += formatted_volume
            
            # Update order immediately
            order._set_sync_field('volume', formatted_volume)
            order.update_modify_time(broker)
            
            # Activate order if it's in NEW status
            if order.status == OrderStatus.NEW:
                order._set_sync_field('status', OrderStatus.ACTIVE)
        
        # 9. Process last order (closes remaining volume)
        last_order = sorted_take_orders[-1]
        last_order_volume = target_volume - rounded_volume_sum
        # Apply rounding to last order as well to ensure proper precision
        last_order._set_sync_field('volume', broker.format_volume_round(last_order_volume))
        last_order.update_modify_time(broker)
        
        # Activate last order if it's in NEW status
        if last_order.status == OrderStatus.NEW:
            last_order._set_sync_field('status', OrderStatus.ACTIVE)


class Broker(ABC):
    """
    Generic broker base class.
    """
    
    def __init__(
        self, 
        task: 'Task', 
        result_id: str,
        callbacks_dict: Dict[str, Any] = None,
        results_save_period: float = TRADE_RESULTS_SAVE_PERIOD
    ):
        """
        Initialize broker.
        
        Args:
            task: Task instance (must contain precision_amount and precision_price > 0)
            result_id: Unique ID for this backtesting run
            callbacks_dict: Dictionary with callback functions (optional)
            results_save_period: Period for saving results in seconds (default: TRADE_RESULTS_SAVE_PERIOD)
        """
        if task.precision_amount <= 0.0:
            raise ValueError("precision_amount must be greater than 0")
        if task.precision_price <= 0.0:
            raise ValueError("precision_price must be greater than 0")
        
        self.task: 'Task' = task
        self.source: str = task.source
        self.symbol: str = task.symbol
        self.deals: List['Deal'] = []
        self.orders: List['Order'] = []
        self.trades: List['Trade'] = []
        self.result_id = result_id
        self.last_auto_deal_id: Optional[int] = None
        self.active_deals: Set[int] = set()  # Set of deal_id for active (open) deals
        self.current_time: Optional[np.datetime64] = None
        self.i_time: int = task.history_size  # Current bar index, initialized with history_size
        self.price: Optional[PRICE_TYPE] = None  # Current price
        
        # Precision for amount and price
        self.precision_amount: float = task.precision_amount
        self.precision_price: float = task.precision_price
        
        # Callbacks and results save period
        self.callbacks: Dict[str, Any] = callbacks_dict if callbacks_dict is not None else {}
        self.results_save_period: float = results_save_period
        
        # Trading state tracking
        self._exchange_order_map: Dict[str, 'Order'] = {}  # Map exchange_order_id -> Order
        self._processed_trade_ids: Set[str] = set()       # Set of processed trade IDs to avoid duplicates
        self._last_trade_time: Optional[int] = None       # Timestamp of the last processed trade
        
        self.date_start: Optional[np.datetime64] = None
        
        # Wait intervals for order processing and bar fetching
        self.bar_wait_interval: float = BAR_WAIT_INTERVAL
        self.order_wait_interval: float = ORDER_WAIT_INTERVAL
        
        self.stats = TradingStats(
            initial_equity_usd=0.0,
            fee_taker=task.fee_taker if task.fee_taker > 0 else 0.001,
            fee_maker=task.fee_maker if task.fee_maker > 0 else 0.001,
            slippage=(task.slippage_in_steps * task.price_step) if task.price_step > 0 else 0.0,
            price_step=task.price_step,
            source=task.source,
            symbol=task.symbol,
            timeframe=task.timeframe,
            date_start=task.dateStart,
            date_end=task.dateEnd
        )
    
    def format_volume(self, value: VOLUME_TYPE) -> VOLUME_TYPE:
        """
        Format volume by rounding down to nearest multiple of precision_amount.
        
        Args:
            value: Volume value to format (must be >= 0)
        
        Returns:
            Formatted volume rounded down to precision_amount
        
        Raises:
            AssertionError: If value < 0 or precision_amount <= 0
        """
        assert value >= 0, f"Volume must be >= 0, got {value}"
        assert self.precision_amount > 0, f"precision_amount must be > 0, got {self.precision_amount}"
        
        if value == 0:
            return VOLUME_TYPE(0.0)
        
        # Use relative epsilon based on precision_amount to compensate for floating point errors
        # This ensures values like 0.3 / 0.1 = 3.0 are handled correctly
        # The epsilon is proportional to precision_amount to scale with the operation
        epsilon = max(sys.float_info.epsilon, self.precision_amount * 1e-15)
        quotient = value / self.precision_amount
        return VOLUME_TYPE(math.floor(quotient + epsilon) * self.precision_amount)
    
    def format_volume_round(self, value: VOLUME_TYPE) -> VOLUME_TYPE:
        """
        Format volume by rounding to nearest multiple of precision_amount.
        
        Used for order volume calculations where rounding is preferred over floor.
        
        Args:
            value: Volume value to format (must be >= 0)
        
        Returns:
            Formatted volume rounded to nearest precision_amount
        
        Raises:
            AssertionError: If value < 0 or precision_amount <= 0
        """
        assert value >= 0, f"Volume must be >= 0, got {value}"
        assert self.precision_amount > 0, f"precision_amount must be > 0, got {self.precision_amount}"
        
        if value == 0:
            return VOLUME_TYPE(0.0)
        
        return VOLUME_TYPE(round(value / self.precision_amount) * self.precision_amount)
    
    def format_price(self, value: PRICE_TYPE) -> PRICE_TYPE:
        """
        Format price by rounding to nearest multiple of precision_price.
        
        Args:
            value: Price value to format (must be >= 0)
        
        Returns:
            Formatted price rounded to nearest precision_price
        
        Raises:
            AssertionError: If value < 0 or precision_price <= 0
        """
        assert value >= 0, f"Price must be >= 0, got {value}"
        assert self.precision_price > 0, f"precision_price must be > 0, got {self.precision_price}"
        
        if value == 0:
            return PRICE_TYPE(0.0)
        
        return PRICE_TYPE(round(value / self.precision_price) * self.precision_price)
    
    # ------------------------------------------------------------------
    # Price comparison helpers (with precision tolerance)
    # ------------------------------------------------------------------
    
    def _price_eps(self) -> float:
        """
        Get epsilon for price comparisons based on precision_price.
        We treat prices as equal if they differ by no more than precision_price / 10.
        
        Returns:
            Epsilon value for price comparisons
        """
        return self.precision_price / 10.0
    
    def eq(self, a: float, b: float) -> bool:
        """
        Return True if prices a and b are equal within price epsilon.
        
        Args:
            a: First price
            b: Second price
        
        Returns:
            True if prices are equal within tolerance
        """
        return abs(a - b) <= self._price_eps()
    
    def gt(self, a: float, b: float) -> bool:
        """
        Return True if price a is greater than price b beyond price epsilon.
        
        Args:
            a: First price
            b: Second price
        
        Returns:
            True if a > b (beyond tolerance)
        """
        return (a - b) > self._price_eps()
    
    def lt(self, a: float, b: float) -> bool:
        """
        Return True if price a is less than price b beyond price epsilon.
        
        Args:
            a: First price
            b: Second price
        
        Returns:
            True if a < b (beyond tolerance)
        """
        return (b - a) > self._price_eps()
    
    def gteq(self, a: float, b: float) -> bool:
        """
        Return True if price a is greater than or equal to price b within price epsilon.
        
        Args:
            a: First price
            b: Second price
        
        Returns:
            True if a >= b (within tolerance)
        """
        return self.gt(a, b) or self.eq(a, b)
    
    def lteq(self, a: float, b: float) -> bool:
        """
        Return True if price a is less than or equal to price b within price epsilon.
        
        Args:
            a: First price
            b: Second price
        
        Returns:
            True if a <= b (within tolerance)
        """
        return self.lt(a, b) or self.eq(a, b)
    
    def get_deal(self, deal_id: int) -> 'Deal':
        """
        Get deal by deal_id (deal_id = index + 1).
        
        Args:
            deal_id: Deal ID (1-based)
        
        Returns:
            Deal instance
        
        Raises:
            IndexError: If deal with such deal_id does not exist
        """
        # Convert deal_id to index (deal_id = index + 1, so index = deal_id - 1)
        index = deal_id - 1
        if index < 0 or index >= len(self.deals):
            raise IndexError(f"Deal with deal_id {deal_id} does not exist (len={len(self.deals)})")
        
        return self.deals[index]
    
    def execute_deal(
        self,
        deal_type: DealType,
        entries: List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]],
        stop_losses: List[Tuple[Optional[float], PRICE_TYPE]],
        take_profits: List[Tuple[Optional[float], PRICE_TYPE]],
        existing_deal_id: Optional[int] = None,
        clear_enter: bool = False,
        clear_stop_loss: bool = False,
        clear_take_profit: bool = False
    ) -> Tuple[Optional['Deal'], List['Order'], List[int], List[str]]:
        """
        Execute a deal with entry orders, stop losses, and take profits.
        
        This is an internal method used by buy_sltp(), sell_sltp(), and modify_deal() methods.
        
        Args:
            deal_type: Deal type (LONG or SHORT)
            entries: List of entry orders as (volume, price) tuples.
                    Price can be None for market orders. If price is None (market order),
                    the list must contain only one element.
                    Volume can be negative for closing position (only for existing deals).
            stop_losses: List of stop loss orders as (fraction, price) tuples.
                        Fraction can be None for "all remaining" - this should be
                        the order with the farthest price from entry points.
                        For LONG: farthest = minimum price.
                        For SHORT: farthest = maximum price.
            take_profits: List of take profit orders as (fraction, price) tuples.
                         Fraction can be None for "all remaining" - this should be
                         the order with the farthest price from entry points.
                         For LONG: farthest = maximum price.
                         For SHORT: farthest = minimum price.
            existing_deal_id: Optional existing deal ID for modification. If provided,
                             uses existing deal instead of creating new one.
            clear_enter: If True, cancel all entry orders (OrderGroup.NONE) before creating new ones.
                        Only used when existing_deal_id is provided.
            clear_stop_loss: If True, cancel all stop loss orders (OrderGroup.STOP_LOSS) before creating new ones.
                           Only used when existing_deal_id is provided.
            clear_take_profit: If True, cancel all take profit orders (OrderGroup.TAKE_PROFIT) before creating new ones.
                              Only used when existing_deal_id is provided.
        
        Returns:
            Tuple[Optional[Deal], List[Order], List[int], List[str]]: 
            - Deal that groups all orders (or None if deal was not created due to errors)
            - List of new orders created in this call
            - List of canceled order IDs (old orders canceled when modifying existing deal, or new orders canceled on error)
            - List of error messages (empty if no errors occurred)
        
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        assert self.current_time is not None, "current_time must be set before executing deal"
        
        deal, canceled_order_ids = self._prepare_deal(
            deal_type, existing_deal_id, clear_enter, clear_stop_loss, clear_take_profit
        )
        
        new_orders = []
        entry_side = OrderSide.BUY if deal_type == DealType.LONG else OrderSide.SELL
        opposite_side = OrderSide.SELL if deal_type == DealType.LONG else OrderSide.BUY
        
        entry_orders = self._create_entry_orders(deal, entries, entry_side, opposite_side)
        new_orders.extend(entry_orders)
        
        stop_orders = self._create_stop_loss_orders(deal, stop_losses, opposite_side)
        new_orders.extend(stop_orders)
        
        take_orders = self._create_take_profit_orders(deal, take_profits, opposite_side)
        new_orders.extend(take_orders)
        
        #deal.calc_fraction_remain(self, OrderGroup.STOP_LOSS)
        #deal.calc_fraction_remain(self, OrderGroup.TAKE_PROFIT)
        
        # Start deal: activate entry and stop loss orders
        orders_to_sync = deal.start(self)
        
        # Note: orders_to_sync contains orders that need to be sent to exchange
        # This will be handled later by exchange synchronization logic
        # For now, we don't collect errors from start() as it no longer returns them
        
        return (deal, new_orders, canceled_order_ids, [])
    
    def _prepare_deal(
        self,
        deal_type: DealType,
        existing_deal_id: Optional[int],
        clear_enter: bool,
        clear_stop_loss: bool,
        clear_take_profit: bool
    ) -> Tuple['Deal', List[int]]:
        """
        Prepare deal for execution: create new or get existing and clear orders if needed.
        
        Returns:
            Tuple of (deal, canceled_order_ids)
        """
        if existing_deal_id is not None:
            deal = self.get_deal(existing_deal_id)
            canceled_order_ids = self._clear_deal_orders(deal, clear_enter, clear_stop_loss, clear_take_profit)
        else:
            new_deal_id = len(self.deals) + 1
            deal = Deal(
                deal_id=new_deal_id,
                type=deal_type
            )
            self.deals.append(deal)
            canceled_order_ids = []
        
        return (deal, canceled_order_ids)
    
    def _clear_deal_orders(
        self,
        deal: 'Deal',
        clear_enter: bool,
        clear_stop_loss: bool,
        clear_take_profit: bool
    ) -> List[int]:
        """
        Clear order groups from deal according to flags.
        
        Returns:
            List of canceled order IDs
        """
        canceled_order_ids = []
        
        # Cancel in order: take profits, entries, stop losses
        if clear_take_profit:
            canceled = deal.cancel_orders(self, OrderGroup.TAKE_PROFIT)
            canceled_order_ids.extend([o.order_id for o in canceled])
        
        if clear_enter:
            canceled = deal.cancel_orders(self, OrderGroup.NONE)
            canceled_order_ids.extend([o.order_id for o in canceled])
        
        if clear_stop_loss:
            canceled = deal.cancel_orders(self, OrderGroup.STOP_LOSS)
            canceled_order_ids.extend([o.order_id for o in canceled])
        
        return canceled_order_ids
    
    def _create_entry_orders(
        self,
        deal: 'Deal',
        entries: List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]],
        entry_side: OrderSide,
        opposite_side: OrderSide
    ) -> List['Order']:
        """
        Create entry orders from entries list.
        
        Returns:
            List of created orders
        """
        orders = []
        
        for volume, price in entries:
            if volume < 0:
                # Negative volume: market order opposite to deal direction
                order = self._create_order(
                    deal=deal,
                    order_type=OrderType.MARKET,
                    side=opposite_side,
                    price=None,
                    trigger_price=None,
                    volume=abs(volume),
                    order_group=OrderGroup.NONE,
                    fraction=None
                )
            elif price is None:
                # Market order
                order = self._create_order(
                    deal=deal,
                    order_type=OrderType.MARKET,
                    side=entry_side,
                    price=None,
                    trigger_price=None,
                    volume=volume,
                    order_group=OrderGroup.NONE,
                    fraction=None
                )
            else:
                # Limit order
                order = self._create_order(
                    deal=deal,
                    order_type=OrderType.LIMIT,
                    side=entry_side,
                    price=self.format_price(price),
                    trigger_price=None,
                    volume=self.format_volume(volume),
                    order_group=OrderGroup.NONE,
                    fraction=None
                )
            
            orders.append(order)
        
        return orders
    
    def _create_stop_loss_orders(
        self,
        deal: 'Deal',
        stop_losses: List[Tuple[Optional[float], PRICE_TYPE]],
        opposite_side: OrderSide
    ) -> List['Order']:
        """
        Create stop loss orders from stop_losses list.
        
        Returns:
            List of created orders
        """
        orders = []
        
        for fraction, price in stop_losses:
            order = self._create_order(
                deal=deal,
                order_type=OrderType.STOP,
                side=opposite_side,
                price=None,
                trigger_price=self.format_price(price),
                volume=0.0,  # Will be set later
                order_group=OrderGroup.STOP_LOSS,
                fraction=fraction
            )
            orders.append(order)
        
        return orders
    
    def _create_take_profit_orders(
        self,
        deal: 'Deal',
        take_profits: List[Tuple[Optional[float], PRICE_TYPE]],
        opposite_side: OrderSide
    ) -> List['Order']:
        """
        Create take profit orders from take_profits list.
        
        Returns:
            List of created orders
        """
        orders = []
        
        for fraction, price in take_profits:
            order = self._create_order(
                deal=deal,
                order_type=OrderType.LIMIT,
                side=opposite_side,
                price=self.format_price(price),
                trigger_price=None,
                volume=0.0,  # Will be set later
                order_group=OrderGroup.TAKE_PROFIT,
                fraction=fraction
            )
            orders.append(order)
        
        return orders
    
    def _create_order(
        self,
        deal: 'Deal',
        order_type: OrderType,
        side: OrderSide,
        volume: VOLUME_TYPE,
        order_group: OrderGroup,
        price: Optional[PRICE_TYPE] = None,
        trigger_price: Optional[PRICE_TYPE] = None,
        fraction: Optional[float] = None
    ) -> 'Order':
        """
        Create order and add it to broker's orders list and deal.
        
        Returns:
            Created order
        """
        order_id = len(self.orders) + 1
        order = Order(
            order_id=order_id,
            deal_id=deal.deal_id,
            order_type=order_type,
            create_time=self.current_time,
            modify_time=self.current_time,
            side=side,
            price=price,
            trigger_price=trigger_price,
            volume=volume,
            filled_volume=0.0,
            status=OrderStatus.NEW,
            order_group=order_group,
            fraction=fraction,
            errors=[]
        )
        
        self.orders.append(order)
        deal.add_order(order)
        
        return order
    
    def close_deals(self) -> None:
        """
        Close all open positions.
        
        Iterates through all deals and closes those that are not closed yet
        by calling close_deal() for each open deal.
        """
        for deal in self.deals:
            if not deal.is_closed:
                self.close_deal(deal.deal_id)
    
    def close_deal(self, deal_id: int) -> None:
        """
        Close a specific deal by canceling all active orders and closing position.
        
        Args:
            deal_id: ID of the deal to close
        
        Default implementation (stub). Should be overridden in subclasses if needed.
        """
        deal = self.get_deal(deal_id)
        
        # 1. Cancel all active/new orders associated with the deal
        deal.cancel_orders(self)
        
        # 2. Create market order to close position if quantity is not zero
        if deal.quantity != 0:
            side = OrderSide.SELL if deal.quantity > 0 else OrderSide.BUY
            order = self._create_order(
                deal=deal,
                order_type=OrderType.MARKET,
                side=side,
                volume=abs(deal.quantity),
                order_group=OrderGroup.NONE,
                price=None,
                trigger_price=None,
                fraction=None
            )
            # Activate order so it will be sent to exchange
            order._set_sync_field('status', OrderStatus.ACTIVE)
            order.update_modify_time(self)
            
        # 3. Process orders (cancel old ones and place closing order)
        self.order_processing()
        
        # 4. Check if deal should be closed (quantity == 0 after processing)
        if deal.quantity == 0:
            deal.is_closed = True
    
    def cancel_orders(self, order_ids: List[int]) -> List['Order']:
        """
        Cancel orders by their IDs.
        
        Args:
            order_ids: List of order IDs to cancel
        
        Returns:
            List of canceled orders
        
        Default implementation (stub). Should be overridden in subclasses if needed.
        """
        raise NotImplementedError("cancel_orders must be implemented by subclass")
    
    def logging(self, message: str, level: str = "info", deal_id: Optional[int] = None) -> None:
        """
        Send log message to frontend via task.
        
        Args:
            message: Message text (required)
            level: Message level (optional, default: "info")
                  Valid levels: info, warning, error, critical, success, debug
            deal_id: Deal ID associated with the message (optional, processing to be implemented later)
        """
        # Log to system logger
        if level == "critical":
            logger.critical(message)
        elif level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "debug":
            logger.debug(message)
        else:
            logger.info(message)
            
        if hasattr(self.task, 'send_message'):
            self.task.send_message(MessageType.MESSAGE, {"level": level, "message": message})
    
    def update_state(self, results: Optional['TaskResults'], is_finish: bool = False) -> None:
        """
        Update task state and progress.
        Checks if task is still running by reading isRunning flag from Redis.
        Calculates and sends progress update via MessageType.EVENT.
        If isRunning is False, sends error notification and raises exception to stop backtesting.
        
        Args:
            results: TaskResults instance to save results to Redis, or None if results should not be saved
            is_finish: If True, marks the backtesting result as completed. Default: False.
        
        Raises:
            RuntimeError: If task is stopped (isRunning == False) or duplicate worker detected
        """
        # Check if task is associated with a list (has Redis connection)
        if self.task._list is None:
            # If no list, skip state update (standalone mode)
            return
        
        # Calculate progress
        progress_val = self.progress()
        
        # Prepare event data
        event_data = {
            "event": "progress",
            "result_id": self.result_id,
            "progress": progress_val
        }
        
        # Add optional date fields if available
        if self.date_start is not None:
            event_data["date_start"] = datetime64_to_iso(self.date_start)
        
        if self.current_time is not None:
            event_data["current_time"] = datetime64_to_iso(self.current_time)
        
        # Save results to Redis if results instance is provided
        if results is not None:
            results.put_result(is_finish=is_finish)
        
        self.task.send_message(MessageType.EVENT, event_data)
        
        # Load task from Redis to get current state
        current_task = self.task.load()
        if current_task is None:
            logger.warning(f"Task {self.task.id} not found in Redis during state update")
            return
        
        # Check if result_id matches (detect duplicate workers)
        if current_task.result_id != self.result_id:
            # Another worker is running, send error notification and raise exception
            error_message = f"Another backtesting worker is running for this task (expected result_id: {current_task.result_id}, got: {self.result_id})"
            logger.error(f"Task {self.task.id} result_id mismatch: {error_message}")
            
            # Send error notification
            self.task.backtesting_error(error_message)
            
            # Raise exception to exit from run() loop
            raise RuntimeError(error_message)
        
        # Check if task is still running
        if not current_task.isRunning:
            # Task was stopped, send error notification and raise exception
            cancel_message = "Backtesting was stopped by user request"
            logger.info(f"Task {self.task.id} stopped: {cancel_message}")
            
            # Send error notification
            self.task.backtesting_error(cancel_message)
            
            # Raise exception to exit from run() loop
            raise RuntimeError(cancel_message)

    @abstractmethod
    def progress(self) -> float:
        """
        Calculate current progress percentage.
        
        Returns:
            float: Progress in range [0.0, 100.0]
        """
        raise NotImplementedError("progress must be implemented by subclass")
    
    def check_trading_results(self) -> List[str]:
        """
        Check trading results for consistency and correctness.
        
        Validates:
        - All deal_id correspond to their index (deal_id = index + 1)
        - All trade_id are > 0 and unique
        - All trade_id are in ascending order by time
        - All deals are closed
        - Recalculates and compares average buy/sell prices and profit
        
        Returns:
            List of error messages. Empty list means no errors.
        """
        if self.deals is None or not self.deals:
            return []
        
        errors = []
        
        # Check 1: All deal_id correspond to index (deal_id = index + 1)
        errors.extend([
            f"Deal at index {i} has deal_id={deal.deal_id}, expected {i + 1}"
            for i, deal in enumerate(self.deals)
            if deal.deal_id != i + 1
        ])
        
        # Collect all trades from all deals
        all_trades = [trade for deal in self.deals for trade in deal.trades]
        
        if not all_trades:
            return errors
        
        # Check 2: All trade_id > 0 and unique
        trade_ids = [trade.trade_id for trade in all_trades]
        if invalid := [tid for tid in trade_ids if tid <= 0]:
            errors.append(f"Found trade_id <= 0: {invalid}")
        
        if len(trade_ids) != len(trade_id_set := set(trade_ids)):
            errors.append(f"Duplicate trade_id found: {[tid for tid in trade_id_set if trade_ids.count(tid) > 1]}")
        
        # Check 2a: All exchange_trade_id are present and unique
        exchange_trade_ids = [trade.exchange_trade_id for trade in all_trades]
        if missing := [i for i, etid in enumerate(exchange_trade_ids) if not etid]:
            errors.append(f"Found missing exchange_trade_id at trade indices: {missing}")
        
        if len(exchange_trade_ids) != len(exchange_trade_id_set := set(exchange_trade_ids)):
            errors.append(f"Duplicate exchange_trade_id found: {[etid for etid in exchange_trade_id_set if exchange_trade_ids.count(etid) > 1]}")
        
        # Check 3: All trade_id in ascending order by time
        if all_trades:
            trades_by_time = sorted(all_trades, key=lambda t: t.time)
            trade_ids_by_time = [t.trade_id for t in trades_by_time]
            if trade_ids != trade_ids_by_time:
                errors.append("trade_id are not in ascending order by time")
        
        # Check 4: All deals are closed
        if unclosed := [deal.deal_id for deal in self.deals if not deal.is_closed]:
            errors.append(f"Unclosed deals found: {unclosed}")
        
        # Check 5: Recalculate and compare average prices and profit
        volume_tolerance = self.precision_amount / 10.0
        price_tolerance = self._price_eps()  # precision_price / 10.0
        
        for deal in self.deals:
            if not deal.trades:
                continue
            
            buy_trades = [t for t in deal.trades if t.side == OrderSide.BUY]
            sell_trades = [t for t in deal.trades if t.side == OrderSide.SELL]
            
            recalc_buy_quantity = sum(t.quantity for t in buy_trades)
            recalc_buy_cost = sum(t.sum for t in buy_trades)
            recalc_avg_buy_price = recalc_buy_cost / recalc_buy_quantity if recalc_buy_quantity > 0 else None
            
            recalc_sell_quantity = sum(t.quantity for t in sell_trades)
            recalc_sell_proceeds = sum(t.sum for t in sell_trades)
            recalc_avg_sell_price = recalc_sell_proceeds / recalc_sell_quantity if recalc_sell_quantity > 0 else None
            
            recalc_fee = sum(t.fee for t in deal.trades)
            recalc_profit = (recalc_sell_proceeds - recalc_buy_cost - recalc_fee) if deal.is_closed else None
            
            # Compare volumes (use volume_tolerance)
            volume_comparisons = [
                ('buy_quantity', deal.buy_quantity, recalc_buy_quantity),
                ('sell_quantity', deal.sell_quantity, recalc_sell_quantity),
            ]
            for field, stored, recalc in volume_comparisons:
                if abs(stored - recalc) > volume_tolerance:
                    errors.append(f"Deal {deal.deal_id}: {field} mismatch (stored={stored}, recalc={recalc})")
            
            # Compare prices/sums (use price_tolerance)
            price_comparisons = [
                ('buy_cost', deal.buy_cost, recalc_buy_cost),
                ('sell_proceeds', deal.sell_proceeds, recalc_sell_proceeds),
                ('fee', deal.fee, recalc_fee),
            ]
            for field, stored, recalc in price_comparisons:
                if abs(stored - recalc) > price_tolerance:
                    errors.append(f"Deal {deal.deal_id}: {field} mismatch (stored={stored}, recalc={recalc})")
            
            # Compare avg_buy_price
            # Both None is OK (no buy trades), both not None should match, one None one not None is OK (normal case)
            if recalc_avg_buy_price is not None and deal.avg_buy_price is not None:
                if abs(recalc_avg_buy_price - deal.avg_buy_price) > price_tolerance:
                    errors.append(f"Deal {deal.deal_id}: avg_buy_price mismatch (stored={deal.avg_buy_price}, recalc={recalc_avg_buy_price})")
            # If one is None and other is not None - this is normal (deal might have only buy or only sell trades)
            
            # Compare avg_sell_price
            if recalc_avg_sell_price is not None and deal.avg_sell_price is not None:
                if abs(recalc_avg_sell_price - deal.avg_sell_price) > price_tolerance:
                    errors.append(f"Deal {deal.deal_id}: avg_sell_price mismatch (stored={deal.avg_sell_price}, recalc={recalc_avg_sell_price})")
            # If one is None and other is not None - this is normal (deal might have only buy or only sell trades)
            
            # Compare profit for closed deals
            # If deal is closed, profit should be calculated and match
            if deal.is_closed:
                if recalc_profit is not None and deal.profit is not None:
                    if abs(recalc_profit - deal.profit) > price_tolerance:
                        errors.append(f"Deal {deal.deal_id}: profit mismatch (stored={deal.profit}, recalc={recalc_profit})")
                elif recalc_profit != deal.profit:
                    # One is None, other is not None - error for closed deal
                    errors.append(f"Deal {deal.deal_id}: profit mismatch (stored={deal.profit}, recalc={recalc_profit})")
        
        return errors
    
    def create_trade(self, order: Order, quantity: VOLUME_TYPE, price: PRICE_TYPE, fee: PRICE_TYPE, exchange_trade_id: str) -> None:
        """
        Create a trade from an executed order.
        
        Creates a Trade object, updates order's filled_volume, sets order status to EXECUTED
        if fully filled, and adds the trade to the deal.
        
        Args:
            order: Order that was executed
            quantity: Quantity executed in this trade
            price: Execution price
            fee: Fee for this trade
            exchange_trade_id: Exchange trade ID from exchange API
        
        Raises:
            AssertionError: If quantity <= 0, price <= 0, fee < 0, or current_time is not set
            IndexError: If deal with order.deal_id does not exist
        """
        # Validate inputs
        assert quantity > 0, f"quantity must be > 0, got {quantity}"
        assert price > 0, f"price must be > 0, got {price}"
        assert fee >= 0, f"fee must be >= 0, got {fee}"
        assert self.current_time is not None, "current_time must be set before creating trade"
        assert exchange_trade_id, "exchange_trade_id must be provided"
        
        # Generate trade_id (size of trades list + 1)
        trade_id = len(self.trades) + 1
        
        # Calculate trade sum
        trade_sum = quantity * price
        
        # Create Trade
        trade = Trade(
            trade_id=trade_id,
            exchange_trade_id=exchange_trade_id,
            deal_id=order.deal_id,
            order_id=order.order_id,
            time=self.current_time,
            side=order.side,
            price=price,
            quantity=quantity,
            fee=fee,
            sum=trade_sum
        )
        
        # Update order filled_volume
        order.filled_volume += quantity
        
        # Check if order is fully filled
        if order.filled_volume >= order.volume:
            order._set_sync_field('status', OrderStatus.EXECUTED)
        
        # Update modify_time after changes
        order.update_modify_time(self)
        
        # Get deal and add trade to it
        deal = self.get_deal(order.deal_id)
        
        # Check if deal was closed before adding trade
        was_closed = deal.is_closed
        
        deal.add_trade(self, trade, self.precision_amount)
        
        # Add trade to broker's trades list
        self.trades.append(trade)
        
        # Update statistics
        if self.stats:
            self.stats.add_trade(trade)
            # If deal was just closed, add it to statistics
            if not was_closed and deal.is_closed:
                self.stats.add_deal(deal)
    
    def fetch_new_trades(self) -> Set[int]:
        """
        Fetch and process new trades from exchange.
        
        Fetches trades since last processed time, filters duplicates,
        and creates internal Trade objects for matched orders.
        
        Returns:
            Set of deal_id for deals that had trades added during this call.
        """
        updated_deal_ids: Set[int] = set()
        
        trades = self.exchange_fetch_my_trades(self.symbol, since=self._last_trade_time)
            
        for trade_data in trades:

            trade_id = str(trade_data['id'])
            if trade_id in self._processed_trade_ids:
                continue
                
            self._processed_trade_ids.add(trade_id)
            
            # Update last trade time
            timestamp = trade_data['timestamp']
            if self._last_trade_time is None or timestamp > self._last_trade_time:
                self._last_trade_time = timestamp
            
            exchange_order_id = str(trade_data['order'])
            order = self._exchange_order_map.get(exchange_order_id)
            
            if order:
                try:
                    self.create_trade(
                        order=order,
                        quantity=float(trade_data['amount']),
                        price=float(trade_data['price']),
                        fee=float(trade_data['fee']),
                        exchange_trade_id=trade_id
                    )
                    # Add deal_id to set of updated deals
                    updated_deal_ids.add(order.deal_id)
                except Exception as e:
                    self.logging(f"Error creating trade for order {order.order_id}: {str(e)}", level="critical", deal_id=order.deal_id)
            else:
                self.logging(f"Received trade {trade_id} for unknown order {exchange_order_id}", level="critical")
        
        return updated_deal_ids
    
    def place_orders(self) -> int:
        """
        Place orders to exchange that are marked as unsynced (actual=False).
        
        This method should:
        1. Find all orders where actual=False and status != NEW
        2. For orders with status ACTIVE: call create_order() to place them on exchange
        3. For orders with status CANCELED or EXECUTED: call cancel_order() to cancel them on exchange
        4. After successful placement/cancellation, set actual=True
        
        Returns:
            int: Number of orders successfully placed/updated
        """
        updated_count = 0
        
        # Filter orders that need sync and are not in NEW status
        orders_to_sync = [
            order for order in self.orders 
            if not order.actual and order.status != OrderStatus.NEW
        ]
        
        for order in orders_to_sync:
            try:
                # Handle ACTIVE orders
                if order.status == OrderStatus.ACTIVE:
                    # If order already has exchange ID, it means it was modified or re-placed
                    # We need to cancel the old one first
                    if order.exchange_order_id:
                        self.exchange_cancel_order(str(order.exchange_order_id), self.symbol)
                        # Clear exchange_order_id after cancellation attempt
                        order.exchange_order_id = None
                        
                    # Create new order on exchange
                    # Determine price: price for limit, trigger_price for stop
                    price = order.price if order.price is not None else order.trigger_price
                    
                    create_result = self.exchange_create_order(
                        symbol=self.symbol,
                        order_type=order.order_type,
                        side=order.side,
                        amount=order.volume,
                        price=price
                    )
                    
                    # Check for errors in result
                    if 'id' in create_result:
                        order.exchange_order_id = create_result['id']
                        # Add to exchange order map
                        self._exchange_order_map[str(order.exchange_order_id)] = order
                        
                        order.actual = True
                        order.update_modify_time(self)
                        updated_count += 1
                    else:
                        self.logging(f"Failed to place order {order.order_id}: {create_result}", level="error", deal_id=order.deal_id)
                
                # Handle CANCELED or EXECUTED orders (need to remove from exchange if present)
                elif order.status in (OrderStatus.CANCELED, OrderStatus.EXECUTED):
                    if order.exchange_order_id:
                        self.exchange_cancel_order(str(order.exchange_order_id), self.symbol)
                        
                        # Clear exchange_order_id
                        order.exchange_order_id = None
                        order.actual = True
                        order.update_modify_time(self)
                        updated_count += 1
                    else:
                        # Order was not on exchange, just mark as actual
                        order.actual = True
                        order.update_modify_time(self)
                        updated_count += 1
                        
            except Exception as e:
                self.logging(f"Error processing order {order.order_id}: {str(e)}", level="error", deal_id=order.deal_id)
                # Do not set actual=True, so we retry next time
                
        return updated_count

    def get_next_bar(
        self,
        quotes_data: Dict[str, Any],
        ta_proxies: Dict[str, Any]
    ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.datetime64, PRICE_TYPE]]:
        """
        Get next bar data, waiting if necessary.
        
        Calls fetch_next_bar() in a loop until data is received or finished.
        
        Args:
            quotes_data: Quotes data dictionary
            ta_proxies: Dictionary of TA proxies
            
        Returns:
            Tuple of bar data or None if finished
        """
        while True:
            self.order_processing()
            status, bar_data = self.fetch_next_bar(quotes_data, ta_proxies)
            
            if status == BarStatus.FINISHED:
                return None
            
            if status == BarStatus.WAITING:
                if self.bar_wait_interval > 0:
                    time.sleep(self.bar_wait_interval)
                continue
            
            # status == BarStatus.RECEIVED
            assert bar_data is not None, "bar_data must be present when status is RECEIVED"
            return bar_data

    def order_processing(self) -> None:
        """
        Process orders cycle: fetch updates and place pending orders.
        Repeats if orders were placed to handle immediate updates/fills.
        """
        while True:
            updated_deal_ids = self.fetch_new_trades()
            
            # Update order volumes for deals that had trades added
            for deal_id in updated_deal_ids:
                deal = self.get_deal(deal_id)
                if not deal.is_closed:
                    deal.update_order_volumes(self)
            
            placed_count = self.place_orders()
            
            if placed_count == 0:
                break
                
            if self.order_wait_interval > 0:
                time.sleep(self.order_wait_interval)

    def run(self, save_results: bool = True):
        """
        Run strategy execution.
        Iterates through bars, calling on_bar for each bar.
        Periodically updates state and progress based on results_save_period.
        
        Args:
            save_results: If True, creates TaskResults and saves results to Redis.
                         If False, results are not saved. Default: True.
        """
        self.initialize_run()
        
        ta_proxies = {
            'talib': ta_proxy_talib(broker=self)
        }
        
        # Calls set_quotes on proxies inside
        quotes_data = self.initialize_quotes(self.task.history_size, ta_proxies)
        
        results = None
        if save_results:
            from app.services.tasks.task_results import TaskResults
            results = TaskResults(self.task, self, ta_proxies)
        
        self.i_time = self.task.history_size
        
        if hasattr(self, 'callbacks') and 'on_start' in self.callbacks:
            self.callbacks['on_start'](self.task.parameters, ta_proxies)
        
        state_update_period = 1.0
        last_update_time = time.time()
        
        while True:
            bar_data = self.get_next_bar(quotes_data, ta_proxies)
            if bar_data is None:
                break
            
            (time_array, open_array, high_array, low_array, close_array, 
             volume_array, current_time, current_price) = bar_data
            
            self.current_time = current_time
            if hasattr(self, 'price'):
                self.price = current_price
            
            if hasattr(self, 'callbacks') and 'on_bar' in self.callbacks:
                equity_usd = getattr(self, 'equity_usd', 0.0)
                equity_symbol = getattr(self, 'equity_symbol', 0.0)
                self.callbacks['on_bar'](
                    current_price,
                    current_time,
                    time_array,
                    open_array,
                    high_array,
                    low_array,
                    close_array,
                    volume_array,
                    equity_usd,
                    equity_symbol
                )
            
            current_time_real = time.time()
            if hasattr(self, 'results_save_period'):
                if current_time_real - last_update_time >= self.results_save_period:
                    self.update_state(results)
                    last_update_time = current_time_real
                    state_update_period = min(state_update_period + 1.0, self.results_save_period)
            
            #self.i_time += 1
        
        self.close_deals()
        
        if __debug__:
            errors = self.check_trading_results()
            if errors:
                error_message = f"Trading results validation failed:\n" + "\n".join(errors)
                if hasattr(self, 'task') and hasattr(self.task, 'backtesting_error'):
                    self.task.backtesting_error(error_message)
                raise RuntimeError(error_message)
        
        if hasattr(self, 'callbacks') and 'on_finish' in self.callbacks:
            self.callbacks['on_finish']()
        
        if hasattr(self, 'update_state') and hasattr(self, 'date_end'):
            self.current_time = self.date_end
            self.update_state(results, is_finish=True)
    
    # Abstract methods (must be implemented by subclasses)
    
    @abstractmethod
    def exchange_create_order(
        self, 
        symbol: str, 
        order_type: OrderType, 
        side: OrderSide, 
        amount: float, 
        price: Optional[float] = None
    ) -> Dict:
        """
        Create an order (abstract method).
        
        Args:
            symbol: Trading symbol
            order_type: Order type (MARKET, LIMIT, STOP)
            side: Order side (BUY, SELL)
            amount: Order amount
            price: Order price (optional, for limit/stop orders)
        
        Returns:
            Dictionary with order details (simulated exchange response)
        
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("exchange_create_order must be implemented by subclass")
    
    @abstractmethod
    def exchange_cancel_order(self, exchange_order_id: str, symbol: str) -> Dict:
        """
        Cancel an order by its ID.
        
        Args:
            exchange_order_id: Exchange order ID to cancel
            symbol: Trading symbol
        
        Returns:
            Dictionary with cancelled order details
        
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("exchange_cancel_order must be implemented by subclass")

    @abstractmethod
    def exchange_fetch_my_trades(self, symbol: str, since: Optional[int] = None) -> List[Dict]:
        """
        Fetch executed trades.
        
        Args:
            symbol: Trading symbol
            since: Timestamp in ms to fetch trades from (optional)
            
        Returns:
            List of dictionaries with trade details
            
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("exchange_fetch_my_trades must be implemented by subclass")
    
    @abstractmethod
    def initialize_run(self) -> None:
        """
        Initialize broker for running strategy.
        
        Called at the start of run() method to set up broker state.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("initialize_run must be implemented by subclass")
    
    @abstractmethod
    def initialize_quotes(self, history_size: int, ta_proxies: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initialize quotes data for strategy execution.
        
        Args:
            history_size: Number of bars to load for strategy initialization
            ta_proxies: Dictionary of TA proxies (e.g., {'talib': ta_proxy_talib(...)})
                       Should call set_quotes() on each proxy with initial quotes data
        
        Returns:
            Dictionary with quotes data (structure is implementation-specific)
        """
        raise NotImplementedError("initialize_quotes must be implemented by subclass")
    
    @abstractmethod
    def fetch_next_bar(
        self, 
        quotes_data: Dict[str, Any], 
        ta_proxies: Dict[str, Any]
    ) -> Tuple[BarStatus, Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.datetime64, PRICE_TYPE]]]:
        """
        Get next bar data for strategy execution.
        
        Args:
            quotes_data: Quotes data dictionary (from initialize_quotes)
            ta_proxies: Dictionary of TA proxies (for real trading, should call set_quotes() on each proxy)
        
        Returns:
            Tuple of (status, data_tuple):
            - status: BarStatus (RECEIVED, WAITING, FINISHED)
            - data_tuple: Tuple of (time_array, open_array, high_array, low_array, close_array, volume_array, current_time, current_price) if status is RECEIVED, else None
        """
        raise NotImplementedError("fetch_next_bar must be implemented by subclass")
    
    def buy(
        self,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        trigger_price: Optional[PRICE_TYPE] = None
    ) -> List['Order']:
        """
        Create buy order(s) and execute/place them.
        If price is specified, creates a limit order.
        If trigger_price is specified, creates a stop order.
        Otherwise creates a market order.
        
        Args:
            quantity: Quantity to buy
            price: Optional limit price. If None and trigger_price is None, creates market order.
            trigger_price: Optional trigger price for stop order.
        
        Returns:
            List of copies of executed/placed orders
        
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("buy must be implemented by subclass")
    
    def sell(
        self,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        trigger_price: Optional[PRICE_TYPE] = None
    ) -> List['Order']:
        """
        Create sell order(s) and execute/place them.
        If price is specified, creates a limit order.
        If trigger_price is specified, creates a stop order.
        Otherwise creates a market order.
        
        Args:
            quantity: Quantity to sell
            price: Optional limit price. If None and trigger_price is None, creates market order.
            trigger_price: Optional trigger price for stop order.
        
        Returns:
            List of copies of executed/placed orders
        
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("sell must be implemented by subclass")
        

