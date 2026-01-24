from abc import ABC, abstractmethod
from enum import Enum, IntEnum
from typing import List, Optional, Set, Dict, Any, Tuple, Union, TYPE_CHECKING
import math
import time

import numpy as np
from pydantic import BaseModel, Field, ConfigDict, model_validator, PrivateAttr

from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.indicator_proxy import ta_proxy_talib
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType
from app.core.config import BAR_WAIT_INTERVAL, ORDER_WAIT_INTERVAL

if TYPE_CHECKING:
    from app.services.tasks.tasks import Task
    from app.services.tasks.task_results import TaskResults


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(IntEnum):
    NEW = 0  # Only created, not processed
    ACTIVE = 1  # Validated and active (only limit and stop orders)
    EXECUTED = 2  # Executed (market immediately, limit/stop after execution)
    CANCELED = 3  # Was active, canceled (in real trading may be partially executed)
    ERROR = 4  # Failed validation (in real trading may be other reasons)


class OrderGroup(IntEnum):
    NONE = 0  # Outside of group (default)
    STOP_LOSS = 1  # Stop loss order
    TAKE_PROFIT = 2  # Take profit order


class DealType(Enum):
    LONG = "long"
    SHORT = "short"


class BarStatus(IntEnum):
    RECEIVED = 1  # Data received
    WAITING = 2   # Waiting for data
    FINISHED = 3  # No more data (finish)


