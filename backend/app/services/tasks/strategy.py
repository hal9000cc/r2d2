from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict, Any, Callable, TYPE_CHECKING, Union
import traceback
import numpy as np
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide, OrderStatus
from pydantic import BaseModel, Field
from app.core.logger import get_logger
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

# Import Order for runtime use (needed for OrderOperationResult)
from app.services.tasks.broker_backtesting import Order

if TYPE_CHECKING:
    from app.services.tasks.broker_backtesting import BrokerBacktesting as Broker, ta_proxy

logger = get_logger(__name__)


class OrderOperationResult(BaseModel):
    """
    Result of order operation (buy/sell/cancel).
    Contains orders, error messages, and categorized order IDs by status.
    """
    orders: List['Order'] = Field(default_factory=list, description="List of orders created by this operation")
    error_messages: List[str] = Field(default_factory=list, description="List of error messages (if any)")
    active: List[int] = Field(default_factory=list, description="List of active order IDs")
    executed: List[int] = Field(default_factory=list, description="List of executed order IDs")
    canceled: List[int] = Field(default_factory=list, description="List of canceled order IDs")
    error: List[int] = Field(default_factory=list, description="List of error order IDs")
    deal_id: int = Field(default=0, description="Deal ID that groups all orders in this operation. 0 means automatic deal creation (for buy/sell methods).")
    volume: VOLUME_TYPE = Field(default=0.0, description="Current position volume for the deal (deal.quantity) at the time of the request")


