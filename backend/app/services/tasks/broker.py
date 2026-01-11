"""
Generic broker classes for handling trading operations.
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Dict, Tuple, Set, TYPE_CHECKING
import math
import numpy as np
from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.services.tasks.tasks import Task

logger = get_logger(__name__)


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
    """
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trade_id: int = Field(gt=0)
    deal_id: int = 0  # Will be set when trade is added to deal
    order_id: int
    time: np.datetime64
    side: OrderSide
    price: PRICE_TYPE
    quantity: VOLUME_TYPE
    fee: PRICE_TYPE
    sum: PRICE_TYPE


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
    
    The `fraction` field is used for stop loss and take profit orders to specify what fraction
    of the position should be closed when the order executes. For entry orders, this field is None.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    order_id: int = Field(description="Order ID (assigned when order is added to orders list)")
    deal_id: int = 0  # Deal ID (0 means no deal)
    order_type: OrderType  # Type of order: limit or stop (market orders are not stored as Order objects)
    create_time: np.datetime64
    modify_time: np.datetime64
    side: OrderSide
    price: Optional[PRICE_TYPE] = None
    trigger_price: Optional[PRICE_TYPE] = None
    volume: VOLUME_TYPE
    filled_volume: VOLUME_TYPE = 0.0
    status: OrderStatus = OrderStatus.NEW
    order_group: OrderGroup = OrderGroup.NONE  # Order group: 0 - none, 1 - stop loss, 2 - take profit
    fraction: Optional[float] = None  # Fraction of position to close (for stop loss and take profit orders)
    errors: List[str] = Field(default_factory=list)  # List of validation/execution errors
    
    @model_validator(mode='after')
    def validate_order(self):
        """Validate order fields.
        
        - order_id must be greater than 0 if order is not in NEW or ERROR status.
        - fraction must be set (not None) for orders with order_group != NONE.
        """
        # Validate order_id
        if self.order_id <= 0 and self.status not in (OrderStatus.NEW, OrderStatus.ERROR):
            raise ValueError(f"order_id must be greater than 0 for orders with status {self.status}")
        
        # Validate fraction for exit orders
        if self.order_group != OrderGroup.NONE and self.fraction is None:
            raise ValueError(f"fraction must be set for orders with order_group={self.order_group}")

        if self.volume < 0:
            raise ValueError(f"volume must be greater than or equal to 0, got {self.volume}")
        
        return self


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
    
    # Automatic deal flag (True for deals created via Strategy.buy/sell, False for buy_sltp/sell_sltp)
    auto: bool = False
    
    # Initial entry volume (sum of all entry order volumes) - set for deals created via buy_sltp/sell_sltp
    # Used for calculating stop loss and take profit order target volumes
    # Defaults to 0.0 for automatic deals (created via regular buy/sell methods)
    enter_volume: VOLUME_TYPE = 0.0

    # Internal accumulators for efficient incremental updates
    buy_quantity: VOLUME_TYPE = 0.0
    buy_cost: PRICE_TYPE = 0.0
    sell_quantity: VOLUME_TYPE = 0.0
    sell_proceeds: PRICE_TYPE = 0.0

    def add_trade(self, trade: Trade) -> None:
        """
        Add trade to the deal and update aggregates incrementally.

        - Sets trade.deal_id to this deal_id.
        - Sets deal type (long/short) based on first trade if not set.
        - Updates quantity, avg_buy_price, avg_sell_price, fee and profit.
        """

        assert trade.quantity > 0, f"Trade quantity must be greater than 0, got {trade.quantity}"
        
        trade.deal_id = self.deal_id
        self.trades.append(trade)

        # Set deal type based on first trade
        if self.type is None:
            if trade.side == OrderSide.BUY:
                self.type = DealType.LONG
            else:
                self.type = DealType.SHORT

        self.fee += trade.fee

        if trade.side == OrderSide.BUY:
            self.buy_quantity += trade.quantity
            self.buy_cost += trade.sum
            self.quantity += trade.quantity
        else:
            self.sell_quantity += trade.quantity
            self.sell_proceeds += trade.sum
            self.quantity -= trade.quantity

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
        

    def check_closed(self) -> bool:
        """
        Check if deal should be closed and set is_closed to True if conditions are met.
        
        Deal is closed if quantity == 0 and there are no active entry orders.
        This method does not check is_closed status itself - it should be called
        only when is_closed is False.
        
        When closing, sets close_type based on the last trade's order:
        - If last trade has order_id != 0, finds the order and copies its order_group to close_type
        - If order_id == 0 or order not found, sets close_type = OrderGroup.NONE
        
        Returns:
            True if deal was just closed (status changed from open to closed), False otherwise
        """
        if self.quantity == 0:
            # Check if there are any active entry orders (OrderGroup.NONE and status ACTIVE)
            has_active_entry_orders = any(
                order.order_group == OrderGroup.NONE and order.status == OrderStatus.ACTIVE
                for order in self.orders
            )
            if not has_active_entry_orders:
                was_closed = self.is_closed
                self.is_closed = True
                
                # Set close_type based on last trade's order
                if self.trades:
                    # Find last trade by time (and by trade_id if times are equal)
                    last_trade = max(self.trades, key=lambda t: (t.time, t.trade_id))
                    
                    if last_trade.order_id != 0:
                        # Find order by order_id
                        order = next((o for o in self.orders if o.order_id == last_trade.order_id), None)
                        if order and order.order_group != OrderGroup.NONE:
                            self.close_type = order.order_group
                        else:
                            self.close_type = OrderGroup.NONE
                    else:
                        self.close_type = OrderGroup.NONE
                else:
                    self.close_type = OrderGroup.NONE
                
                # Return True if status changed from open to closed
                return not was_closed
        return False

    def get_unrealized_profit(self, current_price: PRICE_TYPE) -> Optional[PRICE_TYPE]:
        """
        Calculate unrealized profit for an open position at the given price.

        For closed positions, the result matches the realized profit.
        """
        # Value of current open position at market price
        current_value = self.quantity * current_price

        # Hypothetical total PnL if we closed the position now:
        # (all sells done + value of remaining position) - all buys - all fees
        return self.sell_proceeds + current_value - self.buy_cost - self.fee


