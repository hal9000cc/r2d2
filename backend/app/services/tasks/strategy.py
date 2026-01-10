from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict, Any, Callable, TYPE_CHECKING, Union
import traceback
import numpy as np
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.tasks.tasks import Task
from app.services.tasks.broker import OrderSide, OrderStatus, DealType
from pydantic import BaseModel, Field
from app.core.logger import get_logger
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.objects2redis import MessageType

# Import Order and Deal for runtime use (needed for OrderOperationResult and close_deal)
from app.services.tasks.broker import Order, Deal

if TYPE_CHECKING:
    from app.services.tasks.broker_backtesting import BrokerBacktesting as Broker, ta_proxy

logger = get_logger(__name__)

class OrderOperationResult(BaseModel):
    """
    Result of order operation (buy/sell/cancel).
    Contains orders, error messages, and categorized order IDs by status.
    """
    orders: List[Order] = Field(default_factory=list, description="List of orders created by this operation")
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
    
    @property
    def precision_amount(self) -> float:
        """
        Read-only volume precision taken from broker.
        """
        assert self.broker is not None, "Broker is not set on strategy"
        return self.broker.precision_amount

    @property
    def precision_price(self) -> float:
        """
        Read-only price precision taken from broker.
        """
        assert self.broker is not None, "Broker is not set on strategy"
        return self.broker.precision_price

    # ------------------------------------------------------------------
    # Price comparison proxies (delegate to broker)
    # ------------------------------------------------------------------
    def eq(self, a: float, b: float) -> bool:
        """Proxy for broker.eq(a, b) - price equality with precision tolerance."""
        assert self.broker is not None, "Broker is not set on strategy"
        return self.broker.eq(a, b)

    def gt(self, a: float, b: float) -> bool:
        """Proxy for broker.gt(a, b) - a > b with precision tolerance."""
        assert self.broker is not None, "Broker is not set on strategy"
        return self.broker.gt(a, b)

    def lt(self, a: float, b: float) -> bool:
        """Proxy for broker.lt(a, b) - a < b with precision tolerance."""
        assert self.broker is not None, "Broker is not set on strategy"
        return self.broker.lt(a, b)

    def gteq(self, a: float, b: float) -> bool:
        """Proxy for broker.gteq(a, b) - a >= b with precision tolerance."""
        assert self.broker is not None, "Broker is not set on strategy"
        return self.broker.gteq(a, b)

    def lteq(self, a: float, b: float) -> bool:
        """Proxy for broker.lteq(a, b) - a <= b with precision tolerance."""
        assert self.broker is not None, "Broker is not set on strategy"
        return self.broker.lteq(a, b)

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
    
    def round_to_precision(self, value: float, precision: float) -> float:
        """
        Round value to nearest multiple of precision.
        Delegates to broker's round_to_precision method.
        
        Args:
            value: Value to round
            precision: Precision step (e.g., 0.01, 0.001)
        
        Returns:
            Rounded value
        """
        if self.broker is None:
            return value
        return self.broker.round_to_precision(value, precision)
    
    def floor_to_precision(self, value: float, precision: float) -> float:
        """
        Round value down to nearest multiple of precision.
        Delegates to broker's floor_to_precision method.
        
        Args:
            value: Value to round down
            precision: Precision step (e.g., 0.01, 0.001)
        
        Returns:
            Rounded down value
        """
        if self.broker is None:
            return value
        return self.broker.floor_to_precision(value, precision)
    
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
        # Round quantity down to precision_amount
        original_quantity = quantity
        quantity = self.floor_to_precision(quantity, self.precision_amount)
        volume_eps = self.precision_amount * 1e-3
        if abs(quantity - original_quantity) > volume_eps:
            msg = f"Volume {original_quantity} rounded down to {quantity} due to precision_amount={self.precision_amount}"
            logger.warning(msg)
            print(msg)
        
        # Round price to precision_price if specified
        original_price = price
        if price is not None:
            price = self.round_to_precision(price, self.precision_price)
            # Use price comparison helper to detect actual change
            if not self.eq(float(price), float(original_price)):
                msg = f"Price {original_price} rounded to {price} due to precision_price={self.precision_price}"
                logger.warning(msg)
                print(msg)
        
        # Round trigger_price to precision_price if specified
        original_trigger_price = trigger_price
        if trigger_price is not None:
            trigger_price = self.round_to_precision(trigger_price, self.precision_price)
            if not self.eq(float(trigger_price), float(original_trigger_price)):
                msg = f"Trigger price {original_trigger_price} rounded to {trigger_price} due to precision_price={self.precision_price}"
                logger.warning(msg)
                print(msg)
        
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
            deal_id = orders[0].deal_id
        
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
        # Round quantity down to precision_amount
        original_quantity = quantity
        quantity = self.floor_to_precision(quantity, self.precision_amount)
        volume_eps = self.precision_amount * 1e-3
        if abs(quantity - original_quantity) > volume_eps:
            msg = f"Volume {original_quantity} rounded down to {quantity} due to precision_amount={self.precision_amount}"
            logger.warning(msg)
            print(msg)
        
        # Round price to precision_price if specified
        original_price = price
        if price is not None:
            price = self.round_to_precision(price, self.precision_price)
            if not self.eq(float(price), float(original_price)):
                msg = f"Price {original_price} rounded to {price} due to precision_price={self.precision_price}"
                logger.warning(msg)
                print(msg)
        
        # Round trigger_price to precision_price if specified
        original_trigger_price = trigger_price
        if trigger_price is not None:
            trigger_price = self.round_to_precision(trigger_price, self.precision_price)
            if not self.eq(float(trigger_price), float(original_trigger_price)):
                msg = f"Trigger price {original_trigger_price} rounded to {trigger_price} due to precision_price={self.precision_price}"
                logger.warning(msg)
                print(msg)
        
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
            deal_id = orders[0].deal_id
        
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
            List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]]
        ],
        allow_negative: bool = False,
        current_volume: Optional[VOLUME_TYPE] = None
    ) -> List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]]:
        """
        Normalize enter parameter to list of (volume, price) tuples.
        Price can be None for market orders.
        Applies precision rounding: volume rounded down, price rounded to nearest.
        
        Args:
            enter: Entry order - volume (market), (volume, price) tuple, or list of tuples.
                   Price can be None in tuples for market orders.
            allow_negative: If True, allow negative volumes (for closing position)
            current_volume: Current position volume for validation of negative volumes
        
        Returns:
            List of (volume, price) tuples. Price is None for market orders.
        """
        if isinstance(enter, (int, float)):
            # Market order: volume only
            original_vol = enter
            # For negative volumes, round absolute value then restore sign
            if allow_negative and enter < 0:
                rounded_abs = self.floor_to_precision(abs(enter), self.precision_amount)
                vol = -rounded_abs  # Restore negative sign after rounding
            else:
                vol = self.floor_to_precision(enter, self.precision_amount)
            volume_eps = self.precision_amount * 1e-3
            if abs(vol - original_vol) > volume_eps:
                msg = f"Volume {original_vol} rounded down to {vol} due to precision_amount={self.precision_amount}"
                logger.warning(msg)
                print(msg)
            # Validate negative volume if needed
            if allow_negative and vol < 0 and current_volume is not None:
                if abs(vol) > abs(current_volume):
                    raise ValueError(f"Negative volume {vol} exceeds current position volume {current_volume}")
            return [(VOLUME_TYPE(vol), None)]
        elif isinstance(enter, tuple) and len(enter) == 2:
            # Single limit order: (volume, price)
            original_vol = enter[0]
            original_price = enter[1]
            # For negative volumes, round absolute value then restore sign
            if allow_negative and enter[0] < 0:
                rounded_abs = self.floor_to_precision(abs(enter[0]), self.precision_amount)
                vol = -rounded_abs  # Restore negative sign after rounding
            else:
                vol = self.floor_to_precision(enter[0], self.precision_amount)
            # Handle None price for market orders
            if original_price is None:
                price = None
            else:
                price = self.round_to_precision(enter[1], self.precision_price)
            volume_eps = self.precision_amount * 1e-3
            if abs(vol - original_vol) > volume_eps:
                msg = f"Volume {original_vol} rounded down to {vol} due to precision_amount={self.precision_amount}"
                logger.warning(msg)
                print(msg)
            if price is not None and not self.eq(float(price), float(original_price)):
                msg = f"Price {original_price} rounded to {price} due to precision_price={self.precision_price}"
                logger.warning(msg)
                print(msg)
            # Validate negative volume if needed
            if allow_negative and vol < 0 and current_volume is not None:
                if abs(vol) > abs(current_volume):
                    raise ValueError(f"Negative volume {vol} exceeds current position volume {current_volume}")
            return [(VOLUME_TYPE(vol), PRICE_TYPE(price) if price is not None else None)]
        elif isinstance(enter, list):
            # Multiple limit orders: list of (volume, price) tuples
            result = []
            for vol, price in enter:
                original_vol = vol
                original_price = price
                # For negative volumes, round absolute value then restore sign
                if allow_negative and vol < 0:
                    rounded_abs = self.floor_to_precision(abs(vol), self.precision_amount)
                    rounded_vol = -rounded_abs  # Restore negative sign after rounding
                else:
                    rounded_vol = self.floor_to_precision(vol, self.precision_amount)
                # Handle None price for market orders
                if original_price is None:
                    rounded_price = None
                else:
                    rounded_price = self.round_to_precision(price, self.precision_price)
                volume_eps = self.precision_amount * 1e-3
                if abs(rounded_vol - original_vol) > volume_eps:
                    msg = f"Volume {original_vol} rounded down to {rounded_vol} due to precision_amount={self.precision_amount}"
                    logger.warning(msg)
                    print(msg)
                if rounded_price is not None and not self.eq(float(rounded_price), float(original_price)):
                    msg = f"Price {original_price} rounded to {rounded_price} due to precision_price={self.precision_price}"
                    logger.warning(msg)
                    print(msg)
                # Validate negative volume if needed
                if allow_negative and rounded_vol < 0 and current_volume is not None:
                    if abs(rounded_vol) > abs(current_volume):
                        raise ValueError(f"Negative volume {rounded_vol} exceeds current position volume {current_volume}")
                result.append((VOLUME_TYPE(rounded_vol), PRICE_TYPE(rounded_price) if rounded_price is not None else None))
            return result
        else:
            raise ValueError(f"Invalid enter parameter type: {type(enter)}")
    
    def _normalize_sltp_exit(
        self,
        exit_param: Optional[Union[
            PRICE_TYPE,
            List[PRICE_TYPE],
            List[Tuple[float, PRICE_TYPE]]
        ]]
    ) -> List[Tuple[float, PRICE_TYPE]]:
        """
        Normalize stop_loss or take_profit parameter to list of (fraction, price) tuples.
        Applies precision rounding: prices rounded to nearest.
        
        Args:
            exit_param: Exit parameter - price, list of prices, or list of (fraction, price) tuples
        
        Returns:
            List of (fraction, price) tuples.
            All fractions are explicit and must sum to 1.0.
            For list of prices, fractions are distributed equally and adjusted on the last
            element so that the total sum is exactly 1.0.
        """
        if exit_param is None:
            return []
        
        # Single price: full position at this price (fraction = 1.0)
        if isinstance(exit_param, (int, float)):
            original_price = exit_param
            price = self.round_to_precision(exit_param, self.precision_price)
            if not self.eq(float(price), float(original_price)):
                msg = f"Price {original_price} rounded to {price} due to precision_price={self.precision_price}"
                logger.warning(msg)
                print(msg)
            return [(1.0, PRICE_TYPE(price))]
        
        if isinstance(exit_param, list):
            if not exit_param:
                return []
            
            # Check if first element is a tuple (fraction, price) or just a price
            if isinstance(exit_param[0], tuple):
                # List of (fraction, price) tuples - keep fractions as provided (explicit)
                result: List[Tuple[float, PRICE_TYPE]] = []
                for f, p in exit_param:
                    if f is None:
                        raise ValueError("Fractions must be explicit for SL/TP orders; None is not allowed")
                    original_price = p
                    rounded_price = self.round_to_precision(p, self.precision_price)
                    if not self.eq(float(rounded_price), float(original_price)):
                        msg = f"Price {original_price} rounded to {rounded_price} due to precision_price={self.precision_price}"
                        logger.warning(msg)
                        print(msg)
                    result.append((float(f), PRICE_TYPE(rounded_price)))
                return result
            else:
                # List of prices: distribute equally with explicit fractions summing to 1.0
                num_prices = len(exit_param)
                if num_prices == 1:
                    original_price = exit_param[0]
                    price = self.round_to_precision(exit_param[0], self.precision_price)
                    if not self.eq(float(price), float(original_price)):
                        msg = f"Price {original_price} rounded to {price} due to precision_price={self.precision_price}"
                        logger.warning(msg)
                        print(msg)
                    return [(1.0, PRICE_TYPE(price))]
                else:
                    base_fraction = 1.0 / num_prices
                    result: List[Tuple[float, PRICE_TYPE]] = []
                    # First n-1 prices get base_fraction, last gets the remainder to make sum exactly 1.0
                    for p in exit_param[:-1]:
                        original_price = p
                        rounded_price = self.round_to_precision(p, self.precision_price)
                        if not self.eq(float(rounded_price), float(original_price)):
                            msg = f"Price {original_price} rounded to {rounded_price} due to precision_price={self.precision_price}"
                            logger.warning(msg)
                            print(msg)
                        result.append((base_fraction, PRICE_TYPE(rounded_price)))
                    # Last price
                    original_price = exit_param[-1]
                    price = self.round_to_precision(exit_param[-1], self.precision_price)
                    if not self.eq(float(price), float(original_price)):
                        msg = f"Price {original_price} rounded to {price} due to precision_price={self.precision_price}"
                        logger.warning(msg)
                        print(msg)
                    used_fraction = base_fraction * (num_prices - 1)
                    last_fraction = 1.0 - used_fraction
                    result.append((last_fraction, PRICE_TYPE(price)))
                    return result
        
        raise ValueError(f"Invalid exit parameter type: {type(exit_param)}")
    
    def _validate_sltp_structure(
        self,
        entries: List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]],
        stop_losses: List[Tuple[float, PRICE_TYPE]],
        take_profits: List[Tuple[float, PRICE_TYPE]],
        allow_empty_enter: bool = False,
        allow_negative: bool = False
    ) -> List[str]:
        """
        Validate structure of SLTP parameters.
        
        Args:
            entries: List of entry orders
            stop_losses: List of stop loss orders
            take_profits: List of take profit orders
            allow_empty_enter: If True, allow empty entries list
            allow_negative: If True, allow negative volumes
        
        Returns:
            List of error messages. Empty list means no errors.
        """
        errors = []
        
        # Validate entries
        if not entries:
            if not allow_empty_enter:
                errors.append("enter parameter must not be empty")
                return errors  # Can't continue without entries
            else:
                # Empty entries allowed, skip further entry validation
                pass
        else:
            # Check if market order (price=None) - must be single element
            market_orders = [e for e in entries if e[1] is None]
            if market_orders and len(entries) > 1:
                errors.append("Market order (enter=volume) must be single entry, cannot mix with limit orders")
            
            # Validate volumes
            for i, (vol, price) in enumerate(entries):
                if allow_negative:
                    # For negative volumes, check that they are negative
                    if vol == 0:
                        errors.append(f"Entry {i}: volume must not be zero, got {vol}")
                else:
                    # For positive volumes, check that they are positive
                    if vol <= 0:
                        errors.append(f"Entry {i}: volume must be greater than 0, got {vol}")
                if price is not None and price <= 0:
                    errors.append(f"Entry {i}: price must be greater than 0, got {price}")
        
        # Helper to validate fractions list (no None, sum ~ 1.0, each in (0, 1])
        def _validate_fractions(name: str, items: List[Tuple[float, PRICE_TYPE]]) -> None:
            if not items:
                return
            fractions = [f for f, _ in items]
            # Check for invalid fractions
            for i, f in enumerate(fractions):
                if f is None:  # Defensive, should not happen after normalization
                    errors.append(f"{name} {i}: fraction must be explicit, None is not allowed")
                elif f <= 0.0 or f > 1.0:
                    errors.append(f"{name} {i}: fraction must be in (0, 1], got {f}")
            total = sum(float(f) for f in fractions)
            if abs(total - 1.0) > 1e-3:
                errors.append(f"{name}: sum of fractions ({total}) must be equal to 1.0")
        
        # Validate stop_losses
        if stop_losses:
            _validate_fractions("stop_loss", stop_losses)
            
            # Validate prices
            for i, (fraction, price) in enumerate(stop_losses):
                if price <= 0:
                    errors.append(f"stop_loss {i}: price must be greater than 0, got {price}")
        
        # Validate take_profits
        if take_profits:
            _validate_fractions("take_profit", take_profits)
            
            # Validate prices
            for i, (fraction, price) in enumerate(take_profits):
                if price <= 0:
                    errors.append(f"take_profit {i}: price must be greater than 0, got {price}")
        
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
        deal_type: DealType,
        entries: List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]],
        stop_losses: List[Tuple[float, PRICE_TYPE]],
        take_profits: List[Tuple[float, PRICE_TYPE]]
    ) -> List[str]:
        """
        Validate prices relative to current market price.
        
        Args:
            deal_type: Deal type (LONG or SHORT)
            entries: List of entry orders
            stop_losses: List of stop loss orders
            take_profits: List of take profit orders
        
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
                if deal_type == DealType.LONG:
                    # LONG: buy limit must be < current price (with precision tolerance)
                    if self.gteq(price, current_price):
                        errors.append(
                            f"Entry {i}: LONG buy limit order price ({price}) must be below current price ({current_price})"
                        )
                else:  # SHORT
                    # SHORT: sell limit must be > current price (with precision tolerance)
                    if self.lteq(price, current_price):
                        errors.append(
                            f"Entry {i}: SHORT sell limit order price ({price}) must be above current price ({current_price})"
                        )
        
        # Validate stop_losses
        for i, (fraction, price) in enumerate(stop_losses):
            if deal_type == DealType.LONG:
                # LONG position: stop loss is SELL stop, trigger_price must be < current price
                if self.gteq(price, current_price):
                    errors.append(
                        f"stop_loss {i}: LONG stop loss trigger price ({price}) must be below current price ({current_price})"
                    )
            else:  # SHORT
                # SHORT position: stop loss is BUY stop, trigger_price must be > current price
                if self.lteq(price, current_price):
                    errors.append(
                        f"stop_loss {i}: SHORT stop loss trigger price ({price}) must be above current price ({current_price})"
                    )
        
        # Validate take_profits
        for i, (fraction, price) in enumerate(take_profits):
            if deal_type == DealType.LONG:
                # LONG position: take profit is SELL limit, price must be > current price
                if self.lteq(price, current_price):
                    errors.append(
                        f"take_profit {i}: LONG take profit price ({price}) must be above current price ({current_price})"
                    )
            else:  # SHORT
                # SHORT position: take profit is BUY limit, price must be < current price
                if self.gteq(price, current_price):
                    errors.append(
                        f"take_profit {i}: SHORT take profit price ({price}) must be below current price ({current_price})"
                    )
        
        # Validate that all entry limit orders are protected by stop loss
        # Extract limit entry prices (skip market orders where price is None)
        limit_entry_prices = [price for _, price in entries if price is not None]
        
        # Only check if there are limit entries and stop losses
        if limit_entry_prices and stop_losses:
            stop_prices = [price for _, price in stop_losses]
            
            if deal_type == DealType.LONG:
                # LONG position: minimum stop price must be below minimum entry limit price
                min_entry_limit = min(limit_entry_prices)
                min_stop = min(stop_prices)
                if not self.lt(min_stop, min_entry_limit):
                    errors.append(
                        f"Entry limit order at {min_entry_limit} is not protected by stop loss (minimum stop price is {min_stop})"
                    )
            else:  # SHORT
                # SHORT position: maximum stop price must be above maximum entry limit price
                max_entry_limit = max(limit_entry_prices)
                max_stop = max(stop_prices)
                if not self.gt(max_stop, max_entry_limit):
                    errors.append(
                        f"Entry limit order at {max_entry_limit} is not protected by stop loss (maximum stop price is {max_stop})"
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
        price_errors = self._validate_sltp_prices(DealType.LONG, entries, stop_losses, take_profits)
        
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
        deal, new_orders, canceled_order_ids = self.broker.execute_deal(DealType.LONG, entries, stop_losses, take_profits)
        
        # Get orders from new_orders (created in this call)
        orders = new_orders if deal else []
        
        # Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        canceled_ids = canceled_order_ids
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
            canceled=canceled_ids,
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
        price_errors = self._validate_sltp_prices(DealType.SHORT, entries, stop_losses, take_profits)
        
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
        deal, new_orders, canceled_order_ids = self.broker.execute_deal(DealType.SHORT, entries, stop_losses, take_profits)
        
        # Get orders from new_orders (created in this call)
        orders = new_orders if deal else []
        
        # Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        canceled_ids = canceled_order_ids
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
            canceled=canceled_ids,
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
    
    def close_deal(self, deal_id: int) -> Deal:
        """
        Close a specific deal by canceling all active orders and closing position.
        
        Args:
            deal_id: ID of the deal to close
        
        Returns:
            Deal: Deep copy of the closed deal
        
        Raises:
            IndexError: If deal with specified deal_id does not exist
        """
        # Call broker's close_deal method
        self.broker.close_deal(deal_id)
        
        # Get deal and return deep copy
        deal = self.broker.get_deal_by_id(deal_id)
        return deal.model_copy(deep=True)
    
    def modify_deal(
        self,
        deal_id: int,
        enter: Optional[Union[
            VOLUME_TYPE,
            Tuple[VOLUME_TYPE, PRICE_TYPE],
            List[Tuple[VOLUME_TYPE, Optional[PRICE_TYPE]]]
        ]] = None,
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
        Modify an existing deal by canceling all active orders and placing new ones.
        
        The existing position volume in the market is preserved. The deal direction
        (long/short) cannot be changed.
        
        Args:
            deal_id: ID of the deal to modify (required)
            enter: Entry order(s) - same format as buy_sltp()/sell_sltp(), or None/0
                   to skip adding new entry orders, or negative value to close part of position
            stop_loss: Stop loss order(s) - same format as buy_sltp()/sell_sltp() (optional)
            take_profit: Take profit order(s) - same format as buy_sltp()/sell_sltp() (optional)
        
        Returns:
            OrderOperationResult with all orders (new entry + exit if specified),
            categorized by status.
        """
        # 1. Get existing deal
        try:
            deal = self.broker.get_deal_by_id(deal_id)
        except IndexError:
            return OrderOperationResult(
                orders=[],
                error_messages=[f"modify_deal(): Deal {deal_id} not found"],
                active=[],
                executed=[],
                canceled=[],
                error=[],
                deal_id=deal_id,
                volume=0.0
            )
        
        # 2. Check if deal is closed
        if deal.quantity == 0:
            return OrderOperationResult(
                orders=[],
                error_messages=[f"modify_deal(): Deal {deal_id} is already closed"],
                active=[],
                executed=[],
                canceled=[],
                error=[],
                deal_id=deal_id,
                volume=0.0
            )
        
        # 3. Determine deal type
        if deal.type is None:
            return OrderOperationResult(
                orders=[],
                error_messages=[f"modify_deal(): Deal {deal_id} has no type set"],
                active=[],
                executed=[],
                canceled=[],
                error=[],
                deal_id=deal_id,
                volume=0.0
            )
        deal_type = deal.type
        
        # 4. Normalize parameters
        # Handle enter parameter: None, 0, or not specified means no new entry orders
        if enter is None or enter == 0:
            entries = []
        else:
            try:
                entries = self._normalize_sltp_enter(
                    enter,
                    allow_negative=True,
                    current_volume=abs(deal.quantity)
                )
            except ValueError as e:
                return OrderOperationResult(
                    orders=[],
                    error_messages=[f"modify_deal(): {str(e)}"],
                    active=[],
                    executed=[],
                    canceled=[],
                    error=[],
                    deal_id=deal_id,
                    volume=deal.quantity
                )
        
        stop_losses = self._normalize_sltp_exit(stop_loss)
        take_profits = self._normalize_sltp_exit(take_profit)
        
        # 5. Validate structure
        structure_errors = self._validate_sltp_structure(
            entries,
            stop_losses,
            take_profits,
            allow_empty_enter=True,
            allow_negative=True
        )
        
        # 6. Validate prices relative to current price
        price_errors = self._validate_sltp_prices(deal_type, entries, stop_losses, take_profits)
        
        # 7. Combine all errors
        all_errors = structure_errors + price_errors
        
        # 8. If there are errors, return error result
        if all_errors:
            self._log_result_errors(all_errors, "modify_deal")
            return OrderOperationResult(
                orders=[],
                error_messages=all_errors,
                active=[],
                executed=[],
                canceled=[],
                error=[],
                deal_id=deal_id,
                volume=deal.quantity
            )
        
        # 9. Execute deal through broker with existing deal_id
        deal_result, new_orders, canceled_order_ids = self.broker.execute_deal(
            deal_type,
            entries,
            stop_losses,
            take_profits,
            existing_deal_id=deal_id
        )
        
        # 11. Get orders from new_orders (created in this call)
        orders = new_orders if deal_result else []
        
        # 12. Extract errors from orders
        all_errors = [error for order in orders for error in order.errors]
        
        # 13. Categorize orders by status
        active_ids = [order.order_id for order in orders if order.status == OrderStatus.ACTIVE]
        executed_ids = [order.order_id for order in orders if order.status == OrderStatus.EXECUTED]
        canceled_ids = canceled_order_ids
        error_ids = [order.order_id for order in orders if order.status == OrderStatus.ERROR]
        
        # 14. Log errors if any
        if all_errors:
            self._log_result_errors(all_errors, "modify_deal")
        
        # 15. Get deal_id and volume from deal
        deal_id_result = deal_result.deal_id if deal_result else deal_id
        volume = deal_result.quantity if deal_result else deal.quantity
        
        return OrderOperationResult(
            orders=orders,
            error_messages=all_errors,
            active=active_ids,
            executed=executed_ids,
            canceled=canceled_ids,
            error=error_ids,
            deal_id=deal_id_result,
            volume=volume
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

    