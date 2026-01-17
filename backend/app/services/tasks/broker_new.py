from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Set, Dict, Any, Tuple, TYPE_CHECKING
import math
import weakref

import numpy as np
from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE

if TYPE_CHECKING:
    from app.services.tasks.tasks import Task
    from app.services.tasks.broker import Deal, Trade


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(Enum):
    NEW = 0  # Only created, not processed
    ACTIVE = 1  # Validated and active (only limit and stop orders)
    EXECUTED = 2  # Executed (market immediately, limit/stop after execution)
    CANCELED = 3  # Was active, canceled (in real trading may be partially executed)
    ERROR = 4  # Failed validation (in real trading may be other reasons)


class OrderGroup(Enum):
    NONE = 0  # Outside of group (default)
    STOP_LOSS = 1  # Stop loss order
    TAKE_PROFIT = 2  # Take profit order


class DealType(Enum):
    LONG = "long"
    SHORT = "short"


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
    
    The `modify_time` field is updated automatically whenever any field is modified.
    Immutable fields: create_time, side, price, trigger_price.
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
    
    # Weak reference to broker (internal, set at creation)
    _broker_ref: weakref.ref = Field(exclude=True)
    
    # Mutable fields
    modify_time: np.datetime64
    volume: VOLUME_TYPE
    filled_volume: VOLUME_TYPE = 0.0
    status: OrderStatus = OrderStatus.NEW
    order_group: OrderGroup = OrderGroup.NONE
    fraction: Optional[float] = None
    fraction_remain: Optional[float] = None
    errors: List[str] = Field(default_factory=list)
    
    def __init__(self, broker: 'Broker', **data):
        """
        Initialize Order with broker.
        
        Args:
            broker: Broker instance (required, stored as weak reference)
            **data: Other Order fields
        """
        # Create weak reference to broker immediately
        if broker is None:
            raise ValueError("broker must be provided and cannot be None")
        self._broker_ref = weakref.ref(broker)
        
        # Initialize Pydantic model without broker field
        super().__init__(**data)
    
    def __setattr__(self, name: str, value) -> None:
        """
        Override __setattr__ to:
        1. Protect immutable fields from modification
        2. Automatically update modify_time when any mutable field changes
        """
        # List of immutable fields
        immutable_fields = {'order_id', 'deal_id', 'order_type', 'create_time', 'side', 'price', 'trigger_price'}
        
        # Check if object is already initialized by checking if __pydantic_fields_set__ exists
        # This is set by Pydantic after model initialization
        is_initialized = hasattr(self, '__pydantic_fields_set__')
        
        if is_initialized:
            # Protect immutable fields
            if name in immutable_fields:
                # Get current value if field exists
                try:
                    current_value = object.__getattribute__(self, name)
                    if current_value is not None and current_value != value:
                        raise ValueError(f"Cannot modify immutable field '{name}' after object creation")
                except AttributeError:
                    # Field doesn't exist yet, allow setting during initialization
                    pass
            
            # Protect modify_time from direct modification
            if name == 'modify_time':
                raise ValueError("Cannot modify 'modify_time' directly. It is updated automatically when other fields change.")
            
            # Update modify_time when mutable field changes (except modify_time itself)
            if name != 'modify_time' and name not in immutable_fields:
                # Get broker from weak reference
                broker = self._broker_ref()
                if broker is None:
                    raise RuntimeError("Cannot update modify_time: broker has been garbage collected")
                
                # Get current_time from broker
                current_time = broker.current_time
                assert current_time is not None, "Broker's current_time is not set"
                
                # Use BaseModel's __setattr__ to allow Pydantic validation
                # This will trigger validate_assignment=True validation
                BaseModel.__setattr__(self, name, value)
                
                # Then update modify_time using BaseModel.__setattr__ to bypass our __setattr__
                # This avoids recursion and allows Pydantic to handle it
                BaseModel.__setattr__(self, 'modify_time', current_time)
                return
        
        # For initial assignment (during __init__), use BaseModel's __setattr__
        # Pydantic will handle validation through its normal mechanism
        BaseModel.__setattr__(self, name, value)
    
    @model_validator(mode='after')
    def validate_order(self):
        """Validate order fields.
        
        - order_id and deal_id must be greater than 0
        - Either price or trigger_price must be set (not both None)
        - If status is ACTIVE, volume must be greater than 0
        - fraction must be set for orders with order_group != NONE
        - price, trigger_price, and volume must be properly rounded according to broker precision
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
        
        # Validate rounding: price, trigger_price, and volume must be properly rounded
        broker = self._broker_ref()
        if broker is None:
            raise RuntimeError("Cannot validate rounding: broker has been garbage collected")
        
        # Validate price rounding
        if self.price is not None:
            formatted_price = broker.format_price(self.price)
            assert self.price == formatted_price, \
                f"price must be properly rounded (got {self.price}, expected {formatted_price})"
        
        # Validate trigger_price rounding
        if self.trigger_price is not None:
            formatted_trigger_price = broker.format_price(self.trigger_price)
            assert self.trigger_price == formatted_trigger_price, \
                f"trigger_price must be properly rounded (got {self.trigger_price}, expected {formatted_trigger_price})"
        
        # Validate volume rounding
        formatted_volume = broker.format_volume(self.volume)
        assert self.volume == formatted_volume, \
            f"volume must be properly rounded (got {self.volume}, expected {formatted_volume})"
        
        return self
    
    def broker(self) -> 'Broker':
        """
        Get broker instance from weak reference.
        
        Returns:
            Broker instance
        
        Raises:
            RuntimeError: If broker has been garbage collected
        """
        broker = self._broker_ref()
        if broker is None:
            raise RuntimeError("Broker has been garbage collected")
        return broker
    
    def cancel(self) -> List[str]:
        """
        Cancel this order.
        
        Calls broker.cancel_order() and updates order status based on result.
        If cancellation is successful and filled_volume == 0, sets status to CANCELED.
        If cancellation is successful and filled_volume > 0, sets status to EXECUTED.
        If there are errors, adds them to order.errors and returns the error list.
        
        Returns:
            List of error messages. Empty list means success.
        
        Raises:
            AssertionError: If order status is not ACTIVE or NEW
            RuntimeError: If broker has been garbage collected
        """
        # Check that order can be canceled
        assert self.status in (OrderStatus.ACTIVE, OrderStatus.NEW), \
            f"Cannot cancel order with status {self.status}"
        
        # Get broker and call cancel_order
        broker = self.broker()
        errors = broker.cancel_order(str(self.order_id), broker.symbol)
        
        # If no errors, update status
        if not errors:
            if self.filled_volume == 0:
                self.status = OrderStatus.CANCELED
            else:
                self.status = OrderStatus.EXECUTED
        else:
            # Add errors to order.errors
            self.errors.extend(errors)
        
        return errors


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
    
    # Type of deal closure (copied from last exit order's order_group, or NONE if closed via regular buy/sell)
    close_type: Optional[OrderGroup] = None
    
    # Internal accumulators for efficient incremental updates
    buy_quantity: VOLUME_TYPE = 0.0
    buy_cost: PRICE_TYPE = 0.0
    sell_quantity: VOLUME_TYPE = 0.0
    sell_proceeds: PRICE_TYPE = 0.0
    
    # Weak reference to broker (internal, set at creation)
    _broker_ref: weakref.ref = Field(exclude=True)
    
    def __init__(self, broker: 'Broker', **data):
        """
        Initialize Deal with broker.
        
        Args:
            broker: Broker instance (required, stored as weak reference)
            **data: Other Deal fields
        """
        # Create weak reference to broker immediately
        if broker is None:
            raise ValueError("broker must be provided and cannot be None")
        self._broker_ref = weakref.ref(broker)
        
        # Initialize Pydantic model without broker field
        super().__init__(**data)
    
    def add_trade(self, trade: Trade, precision_amount: float) -> None:
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
        

    @property
    def unrealized_profit(self) -> Optional[PRICE_TYPE]:
        """
        Calculate unrealized profit for an open position at current_price from broker.

        For closed positions, the result matches the realized profit.
        
        Returns:
            Unrealized profit if broker and current_price are available, None otherwise
        """
        # Get broker from weak reference
        broker = self._broker_ref()
        if broker is None:
            return None
        
        current_price = broker.current_price
        
        # Value of current open position at market price
        current_value = self.quantity * current_price

        # Hypothetical total PnL if we closed the position now:
        # (all sells done + value of remaining position) - all buys - all fees
        return self.sell_proceeds + current_value - self.buy_cost - self.fee
    
    def cancel_orders(self, group: Optional[OrderGroup] = None) -> Tuple[List[str], List['Order']]:
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
                errors = order.cancel()
                
                if not errors:
                    # Success: check if order should be removed
                    if order.status in (OrderStatus.CANCELED, OrderStatus.EXECUTED):
                        self.orders.remove(order)
                        orders_to_cancel.remove(order)
                        canceled_count += 1
                        canceled_orders.append(order)
                else:
                    # Errors occurred: add to error list
                    all_errors.extend(errors)
            
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
    
    def calc_fraction_remain(self, order_group: OrderGroup) -> None:
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
            
            # Update remain
            remain = remain - order.fraction
        
        # Assert that remain is 0 after processing all orders
        assert abs(remain) < 1e-10, f"Remain should be 0 after processing all orders, got {remain}"


class Broker(ABC):
    """
    Generic broker base class.
    """
    
    def __init__(self, task: 'Task', result_id: str):
        """
        Initialize broker.
        
        Args:
            task: Task instance (must contain precision_amount and precision_price > 0)
            result_id: Unique ID for this backtesting run
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
        
        # Precision for amount and price
        self.precision_amount: float = task.precision_amount
        self.precision_price: float = task.precision_price
    
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
    
    @abstractmethod
    def create_order(
        self,
        symbol: str,
        type: OrderType,
        side: OrderSide,
        amount: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create an order (abstract method, corresponds to exchange.create_order() from ccxt).
        
        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            type: Order type (OrderType enum: MARKET, LIMIT, STOP)
            side: Order side (OrderSide enum: BUY or SELL)
            amount: Order amount (quantity) as VOLUME_TYPE
            price: Optional price for limit orders as PRICE_TYPE
            params: Optional additional parameters (e.g., {'stopPrice': 100.0} for stop orders)
        
        Returns:
            Dictionary with order information (typically contains 'id', 'symbol', 'type', 'side', 
            'amount', 'price', 'status', 'timestamp', etc.)
        
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("create_order must be implemented by subclass")
    
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
        
        deal.calc_fraction_remain(OrderGroup.STOP_LOSS)
        deal.calc_fraction_remain(OrderGroup.TAKE_PROFIT)
        
        return (deal, new_orders, canceled_order_ids, [])
    
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
                broker=self,
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
            errors, canceled = deal.cancel_orders(OrderGroup.TAKE_PROFIT)
            canceled_order_ids.extend([o.order_id for o in canceled])
            all_errors.extend(errors)
        
        if clear_enter:
            errors, canceled = deal.cancel_orders(OrderGroup.NONE)
            canceled_order_ids.extend([o.order_id for o in canceled])
            all_errors.extend(errors)
        
        if clear_stop_loss:
            errors, canceled = deal.cancel_orders(OrderGroup.STOP_LOSS)
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
            broker=self,
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
    
    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> List[str]:
        """
        Cancel an order by its ID.
        
        Args:
            order_id: Order ID to cancel
            symbol: Trading symbol (e.g., 'BTC/USDT')
        
        Returns:
            List of error messages. Empty list means success (order was canceled successfully).
            Non-empty list contains error descriptions if cancellation failed.
        
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("cancel_order must be implemented by subclass")

