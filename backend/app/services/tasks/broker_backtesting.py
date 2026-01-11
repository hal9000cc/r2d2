"""
Broker class for handling trading operations and backtesting execution.
"""
from typing import Optional, Dict, Callable, List, Tuple, TYPE_CHECKING
import numpy as np
import time
from pydantic import BaseModel, Field, ConfigDict
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import Broker, OrderSide, OrderType, OrderStatus, OrderGroup, Trade, Order, Deal, DealType
from app.services.tasks.backtesting_result import BackTestingResults
from app.core.logger import get_logger
from app.core.datetime_utils import parse_utc_datetime, parse_utc_datetime64, datetime64_to_iso
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType
from app.services.tasks.indicator_proxy import ta_proxy_talib


logger = get_logger(__name__)


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
            task: Task instance (contains fee_taker, fee_maker, price_step, precision_amount, precision_price, slippage_in_steps)
            result_id: Unique ID for this backtesting run
            callbacks_dict: Dictionary with callback functions:
                - 'on_start': Callable(parameters: Dict[str, Any])
                - 'on_bar': Callable(price, current_time, time, open, high, low, close, volume, equity_usd, equity_symbol)
                - 'on_finish': Callable with no arguments
            results_save_period: Period for saving results in seconds (default: TRADE_RESULTS_SAVE_PERIOD)
        """
        super().__init__(task=task, result_id=result_id)
        
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
                order.status = OrderStatus.ERROR
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
                        if self.lt(self.price, order.price):
                            time_str = datetime64_to_iso(self.current_time)
                            order.errors.append(
                                f"BUY limit order price ({order.price}) must be below or equal to current price ({self.price}) at time {time_str}"
                            )
                            order.status = OrderStatus.ERROR
                            error_count += 1
                    else:  # SELL
                        # For SELL limit: current price must be <= limit price (limit above or equal to current)
                        if self.gt(self.price, order.price):
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
                        if self.gteq(self.price, order.trigger_price):
                            time_str = datetime64_to_iso(self.current_time)
                            order.errors.append(
                                f"BUY stop order trigger_price ({order.trigger_price}) must be above current price ({self.price}) at time {time_str}"
                            )
                            order.status = OrderStatus.ERROR
                            error_count += 1
                    else:  # SELL
                        # For SELL stop: current price must be > trigger_price
                        if self.lteq(self.price, order.trigger_price):
                            time_str = datetime64_to_iso(self.current_time)
                            order.errors.append(
                                f"SELL stop order trigger_price ({order.trigger_price}) must be below current price ({self.price}) at time {time_str}"
                            )
                            order.status = OrderStatus.ERROR
                            error_count += 1
        
        return orders, error_count
    
    def _add_order(self, order: Order) -> int:
        """
        Add order to orders list and assign order_id.
        If order has deal_id set, also adds order to the deal's orders list.
        
        Args:
            order: Order to add
            
        Returns:
            int: Assigned order_id
        """

        # Assign order_id
        order.order_id = len(self.orders) + 1
        
        # If deal_id is set, add order to deal's orders list
        if order.deal_id != 0:
            deal = self.get_deal_by_id(order.deal_id)
            deal.orders.append(order)
        
        # Add order to orders list
        self.orders.append(order)
        
        return order.order_id
    
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
                    
                    # Update order state before execution
                    # Note: slippage will be applied in _execute_trade(), so we store base price here
                    order.price = self.price
                    order.modify_time = self.current_time
                    
                    # Add to orders list for history (before execution)
                    self._add_order(order)
                    
                    # Execute trade (slippage will be applied in _execute_trade for market orders)
                    self._execute_trade(
                        order.side,
                        order.volume,
                        self.price,  # Pass base price, slippage applied in _execute_trade
                        deal_id=order.deal_id,
                        order_id=order.order_id,
                        is_market_order=True
                    )
                    
                    # Update order state after execution
                    # Get actual execution price from the trade that was just created
                    if len(self.trades) > 0:
                        last_trade = self.trades[-1]
                        order.price = last_trade.price  # Update with actual execution price (with slippage)
                    order.filled_volume = order.volume
                    order.status = OrderStatus.EXECUTED
                    
                elif order.order_type == OrderType.LIMIT:
                    # Limit order: place it
                    order.status = OrderStatus.ACTIVE
                    self._add_order(order)
                    self._add_order_to_np_arrays(order)
                    
                elif order.order_type == OrderType.STOP:
                    # Stop order: place it
                    order.status = OrderStatus.ACTIVE
                    self._add_order(order)
                    self._add_order_to_np_arrays(order)
                
                # Create a copy of the order for return
                executed_orders.append(order.model_copy(deep=True))
                
            except Exception as e:
                # Add error to order and mark as error
                order.errors.append(str(e))
                order.status = OrderStatus.ERROR
                # Still add to executed orders list (with error)
                executed_orders.append(order.model_copy(deep=True))
        
        return executed_orders
    
    def execute_orders_sltp(self, orders: List[Order]) -> List[Order]:
        """
        Execute or place orders from the list (for SLTP deals).
        
        Similar to execute_orders, but orders are already added via _add_order.
        This method only processes orders (executes market, activates limit/stop).
        
        Args:
            orders: List of orders already added via _add_order to execute/place
            
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
                # Assert that order was already added (has order_id)
                assert order.order_id > 0, f"Order must be added via _add_order before processing (order_id={order.order_id})"
                assert order.status == OrderStatus.NEW, f"Order must be in NEW status before processing (status={order.status})"
                
                if order.order_type == OrderType.MARKET:
                    # Market order: execute immediately
                    if self.price is None:
                        raise RuntimeError("Cannot execute market order: price is not set")
                    
                    # Update order state before execution
                    order.price = self.price
                    order.modify_time = self.current_time
                    
                    # Execute trade (slippage will be applied in _execute_trade for market orders)
                    self._execute_trade(
                        order.side,
                        order.volume,
                        self.price,  # Pass base price, slippage applied in _execute_trade
                        deal_id=order.deal_id,
                        order_id=order.order_id,
                        is_market_order=True
                    )
                    
                    # Update order state after execution
                    # Get actual execution price from the trade that was just created
                    if len(self.trades) > 0:
                        last_trade = self.trades[-1]
                        order.price = last_trade.price  # Update with actual execution price (with slippage)
                    order.filled_volume = order.volume
                    order.status = OrderStatus.EXECUTED
                    order.modify_time = self.current_time
                    
                elif order.order_type == OrderType.LIMIT:
                    # Limit order: place it
                    order.status = OrderStatus.ACTIVE
                    order.modify_time = self.current_time
                    self._add_order_to_np_arrays(order)
                    
                elif order.order_type == OrderType.STOP:
                    # Stop order: place it
                    order.status = OrderStatus.ACTIVE
                    order.modify_time = self.current_time
                    self._add_order_to_np_arrays(order)
                
                # Create a copy of the order for return
                executed_orders.append(order.model_copy(deep=True))
                
            except Exception as e:
                # Add error to order and mark as error
                order.errors.append(str(e))
                order.status = OrderStatus.ERROR
                order.modify_time = self.current_time
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
                deal_id=0,
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
                deal_id=0,
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
                deal_id=0,
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
                deal_id=0,
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
                deal_id=0,
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
                deal_id=0,
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
    ) -> Tuple[Optional[Deal], List[Order], List[int]]:
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
            Tuple[Optional[Deal], List[Order], List[int]]: 
            - Deal that groups all orders (or None if deal was not created due to errors)
            - List of new orders created in this call
            - List of canceled order IDs (old orders canceled when modifying existing deal, or new orders canceled on error)
        """
        if self.current_time is None:
            raise RuntimeError("Cannot execute deal: current_time is not set")
        
        # 1. Handle existing deal or create new one
        canceled_old_orders = []
        if existing_deal_id is not None:
            # Get existing deal
            deal = self.get_deal_by_id(existing_deal_id)
            deal_id = existing_deal_id
            
            # Cancel active orders selectively based on clear flags
            canceled_old_orders = self._cancel_deal_orders(
                deal,
                self.current_time,
                cancel_entry=clear_enter,
                cancel_stop_loss=clear_stop_loss,
                cancel_take_profit=clear_take_profit
            )
            
            # Use deal type from existing deal (should match provided deal_type)
            deal_type = deal.type
            
            # Get current position volume
            current_position_volume = abs(deal.quantity)
        else:
            # Create new deal
            deal_id = self.create_deal()
            deal = self.get_deal_by_id(deal_id)
            current_position_volume = 0.0
        
        # Determine side from deal type
        side = OrderSide.BUY if deal_type == DealType.LONG else OrderSide.SELL
        
        # 2. Separate positive and negative entries
        positive_entries = [(vol, price) for vol, price in entries if vol > 0]
        negative_entries = [(vol, price) for vol, price in entries if vol < 0]
        
        # 3. Check market entry constraint (only for positive entries)
        if positive_entries:
            market_entry_count = sum(1 for _, price in positive_entries if price is None)
            if market_entry_count > 0:
                assert len(positive_entries) == 1, f"Market entry (price=None) must be the only entry, got {len(positive_entries)} entries"
        
        # 4. Determine entry type and calculate volumes
        is_market_entry = len(positive_entries) > 0 and sum(1 for _, price in positive_entries if price is None) > 0
        new_positive_enter = sum(vol for vol, _ in positive_entries)
        closed_volume = sum(abs(vol) for vol, _ in negative_entries)
        
        # For new deals, total entry volume must be positive
        if existing_deal_id is None:
            assert new_positive_enter > 0, f"Total entry volume must be positive, got {new_positive_enter}"
        
        # 5. Create entry orders for positive volumes
        entry_orders = []
        for volume, price in positive_entries:
            if price is None:
                # Market order
                order = Order(
                    order_id=0,  # Will be assigned by _add_order
                    deal_id=deal_id,
                    order_type=OrderType.MARKET,
                    create_time=self.current_time,
                    modify_time=self.current_time,
                    side=side,
                    price=None,
                    trigger_price=None,
                    volume=volume,
                    filled_volume=0.0,
                    status=OrderStatus.NEW,
                    order_group=OrderGroup.NONE,
                    fraction=None,
                    errors=[]
                )
            else:
                # Limit order
                order = Order(
                    order_id=0,  # Will be assigned by _add_order
                    deal_id=deal_id,
                    order_type=OrderType.LIMIT,
                    create_time=self.current_time,
                    modify_time=self.current_time,
                    side=side,
                    price=PRICE_TYPE(price),
                    trigger_price=None,
                    volume=volume,
                    filled_volume=0.0,
                    status=OrderStatus.NEW,
                    order_group=OrderGroup.NONE,
                    fraction=None,
                    errors=[]
                )
            entry_orders.append(order)
            self._add_order(order)
        
        # 6. Create market orders for negative volumes (closing position)
        opposite_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        for volume, price in negative_entries:
            # Negative volume means closing position - create opposite side market order
            close_volume = abs(volume)
            order = Order(
                order_id=0,  # Will be assigned by _add_order
                deal_id=deal_id,
                order_type=OrderType.MARKET,
                create_time=self.current_time,
                modify_time=self.current_time,
                side=opposite_side,
                price=None,
                trigger_price=None,
                volume=close_volume,
                filled_volume=0.0,
                status=OrderStatus.NEW,
                order_group=OrderGroup.NONE,
                fraction=None,
                errors=[]
            )
            entry_orders.append(order)
            self._add_order(order)
        
        # 7. Set deal type and update enter_volume
        deal.type = deal_type
        if existing_deal_id is not None:
            # Update enter_volume: current_position_volume + new_positive_enter - closed_volume
            if clear_enter:
                deal.enter_volume = current_position_volume
            else:
                deal.enter_volume = deal.enter_volume + new_positive_enter - closed_volume
        else:
            # Store initial entry volume for calculating stop/take target volumes
            deal.enter_volume = new_positive_enter
        
        assert deal.enter_volume > 0, f"Enter volume must be greater than 0, got {deal.enter_volume}"

        # 6. Create stop loss orders (with temporary volume=0, will be updated later)
        stop_orders = []
        opposite_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        if stop_losses:
            for fraction, price in stop_losses:
                assert fraction is not None, "Fraction must be set for stop loss orders"
                assert 0 < fraction <= 1.0, f"Stop loss fraction must be in (0, 1], got {fraction}"
                
                order = Order(
                    order_id=0,  # Will be assigned by _add_order
                    deal_id=deal_id,
                    order_type=OrderType.STOP,
                    create_time=self.current_time,
                    modify_time=self.current_time,
                    side=opposite_side,
                    price=None,
                    trigger_price=PRICE_TYPE(price),
                    volume=0.0,  # Temporary volume, will be updated by _update_stop_loss_volumes
                    filled_volume=0.0,
                    status=OrderStatus.NEW,
                    order_group=OrderGroup.STOP_LOSS,
                    fraction=float(fraction),
                    errors=[]
                )
                stop_orders.append(order)
                self._add_order(order)
        
        # 7. Create take profit orders (with temporary volume=0, will be updated later)
        take_orders = []
        if take_profits:
            for fraction, price in take_profits:
                assert fraction is not None, "Fraction must be set for take profit orders"
                assert 0 < fraction <= 1.0, f"Take profit fraction must be in (0, 1], got {fraction}"
                
                order = Order(
                    order_id=0,  # Will be assigned by _add_order
                    deal_id=deal_id,
                    order_type=OrderType.LIMIT,
                    create_time=self.current_time,
                    modify_time=self.current_time,
                    side=opposite_side,
                    price=PRICE_TYPE(price),
                    trigger_price=None,
                    volume=0.0,  # Temporary volume, will be updated by _update_take_profit_volumes
                    filled_volume=0.0,
                    status=OrderStatus.NEW,
                    order_group=OrderGroup.TAKE_PROFIT,
                    fraction=float(fraction),
                    errors=[]
                )
                take_orders.append(order)
                self._add_order(order)
        
        # 8. Update stop loss volumes using extreme stop logic
        if stop_orders:
            if existing_deal_id is not None:
                # For existing deal, use current position volume
                self._update_stop_loss_volumes(deal, deal.enter_volume, current_position_volume)
            else:
                # At deal creation, current volume equals initial entry volume
                self._update_stop_loss_volumes(deal, deal.enter_volume, deal.enter_volume)
        
        # 9. Update take profit volumes using extreme take logic
        if take_orders:
            if existing_deal_id is not None:
                # For existing deal, use current position volume
                self._update_take_profit_volumes(deal, deal.enter_volume, current_position_volume)
            else:
                # At deal creation, current volume equals initial entry volume
                self._update_take_profit_volumes(deal, deal.enter_volume, deal.enter_volume)
        
        # 9.5. Collect all new orders created in this call
        all_new_orders = entry_orders + stop_orders + take_orders
        
        # 10. Form list of orders to execute
        orders_to_execute = []
        # Always add entry orders and stop orders
        orders_to_execute.extend(entry_orders)
        orders_to_execute.extend(stop_orders)
        # Add take profit orders only for market entry (or if no entry orders for existing deal)
        if is_market_entry or (existing_deal_id is not None and not entry_orders):
            orders_to_execute.extend(take_orders)
        # Note: take profit orders for limit entry remain in NEW status and will be activated later
        
        # 11. Execute orders
        executed_orders = self.execute_orders_sltp(orders_to_execute)
        
        # 12. Check for errors
        has_errors = any(order.status == OrderStatus.ERROR for order in executed_orders)
        if has_errors:
            self.close_deal(deal_id)
            # Get deal after closing
            deal = self.get_deal_by_id(deal_id)
            # Collect IDs of canceled new orders (from all_new_orders with CANCELED status)
            canceled_new_order_ids = [o.order_id for o in all_new_orders if o.status == OrderStatus.CANCELED]
            # Combine old and new canceled order IDs
            canceled_old_order_ids = [o.order_id for o in canceled_old_orders]
            all_canceled_ids = canceled_old_order_ids + canceled_new_order_ids
            return (deal, all_new_orders, all_canceled_ids)
        
        # 13. Return deal with new orders and canceled order IDs
        deal = self.get_deal_by_id(deal_id)
        canceled_old_order_ids = [o.order_id for o in canceled_old_orders]
        return (deal, all_new_orders, canceled_old_order_ids)
    
    def _add_order_to_np_arrays(self, order: Order) -> None:
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
    
    def _remove_order_from_np_arrays(self, order: Order) -> None:
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
    
    def _execute_triggered_order(self, order: Order) -> None:
        """
        Execute a triggered order (limit or stop).
        
        Args:
            order: Order to execute
        """
        if order.status != OrderStatus.ACTIVE:
            return
        
        # Determine execution price and market order flag based on order type
        if order.order_type == OrderType.STOP:
            # Stop order: execute at trigger_price as market order (with slippage, fee_taker)
            execution_price = order.trigger_price
            is_market_order = True
        elif order.order_type == OrderType.LIMIT:
            # Limit order: execute at limit price (no slippage, fee_maker)
            execution_price = order.price
            is_market_order = False
        else:
            # Should not happen for triggered orders, but handle gracefully
            logger.warning(f"Unexpected order type {order.order_type} in _execute_triggered_order {order.order_id}")
            return
        
        # Execute order
        self._execute_trade(
            order.side,
            order.volume,
            execution_price,
            deal_id=order.deal_id,
            order_id=order.order_id,
            is_market_order=is_market_order
        )

        assert order.volume > 0, f"Order volume must be greater than 0, got {order.volume}"
        # Mark order as executed
        order.filled_volume = order.volume
        order.price = execution_price  # Set execution price
        order.status = OrderStatus.EXECUTED
        # Update modify_time to execution time
        order.modify_time = self.current_time
        
        # Remove order from arrays (no longer active)
        self._remove_order_from_np_arrays(order)
    
    def _execute_triggered_orders_old(self, high: PRICE_TYPE, low: PRICE_TYPE, order_group: OrderGroup) -> None:
        """
        Execute triggered orders of specified group (limit and stop) on current bar.
        Uses vectorized operations to find triggered orders.
        
        Executes orders in the following order:
        1. Long stop orders (BUY): triggered if high >= trigger_price
        2. Short stop orders (SELL): triggered if low <= trigger_price
        3. Long limit orders (BUY): triggered if low < price
        4. Short limit orders (SELL): triggered if high > price
        
        Only orders matching the specified order_group are executed.
        
        Args:
            high: High price of current bar
            low: Low price of current bar
            order_group: Order group to filter by (NONE for entries, STOP_LOSS for stops, TAKE_PROFIT for takes)
        """
        # Execute long stop orders (BUY): triggered if high >= trigger_price
        if len(self.long_stop_order_ids) > 0:
            triggered_mask = high >= self.long_stop_trigger_prices
            triggered_order_ids = self.long_stop_order_ids[triggered_mask]
            
            if len(triggered_order_ids) > 0:
                for order_id in triggered_order_ids:
                    order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                    if order.order_group == order_group:
                        self._execute_triggered_order(order)
        
        # Execute short stop orders (SELL): triggered if low <= trigger_price
        if len(self.short_stop_order_ids) > 0:
            triggered_mask = low <= self.short_stop_trigger_prices
            triggered_order_ids = self.short_stop_order_ids[triggered_mask]
            
            if len(triggered_order_ids) > 0:
                for order_id in triggered_order_ids:
                    order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                    if order.order_group == order_group:
                        self._execute_triggered_order(order)
        
        # Execute long limit orders (BUY): triggered if low < price
        if len(self.long_order_ids) > 0:
            triggered_mask = low < self.long_order_prices
            triggered_order_ids = self.long_order_ids[triggered_mask]
            
            if len(triggered_order_ids) > 0:
                for order_id in triggered_order_ids:
                    order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                    if order.order_group == order_group:
                        self._execute_triggered_order(order)
        
        # Execute short limit orders (SELL): triggered if high > price
        if len(self.short_order_ids) > 0:
            triggered_mask = high > self.short_order_prices
            triggered_order_ids = self.short_order_ids[triggered_mask]
            
            if len(triggered_order_ids) > 0:
                for order_id in triggered_order_ids:
                    order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                    if order.order_group == order_group:
                        self._execute_triggered_order(order)
    
    def _deals_of_triggered_orders(self, high: PRICE_TYPE, low: PRICE_TYPE) -> Tuple[set, List[Order]]:
        """
        Get set of deal IDs for deals that have triggered orders on current bar,
        and list of orphan orders (deal_id == 0) that have triggered.
        
        Checks all four types of orders (long stop, short stop, long limit, short limit)
        and collects deal IDs from orders that would trigger, as well as orphan orders.
        
        Args:
            high: High price of current bar
            low: Low price of current bar
        
        Returns:
            Tuple of (set of deal IDs that have triggered orders, list of orphan orders with deal_id == 0)
        """
        deal_ids = set()
        orphan_orders = []
        
        # Check long stop orders (BUY): triggered if high >= trigger_price
        if len(self.long_stop_order_ids) > 0:
            triggered_mask = high >= self.long_stop_trigger_prices
            triggered_order_ids = self.long_stop_order_ids[triggered_mask]
            
            for order_id in triggered_order_ids:
                order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                if order.deal_id > 0:
                    deal_ids.add(order.deal_id)
                else:
                    orphan_orders.append(order)
        
        # Check short stop orders (SELL): triggered if low <= trigger_price
        if len(self.short_stop_order_ids) > 0:
            triggered_mask = low <= self.short_stop_trigger_prices
            triggered_order_ids = self.short_stop_order_ids[triggered_mask]
            
            for order_id in triggered_order_ids:
                order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                if order.deal_id > 0:
                    deal_ids.add(order.deal_id)
                else:
                    orphan_orders.append(order)
        
        # Check long limit orders (BUY): triggered if low < price
        if len(self.long_order_ids) > 0:
            triggered_mask = low < self.long_order_prices
            triggered_order_ids = self.long_order_ids[triggered_mask]
            
            for order_id in triggered_order_ids:
                order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                if order.deal_id > 0:
                    deal_ids.add(order.deal_id)
                else:
                    orphan_orders.append(order)
        
        # Check short limit orders (SELL): triggered if high > price
        if len(self.short_order_ids) > 0:
            triggered_mask = high > self.short_order_prices
            triggered_order_ids = self.short_order_ids[triggered_mask]
            
            for order_id in triggered_order_ids:
                order = self.orders[order_id - 1]  # order_id is 1-based, list is 0-based
                if order.deal_id > 0:
                    deal_ids.add(order.deal_id)
                else:
                    orphan_orders.append(order)
        
        return (deal_ids, orphan_orders)
    
    def _check_order_trigger_condition(self, order: Order, high: PRICE_TYPE, low: PRICE_TYPE) -> bool:
        """
        Check if order should be triggered based on current bar prices.
        
        Args:
            order: Order to check
            high: High price of current bar
            low: Low price of current bar
        
        Returns:
            True if order should be executed, False otherwise
        """
        if order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY:
                # Buy limit: low < price
                return order.price is not None and low < order.price
            else:  # SELL
                # Sell limit: high > price
                return order.price is not None and high > order.price
        elif order.order_type == OrderType.STOP:
            if order.side == OrderSide.BUY:
                # Buy stop: high >= trigger_price
                return order.trigger_price is not None and high >= order.trigger_price
            else:  # SELL
                # Sell stop: low <= trigger_price
                return order.trigger_price is not None and low <= order.trigger_price
        return False
    
    def _process_order_group(self, orders: List[Order], high: PRICE_TYPE, low: PRICE_TYPE, deal: Deal, reverse: bool = False) -> bool:
        """
        Process a group of orders: sort by price and execute triggered ones.
        
        Args:
            orders: List of orders to process
            high: High price of current bar
            low: Low price of current bar
            deal: Deal these orders belong to
            reverse: If True, sort in descending order, otherwise ascending
        
        Returns:
            True if deal was closed during processing, False otherwise
        """
        # Prepare orders with sort prices
        orders_with_price = []
        for order in orders:
            sort_price = order.price if order.order_type == OrderType.LIMIT else order.trigger_price
            if sort_price is not None:
                orders_with_price.append((sort_price, order))
        
        # Sort by price
        orders_with_price.sort(key=lambda x: x[0], reverse=reverse)
        
        # Process orders
        for sort_price, order in orders_with_price:
            if self._check_order_trigger_condition(order, high, low):
                self._execute_triggered_order(order)
                # Check if deal is closed
                if deal.is_closed:
                    return True
        
        return False
    
    def _execute_triggered_orders_for_long_deal(self, deal: Deal, high: PRICE_TYPE, low: PRICE_TYPE) -> None:
        """
        Execute triggered orders for a LONG deal.
        
        First (descending): buy limit and sell stop
        Then (ascending): sell limit and buy stop
        
        Args:
            deal: LONG deal to process
            high: High price of current bar
            low: Low price of current bar
        """
        active_orders = [o for o in deal.orders if o.status == OrderStatus.ACTIVE]
        
        # First (descending) - buy limit and sell stop
        first_orders = []
        for order in active_orders:
            if ((order.order_type == OrderType.LIMIT and order.side == OrderSide.BUY) or
                (order.order_type == OrderType.STOP and order.side == OrderSide.SELL)):
                first_orders.append(order)
        
        if self._process_order_group(first_orders, high, low, deal, reverse=True):
            return  # Deal closed
        
        if deal.quantity == 0:
            return
        # Update SL/TP orders after first group processing
        self._update_sltp_orders_for_deal(deal)
        
        # Then (ascending) - sell limit and buy stop
        second_orders = []
        for order in active_orders:
            if ((order.order_type == OrderType.LIMIT and order.side == OrderSide.SELL) or
                (order.order_type == OrderType.STOP and order.side == OrderSide.BUY)):
                second_orders.append(order)
        
        if self._process_order_group(second_orders, high, low, deal, reverse=False):
            return  # Deal closed
        
        # Update SL/TP orders after second group processing
        self._update_sltp_orders_for_deal(deal)
    
    def _execute_triggered_orders_for_short_deal(self, deal: Deal, high: PRICE_TYPE, low: PRICE_TYPE) -> None:
        """
        Execute triggered orders for a SHORT deal.
        
        First (ascending): sell limit and buy stop
        Then (descending): buy limit and sell stop
        
        Args:
            deal: SHORT deal to process
            high: High price of current bar
            low: Low price of current bar
        """
        active_orders = [o for o in deal.orders if o.status == OrderStatus.ACTIVE]
        
        # First (ascending) - sell limit and buy stop
        first_orders = []
        for order in active_orders:
            if ((order.order_type == OrderType.LIMIT and order.side == OrderSide.SELL) or
                (order.order_type == OrderType.STOP and order.side == OrderSide.BUY)):
                first_orders.append(order)
        
        if self._process_order_group(first_orders, high, low, deal, reverse=False):
            return  # Deal closed
        
        if deal.quantity == 0:
            return
        # Update SL/TP orders after first group processing
        self._update_sltp_orders_for_deal(deal)
        
        # Then (descending) - buy limit and sell stop
        second_orders = []
        for order in active_orders:
            if ((order.order_type == OrderType.LIMIT and order.side == OrderSide.BUY) or
                (order.order_type == OrderType.STOP and order.side == OrderSide.SELL)):
                second_orders.append(order)
        
        if self._process_order_group(second_orders, high, low, deal, reverse=True):
            return  # Deal closed
        
        # Update SL/TP orders after second group processing
        self._update_sltp_orders_for_deal(deal)
    
    def _execute_triggered_orders(self, high: PRICE_TYPE, low: PRICE_TYPE) -> None:
        """
        Execute triggered orders on current bar.
        
        Processes orders for each deal in the correct price order:
        - For LONG deals: buy limit and sell stop (descending), then sell limit and buy stop (ascending)
        - For SHORT deals: sell limit and buy stop (ascending), then buy limit and sell stop (descending)
        
        After each executed order, checks if deal is closed and stops processing if so.
        
        After processing all deals, executes orphan orders (deal_id == 0) that have triggered.
        
        Args:
            high: High price of current bar
            low: Low price of current bar
        """
        # Get deals that have triggered orders and orphan orders
        deal_ids, orphan_orders = self._deals_of_triggered_orders(high, low)
        
        # Process deals with deal_id > 0
        for deal_id in deal_ids:
            deal = self.get_deal_by_id(deal_id)
            assert deal is not None, f"Deal {deal_id} not found, but was in triggered orders list"
            
            if deal.type == DealType.LONG:
                self._execute_triggered_orders_for_long_deal(deal, high, low)
            else:  # SHORT
                self._execute_triggered_orders_for_short_deal(deal, high, low)
        
        # Execute orphan orders (deal_id == 0)
        for order in orphan_orders:
            self._execute_triggered_order(order)
    
    def _find_extreme_stop_order(self, deal: Deal) -> Optional[Order]:
        """
        Find the extreme stop loss order for a deal.
        
        For LONG: returns stop with minimum trigger_price (farthest down)
        For SHORT: returns stop with maximum trigger_price (farthest up)
        
        Args:
            deal: Deal to find extreme stop for
        
        Returns:
            Extreme stop order or None if no stop orders exist
        """
        stop_orders = [order for order in deal.orders if order.order_group == OrderGroup.STOP_LOSS and order.status in [OrderStatus.NEW, OrderStatus.ACTIVE]]
        if not stop_orders:
            return None
        
        if deal.type == DealType.LONG:
            # LONG: minimum trigger_price (farthest down)
            return min(stop_orders, key=lambda o: o.trigger_price if o.trigger_price is not None else float('inf'))
        else:  # SHORT
            # SHORT: maximum trigger_price (farthest up)
            return max(stop_orders, key=lambda o: o.trigger_price if o.trigger_price is not None else float('-inf'))
    
    def _find_extreme_take_order(self, deal: Deal) -> Optional[Order]:
        """
        Find the extreme take profit order for a deal.
        
        For LONG: returns take with maximum price (farthest up)
        For SHORT: returns take with minimum price (farthest down)
        
        Args:
            deal: Deal to find extreme take for
        
        Returns:
            Extreme take order or None if no take orders exist
        """
        take_orders = [order for order in deal.orders if order.order_group == OrderGroup.TAKE_PROFIT and order.status in [OrderStatus.NEW, OrderStatus.ACTIVE]]
        if not take_orders:
            return None
        
        if deal.type == DealType.LONG:
            # LONG: maximum price (farthest up)
            return max(take_orders, key=lambda o: o.price if o.price is not None else float('-inf'))
        else:  # SHORT
            # SHORT: minimum price (farthest down)
            return min(take_orders, key=lambda o: o.price if o.price is not None else float('inf'))
    
    def _get_unexecuted_entry_limit_volume(
        self,
        deal: Deal,
        current_price: PRICE_TYPE,
        extreme_stop_price: PRICE_TYPE
    ) -> VOLUME_TYPE:
        """
        Get volume of unexecuted entry limit orders that are in range between
        current price and extreme stop price.
        
        Args:
            deal: Deal to check
            current_price: Current market price
            extreme_stop_price: Extreme stop trigger price
        
        Returns:
            Sum of volumes of unexecuted entry limit orders in range
        """
        unexecuted_volume = 0.0
        
        for order in deal.orders:
            # Check if it's an entry limit order (not executed)
            if (order.order_group == OrderGroup.NONE and
                order.order_type == OrderType.LIMIT and
                order.status in [OrderStatus.NEW, OrderStatus.ACTIVE] and
                order.price is not None):
                
                # Check if price is in range (non-strict inequalities)
                if deal.type == DealType.LONG:
                    # LONG: current_price >= order.price >= extreme_stop_price
                    if current_price >= order.price >= extreme_stop_price:
                        unexecuted_volume += order.volume
                else:  # SHORT
                    # SHORT: current_price <= order.price <= extreme_stop_price
                    if current_price <= order.price <= extreme_stop_price:
                        unexecuted_volume += order.volume
        
        return VOLUME_TYPE(unexecuted_volume)
    
    def _get_executed_stop_loss_volume(self, deal: Deal) -> VOLUME_TYPE:
        """
        Get total volume of executed stop loss orders in a deal.
        
        Args:
            deal: Deal to check
        
        Returns:
            Sum of filled_volume of all executed stop loss orders, or 0.0 if none
        """
        executed_volume = 0.0
        
        for order in deal.orders:
            # Check if it's an executed stop loss order
            if (order.order_group == OrderGroup.STOP_LOSS and
                order.status == OrderStatus.EXECUTED):
                executed_volume += order.filled_volume
        
        return VOLUME_TYPE(executed_volume)
    
    def _get_executed_take_profit_volume(self, deal: Deal) -> VOLUME_TYPE:
        """
        Get total volume of executed take profit orders in a deal.
        
        Args:
            deal: Deal to check
        
        Returns:
            Sum of filled_volume of all executed take profit orders, or 0.0 if none
        """
        executed_volume = 0.0
        
        for order in deal.orders:
            # Check if it's an executed take profit order
            if (order.order_group == OrderGroup.TAKE_PROFIT and
                order.status == OrderStatus.EXECUTED):
                executed_volume += order.filled_volume
        
        return VOLUME_TYPE(executed_volume)
    
    def _update_stop_loss_volumes(self, deal: Deal, target_volume: VOLUME_TYPE, current_volume: VOLUME_TYPE) -> None:
        """
        Update volumes of all stop loss orders in a deal.
        
        All stops except extreme one get rounded volumes based on fraction and target_volume.
        Extreme stop gets remainder from current_volume to ensure it closes the remaining position.
        
        Args:
            deal: Deal to update stop orders for
            target_volume: Target total volume for calculating regular stop volumes (based on fraction)
            current_volume: Current position volume for calculating extreme stop volume (remainder)
        """
        assert target_volume >= 0, f"Target volume must be >= 0, got {target_volume}"

        stop_orders = [order for order in deal.orders if order.order_group == OrderGroup.STOP_LOSS and order.status in [OrderStatus.NEW, OrderStatus.ACTIVE]]
        if not stop_orders:
            return
        
        extreme_stop = self._find_extreme_stop_order(deal)
        if extreme_stop is None:
            return
        
        # Calculate volumes for all stops except extreme
        stop_volumes = []
        for order in stop_orders:
            if order.order_id == extreme_stop.order_id:
                # Extreme stop: will be calculated as remainder
                stop_volumes.append(0.0)
            else:
                # Regular stop: round to precision based on target_volume
                assert order.fraction is not None, f"Stop order {order.order_id} must have fraction"
                volume = self.round_to_precision(order.fraction * target_volume, self.precision_amount)
                stop_volumes.append(volume)
        
        # Calculate extreme stop volume as remainder from current position volume
        extreme_index = next(i for i, order in enumerate(stop_orders) if order.order_id == extreme_stop.order_id)
        extreme_volume = current_volume - sum(stop_volumes)
        stop_volumes[extreme_index] = extreme_volume
        
        # Update all stop orders
        for order, volume in zip(stop_orders, stop_volumes):
            #assert volume > 0, f"Order volume must be > 0, got {volume} for order {order.order_id}"
            order.volume = volume
            order.modify_time = self.current_time
    
    def _update_take_profit_volumes(self, deal: Deal, target_volume: VOLUME_TYPE, current_volume: VOLUME_TYPE) -> List[Order]:
        """
        Update volumes of all take profit orders in a deal.
        
        Processes only take profit orders with status NEW or ACTIVE.
        All takes except extreme one get rounded volumes based on fraction and target_volume.
        Extreme take gets remainder from current_volume to ensure it closes the remaining position.
        
        Args:
            deal: Deal to update take orders for
            target_volume: Target total volume for calculating regular take volumes (based on fraction)
            current_volume: Current position volume for calculating extreme take volume (remainder)
        
        Returns:
            List of take orders in NEW status that need to be activated
        """
        take_orders = [order for order in deal.orders if order.order_group == OrderGroup.TAKE_PROFIT and order.status in [OrderStatus.NEW, OrderStatus.ACTIVE]]
        if not take_orders:
            return []
        
        extreme_take = self._find_extreme_take_order(deal)
        if extreme_take is None:
            return []
        
        # Extract NEW orders for activation
        new_takes = [order for order in take_orders if order.status == OrderStatus.NEW]
        
        # Calculate volumes for all takes except extreme
        take_volumes = []
        for order in take_orders:
            if order.order_id == extreme_take.order_id:
                # Extreme take: will be calculated as remainder
                take_volumes.append(0.0)
            else:
                # Regular take: round to precision based on target_volume
                assert order.fraction is not None, f"Take order {order.order_id} must have fraction"
                volume = self.round_to_precision(order.fraction * target_volume, self.precision_amount)
                take_volumes.append(volume)
        
        # Calculate extreme take volume as remainder from current position volume
        extreme_index = next(i for i, order in enumerate(take_orders) if order.order_id == extreme_take.order_id)
        extreme_volume = current_volume - sum(take_volumes)
        take_volumes[extreme_index] = extreme_volume
        
        # Update volumes for all NEW and ACTIVE take orders
        for order, volume in zip(take_orders, take_volumes):
            #assert volume > 0, f"Order volume must be > 0, got {volume} for order {order.order_id}"
            order.volume = volume
            order.modify_time = self.current_time
        
        return new_takes
    
    def _update_sltp_orders_for_deal(self, deal: Deal) -> None:
        """
        Update stop loss and take profit orders for a single deal.
        Updates order volumes and activation status based on current deal position.
        
        Args:
            deal: Deal to update SL/TP orders for
        """
        assert self.current_time is not None, "Cannot update SL/TP orders: current_time is not set"
        assert self.price is not None, "Cannot update SL/TP orders: price is not set"
        
        # Safety check: deal should be open
        assert not deal.is_closed, f"Deal {deal.deal_id} is closed but in active_deals"
        
        # 1. Update stop loss volumes
        extreme_stop = self._find_extreme_stop_order(deal)
        if extreme_stop is not None:
            assert deal.enter_volume > 0, f"Deal {deal.deal_id} must have enter_volume > 0 for stop loss volume calculation"
            # Calculate unexecuted entry limit volume (for range check)
            extreme_stop_price = extreme_stop.trigger_price
            if extreme_stop_price is not None:
                unexecuted_entry_volume = self._get_unexecuted_entry_limit_volume(
                    deal, self.price, extreme_stop_price
                )
                executed_take_volume = self._get_executed_take_profit_volume(deal)
                # Target volume = initial entry volume - unexecuted entry limits - executed take volumes
                target_volume = deal.enter_volume - unexecuted_entry_volume - executed_take_volume
                # Current volume = current position size (abs(deal.quantity) for LONG/SHORT)
                current_volume = abs(deal.quantity)
                self._update_stop_loss_volumes(deal, target_volume, current_volume)
        
        # 2. Update take profit volumes (only if deal has position)
        if abs(deal.quantity) > 0:
            assert deal.enter_volume > 0, f"Deal {deal.deal_id} must have enter_volume > 0 for take profit volume calculation"
            executed_stop_volume = self._get_executed_stop_loss_volume(deal)
            # IMPORTANT: Take profit volumes are calculated from FULL ENTRY VOLUME (deal.enter_volume),
            # MINUS executed stop volumes, NOT from current position size
            # This is the same logic as stop losses: calculated from all requested entry volumes (including unexecuted limits)
            # Target volume = initial entry volume - executed stop volumes
            target_volume = deal.enter_volume - executed_stop_volume
            # Current volume = current position size (abs(deal.quantity) for LONG/SHORT)
            # Used only for calculating extreme take profit volume (remainder)
            current_volume = abs(deal.quantity)
            new_takes = self._update_take_profit_volumes(deal, target_volume, current_volume)
            
            # 3. Activate take profit orders in NEW status
            if new_takes:
                self.execute_orders_sltp(new_takes)
    
    def _update_sltp_orders(self) -> None:
        """
        Update stop loss and take profit orders for active deals.
        Updates order volumes and activation status based on current deal positions.
        
        This method iterates through all active deals and updates their exit orders
        (stop losses and take profits) to reflect current position sizes.
        """
        # Iterate through active deals
        for deal_id in list(self.active_deals):  # Iterate over copy as set may change
            deal = self.get_deal_by_id(deal_id)
            self._update_sltp_orders_for_deal(deal)
    
    def _check_and_execute_orders(self, high: PRICE_TYPE, low: PRICE_TYPE) -> None:
        """
        Check and execute orders on current bar.
        
        First executes triggered orders (limit and stop), then updates SL/TP orders
        for active deals based on current position sizes.
        
        Args:
            high: High price of current bar
            low: Low price of current bar
        """
        # First: execute triggered orders
        self._execute_triggered_orders(high, low)
        
        # # Second: update stop loss and take profit orders for active deals
        # self._update_sltp_orders()
    
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
        assert self.current_time is not None, "Cannot cancel orders: current_time is not set"
        
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
                order.modify_time = self.current_time
                
                # Remove from numpy arrays
                self._remove_order_from_np_arrays(order)
            
            # Add copy to result (whether it was ACTIVE and canceled, or already non-ACTIVE)
            canceled_orders.append(order.model_copy(deep=True))
        
        return canceled_orders
    
    def ex_current_time(self) -> np.datetime64:
        """
        Get current time for order modification.
        
        Returns:
            Current time as np.datetime64
        """
        return self.current_time

    def ex_cancel_order(self, order: Order) -> None:
        """
        Implementation-specific order cancellation logic for backtesting.
        
        Removes the order from numpy arrays used for efficient order matching.
        Only LIMIT and STOP orders are stored in numpy arrays, so MARKET orders are skipped.
        
        Args:
            order: Order that was canceled
        """
        # Only LIMIT and STOP orders are stored in numpy arrays
        if order.order_type in [OrderType.LIMIT, OrderType.STOP]:
            self._remove_order_from_np_arrays(order)
    
    def close_deal(self, deal_id: int) -> None:
        """
        Close a specific deal by canceling all active orders and closing position.
        
        Args:
            deal_id: ID of the deal to close
        """
        assert self.current_time is not None, "Cannot close deal: current_time is not set"
        
        deal = self.get_deal_by_id(deal_id)
        
        # Close position if there is any
        # Use 1/10 of volume precision as tolerance for floating point comparison
        if abs(deal.quantity) > self.precision_amount / 10.0:
            # Determine closing side based on deal type
            if deal.type is None:
                # If deal type is not set, determine from quantity sign
                # Positive quantity means we bought (LONG), need to sell
                # Negative quantity means we sold (SHORT), need to buy
                close_side = OrderSide.SELL if deal.quantity > 0 else OrderSide.BUY
            else:
                # Use deal type
                if deal.type == DealType.LONG:
                    assert deal.quantity > 0, "Deal quantity must be positive for LONG deal"
                    close_side = OrderSide.SELL
                else:  # DealType.SHORT
                    assert deal.quantity < 0, "Deal quantity must be negative for SHORT deal"
                    close_side = OrderSide.BUY
            
            # Create market order to close position
            close_order = Order(
                order_id=0,  # Will be assigned by _add_order
                deal_id=deal_id,
                order_type=OrderType.MARKET,
                create_time=self.current_time,
                modify_time=self.current_time,
                side=close_side,
                price=None,
                trigger_price=None,
                volume=abs(deal.quantity),
                filled_volume=0.0,
                status=OrderStatus.NEW,
                order_group=OrderGroup.NONE,
                fraction=None,
                errors=[]
            )
            
            # Add order and execute
            self._add_order(close_order)
            self.execute_orders_sltp([close_order])

        self._cancel_deal_orders(deal, self.current_time)
        self.check_closed(deal)

    
    def close_deals(self):
        """
        Close all open deals by executing market orders.
        Iterates through all deals and closes each one that is not already closed.
        """
        # Iterate through all deals (not just active ones)
        if self.deals is None:
            return
        
        # Close each deal (close_deal handles already-closed deals gracefully)
        for deal in self.deals:
            self.close_deal(deal.deal_id)
    
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
        
        # Assert that current_time is set (required for progress calculation)
        assert self.current_time is not None, "Cannot update state: current_time is not set"
        assert self.date_start is not None, "Cannot update state: date_start is not set"
        assert self.date_end is not None, "Cannot update state: date_end is not set"
        
        # Calculate and update progress based on current_time and date range
        total_delta = self.date_end - self.date_start
        current_delta = self.current_time - self.date_start
        progress = float(current_delta / total_delta * 100.0)
        self.progress = round(max(0.0, min(100.0, progress)), 1)
        
        # Convert datetime64 to ISO strings for frontend
        date_start_iso = datetime64_to_iso(self.date_start)
        current_time_iso = datetime64_to_iso(self.current_time)
        
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
        # Use 1/10 of price precision as tolerance for floating point comparison
        equity_tolerance = self.precision_price / 10.0
        assert abs(self.equity_symbol) <= equity_tolerance, \
            f"Equity symbol should be 0 (within tolerance {equity_tolerance}), got {self.equity_symbol}"
        assert len(self.active_deals) == 0, f"Active deals set is not empty after closing: {self.active_deals}"
        
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
