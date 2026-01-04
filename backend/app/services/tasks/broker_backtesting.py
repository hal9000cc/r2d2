"""
Broker class for handling trading operations and backtesting execution.
"""
from typing import Optional, Dict, Callable, List
import numpy as np
import time
from pydantic import BaseModel, Field, ConfigDict
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import Broker, OrderSide, OrderResult, CancelOrderResult
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
    
    order_id: int = Field(gt=0)
    price: Optional[PRICE_TYPE] = None
    volume: VOLUME_TYPE
    create_time: np.datetime64
    modify_time: np.datetime64
    filled_volume: VOLUME_TYPE = 0.0
    active: bool = True
    side: OrderSide
    deal_id: Optional[int] = None
    trigger_price: Optional[PRICE_TYPE] = None


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
        super().reset()
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
    ) -> OrderResult:
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
            OrderResult with 'trades', 'deals', 'orders', and 'errors' lists
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
            result = self.reg_buy(quantity, trade_fee, execution_price, self.current_time, deal_id=deal_id, order_id=order_id)
        else:  # SELL
            self.equity_symbol -= quantity
            self.equity_usd += trade_amount - trade_fee
            result = self.reg_sell(quantity, trade_fee, execution_price, self.current_time, deal_id=deal_id, order_id=order_id)
        
        # Add empty orders and errors lists
        return OrderResult(
            trades=result.trades,
            deals=result.deals,
            orders=[],
            errors=[]
        )
    
    def buy(self, quantity: VOLUME_TYPE, price: Optional[PRICE_TYPE] = None, trigger_price: Optional[PRICE_TYPE] = None) -> OrderResult:
        """
        Execute buy operation.
        If price is specified, places a limit order.
        If trigger_price is specified, places a stop order.
        Otherwise executes market order.
        Increases equity_symbol and decreases equity_usd.
        
        Args:
            quantity: Quantity to buy
            price: Optional limit price. If None and trigger_price is None, executes market order.
            trigger_price: Optional trigger price for stop order.
        
        Returns:
            OrderResult with 'trades', 'deals', 'orders', and 'errors' lists
        """
        # Validate: either price or trigger_price, but not both
        if price is not None and trigger_price is not None:
            return OrderResult(
                trades=[],
                deals=[],
                orders=[],
                errors=["Cannot specify both price and trigger_price"]
            )
        
        if trigger_price is not None:
            # Place stop order
            try:
                order_id = self.place_stop_order(OrderSide.BUY, quantity, trigger_price)
            except (ValueError, RuntimeError) as e:
                return OrderResult(
                    trades=[],
                    deals=[],
                    orders=[],
                    errors=[str(e)]
                )
            return OrderResult(
                trades=[],
                deals=[],
                orders=[order_id],
                errors=[]
            )
        
        if price is not None:
            # Place limit order
            order_id = self.place_limit_order(OrderSide.BUY, quantity, price)
            return OrderResult(
                trades=[],
                deals=[],
                orders=[order_id],
                errors=[]
            )
        
        # Market order execution
        if self.price is None:
            raise RuntimeError("Cannot execute buy: price is not set")
        
        return self._execute_trade(OrderSide.BUY, quantity, self.price, is_market_order=True)
    
    def sell(self, quantity: VOLUME_TYPE, price: Optional[PRICE_TYPE] = None, trigger_price: Optional[PRICE_TYPE] = None) -> OrderResult:
        """
        Execute sell operation.
        If price is specified, places a limit order.
        If trigger_price is specified, places a stop order.
        Otherwise executes market order.
        Decreases equity_symbol and increases equity_usd.
        
        Args:
            quantity: Quantity to sell
            price: Optional limit price. If None and trigger_price is None, executes market order.
            trigger_price: Optional trigger price for stop order.
        
        Returns:
            OrderResult with 'trades', 'deals', 'orders', and 'errors' lists
        """
        # Validate: either price or trigger_price, but not both
        if price is not None and trigger_price is not None:
            return OrderResult(
                trades=[],
                deals=[],
                orders=[],
                errors=["Cannot specify both price and trigger_price"]
            )
        
        if trigger_price is not None:
            # Place stop order
            try:
                order_id = self.place_stop_order(OrderSide.SELL, quantity, trigger_price)
            except (ValueError, RuntimeError) as e:
                return OrderResult(
                    trades=[],
                    deals=[],
                    orders=[],
                    errors=[str(e)]
                )
            return OrderResult(
                trades=[],
                deals=[],
                orders=[order_id],
                errors=[]
            )
        
        if price is not None:
            # Place limit order
            order_id = self.place_limit_order(OrderSide.SELL, quantity, price)
            return OrderResult(
                trades=[],
                deals=[],
                orders=[order_id],
                errors=[]
            )
        
        # Market order execution
        if self.price is None:
            raise RuntimeError("Cannot execute sell: price is not set")
        
        return self._execute_trade(OrderSide.SELL, quantity, self.price, is_market_order=True)
    
    def place_limit_order(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: PRICE_TYPE,
        deal_id: Optional[int] = None
    ) -> int:
        """
        Place a limit order.
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Order quantity (volume)
            price: Limit price
            deal_id: Optional deal ID to associate with this order
        
        Returns:
            order_id: Unique order identifier
        """
        if self.current_time is None:
            raise RuntimeError("Cannot place limit order: current_time is not set")
        
        # Create order with order_id based on list length
        order_id = len(self.orders) + 1
        
        order = Order(
            order_id=order_id,
            price=price,
            volume=quantity,
            create_time=self.current_time,
            modify_time=self.current_time,  # Initially same as create_time
            filled_volume=0.0,
            active=True,
            side=side,
            deal_id=deal_id
        )
        
        # Add to orders list
        self.orders.append(order)
        
        # Add to numpy arrays for fast lookup
        self._add_order_to_arrays(order)
        
        return order_id
    
    def place_stop_order(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        trigger_price: PRICE_TYPE,
        deal_id: Optional[int] = None
    ) -> int:
        """
        Place a stop order (order on breakout).
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Order quantity (volume)
            trigger_price: Trigger price (breakout price)
            deal_id: Optional deal ID to associate with this order
        
        Returns:
            order_id: Unique order identifier
        
        Raises:
            RuntimeError: If current_time is not set
            ValueError: If stop order validation fails (current price vs trigger_price)
        """
        if self.current_time is None:
            raise RuntimeError("Cannot place stop order: current_time is not set")
        
        if self.price is None:
            raise RuntimeError("Cannot place stop order: current price is not set")
        
        # Validate stop order: for long (BUY) orders, current price must be below trigger_price
        # For short (SELL) orders, current price must be above trigger_price
        if side == OrderSide.BUY:
            if self.price >= trigger_price:
                raise ValueError(
                    f"Cannot place long stop order: current price ({self.price}) must be below trigger_price ({trigger_price})"
                )
        elif side == OrderSide.SELL:
            if self.price <= trigger_price:
                raise ValueError(
                    f"Cannot place short stop order: current price ({self.price}) must be above trigger_price ({trigger_price})"
                )
        
        # Create order with order_id based on list length
        order_id = len(self.orders) + 1
        
        order = Order(
            order_id=order_id,
            price=None,  # Stop orders don't have limit price
            volume=quantity,
            create_time=self.current_time,
            modify_time=self.current_time,  # Initially same as create_time
            filled_volume=0.0,
            active=True,
            side=side,
            deal_id=deal_id,
            trigger_price=trigger_price
        )
        
        # Add to orders list
        self.orders.append(order)
        
        # Add to numpy arrays for fast lookup
        self._add_order_to_arrays(order)
        
        return order_id
    
    def _add_order_to_arrays(self, order: Order) -> None:
        """
        Add order to numpy arrays for fast lookup.
        
        Args:
            order: Order to add
        """
        if order.trigger_price is not None:
            # Stop order
            if order.side == OrderSide.BUY:
                # Add to long stop arrays
                self.long_stop_order_ids = np.append(self.long_stop_order_ids, order.order_id)
                self.long_stop_trigger_prices = np.append(self.long_stop_trigger_prices, order.trigger_price)
            else:  # SELL
                # Add to short stop arrays
                self.short_stop_order_ids = np.append(self.short_stop_order_ids, order.order_id)
                self.short_stop_trigger_prices = np.append(self.short_stop_trigger_prices, order.trigger_price)
        else:
            # Limit order
            if order.side == OrderSide.BUY:
                # Add to long arrays
                self.long_order_ids = np.append(self.long_order_ids, order.order_id)
                self.long_order_prices = np.append(self.long_order_prices, order.price)
            else:  # SELL
                # Add to short arrays
                self.short_order_ids = np.append(self.short_order_ids, order.order_id)
                self.short_order_prices = np.append(self.short_order_prices, order.price)
    
    def _remove_order_from_arrays(self, order_id: int, side: OrderSide, is_stop_order: bool = False) -> None:
        """
        Remove order from numpy arrays.
        
        Args:
            order_id: Order ID to remove
            side: Order side (BUY or SELL)
            is_stop_order: True if this is a stop order, False if limit order
        """
        if is_stop_order:
            # Remove from stop arrays
            if side == OrderSide.BUY:
                mask = self.long_stop_order_ids != order_id
                self.long_stop_order_ids = self.long_stop_order_ids[mask]
                self.long_stop_trigger_prices = self.long_stop_trigger_prices[mask]
            else:  # SELL
                mask = self.short_stop_order_ids != order_id
                self.short_stop_order_ids = self.short_stop_order_ids[mask]
                self.short_stop_trigger_prices = self.short_stop_trigger_prices[mask]
        else:
            # Remove from limit arrays
            if side == OrderSide.BUY:
                mask = self.long_order_ids != order_id
                self.long_order_ids = self.long_order_ids[mask]
                self.long_order_prices = self.long_order_prices[mask]
            else:  # SELL
                mask = self.short_order_ids != order_id
                self.short_order_ids = self.short_order_ids[mask]
                self.short_order_prices = self.short_order_prices[mask]
    
    def _execute_triggered_order(self, order: Order, high: PRICE_TYPE, low: PRICE_TYPE) -> None:
        """
        Execute a triggered order (limit or stop).
        
        Args:
            order: Order to execute
            high: High price of current bar (for logging)
            low: Low price of current bar (for logging)
        """
        if not order.active:
            return
        
        # Determine execution price based on order type
        if order.trigger_price is not None:
            # Stop order: execute at trigger_price
            execution_price = order.trigger_price
            order_type = "stop"
        else:
            # Limit order: execute at limit price
            execution_price = order.price
            order_type = "limit"
        
        # Execute order (limit/stop orders are not market orders, so no slippage, use fee_maker)
        self._execute_trade(
            order.side,
            order.volume,
            execution_price,
            deal_id=order.deal_id,
            order_id=order.order_id,
            is_market_order=False
        )
        # Mark order as executed and inactive
        order.filled_volume = order.volume
        order.active = False
        # Update modify_time to execution time
        order.modify_time = self.current_time
        
        # Log execution
        if order_type == "stop":
            logger.info(
                f"Stop order executed: order_id={order.order_id}, "
                f"side={order.side.value}, trigger_price={order.trigger_price}, "
                f"execution_price={execution_price}, volume={order.volume}, "
                f"bar_high={high}, bar_low={low}"
            )
        else:
            logger.info(
                f"Limit order executed: order_id={order.order_id}, "
                f"side={order.side.value}, price={order.price}, "
                f"volume={order.volume}, bar_high={high}, bar_low={low}"
            )
    
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
    
    def cancel_orders(self, order_ids: List[int]) -> CancelOrderResult:
        """
        Cancel orders by their IDs.
        
        Sets order.active = False, updates modify_time, and removes from numpy arrays.
        Orders that are already inactive are silently skipped.
        
        Args:
            order_ids: List of order IDs to cancel
        
        Returns:
            CancelOrderResult with failed_orders and errors lists
        """
        failed_orders = []
        errors = []
        
        for order_id in order_ids:
            # Check if order exists
            if order_id <= 0 or order_id > len(self.orders):
                failed_orders.append(order_id)
                error_msg = f"cancel_orders(): Order {order_id} not found"
                errors.append(error_msg)
                continue
            
            # Get order (order_id is 1-based, list is 0-based)
            order = self.orders[order_id - 1]
            
            # Skip if already inactive (silently)
            if not order.active:
                continue
            
            # Cancel order
            order.active = False
            if self.current_time is not None:
                order.modify_time = self.current_time
            else:
                # If current_time is not set, use create_time (shouldn't happen in normal flow)
                order.modify_time = order.create_time
            
            # Remove from numpy arrays
            is_stop_order = order.trigger_price is not None
            self._remove_order_from_arrays(order_id, order.side, is_stop_order)
        
        return CancelOrderResult(failed_orders=failed_orders, errors=errors)
    
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
            
            # Check for triggered limit orders
            self._check_and_execute_orders(all_high[i_time], all_low[i_time])
            
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
