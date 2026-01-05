"""
Broker class for handling trading operations and backtesting execution.
"""
from typing import Optional, Dict, Callable, List, Tuple
import numpy as np
import time
from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import Broker, OrderSide, OrderType, OrderStatus
from app.services.tasks.backtesting_result import BackTestingResults
from app.core.logger import get_logger
from app.core.datetime_utils import parse_utc_datetime, parse_utc_datetime64, datetime64_to_iso
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType
from app.services.tasks.indicator_proxy import ta_proxy_talib

logger = get_logger(__name__)


class Order(BaseModel):
    """
    Represents an order.
    
    Can be a limit order or a conditional order (stop order):
    - Limit order: only `price` is set. Executes when market price reaches limit price.
    - Stop order: `trigger_price` is set. Executes when market price reaches trigger price.
    - Stop-limit order: both `price` and `trigger_price` are set. When trigger_price is reached,
      a limit order at `price` is placed.
    
    The `modify_time` field is updated whenever the order is modified (executed, cancelled, etc.).
    This allows filtering orders by modification time for efficient retrieval.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    order_id: int = Field(description="Order ID (assigned when order is added to orders list)")
    deal_id: Optional[int] = None
    order_type: OrderType  # Type of order: limit or stop (market orders are not stored as Order objects)
    create_time: np.datetime64
    modify_time: np.datetime64
    side: OrderSide
    price: Optional[PRICE_TYPE] = None
    trigger_price: Optional[PRICE_TYPE] = None
    volume: VOLUME_TYPE
    filled_volume: VOLUME_TYPE = 0.0
    status: OrderStatus = OrderStatus.NEW
    errors: List[str] = Field(default_factory=list)  # List of validation/execution errors
    
    @model_validator(mode='after')
    def validate_order_id(self):
        """Validate that order_id is greater than 0 if order is not in NEW or ERROR status.
        
        Orders with ERROR status may have order_id=0 if they failed validation before being added to orders list.
        Orders with NEW status have order_id=0 until they are processed in execute_orders().
        """
        if self.order_id <= 0 and self.status not in (OrderStatus.NEW, OrderStatus.ERROR):
            raise ValueError(f"order_id must be greater than 0 for orders with status {self.status}")
        return self


class BrokerBacktesting(Broker):
    """
    Broker class for handling trading operations and backtesting execution.
    Minimal working version with buy/sell stubs.
    """
    
    def __init__(
        self, 
        task: Task, 
        result_id: str,
        callbacks_dict: Dict[str, Callable],
        results_save_period: float = TRADE_RESULTS_SAVE_PERIOD
    ):
        """
        Initialize broker.
        
        Args:
            task: Task instance (contains fee_taker, fee_maker, price_step, slippage_in_steps)
            result_id: Unique ID for this backtesting run
            callbacks_dict: Dictionary with callback functions:
                - 'on_start': Callable(parameters: Dict[str, Any])
                - 'on_bar': Callable(price, current_time, time, open, high, low, close, volume, equity_usd, equity_symbol)
                - 'on_finish': Callable with no arguments
            results_save_period: Period for saving results in seconds (default: TRADE_RESULTS_SAVE_PERIOD)
        """
        super().__init__(result_id)
        self.task = task
        # Get fee and slippage from task, with defaults
        self.fee_taker = task.fee_taker if task.fee_taker > 0 else 0.001  # Default to 0.1% if not set
        self.fee_maker = task.fee_maker if task.fee_maker > 0 else 0.001  # Default to 0.1% if not set
        # Calculate slippage from slippage_in_steps and price_step
        self.slippage = (task.slippage_in_steps * task.price_step) if task.price_step > 0 else 0.0
        self.results_save_period = results_save_period
        self.callbacks = callbacks_dict
        
        # Trading state
        self.price: Optional[PRICE_TYPE] = None
        self.current_time: Optional[np.datetime64] = None
        self.i_time: int = 0  # Current bar index in backtesting loop
        
        # Progress tracking
        self.progress: float = 0.0
        self.date_start: Optional[np.datetime64] = None
        self.date_end: Optional[np.datetime64] = None
        
        # Equity tracking for backtesting
        self.equity_usd: PRICE_TYPE = 0.0
        self.equity_symbol: VOLUME_TYPE = 0.0
        
        # Limit orders tracking (initialized by _init_order_arrays)
        self.orders: List[Order]
        self.long_order_ids: np.ndarray
        self.long_order_prices: np.ndarray
        self.short_order_ids: np.ndarray
        self.short_order_prices: np.ndarray
        # Stop orders tracking
        self.long_stop_order_ids: np.ndarray
        self.long_stop_trigger_prices: np.ndarray
        self.short_stop_order_ids: np.ndarray
        self.short_stop_trigger_prices: np.ndarray
        self._init_order_arrays()
    
    def _init_order_arrays(self) -> None:
        """
        Initialize order tracking arrays.
        Called from __init__ and reset() to avoid code duplication.
        """
        self.orders = []
        # Numpy arrays for fast order lookup (long limit orders)
        self.long_order_ids = np.array([], dtype=np.int64)
        self.long_order_prices = np.array([], dtype=PRICE_TYPE)
        # Numpy arrays for fast order lookup (short limit orders)
        self.short_order_ids = np.array([], dtype=np.int64)
        self.short_order_prices = np.array([], dtype=PRICE_TYPE)
        # Numpy arrays for fast order lookup (long stop orders)
        self.long_stop_order_ids = np.array([], dtype=np.int64)
        self.long_stop_trigger_prices = np.array([], dtype=PRICE_TYPE)
        # Numpy arrays for fast order lookup (short stop orders)
        self.short_stop_order_ids = np.array([], dtype=np.int64)
        self.short_stop_trigger_prices = np.array([], dtype=PRICE_TYPE)
    
    def reset(self) -> None:
        """
        Reset broker state.
        """
        # Pass task to parent reset() to populate stats parameters
        super().reset(task=self.task)
        self.price = None
        
        # Initialize date range for progress calculation
        try:
            self.date_start = parse_utc_datetime64(self.task.dateStart)
            self.date_end = parse_utc_datetime64(self.task.dateEnd)
        except Exception as e:
            raise RuntimeError(
                f"Failed to parse task dateStart/dateEnd for progress calculation: {e}"
            ) from e
        
        # Initialize progress to 0
        self.progress = 0.0
        
        # Reset equity
        self.equity_usd = 0.0
        self.equity_symbol = 0.0
    
        # Reset limit orders
        self._init_order_arrays()
    
    def _execute_trade(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: PRICE_TYPE,
        deal_id: Optional[int] = None,
        order_id: Optional[int] = None,
        is_market_order: bool = False
    ) -> Tuple[List[int], List[int]]:
        """
        Execute a trade (buy or sell) at specified price.
        Common logic for both market and limit order execution.
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Quantity to trade
            price: Execution price (before slippage adjustment)
            deal_id: Optional deal ID to associate with this trade
            order_id: Optional order ID that triggered this trade
            is_market_order: If True, apply slippage and use fee_taker; otherwise use fee_maker
        
        Returns:
            Tuple of (trades: List[int], deals: List[int]) containing IDs
        """
        # Apply slippage for market orders (always in unfavorable direction)
        execution_price = price
        if is_market_order and self.slippage > 0:
            if side == OrderSide.BUY:
                # Buy: slippage increases price (unfavorable)
                execution_price = price + self.slippage
            else:  # SELL
                # Sell: slippage decreases price (unfavorable)
                execution_price = price - self.slippage
        
        # Select fee based on order type
        fee_rate = self.fee_taker if is_market_order else self.fee_maker
        
        # Calculate trade amount and fee
        trade_amount = quantity * execution_price
        trade_fee = trade_amount * fee_rate
        
        # Update equity
        if side == OrderSide.BUY:
            self.equity_symbol += quantity
            self.equity_usd -= trade_amount + trade_fee
            trades, deals = self.reg_buy(quantity, trade_fee, execution_price, self.current_time, deal_id=deal_id, order_id=order_id)
        else:  # SELL
            self.equity_symbol -= quantity
            self.equity_usd += trade_amount - trade_fee
            trades, deals = self.reg_sell(quantity, trade_fee, execution_price, self.current_time, deal_id=deal_id, order_id=order_id)
        
        return (trades, deals)
    
    def _validate_orders(self, orders: List[Order]) -> Tuple[List[Order], int]:
        """
        Validate a list of orders and add errors to order.errors if validation fails.
        
        Args:
            orders: List of orders to validate
            
        Returns:
            Tuple of (validated orders list, number of errors found)
        """
        if not orders:
            return orders, 0
        
        if self.price is None:
            raise RuntimeError("Cannot validate orders: current price is not set")
        
        error_count = 0
        
        for order in orders:
            # Check quantity
            if order.volume <= 0:
                order.errors.append(f"Order quantity must be greater than 0, got {order.volume}")
                error_count += 1
            
            # Check: either price or trigger_price, but not both
            if order.price is not None and order.trigger_price is not None:
                order.errors.append("Cannot specify both price and trigger_price")
                order.status = OrderStatus.ERROR
                error_count += 1
            
            # Validate based on order type
            if order.order_type == OrderType.MARKET:
                # Market order: price and trigger_price must be None
                if order.price is not None:
                    order.errors.append("Market order cannot have price set")
                    order.status = OrderStatus.ERROR
                    error_count += 1
                if order.trigger_price is not None:
                    order.errors.append("Market order cannot have trigger_price set")
                    order.status = OrderStatus.ERROR
                    error_count += 1
            
            elif order.order_type == OrderType.LIMIT:
                # Limit order: trigger_price must be None, price must be set
                if order.trigger_price is not None:
                    order.errors.append("Limit order cannot have trigger_price set")
                    order.status = OrderStatus.ERROR
                    error_count += 1
                if order.price is None:
                    order.errors.append("Limit order must have price set")
                    order.status = OrderStatus.ERROR
                    error_count += 1
                else:
                    # Check proper price placement relative to current price
                    if order.side == OrderSide.BUY:
                        # For BUY limit: current price must be >= limit price (limit below or equal to current)
                        if self.price < order.price:
                            time_str = datetime64_to_iso(self.current_time)
                            order.errors.append(
                                f"BUY limit order price ({order.price}) must be below or equal to current price ({self.price}) at time {time_str}"
                            )
                            order.status = OrderStatus.ERROR
                            error_count += 1
                    else:  # SELL
                        # For SELL limit: current price must be <= limit price (limit above or equal to current)
                        if self.price > order.price:
                            time_str = datetime64_to_iso(self.current_time)
                            order.errors.append(
                                f"SELL limit order price ({order.price}) must be above or equal to current price ({self.price}) at time {time_str}"
                            )
                            order.status = OrderStatus.ERROR
                            error_count += 1
            
            elif order.order_type == OrderType.STOP:
                # Stop order: price must be None, trigger_price must be set
                if order.price is not None:
                    order.errors.append("Stop order cannot have price set")
                    order.status = OrderStatus.ERROR
                    error_count += 1
                if order.trigger_price is None:
                    order.errors.append("Stop order must have trigger_price set")
                    order.status = OrderStatus.ERROR
                    error_count += 1
                else:
                    # Check proper trigger_price placement relative to current price
                    if order.side == OrderSide.BUY:
                        # For BUY stop: current price must be < trigger_price
                        if self.price >= order.trigger_price:
                            time_str = datetime64_to_iso(self.current_time)
                            order.errors.append(
                                f"BUY stop order trigger_price ({order.trigger_price}) must be above current price ({self.price}) at time {time_str}"
                            )
                            order.status = OrderStatus.ERROR
                            error_count += 1
                    else:  # SELL
                        # For SELL stop: current price must be > trigger_price
                        if self.price <= order.trigger_price:
                            time_str = datetime64_to_iso(self.current_time)
                            order.errors.append(
                                f"SELL stop order trigger_price ({order.trigger_price}) must be below current price ({self.price}) at time {time_str}"
                            )
                            order.status = OrderStatus.ERROR
                            error_count += 1
        
        return orders, error_count
    
    def execute_orders(self, orders: List[Order]) -> List[Order]:
        """
        Execute or place orders from the list.
        Market orders are executed immediately, limit/stop orders are placed.
        
        Args:
            orders: List of validated orders to execute/place
            
        Returns:
            List of copies of executed/placed orders
        """
        if not orders:
            return []
        
        if self.current_time is None:
            raise RuntimeError("Cannot execute orders: current_time is not set")
        
        executed_orders = []
        
        for order in orders:
            try:
                if order.order_type == OrderType.MARKET:
                    # Market order: execute immediately
                    if self.price is None:
                        raise RuntimeError("Cannot execute market order: price is not set")
                    
                    # Calculate execution price with slippage
                    execution_price = self.price
                    if self.slippage > 0:
                        if order.side == OrderSide.BUY:
                            # Buy: slippage increases price (unfavorable)
                            execution_price = self.price + self.slippage
                        else:  # SELL
                            # Sell: slippage decreases price (unfavorable)
                            execution_price = self.price - self.slippage
                    
                    # Update order state before execution
                    order.price = execution_price
                    order.modify_time = self.current_time
                    
                    # Add to orders list for history (before execution)
                    order.order_id = len(self.orders) + 1
                    self.orders.append(order)
                    
                    # Execute trade
                    self._execute_trade(
                        order.side,
                        order.volume,
                        execution_price,
                        deal_id=order.deal_id,
                        order_id=order.order_id,
                        is_market_order=True
                    )
                    
                    # Update order state after execution
                    order.filled_volume = order.volume
                    order.status = OrderStatus.EXECUTED
                    
                elif order.order_type == OrderType.LIMIT:
                    # Limit order: place it
                    order.order_id = len(self.orders) + 1
                    order.status = OrderStatus.ACTIVE
                    self.orders.append(order)
                    self._add_order_to_arrays(order)
                    
                elif order.order_type == OrderType.STOP:
                    # Stop order: place it
                    order.order_id = len(self.orders) + 1
                    order.status = OrderStatus.ACTIVE
                    self.orders.append(order)
                    self._add_order_to_arrays(order)
                
                # Create a copy of the order for return
                executed_orders.append(order.model_copy(deep=True))
                
            except Exception as e:
                # Add error to order and mark as error
                order.errors.append(str(e))
                order.status = OrderStatus.ERROR
                # Still add to executed orders list (with error)
                executed_orders.append(order.model_copy(deep=True))
        
        return executed_orders
    
    def buy(self, quantity: VOLUME_TYPE, price: Optional[PRICE_TYPE] = None, trigger_price: Optional[PRICE_TYPE] = None) -> List[Order]:
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
        """
        if self.current_time is None:
            raise RuntimeError("Cannot create buy order: current_time is not set")
        
        # Create order based on parameters
        if trigger_price is not None:
            # Stop order
            order = Order(
                order_id=0,  # Will be assigned in execute_orders
                price=None,
                volume=quantity,
                create_time=self.current_time,
                modify_time=self.current_time,
                filled_volume=0.0,
                status=OrderStatus.NEW,
                side=OrderSide.BUY,
                deal_id=None,
                trigger_price=trigger_price,
                order_type=OrderType.STOP,
                errors=[]
            )
        elif price is not None:
            # Limit order
            order = Order(
                order_id=0,  # Will be assigned in execute_orders
                price=price,
                volume=quantity,
                create_time=self.current_time,
                modify_time=self.current_time,
                filled_volume=0.0,
                status=OrderStatus.NEW,
                side=OrderSide.BUY,
                deal_id=None,
                trigger_price=None,
                order_type=OrderType.LIMIT,
                errors=[]
            )
        else:
            # Market order
            order = Order(
                order_id=0,  # Will be assigned in execute_orders
                price=None,
                volume=quantity,
                create_time=self.current_time,
                modify_time=self.current_time,
                filled_volume=0.0,
                status=OrderStatus.NEW,
                side=OrderSide.BUY,
                deal_id=None,
                trigger_price=None,
                order_type=OrderType.MARKET,
                errors=[]
            )
        
        # Validate orders
        orders, error_count = self._validate_orders([order])
        
        # If validation errors found, return orders with errors
        if error_count > 0:
            return [order.model_copy(deep=True) for order in orders]
        
        # Execute/place orders
        return self.execute_orders(orders)
    
    def sell(self, quantity: VOLUME_TYPE, price: Optional[PRICE_TYPE] = None, trigger_price: Optional[PRICE_TYPE] = None) -> List[Order]:
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
        """
        if self.current_time is None:
            raise RuntimeError("Cannot create sell order: current_time is not set")
        
        # Create order based on parameters
        if trigger_price is not None:
            # Stop order
            order = Order(
                order_id=0,  # Will be assigned in execute_orders
                price=None,
                volume=quantity,
                create_time=self.current_time,
                modify_time=self.current_time,
                filled_volume=0.0,
                status=OrderStatus.NEW,
                side=OrderSide.SELL,
                deal_id=None,
                trigger_price=trigger_price,
                order_type=OrderType.STOP,
                errors=[]
            )
        elif price is not None:
            # Limit order
            order = Order(
                order_id=0,  # Will be assigned in execute_orders
                price=price,
                volume=quantity,
                create_time=self.current_time,
                modify_time=self.current_time,
                filled_volume=0.0,
                status=OrderStatus.NEW,
                side=OrderSide.SELL,
                deal_id=None,
                trigger_price=None,
                order_type=OrderType.LIMIT,
                errors=[]
            )
        else:
            # Market order
            order = Order(
                order_id=0,  # Will be assigned in execute_orders
                price=None,
                volume=quantity,
                create_time=self.current_time,
                modify_time=self.current_time,
                filled_volume=0.0,
                status=OrderStatus.NEW,
                side=OrderSide.SELL,
                deal_id=None,
                trigger_price=None,
                order_type=OrderType.MARKET,
                errors=[]
            )
        
        # Validate orders
        orders, error_count = self._validate_orders([order])
        
        # If validation errors found, return orders with errors
        if error_count > 0:
            return [order.model_copy(deep=True) for order in orders]
        
        # Execute/place orders
        return self.execute_orders(orders)
    
    def _add_order_to_arrays(self, order: Order) -> None:
        """
        Add order to numpy arrays for fast lookup.
        
        Args:
            order: Order to add
        """
        if order.order_type == OrderType.STOP:
            # Stop order
            if order.side == OrderSide.BUY:
                # Add to long stop arrays
                self.long_stop_order_ids = np.append(self.long_stop_order_ids, order.order_id)
                self.long_stop_trigger_prices = np.append(self.long_stop_trigger_prices, order.trigger_price)
            else:  # SELL
                # Add to short stop arrays
                self.short_stop_order_ids = np.append(self.short_stop_order_ids, order.order_id)
                self.short_stop_trigger_prices = np.append(self.short_stop_trigger_prices, order.trigger_price)
        elif order.order_type == OrderType.LIMIT:
            # Limit order
            if order.side == OrderSide.BUY:
                # Add to long arrays
                self.long_order_ids = np.append(self.long_order_ids, order.order_id)
                self.long_order_prices = np.append(self.long_order_prices, order.price)
            else:  # SELL
                # Add to short arrays
                self.short_order_ids = np.append(self.short_order_ids, order.order_id)
                self.short_order_prices = np.append(self.short_order_prices, order.price)
        else:
            raise ValueError(f"Invalid order type: {order.order_type} in _add_order_to_arrays: {order.order_id}")
    
    def _remove_order_from_arrays(self, order: Order) -> None:
        """
        Remove order from numpy arrays.
        
        Args:
            order: Order to remove
        """
        if order.order_type == OrderType.STOP:
            # Remove from stop arrays
            if order.side == OrderSide.BUY:
                mask = self.long_stop_order_ids != order.order_id
                self.long_stop_order_ids = self.long_stop_order_ids[mask]
                self.long_stop_trigger_prices = self.long_stop_trigger_prices[mask]
            else:  # SELL
                mask = self.short_stop_order_ids != order.order_id
                self.short_stop_order_ids = self.short_stop_order_ids[mask]
                self.short_stop_trigger_prices = self.short_stop_trigger_prices[mask]
        elif order.order_type == OrderType.LIMIT:
            # Remove from limit arrays
            if order.side == OrderSide.BUY:
                mask = self.long_order_ids != order.order_id
                self.long_order_ids = self.long_order_ids[mask]
                self.long_order_prices = self.long_order_prices[mask]
            else:  # SELL
                mask = self.short_order_ids != order.order_id
                self.short_order_ids = self.short_order_ids[mask]
                self.short_order_prices = self.short_order_prices[mask]
        else:
            raise ValueError(f"Invalid order type: {order.order_type} in _remove_order_from_arrays: {order.order_id}")
    
    def _execute_triggered_order(self, order: Order, high: PRICE_TYPE, low: PRICE_TYPE) -> None:
        """
        Execute a triggered order (limit or stop).
        
        Args:
            order: Order to execute
            high: High price of current bar (for logging)
            low: Low price of current bar (for logging)
        """
        if order.status != OrderStatus.ACTIVE:
            return
        
        # Determine execution price based on order type
        if order.order_type == OrderType.STOP:
            # Stop order: execute at trigger_price
            execution_price = order.trigger_price
        elif order.order_type == OrderType.LIMIT:
            # Limit order: execute at limit price
            execution_price = order.price
        else:
            # Should not happen for triggered orders, but handle gracefully
            logger.warning(f"Unexpected order type {order.order_type} in _execute_triggered_order {order.order_id}")
            return
        
        # Execute order (limit/stop orders are not market orders, so no slippage, use fee_maker)
        self._execute_trade(
            order.side,
            order.volume,
            execution_price,
            deal_id=order.deal_id,
            order_id=order.order_id,
            is_market_order=False
        )
        # Mark order as executed
        order.filled_volume = order.volume
        order.status = OrderStatus.EXECUTED
        # Update modify_time to execution time
        order.modify_time = self.current_time
        
        # Remove order from arrays (no longer active)
        self._remove_order_from_arrays(order)
    
    def _check_and_execute_orders(self, high: PRICE_TYPE, low: PRICE_TYPE) -> None:
        """
        Check for triggered orders (limit and stop) on current bar and execute them.
        Uses vectorized operations to find triggered orders.
        
        Args:
            high: High price of current bar
            low: Low price of current bar
        """
        # Check long limit orders (BUY): triggered if low < price
        if len(self.long_order_ids) > 0:
            triggered_mask = low < self.long_order_prices
            triggered_order_ids = self.long_order_ids[triggered_mask]
            
            if len(triggered_order_ids) > 0:
                for order_id in triggered_order_ids:
                    order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                    self._execute_triggered_order(order, high, low)
        
        # Check short limit orders (SELL): triggered if high > price
        if len(self.short_order_ids) > 0:
            triggered_mask = high > self.short_order_prices
            triggered_order_ids = self.short_order_ids[triggered_mask]
            
            if len(triggered_order_ids) > 0:
                for order_id in triggered_order_ids:
                    order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                    self._execute_triggered_order(order, high, low)
        
        # Check long stop orders (BUY): triggered if high >= trigger_price (breakout up)
        if len(self.long_stop_order_ids) > 0:
            triggered_mask = high >= self.long_stop_trigger_prices
            triggered_order_ids = self.long_stop_order_ids[triggered_mask]
            
            if len(triggered_order_ids) > 0:
                for order_id in triggered_order_ids:
                    order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                    self._execute_triggered_order(order, high, low)
        
        # Check short stop orders (SELL): triggered if low <= trigger_price (breakout down)
        if len(self.short_stop_order_ids) > 0:
            triggered_mask = low <= self.short_stop_trigger_prices
            triggered_order_ids = self.short_stop_order_ids[triggered_mask]
            
            if len(triggered_order_ids) > 0:
                for order_id in triggered_order_ids:
                    order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                    self._execute_triggered_order(order, high, low)
    
    def cancel_orders(self, order_ids: List[int]) -> List[Order]:
        """
        Cancel orders by their IDs.
        
        For ACTIVE orders: sets order.status = CANCELED, updates modify_time, and removes from numpy arrays.
        For non-ACTIVE orders: includes them in result without modifications.
        Orders that are not found are silently skipped (not included in result).
        
        Args:
            order_ids: List of order IDs to cancel
        
        Returns:
            List of copies of orders (canceled if they were ACTIVE, or as-is if not ACTIVE)
        """
        canceled_orders = []
        
        for order_id in order_ids:
            # Check if order exists
            if order_id <= 0 or order_id > len(self.orders):
                # Order not found - skip silently (will be handled in strategy)
                continue
            
            # Get order (order_id is 1-based, list is 0-based)
            order = self.orders[order_id - 1]
            
            # If order is ACTIVE, cancel it
            if order.status == OrderStatus.ACTIVE:
                # Cancel order
                order.status = OrderStatus.CANCELED
                if self.current_time is not None:
                    order.modify_time = self.current_time
                else:
                    # If current_time is not set, use create_time (shouldn't happen in normal flow)
                    order.modify_time = order.create_time
                
                # Remove from numpy arrays
                self._remove_order_from_arrays(order)
            
            # Add copy to result (whether it was ACTIVE and canceled, or already non-ACTIVE)
            canceled_orders.append(order.model_copy(deep=True))
        
        return canceled_orders
    
    def close_deals(self):
        """
        Close all open positions by executing opposite trades.
        If equity_symbol > 0, sell it. If equity_symbol < 0, buy it.
        """
        if self.equity_symbol > 0:
            self.sell(self.equity_symbol)
        elif self.equity_symbol < 0:
            self.buy(abs(self.equity_symbol))
    
    def update_state(self, results: Optional[BackTestingResults], is_finish: bool = False) -> None:
        """
        Update task state and progress.
        Checks if task is still running by reading isRunning flag from Redis.
        Calculates and sends progress update via MessageType.EVENT.
        If isRunning is False, sends error notification and raises exception to stop backtesting.
        
        Args:
            results: BackTestingResults instance to save results to Redis, or None if results should not be saved
            is_finish: If True, marks the backtesting result as completed. Default: False.
        
        Raises:
            RuntimeError: If task is stopped (isRunning == False) or duplicate worker detected
        """
        # Check if task is associated with a list (has Redis connection)
        if self.task._list is None:
            # If no list, skip state update (standalone mode)
            return
        
        # Calculate and update progress based on current_time and date range
        total_delta = self.date_end - self.date_start
        current_delta = self.current_time - self.date_start
        progress = float(current_delta / total_delta * 100.0)
        self.progress = round(max(0.0, min(100.0, progress)), 1)
        
        # Convert datetime64 to ISO strings for frontend
        date_start_iso = datetime64_to_iso(self.date_start) if self.date_start is not None else None
        current_time_iso = datetime64_to_iso(self.current_time) if self.current_time is not None else None
        
        # Save results to Redis if results instance is provided
        if results is not None:
            results.put_result(is_finish=is_finish)
        
        self.task.send_message(
            MessageType.EVENT, 
            {
                "event": "backtesting_progress",
                "result_id": self.result_id,
                "progress": self.progress,
                "date_start": date_start_iso,
                "current_time": current_time_iso
            }
        )
        
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
    
    def logging(self, message: str, level: str = "info") -> None:
        """
        Send log message to frontend via task.
        
        Args:
            message: Message text (required)
            level: Message level (optional, default: "info")
                  Valid levels: info, warning, error, success, debug
        """
        self.task.send_message(MessageType.MESSAGE, {"level": level, "message": message})
    
    def run(self, save_results: bool = True):
        """
        Run backtest strategy.
        Loads market data and iterates through bars, calling on_bar for each bar.
        Periodically updates state and progress based on results_save_period.
        Uses self.task to get symbol, timeframe, dateStart, dateEnd, source.
        
        Args:
            save_results: If True, creates BackTestingResults and saves results to Redis.
                         If False, results are not saved. Default: True.
        """
        # Reset broker state
        self.reset()
        
        # Convert timeframe string to Timeframe object
        try:
            timeframe = Timeframe.cast(self.task.timeframe)
        except Exception as e:
            raise RuntimeError(f"Failed to parse timeframe '{self.task.timeframe}': {e}") from e
        
        # Convert date strings to datetime objects using datetime_utils
        try:
            history_start = parse_utc_datetime(self.task.dateStart)
            history_end = parse_utc_datetime(self.task.dateEnd)
        except Exception as e:
            raise RuntimeError(f"Failed to parse dateStart/dateEnd: {e}") from e
        
        # Get quotes data directly from Client
        client = QuotesClient()
        logger.debug(f"Getting quotes for {self.task.source}:{self.task.symbol}:{self.task.timeframe} from {history_start} to {history_end}")
        quotes_data = client.get_quotes(self.task.source, self.task.symbol, timeframe, history_start, history_end)
        logger.debug(f"Quotes received: {len(quotes_data['time'])} bars")
        
        # Extract numpy arrays directly
        all_time = quotes_data['time']
        all_open = quotes_data['open']
        all_high = quotes_data['high']
        all_low = quotes_data['low']
        all_close = quotes_data['close']
        all_volume = quotes_data['volume']
        
        # Initialize current_time from first bar
        if len(all_time) > 0:
            self.current_time = all_time[0]
        else:
            raise RuntimeError("No quotes data available for backtesting")
        
        # Create TA proxies dictionary
        ta_proxies = {
            'talib': ta_proxy_talib(broker=self, quotes_data=quotes_data)
        }
        
        # Create BackTestingResults instance (after ta_proxies are created) if save_results is True
        results = None
        if save_results:
            results = BackTestingResults(self.task, self, ta_proxies)
        
        state_update_period = 1.0
        last_update_time = time.time()
        
        # Call on_start callback with task parameters and TA proxies
        if 'on_start' in self.callbacks:
            self.callbacks['on_start'](self.task.parameters, ta_proxies)
        
        for i_time in range(len(all_close)):
            # Update current bar index
            self.i_time = i_time
            
            # Set current time and price
            self.current_time = all_time[i_time]
            self.price = all_close[i_time]
            
            # Prepare arrays for this bar
            time_array = all_time[:i_time+1]
            open_array = all_open[:i_time+1]
            high_array = all_high[:i_time+1]
            low_array = all_low[:i_time+1]
            close_array = all_close[:i_time+1]
            volume_array = all_volume[:i_time+1]
            
            # Check for triggered limit orders FIRST (before on_bar, so orders can execute before strategy cancels them)
            self._check_and_execute_orders(all_high[i_time], all_low[i_time])
            
            # Call on_bar callback with all necessary data
            if 'on_bar' in self.callbacks:
                self.callbacks['on_bar'](
                    self.price,
                    self.current_time,
                    time_array,
                    open_array,
                    high_array,
                    low_array,
                    close_array,
                    volume_array,
                    self.equity_usd,
                    self.equity_symbol
                )
            
            # Check if it's time to update state and progress
            current_time = time.time()
            if current_time - last_update_time >= self.results_save_period:
                self.update_state(results)
                last_update_time = current_time
                state_update_period = min(state_update_period + 1.0, self.results_save_period)
        
        # Close all open positions
        self.close_deals()
        assert self.equity_symbol == 0.0, "Equity symbol is not 0 after closing deals"
        
        # Check trading results for consistency (only in debug mode)
        if __debug__:
            errors = self.check_trading_results()
            if errors:
                error_message = f"Trading results validation failed:\n" + "\n".join(errors)
                logger.error(error_message)
                self.task.backtesting_error(error_message)
                raise RuntimeError(error_message)

        # Call on_finish callback
        if 'on_finish' in self.callbacks:
            self.callbacks['on_finish']()
                
        # Set current_time to date_end to ensure progress is 100% for final update
        self.current_time = self.date_end
        self.update_state(results, is_finish=True) 