class TradingStats(BaseModel):
    """
    Trading statistics.
    
    Tracks:
    - Equity in symbol and USD (similar to broker mechanism)
    - Trade counts (total, buys, sells)
    - Maximum market volume (max absolute equity_symbol)
    - Total fees
    - Deal counts (total, long, short)
    """
    
    # Initial equity in USD
    initial_equity_usd: PRICE_TYPE = 0.0
    
    # Equity tracking (same mechanism as broker) - internal fields
    _equity_symbol: VOLUME_TYPE = 0.0
    _equity_usd: PRICE_TYPE = 0.0
    
    # Trade statistics
    total_trades: int = 0
    buy_trades: int = 0
    sell_trades: int = 0
    
    # Maximum market volume (max absolute value of equity_symbol)
    max_market_volume: VOLUME_TYPE = 0.0
    
    # Total fees
    total_fees: PRICE_TYPE = 0.0
    
    # Profit tracking
    profit: PRICE_TYPE = 0.0  # Current profit: _equity_symbol * price + _equity_usd - initial_equity_usd
    _profit_max: PRICE_TYPE = 0.0  # Maximum profit value (internal)
    drawdown_max: PRICE_TYPE = 0.0  # Maximum drawdown (_profit_max - profit)
    
    # Deal statistics
    total_deals: int = 0
    long_deals: int = 0
    short_deals: int = 0
    profit_deals: int = 0  # Number of profitable deals
    loss_deals: int = 0  # Number of losing deals
    
    # Calculated statistics (set by calc_stat method)
    profit_per_deal: Optional[PRICE_TYPE] = None  # Profit per deal (profit / total_deals)
    profit_gross: Optional[PRICE_TYPE] = None  # Gross profit (profit + total_fees)
    
    # Average profit/loss per deal type (calculated in add_deal)
    avg_profit_per_winning_deal: Optional[PRICE_TYPE] = None  # Average profit per winning deal
    avg_loss_per_losing_deal: Optional[PRICE_TYPE] = None  # Average loss per losing deal
    
    # Profit by deal type (calculated in add_deal)
    profit_long: PRICE_TYPE = 0.0  # Profit from long deals
    profit_short: PRICE_TYPE = 0.0  # Profit from short deals
    
    # Internal accumulators for average profit/loss calculation
    total_profit_winning: PRICE_TYPE = 0.0  # Sum of profits from winning deals
    total_loss_losing: PRICE_TYPE = 0.0  # Sum of losses from losing deals
    
    # Backtesting parameters (set from task)
    fee_taker: PRICE_TYPE = 0.0  # Taker fee rate (as fraction, e.g., 0.001 for 0.1%)
    fee_maker: PRICE_TYPE = 0.0  # Maker fee rate (as fraction, e.g., 0.001 for 0.1%)
    slippage: PRICE_TYPE = 0.0  # Slippage value (absolute, in currency, e.g., 0.001 USD)
    price_step: PRICE_TYPE = 0.0  # Price step (minimum step size, e.g., 0.1, 0.001)
    source: str  # Data source (exchange name)
    symbol: str  # Trading symbol
    timeframe: str  # Timeframe
    date_start: str  # Start date (ISO format)
    date_end: str  # End date (ISO format)
    
    def add_trade(self, trade: Trade) -> None:
        """
        Add trade to statistics.
        
        Updates equity, trade counts, max market volume, and fees.
        
        Args:
            trade: Trade to add
        """
        self.total_trades += 1
        
        # Update trade counts by side
        if trade.side == OrderSide.BUY:
            self.buy_trades += 1
            # Buy: increase equity_symbol, decrease equity_usd
            self._equity_symbol += trade.quantity
            self._equity_usd -= trade.sum + trade.fee
        else:
            self.sell_trades += 1
            # Sell: decrease equity_symbol, increase equity_usd
            self._equity_symbol -= trade.quantity
            self._equity_usd += trade.sum - trade.fee
        
        # Update max market volume (absolute value)
        abs_equity_symbol = abs(self._equity_symbol)
        if abs_equity_symbol > self.max_market_volume:
            self.max_market_volume = abs_equity_symbol
        
        # Accumulate fees
        self.total_fees += trade.fee
        
        # Calculate current profit: _equity_symbol * price + _equity_usd - initial_equity_usd
        # Use trade price as current market price
        current_profit = self._equity_symbol * trade.price + self._equity_usd - self.initial_equity_usd
        self.profit = current_profit
        
        # Update maximum profit
        if current_profit > self._profit_max:
            self._profit_max = current_profit
        
        # Calculate drawdown: _profit_max - profit
        current_drawdown = self._profit_max - current_profit
        if current_drawdown > self.drawdown_max:
            self.drawdown_max = current_drawdown
    
    def add_deal(self, deal: Deal) -> None:
        """
        Add deal to statistics.
        
        Counts deals (total, long, short) and calculates profit by deal type.
        Only adds deals that have at least one trade (non-empty deals).
        
        Args:
            deal: Deal to add
        """
        # Skip empty deals (deals without any trades)
        if len(deal.trades) == 0:
            return
        
        self.total_deals += 1
        
        if deal.type == DealType.LONG:
            self.long_deals += 1
            # Add profit from closed long deal
            if deal.is_closed and deal.profit is not None:
                self.profit_long += deal.profit
                # Count profitable/losing deals and accumulate for averages
                if deal.profit > 0:
                    self.profit_deals += 1
                    self.total_profit_winning += deal.profit
                    # Recalculate average profit per winning deal
                    if self.profit_deals > 0:
                        self.avg_profit_per_winning_deal = self.total_profit_winning / self.profit_deals
                    else:
                        self.avg_profit_per_winning_deal = None
                elif deal.profit < 0:
                    self.loss_deals += 1
                    self.total_loss_losing += deal.profit  # deal.profit is negative, so this accumulates losses
                    # Recalculate average loss per losing deal
                    if self.loss_deals > 0:
                        self.avg_loss_per_losing_deal = self.total_loss_losing / self.loss_deals
                    else:
                        self.avg_loss_per_losing_deal = None
        elif deal.type == DealType.SHORT:
            self.short_deals += 1
            # Add profit from closed short deal
            if deal.is_closed and deal.profit is not None:
                self.profit_short += deal.profit
                # Count profitable/losing deals and accumulate for averages
                if deal.profit > 0:
                    self.profit_deals += 1
                    self.total_profit_winning += deal.profit
                    # Recalculate average profit per winning deal
                    if self.profit_deals > 0:
                        self.avg_profit_per_winning_deal = self.total_profit_winning / self.profit_deals
                    else:
                        self.avg_profit_per_winning_deal = None
                elif deal.profit < 0:
                    self.loss_deals += 1
                    self.total_loss_losing += deal.profit  # deal.profit is negative, so this accumulates losses
                    # Recalculate average loss per losing deal
                    if self.loss_deals > 0:
                        self.avg_loss_per_losing_deal = self.total_loss_losing / self.loss_deals
                    else:
                        self.avg_loss_per_losing_deal = None
    
    def calc_stat(self) -> None:
        """
        Calculate additional statistics.
        
        Calculates:
        - profit_per_deal: profit / total_deals
        - profit_gross: profit + total_fees
        """
        # Profit per deal
        if self.total_deals > 0:
            self.profit_per_deal = self.profit / self.total_deals
        else:
            self.profit_per_deal = None
        
        # Gross profit (profit + fees)
        self.profit_gross = self.profit + self.total_fees


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
        
        self.task: Task = task
        self.deals: Optional[List[Deal]] = None
        self.trades: List[Trade] = []
        self.result_id = result_id
        self.last_auto_deal_id: Optional[int] = None
        self.active_deals: Set[int] = set()  # Set of deal_id for active (open) deals
        
        # Precision for amount and price
        self.precision_amount: float = task.precision_amount
        self.precision_price: float = task.precision_price
    
    # ------------------------------------------------------------------
    # Precision-based rounding helpers
    # ------------------------------------------------------------------
    
    def round_to_precision(self, value: float, precision: float) -> float:
        """
        Round value to nearest multiple of precision.
        
        Args:
            value: Value to round
            precision: Precision step (e.g., 0.01, 0.001)
        
        Returns:
            Rounded value
        """
        return round(value / precision) * precision
    
    def floor_to_precision(self, value: float, precision: float) -> float:
        """
        Round value down to nearest multiple of precision.
        
        Args:
            value: Value to round down
            precision: Precision step (e.g., 0.01, 0.001)
        
        Returns:
            Rounded down value
        """
        return math.floor(value / precision) * precision

    # ------------------------------------------------------------------
    # Price comparison helpers (with precision tolerance)
    # ------------------------------------------------------------------
    def _price_eps(self) -> float:
        """
        Get epsilon for price comparisons based on precision_price.
        We treat prices as equal if they differ by no more than precision_price / 10.
        """
        return self.precision_price / 10.0

    def eq(self, a: float, b: float) -> bool:
        """Return True if prices a and b are equal within price epsilon."""
        return abs(a - b) <= self._price_eps()

    def gt(self, a: float, b: float) -> bool:
        """Return True if price a is greater than price b beyond price epsilon."""
        return (a - b) > self._price_eps()

    def lt(self, a: float, b: float) -> bool:
        """Return True if price a is less than price b beyond price epsilon."""
        return (b - a) > self._price_eps()

    def gteq(self, a: float, b: float) -> bool:
        """Return True if price a is greater than or equal to price b within price epsilon."""
        return self.gt(a, b) or self.eq(a, b)

    def lteq(self, a: float, b: float) -> bool:
        """Return True if price a is less than or equal to price b within price epsilon."""
        return self.lt(a, b) or self.eq(a, b)

    @abstractmethod
    def buy(self, quantity: VOLUME_TYPE, deal_id: Optional[int] = None):
        """
        Execute buy operation.

        Args:
            quantity: Quantity to buy
        """

        raise NotImplementedError

    @abstractmethod
    def sell(self, quantity: VOLUME_TYPE, deal_id: Optional[int] = None):
        """
        Execute sell operation.

        Args:
            quantity: Quantity to sell
        """

        raise NotImplementedError

    def _cancel_deal_orders(
        self,
        deal: Deal,
        current_time: np.datetime64,
        cancel_entry: bool = True,
        cancel_stop_loss: bool = True,
        cancel_take_profit: bool = True
    ) -> List[Order]:
        """
        Cancel active and new orders in a deal, optionally filtered by order group.
        
        Iterates through all orders in the deal and cancels those with
        status ACTIVE or NEW that match the specified order groups.
        
        Args:
            deal: Deal whose orders should be canceled
            current_time: Current time for order modification
            cancel_entry: If True, cancel entry orders (OrderGroup.NONE). Default: True.
            cancel_stop_loss: If True, cancel stop loss orders (OrderGroup.STOP_LOSS). Default: True.
            cancel_take_profit: If True, cancel take profit orders (OrderGroup.TAKE_PROFIT). Default: True.
        
        Returns:
            List of orders that were canceled
        """
        canceled_orders = []
        for order in deal.orders:
            if order.status not in [OrderStatus.ACTIVE, OrderStatus.NEW]:
                continue
            
            # Check if this order group should be canceled
            should_cancel = False
            if order.order_group == OrderGroup.NONE and cancel_entry:
                should_cancel = True
            elif order.order_group == OrderGroup.STOP_LOSS and cancel_stop_loss:
                should_cancel = True
            elif order.order_group == OrderGroup.TAKE_PROFIT and cancel_take_profit:
                should_cancel = True
            
            if should_cancel:
                self._cancel_order(order, current_time)
                canceled_orders.append(order)
        
        return canceled_orders
    
    def _cancel_order(self, order: Order, current_time: np.datetime64) -> None:
        """
        Cancel a single order.
        
        Sets order status to CANCELED, updates modify_time, and calls
        implementation-specific cancellation logic via ex_cancel_order.
        
        Args:
            order: Order to cancel
            current_time: Current time for order modification
        """
        # Update order status and modify time
        order.status = OrderStatus.CANCELED
        order.modify_time = current_time
        
        # Call implementation-specific cancellation logic
        self.ex_cancel_order(order)
    
    @abstractmethod
    def ex_cancel_order(self, order: Order) -> None:
        """
        Implementation-specific order cancellation logic.
        
        Called after order status is set to CANCELED and modify_time is updated.
        This method should handle any implementation-specific cleanup, such as
        removing the order from internal data structures.
        
        Args:
            order: Order that was canceled
        """
        raise NotImplementedError

    @abstractmethod
    def ex_current_time(self) -> np.datetime64:
        """
        Get current time for order modification.
        
        Returns:
            Current time as np.datetime64
        """
        raise NotImplementedError

    def reset(self, initial_equity_usd: PRICE_TYPE = 0.0, *, task: 'Task') -> None:
        """
        Reset broker state. Initialize deals list and trades list.
        
        Args:
            initial_equity_usd: Initial capital in USD for statistics
            task: Task instance to populate backtesting parameters in stats
        """
        self.deals = []
        self.trades = []
        self.active_deals = set()  # Reset active deals set
        
        # Get fee and slippage values (with defaults if not set)
        fee_taker = task.fee_taker if task.fee_taker > 0 else 0.001
        fee_maker = task.fee_maker if task.fee_maker > 0 else 0.001
        slippage = (task.slippage_in_steps * task.price_step) if task.price_step > 0 else 0.0
        
        # Create stats with all backtesting parameters from task
        self.stats = TradingStats(
            initial_equity_usd=initial_equity_usd,
            fee_taker=fee_taker,
            fee_maker=fee_maker,
            slippage=slippage,
            price_step=task.price_step,
            source=task.source,
            symbol=task.symbol,
            timeframe=task.timeframe,
            date_start=task.dateStart,
            date_end=task.dateEnd
        )
        
        self.last_auto_deal_id = None

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
        
        # Check 3: All trade_id in ascending order by time (only for automatic deals)
        auto_deals = [deal for deal in self.deals if deal.auto]
        if auto_deals:
            auto_trades = [trade for deal in auto_deals for trade in deal.trades]
            if auto_trades:
                auto_trade_ids = [trade.trade_id for trade in auto_trades]
                auto_trades_by_time = sorted(auto_trades, key=lambda t: t.time)
                if auto_trade_ids != [t.trade_id for t in auto_trades_by_time]:
                    errors.append("trade_id are not in ascending order by time in automatic deals")
        
        # Check 4: All deals are closed
        if unclosed := [deal.deal_id for deal in self.deals if not deal.is_closed]:
            errors.append(f"Unclosed deals found: {unclosed}")
        
        # Check 5: Recalculate and compare average prices and profit
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
            
            # Compare with stored values using tolerance for floating point
            # Use 1/10 of precision as tolerance: precision_amount for volumes, precision_price for prices/sums
            volume_tolerance = self.precision_amount / 10.0
            price_tolerance = self._price_eps()  # precision_price / 10.0
            
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
            
            # Compare prices with tolerance for floating point
            if recalc_avg_buy_price is not None and deal.avg_buy_price is not None:
                if abs(recalc_avg_buy_price - deal.avg_buy_price) > price_tolerance:
                    errors.append(f"Deal {deal.deal_id}: avg_buy_price mismatch (stored={deal.avg_buy_price}, recalc={recalc_avg_buy_price})")
            elif recalc_avg_buy_price != deal.avg_buy_price:
                errors.append(f"Deal {deal.deal_id}: avg_buy_price mismatch (stored={deal.avg_buy_price}, recalc={recalc_avg_buy_price})")
            
            if recalc_avg_sell_price is not None and deal.avg_sell_price is not None:
                if abs(recalc_avg_sell_price - deal.avg_sell_price) > price_tolerance:
                    errors.append(f"Deal {deal.deal_id}: avg_sell_price mismatch (stored={deal.avg_sell_price}, recalc={recalc_avg_sell_price})")
            elif recalc_avg_sell_price != deal.avg_sell_price:
                errors.append(f"Deal {deal.deal_id}: avg_sell_price mismatch (stored={deal.avg_sell_price}, recalc={recalc_avg_sell_price})")
            
            # Compare profit for closed deals
            if deal.is_closed and recalc_profit is not None and deal.profit is not None:
                if abs(recalc_profit - deal.profit) > price_tolerance:
                    errors.append(f"Deal {deal.deal_id}: profit mismatch (stored={deal.profit}, recalc={recalc_profit})")
            elif deal.is_closed and recalc_profit != deal.profit:
                errors.append(f"Deal {deal.deal_id}: profit mismatch (stored={deal.profit}, recalc={recalc_profit})")
        
        return errors


    def get_deal_by_id(self, deal_id: int) -> Deal:
        """
        Get deal by deal_id (deal_id = index + 1).
        Raises IndexError if deal with such deal_id does not exist.
        """

        # Convert deal_id to index (deal_id = index + 1, so index = deal_id - 1)
        index = deal_id - 1
        if index < 0 or index >= len(self.deals):
            raise IndexError(f"Deal with deal_id {deal_id} does not exist (len={len(self.deals)})")

        return self.deals[index]

    def create_deal(self) -> int:
        """
        Create a new empty deal for special grouping of trades.
        Returns deal_id of the created deal.
        
        Returns:
            deal_id: Unique deal identifier
        """
        new_deal_id = len(self.deals) + 1
        new_deal = Deal(deal_id=new_deal_id)
        self.deals.append(new_deal)
        return new_deal_id
    
    def get_last_open_auto_deal(self) -> Optional[Deal]:
        """
        Return last not-closed automatic deal or None.
        Automatic deals are tracked via last_auto_deal_id.
        """
        if self.last_auto_deal_id is None:
            return None
        
        try:
            deal = self.get_deal_by_id(self.last_auto_deal_id)
            return None if deal.is_closed else deal
        except IndexError:
            # Deal was removed or doesn't exist
            self.last_auto_deal_id = None
            return None
    
    def check_closed(self, deal: Deal) -> None:
        """
        Check if deal should be closed and update broker state accordingly.
        
        Calls deal.check_closed() to check and update deal status.
        If deal was just closed, updates active_deals, registers deal in statistics,
        and clears last_auto_deal_id if needed.
        If deal is open, ensures it's in active_deals.
        
        Args:
            deal: Deal to check
        """
        # Check if deal should be closed (returns True if status changed from open to closed)
        was_just_closed = deal.check_closed()
        
        if was_just_closed:
            assert deal.is_closed, f"Deal {deal.deal_id} is not closed after check_closed()"
            self.active_deals.discard(deal.deal_id)
            self._cancel_deal_orders(deal, self.ex_current_time())
            self.stats.add_deal(deal)
            if deal.deal_id == self.last_auto_deal_id:
                self.last_auto_deal_id = None
        elif not deal.is_closed:
            self.active_deals.add(deal.deal_id)
    
    def _add_trade_to_deal(self, deal: Deal, trade: Trade) -> None:
        """
        Add trade to deal and update statistics.
        
        This is the only method that should be used to add trades to deals.
        It handles:
        - Adding trade to deal
        - Updating trade statistics
        - Checking if deal should be closed and updating broker state
        
        Args:
            deal: Deal to add trade to
            trade: Trade to add
        """
        # Add trade to deal
        deal.add_trade(trade)
        
        # Update trade statistics
        self.stats.add_trade(trade)
        
        # Check if deal should be closed and update broker state
        self.check_closed(deal)

    def reg_buy(
        self,
        quantity: VOLUME_TYPE,
        fee: PRICE_TYPE,
        price: PRICE_TYPE,
        time: np.datetime64,
        deal_id: Optional[int] = None,
        order_id: Optional[int] = None,
    ) -> Tuple[List[int], List[int]]:
        """
        Register buy trade in deals structure.

        1) If deal_id is specified — just add trade to this deal.
        2) If deal_id is None:
           - Take last open deal (create new if none or last is closed).
           - If adding trade doesn't flip position side — just add it.
           - If flip would occur — split trade:
                * part closes current deal;
                * remainder opens a new deal with same side.

        Args:
            quantity: Quantity to buy
            fee: Fee for this trade
            price: Price for this trade
            deal_id: Optional deal index to register trade in
            order_id: Optional order ID that triggered this trade
        
        Returns:
            Tuple of (trades: List[int], deals: List[int]) containing IDs
        """
        trade = self.create_trade(OrderSide.BUY, quantity, price=price, fee=fee, time=time, order_id=order_id)
        result = self.register_trade(trade, deal_id)
        return (result['trades'], result['deals'])

    def reg_sell(
        self,
        quantity: VOLUME_TYPE,
        fee: PRICE_TYPE,
        price: PRICE_TYPE,
        time: np.datetime64,
        deal_id: Optional[int] = None,
        order_id: Optional[int] = None,
    ) -> Tuple[List[int], List[int]]:
        """
        Register sell trade in deals structure.

        See reg_buy() for detailed behaviour description.

        Args:
            quantity: Quantity to sell
            fee: Fee for this trade
            price: Price for this trade
            deal_id: Optional deal index to register trade in
            order_id: Optional order ID that triggered this trade
        
        Returns:
            Tuple of (trades: List[int], deals: List[int]) containing IDs
        """
        trade = self.create_trade(OrderSide.SELL, quantity, price=price, fee=fee, time=time, order_id=order_id)
        result = self.register_trade(trade, deal_id)
        return (result['trades'], result['deals'])

    def create_trade(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: PRICE_TYPE,
        fee: PRICE_TYPE,
        time: np.datetime64,
        order_id: Optional[int] = None,
    ) -> Trade:
        """
        Create Trade object from quantity, price, fee and time.
        Assigns trade_id based on trades list size and adds trade to the list.
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Trade quantity
            price: Trade price
            fee: Trade fee
            time: Trade time
            order_id: Optional order ID that triggered this trade. If None, defaults to 0 (market order).
        """
        trade_id = len(self.trades) + 1
        trade_amount = quantity * price

        trade = Trade(
            trade_id=trade_id,
            deal_id=0,  # Will be set by deal
            order_id=order_id if order_id is not None else 0,
            time=time,
            side=side,
            price=price,
            quantity=quantity,
            fee=fee,
            sum=trade_amount
        )
        
        self.trades.append(trade)
        return trade

    def _create_auto_deal(self) -> Deal:
        """
        Create a new automatic deal and update last_auto_deal_id.
        
        Returns:
            Newly created Deal instance with auto=True
        """
        new_deal_id = len(self.deals) + 1
        new_deal = Deal(deal_id=new_deal_id, auto=True)
        self.deals.append(new_deal)
        self.last_auto_deal_id = new_deal_id
        return new_deal

    def register_trade(self, trade: Trade, deal_id: Optional[int]) -> Dict[str, List[int]]:
        """
        Core logic for registering trade in deals with flip handling.
        
        Returns:
            Dictionary with 'trades' and 'deals' lists containing IDs of created/affected trades and deals
        """
        # Explicit deal_id: just add to that deal, no flip-logic
        if deal_id > 0:
            deal = self.get_deal_by_id(deal_id)
            self._add_trade_to_deal(deal, trade)
            return {
                'trades': [trade.trade_id],
                'deals': [deal.deal_id]
            }

        # If there are no deals at all – create first one and put whole trade there
        if not self.deals:
            new_deal = self._create_auto_deal()
            self._add_trade_to_deal(new_deal, trade)
            return {
                'trades': [trade.trade_id],
                'deals': [new_deal.deal_id]
            }

        last_deal = self.get_last_open_auto_deal()

        # If last automatic deal is closed – create a new one and put whole trade there
        if last_deal is None:
            new_deal = self._create_auto_deal()
            self._add_trade_to_deal(new_deal, trade)
            return {
                'trades': [trade.trade_id],
                'deals': [new_deal.deal_id]
            }

        # There is an open automatic deal; check if trade will flip position or not
        current_qty = last_deal.quantity
        trade_qty = trade.quantity

        if trade.side == OrderSide.BUY:
            new_qty = current_qty + trade_qty
        else:
            new_qty = current_qty - trade_qty

        # If no flip (including full close to 0) – just add trade
        if current_qty == 0 or new_qty == 0 or (current_qty > 0 and new_qty > 0) or (current_qty < 0 and new_qty < 0):
            self._add_trade_to_deal(last_deal, trade)
            return {
                'trades': [trade.trade_id],
                'deals': [last_deal.deal_id]
            }

        # Flip: split trade into closing part and opening part of new deal
        # Remove original trade from list (it will be replaced by two split trades)
        # Find and remove original trade by trade_id
        for i, t in enumerate(self.trades):
            if t.trade_id == trade.trade_id:
                self.trades.pop(i)
                break
        
        # Determine volume needed to fully close current position
        close_volume = abs(current_qty)
        total_volume = trade_qty

        # Remaining volume opens new deal
        remainder_quantity = total_volume - close_volume

        # Trade for closing current deal
        close_ratio = close_volume / trade.quantity
        closing_trade_id = len(self.trades) + 1
        closing_trade = trade.model_copy(
            update={
                "trade_id": closing_trade_id,
                "quantity": close_volume,
                "fee": trade.fee * close_ratio,
                "sum": trade.price * close_volume,
            }
        )
        self.trades.append(closing_trade)
        self._add_trade_to_deal(last_deal, closing_trade)

        # Remaining volume opens new automatic deal with same side
        new_deal = self._create_auto_deal()

        remainder_ratio = remainder_quantity / trade.quantity
        opening_trade_id = len(self.trades) + 1
        opening_trade = trade.model_copy(
            update={
                "trade_id": opening_trade_id,
                "quantity": remainder_quantity,
                "fee": trade.fee * remainder_ratio,
                "sum": trade.price * remainder_quantity,
            }
        )
        self.trades.append(opening_trade)
        self._add_trade_to_deal(new_deal, opening_trade)
        
        # Return both trades and both deals
        return {
            'trades': [closing_trade.trade_id, opening_trade.trade_id],
            'deals': [last_deal.deal_id, new_deal.deal_id]
        }