class Trade(BaseModel):
    """
    Represents a single trade (buy or sell operation).
    
    Immutable class - once created, fields cannot be modified.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        frozen=True  # Make class immutable
    )

    trade_id: int = Field(gt=0, description="Trade ID, must be greater than 0")
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
        
        # Validate that either price or trigger_price is set
        if self.price is None and self.trigger_price is None:
            raise ValueError("Either 'price' or 'trigger_price' must be set (not both None)")
        
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
        
        # Check for active entry orders (OrderGroup.NONE) and update volumes or close deal
        has_active_entry_orders = any(
            order.status in (OrderStatus.ACTIVE, OrderStatus.NEW) 
            and order.order_group == OrderGroup.NONE
            for order in self.orders
        )
        
        if has_active_entry_orders:
            # Update order volumes based on current deal state
            self.update_order_volumes(broker)
        else:
            # No active entry orders - check if deal should be closed
            if self.quantity == 0:
                # Deactivate all ACTIVE and NEW orders before closing deal
                has_errors = False
                
                for order in self.orders:
                    if order.status == OrderStatus.ACTIVE:
                        # Cancel active orders
                        order._set_sync_field('status', OrderStatus.CANCELED)
                        order.update_modify_time(broker)
                    elif order.status == OrderStatus.NEW:
                        # Simply mark new orders as canceled
                        order._set_sync_field('status', OrderStatus.CANCELED)
                        order.update_modify_time(broker)
                
                # Mark deal as closed
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
    
    def cancel_orders(self, broker: 'Broker', group: Optional[OrderGroup] = None) -> Tuple[List[str], List['Order']]:
        """
        Cancel orders in this deal by specified group.
        
        Iterates through orders, canceling each one. If cancellation is successful
        and order status is CANCELED or EXECUTED, removes it from deal's orders list.
        Continues on errors, collecting all errors. Repeats the cycle if there are errors,
        stopping only when all orders are canceled or no orders were canceled in a cycle.
        
        Args:
            group: OrderGroup to filter by. If None, cancels all orders.
        
        Returns:
            Tuple[List[str], List[Order]]:
            - List of error messages remaining after last pass. Empty list means all orders were canceled.
            - List of orders that were successfully canceled/executed and removed from this deal during this call.
        """
        # Filter orders by group (if specified)
        if group is None:
            orders_to_cancel = list(self.orders)
        else:
            orders_to_cancel = [order for order in self.orders if order.order_group == group]
        
        all_errors: List[str] = []
        canceled_orders: List['Order'] = []
        
        while True:
            # Clear errors before each pass
            all_errors.clear()
            
            # Count canceled orders in this pass
            canceled_count = 0
            
            # Process each order
            for order in list(orders_to_cancel):  # Use list() to avoid modification during iteration
                # Skip already canceled/executed orders
                if order.status in (OrderStatus.CANCELED, OrderStatus.EXECUTED):
                    orders_to_cancel.remove(order)
                    continue
                
                # Try to cancel order
                order.cancel(broker)
                
                # Check if order was successfully canceled
                if order.status in (OrderStatus.CANCELED, OrderStatus.EXECUTED):
                    # Success: remove order from deal
                    self.orders.remove(order)
                    orders_to_cancel.remove(order)
                    canceled_count += 1
                    canceled_orders.append(order)
            
            # Check exit conditions
            if not orders_to_cancel:
                # All orders canceled
                break
            
            if canceled_count == 0:
                # No orders were canceled in this pass
                break
        
        return all_errors, canceled_orders
    
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
        
        Combines entry orders and stop loss orders, sorts them, and calculates
        volumes based on simulated volume progression.
        """
        # Collect entry and stop orders with sort keys in one pass
        # For entry orders: use price, for stop orders: use trigger_price
        orders_with_keys = []
        has_stop_orders = False
        
        for order in self.orders:
            if order.status not in (OrderStatus.ACTIVE, OrderStatus.NEW):
                continue
            
            if order.order_group == OrderGroup.NONE:
                # Entry order
                assert order.price is not None, f"Entry order {order.order_id} must have price set"
                orders_with_keys.append((order.price, order, 'entry'))
            elif order.order_group == OrderGroup.STOP_LOSS:
                # Stop loss order
                assert order.trigger_price is not None, f"Stop order {order.order_id} must have trigger_price set"
                orders_with_keys.append((order.trigger_price, order, 'stop'))
                has_stop_orders = True
        
        if not has_stop_orders:
            return
        
        # Determine sort direction: for LONG descending, for SHORT ascending
        reverse = (self.type == DealType.LONG)
        orders_with_keys.sort(key=lambda x: x[0], reverse=reverse)
        
        # Initialize simulated volume with current deal quantity
        sim_volume = abs(self.quantity)
        
        # Process each order
        for sort_key, order, order_type in orders_with_keys:
            if order_type == 'entry':
                # Entry order: add its volume to sim_volume
                sim_volume += order.volume
            else:  # stop
                # Stop order: update volume = sim_volume * fraction_remain, then subtract from sim_volume
                assert order.fraction_remain is not None, f"Stop order {order.order_id} must have fraction_remain set"
                new_volume = sim_volume * order.fraction_remain
                formatted_volume = broker.format_volume(new_volume)
                order._set_sync_field('volume', formatted_volume)
                order.update_modify_time(broker)
                sim_volume -= order.volume
    
    def update_take_profit_volumes(self, broker: 'Broker') -> None:
        """
        Update volumes for take profit orders.
        
        Sorts take profit orders and calculates volumes based on simulated volume.
        """
        # Get take profit orders (ACTIVE or NEW)
        take_orders = [
            order for order in self.orders
            if order.order_group == OrderGroup.TAKE_PROFIT
            and order.status in (OrderStatus.ACTIVE, OrderStatus.NEW)
        ]
        
        if not take_orders:
            return
        
        # Determine sort direction: for LONG ascending, for SHORT descending
        reverse = (self.type == DealType.SHORT)
        # Sort by price
        take_orders.sort(
            key=lambda o: o.price if o.price is not None else float('-inf'),
            reverse=reverse
        )
        
        # Initialize simulated volume with current deal quantity
        sim_volume = abs(self.quantity)
        
        # Process each order
        for order in take_orders:
            assert order.fraction_remain is not None, f"Take profit order {order.order_id} must have fraction_remain set"
            # Update volume = sim_volume * fraction_remain
            new_volume = sim_volume * order.fraction_remain
            formatted_volume = broker.format_volume(new_volume)
            order._set_sync_field('volume', formatted_volume)
            order.update_modify_time(broker)
            # Subtract volume from sim_volume
            sim_volume -= order.volume


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
        
        return VOLUME_TYPE(math.floor(value / self.precision_amount) * self.precision_amount)
    
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
        
        deal, canceled_order_ids, errors = self._prepare_deal(
            deal_type, existing_deal_id, clear_enter, clear_stop_loss, clear_take_profit
        )
        
        # If there are errors during order cancellation, stop and return errors
        if errors:
            return (deal, [], canceled_order_ids, errors)
        
        new_orders = []
        entry_side = OrderSide.BUY if deal_type == DealType.LONG else OrderSide.SELL
        opposite_side = OrderSide.SELL if deal_type == DealType.LONG else OrderSide.BUY
        
        entry_orders = self._create_entry_orders(deal, entries, entry_side, opposite_side)
        new_orders.extend(entry_orders)
        
        stop_orders = self._create_stop_loss_orders(deal, stop_losses, opposite_side)
        new_orders.extend(stop_orders)
        
        take_orders = self._create_take_profit_orders(deal, take_profits, opposite_side)
        new_orders.extend(take_orders)
        
        deal.calc_fraction_remain(self, OrderGroup.STOP_LOSS)
        deal.calc_fraction_remain(self, OrderGroup.TAKE_PROFIT)
        
        # Start deal: activate entry and stop loss orders
        orders_to_sync = deal.start(self)
        
        # Note: orders_to_sync contains orders that need to be sent to exchange
        # This will be handled later by exchange synchronization logic
        # For now, we don't collect errors from start() as it no longer returns them
        
        return (deal, new_orders, canceled_order_ids, errors)
    
    def _prepare_deal(
        self,
        deal_type: DealType,
        existing_deal_id: Optional[int],
        clear_enter: bool,
        clear_stop_loss: bool,
        clear_take_profit: bool
    ) -> Tuple['Deal', List[int], List[str]]:
        """
        Prepare deal for execution: create new or get existing and clear orders if needed.
        
        Returns:
            Tuple of (deal, canceled_order_ids, errors)
        """
        if existing_deal_id is not None:
            deal = self.get_deal(existing_deal_id)
            canceled_order_ids, errors = self._clear_deal_orders(deal, clear_enter, clear_stop_loss, clear_take_profit)
        else:
            new_deal_id = len(self.deals) + 1
            deal = Deal(
                deal_id=new_deal_id,
                type=deal_type
            )
            self.deals.append(deal)
            canceled_order_ids = []
            errors = []
        
        return (deal, canceled_order_ids, errors)
    
    def _clear_deal_orders(
        self,
        deal: 'Deal',
        clear_enter: bool,
        clear_stop_loss: bool,
        clear_take_profit: bool
    ) -> Tuple[List[int], List[str]]:
        """
        Clear order groups from deal according to flags.
        
        Returns:
            Tuple of (canceled_order_ids, errors)
        """
        canceled_order_ids = []
        all_errors = []
        
        # Cancel in order: take profits, entries, stop losses
        if clear_take_profit:
            errors, canceled = deal.cancel_orders(self, OrderGroup.TAKE_PROFIT)
            canceled_order_ids.extend([o.order_id for o in canceled])
            all_errors.extend(errors)
        
        if clear_enter:
            errors, canceled = deal.cancel_orders(self, OrderGroup.NONE)
            canceled_order_ids.extend([o.order_id for o in canceled])
            all_errors.extend(errors)
        
        if clear_stop_loss:
            errors, canceled = deal.cancel_orders(self, OrderGroup.STOP_LOSS)
            canceled_order_ids.extend([o.order_id for o in canceled])
            all_errors.extend(errors)
        
        return (canceled_order_ids, all_errors)
    
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
        
        Default implementation (stub). Should be overridden in subclasses if needed.
        """
        pass
    
    def close_deal(self, deal_id: int) -> None:
        """
        Close a specific deal by canceling all active orders and closing position.
        
        Args:
            deal_id: ID of the deal to close
        
        Default implementation (stub). Should be overridden in subclasses if needed.
        """
        raise NotImplementedError("close_deal must be implemented by subclass")
    
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
    
    def logging(self, message: str, level: str = "info") -> None:
        """
        Send log message to frontend via task.
        
        Args:
            message: Message text (required)
            level: Message level (optional, default: "info")
                  Valid levels: info, warning, error, success, debug
        """
        if hasattr(self.task, 'send_message'):
            self.task.send_message(MessageType.MESSAGE, {"level": level, "message": message})
    
    def update_state(self, results: Optional['TaskResults'], is_finish: bool = False) -> None:
        """
        Update task state and progress.
        
        Args:
            results: TaskResults instance to save results to Redis, or None if results should not be saved
            is_finish: If True, marks the backtesting result as completed. Default: False.
        
        Default implementation (stub). Should be overridden in subclasses if needed.
        """
        raise NotImplementedError("update_state must be implemented by subclass")
    
    def check_trading_results(self) -> List[str]:
        """
        Check trading results for consistency.
        
        Returns:
            List of error messages (empty if no errors found)
        
        Default implementation (stub). Should be overridden in subclasses if needed.
        """
        return []
    
    def create_trade(self, order: Order, quantity: VOLUME_TYPE, price: PRICE_TYPE, fee: PRICE_TYPE) -> None:
        """
        Create a trade from an executed order.
        
        Creates a Trade object, updates order's filled_volume, sets order status to EXECUTED
        if fully filled, and adds the trade to the deal.
        
        Args:
            order: Order that was executed
            quantity: Quantity executed in this trade
            price: Execution price
            fee: Fee for this trade
        
        Raises:
            AssertionError: If quantity <= 0, price <= 0, fee < 0, or current_time is not set
            IndexError: If deal with order.deal_id does not exist
        """
        # Validate inputs
        assert quantity > 0, f"quantity must be > 0, got {quantity}"
        assert price > 0, f"price must be > 0, got {price}"
        assert fee >= 0, f"fee must be >= 0, got {fee}"
        assert self.current_time is not None, "current_time must be set before creating trade"
        
        # Generate trade_id (size of trades list + 1)
        trade_id = len(self.trades) + 1
        
        # Calculate trade sum
        trade_sum = quantity * price
        
        # Create Trade
        trade = Trade(
            trade_id=trade_id,
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
        deal.add_trade(self, trade, self.precision_amount)
        
        # Add trade to broker's trades list
        self.trades.append(trade)
    
    def fetch_orders(self) -> None:
        """
        Fetch and execute orders (check for triggered limit/stop orders).
        
        Must be implemented in subclasses (e.g., backtesting or live trading brokers).
        """
        raise NotImplementedError("fetch_orders not implemented")
    
    def place_orders(self) -> int:
        """
        Place orders to exchange that are marked as unsynced (actual=False).
        
        This method should:
        1. Find all orders where actual=False
        2. For orders with status ACTIVE or NEW: call create_order() to place them on exchange
        3. For orders with status CANCELED or EXECUTED: call cancel_order() to cancel them on exchange
        4. After successful placement/cancellation, set actual=True
        
        Returns:
            int: Number of orders successfully placed/updated
        
        Must be implemented in subclasses (e.g., backtesting or live trading brokers).
        """
        raise NotImplementedError("place_orders not implemented")

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
                time.sleep(BAR_WAIT_INTERVAL)
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
            self.fetch_orders()
            placed_count = self.place_orders()
            
            if placed_count == 0:
                break
                
            time.sleep(ORDER_WAIT_INTERVAL)

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
                    if hasattr(self, 'update_state'):
                        self.update_state(results)
                    last_update_time = current_time_real
                    state_update_period = min(state_update_period + 1.0, self.results_save_period)
            
            self.i_time += 1
        
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
        price: Optional[float] = None, 
        params: Dict = None
    ) -> Dict:
        """
        Create an order (abstract method).
        
        Args:
            symbol: Trading symbol
            order_type: Order type (MARKET, LIMIT, STOP)
            side: Order side (BUY, SELL)
            amount: Order amount
            price: Order price (optional, for limit/stop orders)
            params: Additional parameters (optional)
        
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
    def exchange_fetch_order(self, exchange_order_id: str, symbol: str) -> Dict:
        """
        Fetch an order by its ID.
        
        Args:
            exchange_order_id: Exchange order ID to fetch
            symbol: Trading symbol
        
        Returns:
            Dictionary with order details
        
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("exchange_fetch_order must be implemented by subclass")
    
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
        