class Strategy(ABC):
    def __init__(self):
        """
        Initialize strategy.
        """
        self.time: Optional[np.ndarray] = None  # dtype: TIME_TYPE
        self.open: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.high: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.low: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.close: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.volume: Optional[np.ndarray] = None  # dtype: VOLUME_TYPE
        
        # Equity tracking (updated on each bar)
        self.equity_usd: PRICE_TYPE = 0.0
        self.equity_symbol: VOLUME_TYPE = 0.0
        
        # Parameters will be set in on_start callback
        self.parameters: Optional[Dict[str, Any]] = None
        
        # Broker will be set when callbacks are created
        self.broker: Optional[Broker] = None

        # TA proxy will be set when callbacks are created
        self.talib: Optional[ta_proxy] = None

    def on_start(self):
        """
        Called before the testing loop starts.
        Use this method to initialize any strategy-specific data structures or variables.
        Default implementation does nothing.
        """
        pass

    @abstractmethod
    def on_bar(self):
        """
        Called when a new bar is received.
        """
        pass

    def on_finish(self):
        """
        Called after the testing loop completes.
        Use this method to perform any final calculations or cleanup.
        Default implementation does nothing.
        """
        pass

    @staticmethod
    def get_parameters_description() -> Dict[str, Tuple[Any, str]]:
        """
        Get parameters description of the strategy.
        
        Returns:
            Dictionary where keys are parameter names (str) and values are tuples
            of (default_value, description). Type is determined automatically from default_value.
            For example:
            {
                'fast_ma': (10, 'Fast moving average period'),
                'slow_ma': (20, 'Slow moving average period')
            }
        Default implementation returns empty dictionary (no parameters).
        """
        return {}

    def buy(
        self,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        trigger_price: Optional[PRICE_TYPE] = None
    ) -> OrderOperationResult:
        """
        Place a buy order. Supports market, limit, and stop orders.
        
        Args:
            quantity: Order quantity (volume)
            price: Limit price. If None and trigger_price is None, order is placed as market order.
            trigger_price: Trigger price for stop order (breakout order).
        
        Returns:
            OrderOperationResult with orders, error_messages, and categorized order IDs
        """
        # Execute through broker (returns List[Order])
        orders = self.broker.buy(quantity, price=price, trigger_price=trigger_price)
        
        # Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        error_ids = [order.order_id for order in orders if order.status == OrderStatus.ERROR]
        
        # Log errors if any
        if all_errors:
            self._log_result_errors(all_errors, "buy")
        
        # Get deal_id from orders (all orders should have the same deal_id for buy/sell)
        deal_id = 0
        if orders:
            # Get deal_id from first order (all orders in buy/sell have same deal_id)
            deal_id = orders[0].deal_id if orders[0].deal_id is not None else 0
        
        return OrderOperationResult(
            orders=orders,
            error_messages=all_errors,
            active=active_ids,
            executed=executed_ids,
            error=error_ids,
            deal_id=deal_id,  # Deal ID from orders
            volume=0.0  # Volume will be filled differently
        )
    
    def sell(
        self,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        trigger_price: Optional[PRICE_TYPE] = None
    ) -> OrderOperationResult:
        """
        Place a sell order. Supports market, limit, and stop orders.
        
        Args:
            quantity: Order quantity (volume)
            price: Limit price. If None and trigger_price is None, order is placed as market order.
            trigger_price: Trigger price for stop order (breakout order).
        
        Returns:
            OrderOperationResult with orders, error_messages, and categorized order IDs
        """
        # Execute through broker (returns List[Order])
        orders = self.broker.sell(quantity, price=price, trigger_price=trigger_price)
        
        # Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        error_ids = [order.order_id for order in orders if order.status == OrderStatus.ERROR]
        
        # Log errors if any
        if all_errors:
            self._log_result_errors(all_errors, "sell")
        
        # Get deal_id from orders (all orders should have the same deal_id for buy/sell)
        deal_id = 0
        if orders:
            # Get deal_id from first order (all orders in buy/sell have same deal_id)
            deal_id = orders[0].deal_id if orders[0].deal_id is not None else 0
        
        return OrderOperationResult(
            orders=orders,
            error_messages=all_errors,
            active=active_ids,
            executed=executed_ids,
            error=error_ids,
            deal_id=deal_id,  # Deal ID from orders
            volume=0.0  # Volume will be filled differently
        )
    
    def _normalize_sltp_enter(
        self,
        enter: Union[
            VOLUME_TYPE,
            Tuple[VOLUME_TYPE, PRICE_TYPE],
            List[Tuple[VOLUME_TYPE, PRICE_TYPE]]
        ]
    ) -> List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]]:
        """
        Normalize enter parameter to list of (volume, price) tuples.
        Price can be None for market orders.
        
        Args:
            enter: Entry order - volume (market), (volume, price) tuple, or list of tuples
        
        Returns:
            List of (volume, price) tuples. Price is None for market orders.
        """
        if isinstance(enter, (int, float)):
            # Market order: volume only
            return [(VOLUME_TYPE(enter), None)]
        elif isinstance(enter, tuple) and len(enter) == 2:
            # Single limit order: (volume, price)
            return [(VOLUME_TYPE(enter[0]), PRICE_TYPE(enter[1]))]
        elif isinstance(enter, list):
            # Multiple limit orders: list of (volume, price) tuples
            return [(VOLUME_TYPE(vol), PRICE_TYPE(price)) for vol, price in enter]
        else:
            raise ValueError(f"Invalid enter parameter type: {type(enter)}")
    
    def _normalize_sltp_exit(
        self,
        exit_param: Optional[Union[
            PRICE_TYPE,
            List[PRICE_TYPE],
            List[Tuple[Optional[float], PRICE_TYPE]]
        ]]
    ) -> List[Tuple[Optional[float], PRICE_TYPE]]:
        """
        Normalize stop_loss or take_profit parameter to list of (fraction, price) tuples.
        
        Args:
            exit_param: Exit parameter - price, list of prices, or list of (fraction, price) tuples
        
        Returns:
            List of (fraction, price) tuples. Fraction is None for "all remaining".
            If input was list of prices, fractions are distributed equally, last one has None.
        """
        if exit_param is None:
            return []
        
        if isinstance(exit_param, (int, float)):
            # Single price: (None, price) - all remaining
            return [(None, PRICE_TYPE(exit_param))]
        
        if isinstance(exit_param, list):
            if not exit_param:
                return []
            
            # Check if first element is a tuple (fraction, price) or just a price
            if isinstance(exit_param[0], tuple):
                # List of (fraction, price) tuples
                return [(f if f is None else float(f), PRICE_TYPE(p)) for f, p in exit_param]
            else:
                # List of prices: distribute equally
                num_prices = len(exit_param)
                if num_prices == 1:
                    return [(None, PRICE_TYPE(exit_param[0]))]
                else:
                    # Equal fractions, last one is None
                    fraction = 1.0 / num_prices
                    result = [(fraction, PRICE_TYPE(p)) for p in exit_param[:-1]]
                    result.append((None, PRICE_TYPE(exit_param[-1])))
                    return result
        
        raise ValueError(f"Invalid exit parameter type: {type(exit_param)}")
    
    def _validate_sltp_structure(
        self,
        entries: List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]],
        stop_losses: List[Tuple[Optional[float], PRICE_TYPE]],
        take_profits: List[Tuple[Optional[float], PRICE_TYPE]]
    ) -> List[str]:
        """
        Validate structure of SLTP parameters.
        
        Returns:
            List of error messages. Empty list means no errors.
        """
        errors = []
        
        # Validate entries
        if not entries:
            errors.append("enter parameter must not be empty")
            return errors  # Can't continue without entries
        
        # Check if market order (price=None) - must be single element
        market_orders = [e for e in entries if e[1] is None]
        if market_orders and len(entries) > 1:
            errors.append("Market order (enter=volume) must be single entry, cannot mix with limit orders")
        
        # Validate volumes
        for i, (vol, price) in enumerate(entries):
            if vol <= 0:
                errors.append(f"Entry {i}: volume must be greater than 0, got {vol}")
            if price is not None and price <= 0:
                errors.append(f"Entry {i}: price must be greater than 0, got {price}")
        
        # Validate stop_losses
        if stop_losses:
            # Check that exactly one has fraction=None
            none_count = sum(1 for f, _ in stop_losses if f is None)
            if none_count == 0:
                errors.append("stop_loss: exactly one order must have fraction=None (for 'all remaining')")
            elif none_count > 1:
                errors.append("stop_loss: only one order can have fraction=None")
            
            # Check sum of fractions < 1.0
            fractions = [f for f, _ in stop_losses if f is not None]
            if fractions:
                total = sum(fractions)
                if total >= 1.0:
                    errors.append(f"stop_loss: sum of fractions ({total}) must be less than 1.0")
            
            # Validate prices
            for i, (fraction, price) in enumerate(stop_losses):
                if price <= 0:
                    errors.append(f"stop_loss {i}: price must be greater than 0, got {price}")
                if fraction is not None and (fraction <= 0 or fraction >= 1.0):
                    errors.append(f"stop_loss {i}: fraction must be between 0 and 1, got {fraction}")
        
        # Validate take_profits
        if take_profits:
            # Check that exactly one has fraction=None
            none_count = sum(1 for f, _ in take_profits if f is None)
            if none_count == 0:
                errors.append("take_profit: exactly one order must have fraction=None (for 'all remaining')")
            elif none_count > 1:
                errors.append("take_profit: only one order can have fraction=None")
            
            # Check sum of fractions < 1.0
            fractions = [f for f, _ in take_profits if f is not None]
            if fractions:
                total = sum(fractions)
                if total >= 1.0:
                    errors.append(f"take_profit: sum of fractions ({total}) must be less than 1.0")
            
            # Validate prices
            for i, (fraction, price) in enumerate(take_profits):
                if price <= 0:
                    errors.append(f"take_profit {i}: price must be greater than 0, got {price}")
                if fraction is not None and (fraction <= 0 or fraction >= 1.0):
                    errors.append(f"take_profit {i}: fraction must be between 0 and 1, got {fraction}")
        
        return errors
    
    def _find_farthest_price_index(
        self,
        side: OrderSide,
        exit_list: List[Tuple[float, PRICE_TYPE]],
        is_stop_loss: bool
    ) -> int:
        """
        Find index of the order with farthest price from entry points.
        
        For BUY:
            - stop_loss: minimum price (farthest down)
            - take_profit: maximum price (farthest up)
        For SELL:
            - stop_loss: maximum price (farthest up)
            - take_profit: minimum price (farthest down)
        
        Args:
            side: Order side (BUY or SELL)
            exit_list: List of (fraction, price) tuples
            is_stop_loss: True if this is stop_loss, False if take_profit
        
        Returns:
            Index of the order with farthest price
        """
        if not exit_list:
            raise ValueError("exit_list must not be empty")
        
        prices = [price for _, price in exit_list]
        
        if side == OrderSide.BUY:
            if is_stop_loss:
                # Stop loss: minimum price (farthest down)
                return min(range(len(prices)), key=lambda i: prices[i])
            else:
                # Take profit: maximum price (farthest up)
                return max(range(len(prices)), key=lambda i: prices[i])
        else:  # SELL
            if is_stop_loss:
                # Stop loss: maximum price (farthest up)
                return max(range(len(prices)), key=lambda i: prices[i])
            else:
                # Take profit: minimum price (farthest down)
                return min(range(len(prices)), key=lambda i: prices[i])
    
    def _validate_sltp_prices(
        self,
        side: OrderSide,
        entries: List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]],
        stop_losses: List[Tuple[float, PRICE_TYPE]],
        take_profits: List[Tuple[float, PRICE_TYPE]]
    ) -> List[str]:
        """
        Validate prices relative to current market price.
        
        Returns:
            List of error messages. Empty list means no errors.
        """
        errors = []
        
        if self.close is None or len(self.close) == 0:
            errors.append("Cannot validate prices: current price is not available")
            return errors
        
        current_price = self.close[-1]
        
        # Validate entry limit orders
        for i, (vol, price) in enumerate(entries):
            if price is not None:  # Limit order
                if side == OrderSide.BUY:
                    # BUY limit: price must be < current price
                    if price >= current_price:
                        errors.append(
                            f"Entry {i}: BUY limit order price ({price}) must be below current price ({current_price})"
                        )
                else:  # SELL
                    # SELL limit: price must be > current price
                    if price <= current_price:
                        errors.append(
                            f"Entry {i}: SELL limit order price ({price}) must be above current price ({current_price})"
                        )
        
        # Validate stop_losses
        for i, (fraction, price) in enumerate(stop_losses):
            if side == OrderSide.BUY:
                # BUY position: stop loss is SELL stop, trigger_price must be < current price
                if price >= current_price:
                    errors.append(
                        f"stop_loss {i}: BUY stop loss trigger price ({price}) must be below current price ({current_price})"
                    )
            else:  # SELL
                # SELL position: stop loss is BUY stop, trigger_price must be > current price
                if price <= current_price:
                    errors.append(
                        f"stop_loss {i}: SELL stop loss trigger price ({price}) must be above current price ({current_price})"
                    )
        
        # Validate take_profits
        for i, (fraction, price) in enumerate(take_profits):
            if side == OrderSide.BUY:
                # BUY position: take profit is SELL limit, price must be > current price
                if price <= current_price:
                    errors.append(
                        f"take_profit {i}: BUY take profit price ({price}) must be above current price ({current_price})"
                    )
            else:  # SELL
                # SELL position: take profit is BUY limit, price must be < current price
                if price >= current_price:
                    errors.append(
                        f"take_profit {i}: SELL take profit price ({price}) must be below current price ({current_price})"
                    )
        
        return errors
    
    def buy_sltp(
        self,
        enter: Union[
            VOLUME_TYPE,
            Tuple[VOLUME_TYPE, PRICE_TYPE],
            List[Tuple[VOLUME_TYPE, PRICE_TYPE]]
        ],
        stop_loss: Optional[Union[
            PRICE_TYPE,
            List[PRICE_TYPE],
            List[Tuple[float, PRICE_TYPE]]
        ]] = None,
        take_profit: Optional[Union[
            PRICE_TYPE,
            List[PRICE_TYPE],
            List[Tuple[float, PRICE_TYPE]]
        ]] = None
    ) -> OrderOperationResult:
        """
        Place a buy order with optional stop loss and/or take profit.
        
        Creates entry order(s) and optional exit orders. Exit orders are placed after
        entry execution using actual executed volume.
        
        Args:
            enter: Entry order - volume (market), (volume, price) tuple (limit),
                   or list of (volume, price) tuples (multiple limits).
            stop_loss: Optional stop loss - price, list of prices (equal parts),
                       or list of (fraction, price) tuples. All fractions are explicit and sum to 1.0.
            take_profit: Optional take profit - same format as stop_loss.
        
        Returns:
            OrderOperationResult with all orders (entry + exit if specified).
            The deal_id field contains the ID of the deal that groups all orders
            (entry and exit orders) created by this operation.
        """
        # Normalize parameters
        entries = self._normalize_sltp_enter(enter)
        stop_losses = self._normalize_sltp_exit(stop_loss)
        take_profits = self._normalize_sltp_exit(take_profit)
        
        # Validate structure
        structure_errors = self._validate_sltp_structure(entries, stop_losses, take_profits)
        
        # Validate prices relative to current price
        price_errors = self._validate_sltp_prices(OrderSide.BUY, entries, stop_losses, take_profits)
        
        # Combine all errors
        all_errors = structure_errors + price_errors
        
        # If there are errors, return error result
        if all_errors:
            self._log_result_errors(all_errors, "buy_sltp")
            return OrderOperationResult(
                orders=[],
                error_messages=all_errors,
                active=[],
                executed=[],
                canceled=[],
                error=[],
                deal_id=0,
                volume=0.0
            )
        
        # Execute deal through broker
        orders, deal = self.broker.execute_deal(OrderSide.BUY, entries, stop_losses, take_profits)
        
        # Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        error_ids = [order.order_id for order in orders if order.status == OrderStatus.ERROR]
        
        # Log errors if any
        if all_errors:
            self._log_result_errors(all_errors, "buy_sltp")
        
        # Get deal_id and volume from deal
        deal_id = deal.deal_id if deal else 0
        volume = deal.quantity if deal else 0.0
        
        return OrderOperationResult(
            orders=orders,
            error_messages=all_errors,
            active=active_ids,
            executed=executed_ids,
            error=error_ids,
            deal_id=deal_id,
            volume=volume
        )
    
    def sell_sltp(
        self,
        enter: Union[
            VOLUME_TYPE,
            Tuple[VOLUME_TYPE, PRICE_TYPE],
            List[Tuple[VOLUME_TYPE, PRICE_TYPE]]
        ],
        stop_loss: Optional[Union[
            PRICE_TYPE,
            List[PRICE_TYPE],
            List[Tuple[float, PRICE_TYPE]]
        ]] = None,
        take_profit: Optional[Union[
            PRICE_TYPE,
            List[PRICE_TYPE],
            List[Tuple[float, PRICE_TYPE]]
        ]] = None
    ) -> OrderOperationResult:
        """
        Place a sell order with optional stop loss and/or take profit.
        
        Creates entry order(s) and optional exit orders. Exit orders are placed after
        entry execution using actual executed volume.
        
        Args:
            enter: Entry order - volume (market), (volume, price) tuple (limit),
                   or list of (volume, price) tuples (multiple limits).
            stop_loss: Optional stop loss - price, list of prices (equal parts),
                       or list of (fraction, price) tuples. All fractions are explicit and sum to 1.0.
            take_profit: Optional take profit - same format as stop_loss.
        
        Returns:
            OrderOperationResult with all orders (entry + exit if specified).
            The deal_id field contains the ID of the deal that groups all orders
            (entry and exit orders) created by this operation.
        """
        # Normalize parameters
        entries = self._normalize_sltp_enter(enter)
        stop_losses = self._normalize_sltp_exit(stop_loss)
        take_profits = self._normalize_sltp_exit(take_profit)
        
        # Validate structure
        structure_errors = self._validate_sltp_structure(entries, stop_losses, take_profits)
        
        # Validate prices relative to current price
        price_errors = self._validate_sltp_prices(OrderSide.SELL, entries, stop_losses, take_profits)
        
        # Combine all errors
        all_errors = structure_errors + price_errors
        
        # If there are errors, return error result
        if all_errors:
            self._log_result_errors(all_errors, "sell_sltp")
            return OrderOperationResult(
                orders=[],
                error_messages=all_errors,
                active=[],
                executed=[],
                canceled=[],
                error=[],
                deal_id=0,
                volume=0.0
            )
        
        # Execute deal through broker
        orders, deal = self.broker.execute_deal(OrderSide.SELL, entries, stop_losses, take_profits)
        
        # Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        error_ids = [order.order_id for order in orders if order.status == OrderStatus.ERROR]
        
        # Log errors if any
        if all_errors:
            self._log_result_errors(all_errors, "sell_sltp")
        
        # Get deal_id and volume from deal
        deal_id = deal.deal_id if deal else 0
        volume = deal.quantity if deal else 0.0
        
        return OrderOperationResult(
            orders=orders,
            error_messages=all_errors,
            active=active_ids,
            executed=executed_ids,
            error=error_ids,
            deal_id=deal_id,
            volume=volume
        )
    
    def logging(self, message: str, level: str = "info") -> None:
        """
        Send log message to frontend via broker.
        Proxies to broker.logging().
        
        Args:
            message: Message text (required)
            level: Message level (optional, default: "info")
                  Valid levels: info, warning, error, success, debug
        """
        if self.broker is None:
            raise RuntimeError("Broker not initialized. Cannot send log message.")
        self.broker.logging(message, level)
    
    def _log_result_errors(self, errors: List[str], method_name: str) -> None:
        """
        Log errors from result objects (OrderOperationResult).
        Logs to both frontend messages and logger.
        
        Args:
            errors: List of error messages
            method_name: Name of the method that produced the errors (for prefix)
        """
        for error in errors:
            self.logging(f"{method_name}(): {error}", level="error")
            logger.info(f"{method_name}(): {error}")
    
    def cancel_orders(self, order_ids: List[int]) -> OrderOperationResult:
        """
        Cancel orders by their IDs.
        
        Args:
            order_ids: List of order IDs to cancel
        
        Returns:
            OrderOperationResult with canceled order IDs and any errors
        """
        canceled_orders = self.broker.cancel_orders(order_ids)
        
        # Extract canceled order IDs
        canceled_ids = [order.order_id for order in canceled_orders]
        
        # Find orders that were not found (not in canceled list)
        error_ids = []
        error_messages = []
        for order_id in order_ids:
            if order_id not in canceled_ids:
                error_ids.append(order_id)
                error_messages.append(f"cancel_orders(): Order {order_id} not found")
        
        # Log errors if any
        if error_messages:
            self._log_result_errors(error_messages, "cancel_orders")
        
        # Get deal_id from canceled orders (use first order's deal_id if available)
        deal_id = 0
        if canceled_orders:
            deal_id = canceled_orders[0].deal_id if canceled_orders[0].deal_id is not None else 0
        
        return OrderOperationResult(
            orders=[order.model_copy(deep=True) for order in canceled_orders],
            error_messages=error_messages,
            canceled=canceled_ids,
            error=error_ids,
            deal_id=deal_id,  # Deal ID from canceled orders
            volume=0.0  # Volume will be filled differently
        )
    
    def deal_orders(self, deal_id: int) -> OrderOperationResult:
        """
        Get all orders associated with a specific deal.
        
        Args:
            deal_id: ID of the deal to get orders for
        
        Returns:
            OrderOperationResult with all orders for the specified deal.
            Orders are categorized by status (active, executed, canceled, error).
            If deal_id is not found, returns empty result with error message.
        
        Raises:
            NotImplementedError: This method is not yet implemented.
        """
        # Placeholder for future implementation
        return OrderOperationResult(
            deal_id=deal_id,
            error_messages=[f"deal_orders(): Method not yet implemented for deal_id {deal_id}"],
            volume=0.0  # Volume will be filled differently
        )
    
    @staticmethod
    def is_strategy_error(exception: Exception) -> Tuple[bool, Optional[str]]:
        """
        Analyze exception traceback to determine if error occurred in strategy code.
        
        Args:
            exception: Exception that occurred
            
        Returns:
            Tuple of (is_strategy_error: bool, error_message: Optional[str])
            If is_strategy_error is True, error_message contains formatted message with line number.
        """
        tb = exception.__traceback__
        if tb is None:
            return False, None
        
        # Collect all traceback frames
        frames = traceback.extract_tb(tb)
        
        # Look for strategy-related frames
        strategy_frame = None
        for frame in frames:
            func_name = frame.name
            
            # Check if frame is in strategy code by method names: on_bar, on_start, on_finish
            if func_name in ('on_bar', 'on_start', 'on_finish'):
                strategy_frame = frame
                break
        
        if strategy_frame is None:
            return False, None
        
        # Format error message
        method_name = strategy_frame.name
        line_no = strategy_frame.lineno
        line_text = strategy_frame.line or ""
        
        error_msg = (
            f"Error in strategy code: {exception.__class__.__name__}: {str(exception)}\n"
            f"Location: method '{method_name}' at line {line_no}"
        )
        
        if line_text.strip():
            error_msg += f"\nCode: {line_text.strip()}"
        
        return True, error_msg
    
    @staticmethod
    def create_strategy_callbacks(strategy: 'Strategy') -> Dict[str, Callable]:
        """
        Create callbacks for broker with closure on strategy.
        
        Args:
            strategy: Strategy instance
            
        Returns:
            Dictionary with callback functions for broker
        """
        def __on_start(parameters: Dict[str, Any], ta_proxies: Dict[str, ta_proxy]):
            strategy.parameters = parameters
            # Set TA library proxies as strategy attributes
            for name, proxy in ta_proxies.items():
                setattr(strategy, name, proxy)
            strategy.on_start()
        
        def __on_bar(
            price: PRICE_TYPE,
            current_time: np.datetime64,
            time: np.ndarray,
            open: np.ndarray,
            high: np.ndarray,
            low: np.ndarray,
            close: np.ndarray,
            volume: np.ndarray,
            equity_usd: PRICE_TYPE,
            equity_symbol: VOLUME_TYPE
        ):
            strategy.time = time
            strategy.open = open
            strategy.high = high
            strategy.low = low
            strategy.close = close
            strategy.volume = volume
            strategy.equity_usd = equity_usd
            strategy.equity_symbol = equity_symbol
            strategy.on_bar()
        
        def __on_finish():
            strategy.on_finish()
        
        return {
            'on_start': __on_start,
            'on_bar': __on_bar,
            'on_finish': __on_finish
        }

    