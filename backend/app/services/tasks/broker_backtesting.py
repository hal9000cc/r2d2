from typing import List, Optional, Dict, Any, Tuple, Callable
import numpy as np

from app.services.tasks.broker import Broker, Order, OrderStatus, OrderType, OrderSide, BarStatus
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.datetime_utils import parse_utc_datetime, parse_utc_datetime64
from app.core.logger import get_logger
from app.services.tasks.tasks import Task

logger = get_logger(__name__)


class OrderExchange:
    """
    Represents an order on the exchange (simulated).
    """
    __slots__ = ('exchange_order_id', 'side', 'order_type', 'amount', 'price')

    def __init__(
        self,
        exchange_order_id: int,
        side: OrderSide,
        order_type: OrderType,
        amount: float,
        price: Optional[float] = None
    ):
        self.exchange_order_id = exchange_order_id
        self.side = side
        self.order_type = order_type
        self.amount = amount
        self.price = price


class BrokerBacktesting(Broker):
    """
    Backtesting broker implementation.
    
    Inherits from Broker and implements abstract methods for backtesting scenarios.
    """
    
    def __init__(
        self, 
        task: Task, 
        result_id: str,
        callbacks_dict: Dict[str, Callable],
        results_save_period: float = TRADE_RESULTS_SAVE_PERIOD
    ):
        """
        Initialize backtesting broker.
        
        Args:
            task: Task instance (contains fee_taker, fee_maker, price_step, precision_amount, precision_price, slippage_in_steps)
            result_id: Unique ID for this backtesting run
            callbacks_dict: Dictionary with callback functions:
                - 'on_start': Callable(parameters: Dict[str, Any])
                - 'on_bar': Callable(price, current_time, time, open, high, low, close, volume, equity_usd, equity_symbol)
                - 'on_finish': Callable with no arguments
            results_save_period: Period for saving results in seconds (default: TRADE_RESULTS_SAVE_PERIOD)
        """
        super().__init__(task=task, result_id=result_id, callbacks_dict=callbacks_dict, results_save_period=results_save_period)
        
        # Get fee and slippage from task, with defaults
        self.fee_taker: float = task.fee_taker if task.fee_taker > 0 else 0.001  # Default to 0.1% if not set
        self.fee_maker: float = task.fee_maker if task.fee_maker > 0 else 0.001  # Default to 0.1% if not set
        # Calculate slippage from slippage_in_steps and price_step
        self.slippage: float = (task.slippage_in_steps * task.price_step) if task.price_step > 0 else 0.0
        
        # Progress tracking
        self.date_end: Optional[np.datetime64] = None
        
        # Equity tracking for backtesting
        self.equity_usd: PRICE_TYPE = 0.0
        self.equity_symbol: VOLUME_TYPE = 0.0
        
        # Current bar prices for stop order processing
        self.bar_high: Optional[PRICE_TYPE] = None
        self.bar_low: Optional[PRICE_TYPE] = None
        
    def progress(self) -> float:
        """
        Calculate current progress percentage for backtesting.
        
        Returns:
            float: Progress in range [0.0, 100.0]
        """
        if self.current_time is None or self.date_start is None or self.date_end is None:
            return 0.0
            
        total_delta = self.date_end - self.date_start
        current_delta = self.current_time - self.date_start
        
        if total_delta <= np.timedelta64(0, 'ns'):
            return 100.0
            
        prog = float(current_delta / total_delta * 100.0)
        return round(max(0.0, min(100.0, prog)), 1)

    def exchange_create_order(
        self, 
        symbol: str, 
        order_type: OrderType, 
        side: OrderSide, 
        amount: float, 
        price: Optional[float] = None
    ) -> Dict:
        """
        Create an order (backtesting implementation).
        
        Args:
            symbol: Trading symbol
            order_type: Order type (MARKET, LIMIT, STOP)
            side: Order side (BUY, SELL)
            amount: Order amount
            price: Order price (optional)
        
        Returns:
            Dictionary with order details (simulated exchange response)
        """
        # Generate new exchange order ID
        self._exchange_order_id_counter += 1
        exchange_order_id = self._exchange_order_id_counter
        
        # Create OrderExchange object
        order = OrderExchange(
            exchange_order_id=exchange_order_id,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price
        )
        
        # Add to general list of active exchange orders
        self.exchange_orders[str(exchange_order_id)] = order
        
        # Handle different order types
        if order_type == OrderType.MARKET:
            # Market orders: add to separate list for immediate processing
            self.market_orders.append(order)
            
        elif order_type == OrderType.STOP:
            # Stop orders: register in numpy tracking arrays
            # price parameter acts as trigger price for stop orders
            if price is None:
                raise ValueError(f"Price (trigger price) must be set for STOP order {exchange_order_id}")
                
            if side == OrderSide.SELL:
                # Long stop orders (SELL stop for LONG deals)
                self.long_stop_order_ids = np.append(self.long_stop_order_ids, exchange_order_id)
                self.long_stop_trigger_prices = np.append(self.long_stop_trigger_prices, price)
            else:
                # Short stop orders (BUY stop for SHORT deals)
                self.short_stop_order_ids = np.append(self.short_stop_order_ids, exchange_order_id)
                self.short_stop_trigger_prices = np.append(self.short_stop_trigger_prices, price)
                
        elif order_type == OrderType.LIMIT:
            # Limit orders: register in numpy tracking arrays
            if price is None:
                raise ValueError(f"Price must be set for LIMIT order {exchange_order_id}")
                
            if side == OrderSide.BUY:
                # Long limit orders
                self.long_order_ids = np.append(self.long_order_ids, exchange_order_id)
                self.long_order_prices = np.append(self.long_order_prices, price)
            else:
                # Short limit orders
                self.short_order_ids = np.append(self.short_order_ids, exchange_order_id)
                self.short_order_prices = np.append(self.short_order_prices, price)
        else:
            raise ValueError(f"Invalid order type: {order_type} for order {exchange_order_id}")
        
        # Return simulated exchange response
        return {
            'id': str(exchange_order_id),
            'symbol': symbol,
            'type': order_type.value if hasattr(order_type, 'value') else order_type,
            'side': side.value if hasattr(side, 'value') else side,
            'amount': amount,
            'price': price,
            'status': 'open',
            'info': {}
        }
    
    def exchange_cancel_order(self, exchange_order_id: str, symbol: str) -> Dict:
        """
        Cancel an order by its ID (backtesting implementation).
        
        Args:
            exchange_order_id: Exchange order ID to cancel
            symbol: Trading symbol
            
        Returns:
            Dictionary with cancelled order details
        """
        # Check if order exists
        if exchange_order_id not in self.exchange_orders:
            logger.warning(f"Order {exchange_order_id} not found in active orders for cancellation")
            return {'id': exchange_order_id, 'status': 'closed', 'info': {'note': 'Not found in active orders'}}
            
        order = self.exchange_orders[exchange_order_id]
        # In OrderExchange exchange_order_id is int
        order_id_int = int(exchange_order_id)
        
        # Remove from type-specific structures
        if order.order_type == OrderType.MARKET:
            # Remove from market orders list
            # Since market orders are usually processed immediately, this case is rare but possible
            self.market_orders = [o for o in self.market_orders if o.exchange_order_id != order_id_int]
            
        elif order.order_type == OrderType.STOP:
            # Remove from stop order arrays using vectorized mask
            if order.side == OrderSide.BUY:
                mask = self.long_stop_order_ids != order_id_int
                self.long_stop_order_ids = self.long_stop_order_ids[mask]
                self.long_stop_trigger_prices = self.long_stop_trigger_prices[mask]
            else:
                mask = self.short_stop_order_ids != order_id_int
                self.short_stop_order_ids = self.short_stop_order_ids[mask]
                self.short_stop_trigger_prices = self.short_stop_trigger_prices[mask]
                
        elif order.order_type == OrderType.LIMIT:
            # Remove from limit order arrays using vectorized mask
            if order.side == OrderSide.BUY:
                mask = self.long_order_ids != order_id_int
                self.long_order_ids = self.long_order_ids[mask]
                self.long_order_prices = self.long_order_prices[mask]
            else:
                mask = self.short_order_ids != order_id_int
                self.short_order_ids = self.short_order_ids[mask]
                self.short_order_prices = self.short_order_prices[mask]
        
        # Remove from general dictionary
        del self.exchange_orders[exchange_order_id]
        
        return {
            'id': exchange_order_id,
            'symbol': symbol,
            'type': order.order_type.value if hasattr(order.order_type, 'value') else order.order_type,
            'side': order.side.value if hasattr(order.side, 'value') else order.side,
            'amount': order.amount,
            'price': order.price,
            'status': 'canceled',
            'info': {}
        }

    def exchange_fetch_my_trades(self, symbol: str, since: Optional[int] = None, markets_only: bool = False) -> List[Dict]:
        """
        Fetch executed trades (backtesting implementation).
        
        Args:
            symbol: Trading symbol
            since: Timestamp in ms to fetch trades from (optional)
            markets_only: If True, only process market orders (skip stop and limit order checks)
            
        Returns:
            List of dictionaries with trade details
        """
        # In backtesting, we process orders on demand and return newly executed trades
        # The 'since' parameter is ignored as we always return trades from the current processing step
        return self._backtesting_process_orders(self.price, self.current_time, markets_only=markets_only)

    def _process_market_orders(self, current_price: float, current_time: np.datetime64) -> List[Dict]:
        """Process market orders execution."""
        trades = []
        
        for order in self.market_orders:
            # Generate trade ID
            self._trade_id_counter += 1
            
            # Calculate execution price with slippage
            # For BUY: price + slippage, For SELL: price - slippage
            slippage_mult = 1 if order.side == OrderSide.BUY else -1
            exec_price = current_price + (self.slippage * slippage_mult)
            
            # Calculate fee
            fee = order.amount * exec_price * self.fee_taker
            
            # Create trade record
            trades.append({
                'id': str(self._trade_id_counter),
                'order': str(order.exchange_order_id),
                'timestamp': current_time,
                'price': exec_price,
                'amount': order.amount,
                'fee': fee
            })
            
        # Clear market orders list
        self.market_orders.clear()
        
        return trades

    def _process_stop_orders(self, bar_high: float, bar_low: float, current_time: np.datetime64) -> List[Dict]:
        """Process stop orders execution (vectorized).
        
        Args:
            bar_high: High price of current bar (for SHORT stop orders)
            bar_low: Low price of current bar (for LONG stop orders)
            current_time: Current timestamp
        """
        trades = []
        
        # Long Stop (SELL for LONG deal): bar_low <= trigger_price (use low of bar)
        long_stop_mask = self.long_stop_trigger_prices >= bar_low
        if np.any(long_stop_mask):
            triggered_ids = self.long_stop_order_ids[long_stop_mask]
            triggered_prices = self.long_stop_trigger_prices[long_stop_mask]
            
            for i, order_id_int in enumerate(triggered_ids):
                order_id = str(order_id_int)
                if order_id not in self.exchange_orders:
                    continue
                    
                order = self.exchange_orders[order_id]
                trigger_price = triggered_prices[i]
                
                # Exec price = trigger_price - slippage (for SELL, worst case)
                exec_price = trigger_price - self.slippage
                
                fee = order.amount * exec_price * self.fee_taker
                
                self._trade_id_counter += 1
                trades.append({
                    'id': str(self._trade_id_counter),
                    'order': order_id,
                    'timestamp': current_time,
                    'price': exec_price,
                    'amount': order.amount,
                    'fee': fee
                })
            
            # Remove executed from numpy arrays
            self.long_stop_order_ids = self.long_stop_order_ids[~long_stop_mask]
            self.long_stop_trigger_prices = self.long_stop_trigger_prices[~long_stop_mask]
            
        # Short Stop (BUY for SHORT deal): bar_high >= trigger_price (use high of bar)
        short_stop_mask = self.short_stop_trigger_prices <= bar_high
        if np.any(short_stop_mask):
            triggered_ids = self.short_stop_order_ids[short_stop_mask]
            triggered_prices = self.short_stop_trigger_prices[short_stop_mask]
            
            for i, order_id_int in enumerate(triggered_ids):
                order_id = str(order_id_int)
                if order_id not in self.exchange_orders:
                    continue
                    
                order = self.exchange_orders[order_id]
                trigger_price = triggered_prices[i]
                
                # Exec price = trigger_price + slippage (for BUY, worst case)
                exec_price = trigger_price + self.slippage
                
                fee = order.amount * exec_price * self.fee_taker
                
                self._trade_id_counter += 1
                trades.append({
                    'id': str(self._trade_id_counter),
                    'order': order_id,
                    'timestamp': current_time,
                    'price': exec_price,
                    'amount': order.amount,
                    'fee': fee
                })
            
            # Remove executed from numpy arrays
            self.short_stop_order_ids = self.short_stop_order_ids[~short_stop_mask]
            self.short_stop_trigger_prices = self.short_stop_trigger_prices[~short_stop_mask]
            
        return trades

    def _process_limit_orders(self, bar_high: float, bar_low: float, current_time: np.datetime64) -> List[Dict]:
        """Process limit orders execution (vectorized).
        
        Args:
            bar_high: High price of current bar (for SELL limit orders)
            bar_low: Low price of current bar (for BUY limit orders)
            current_time: Current timestamp
        """
        trades = []
        
        # Long Limit (BUY): bar_low < order_price (No equality, use low of bar)
        long_limit_mask = self.long_order_prices > bar_low
        if np.any(long_limit_mask):
            triggered_ids = self.long_order_ids[long_limit_mask]
            triggered_prices = self.long_order_prices[long_limit_mask]
            
            for i, order_id_int in enumerate(triggered_ids):
                order_id = str(order_id_int)
                if order_id not in self.exchange_orders:
                    continue
                    
                order = self.exchange_orders[order_id]
                limit_price = triggered_prices[i]
                
                # Exec price = limit_price (no slippage for limits)
                exec_price = limit_price
                
                fee = order.amount * exec_price * self.fee_maker
                
                self._trade_id_counter += 1
                trades.append({
                    'id': str(self._trade_id_counter),
                    'order': order_id,
                    'timestamp': current_time,
                    'price': exec_price,
                    'amount': order.amount,
                    'fee': fee
                })
            
            # Remove executed from numpy arrays
            self.long_order_ids = self.long_order_ids[~long_limit_mask]
            self.long_order_prices = self.long_order_prices[~long_limit_mask]
            
        # Short Limit (SELL): bar_high > order_price (No equality, use high of bar)
        short_limit_mask = self.short_order_prices < bar_high
        if np.any(short_limit_mask):
            triggered_ids = self.short_order_ids[short_limit_mask]
            triggered_prices = self.short_order_prices[short_limit_mask]
            
            for i, order_id_int in enumerate(triggered_ids):
                order_id = str(order_id_int)
                if order_id not in self.exchange_orders:
                    continue
                    
                order = self.exchange_orders[order_id]
                limit_price = triggered_prices[i]
                
                # Exec price = limit_price (no slippage for limits)
                exec_price = limit_price
                
                fee = order.amount * exec_price * self.fee_maker
                
                self._trade_id_counter += 1
                trades.append({
                    'id': str(self._trade_id_counter),
                    'order': order_id,
                    'timestamp': current_time,
                    'price': exec_price,
                    'amount': order.amount,
                    'fee': fee
                })
                
            # Remove executed from numpy arrays
            self.short_order_ids = self.short_order_ids[~short_limit_mask]
            self.short_order_prices = self.short_order_prices[~short_limit_mask]
            
        return trades

    def _backtesting_process_orders(self, current_price: float, current_time: np.datetime64, markets_only: bool = False) -> List[Dict]:
        """
        Process orders execution based on current price (matching engine).
        
        Args:
            current_price: Current market price (close of bar)
            current_time: Current timestamp
            markets_only: If True, only process market orders (skip stop and limit order checks)
            
        Returns:
            List of executed trades
        """
        trades = []
        
        # Process market orders (always processed)
        trades.extend(self._process_market_orders(current_price, current_time))
        
        # Process stop and limit orders only if markets_only is False
        if not markets_only:
            # Get bar high and low for stop/limit order processing
            if self.bar_high is None or self.bar_low is None:
                return trades
            
            bar_high = self.bar_high
            bar_low = self.bar_low
            
            trades.extend(self._process_stop_orders(bar_high, bar_low, current_time))
            trades.extend(self._process_limit_orders(bar_high, bar_low, current_time))
        
        # Remove executed orders from exchange_orders dictionary
        for trade in trades:
            order_id = trade['order']
            if order_id in self.exchange_orders:
                del self.exchange_orders[order_id]
                
        return trades
    
    def initialize_run(self) -> None:
        """
        Initialize broker for running strategy (backtesting implementation).
        
        Called at the start of run() method to set up broker state.
        """
        # Parse date range for progress calculation
        try:
            self.date_start = parse_utc_datetime64(self.task.dateStart)
            self.date_end = parse_utc_datetime64(self.task.dateEnd)
        except Exception as e:
            raise RuntimeError(f"Failed to parse dates: {e}")
        
        # Disable wait intervals for backtesting (everything is synchronous)
        self.bar_wait_interval = 0.0
        self.order_wait_interval = 0.0
            
        # Counter for generating unique exchange order IDs
        self._exchange_order_id_counter = 0
        self._trade_id_counter = 0
        
        # List of all active orders on the exchange
        self.exchange_orders: Dict[str, OrderExchange] = {}
        
        # Initialize numpy arrays for fast order lookup
        # Limit orders tracking
        self.long_order_ids = np.array([], dtype=np.int64)
        self.long_order_prices = np.array([], dtype=PRICE_TYPE)
        self.short_order_ids = np.array([], dtype=np.int64)
        self.short_order_prices = np.array([], dtype=PRICE_TYPE)
        
        # Stop orders tracking
        self.long_stop_order_ids = np.array([], dtype=np.int64)
        self.long_stop_trigger_prices = np.array([], dtype=PRICE_TYPE)
        self.short_stop_order_ids = np.array([], dtype=np.int64)
        self.short_stop_trigger_prices = np.array([], dtype=PRICE_TYPE)
        
        # Market orders waiting for execution
        self.market_orders: List[OrderExchange] = []
        
        # Reset equity
        # self.equity_usd = 0.0
        # self.equity_symbol = 0.0

    def initialize_quotes(self, history_size: int, ta_proxies: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initialize quotes data for strategy execution (backtesting implementation).
        
        Args:
            history_size: Number of bars to load for strategy initialization (unused, taken from self.task.history_size)
            ta_proxies: Dictionary of TA proxies (e.g., {'talib': ta_proxy_talib(...)})
                       Should call set_quotes() on each proxy with initial quotes data
        
        Returns:
            Dictionary with quotes data (structure is implementation-specific)
        """
        # Get history_size from task
        history_size = self.task.history_size
        
        # Convert timeframe string to Timeframe object
        try:
            timeframe = Timeframe.cast(self.task.timeframe)
        except Exception as e:
            raise RuntimeError(f"Failed to parse timeframe '{self.task.timeframe}': {e}") from e
        
        # Convert date strings to datetime objects
        try:
            date_start = parse_utc_datetime(self.task.dateStart)
            date_end = parse_utc_datetime(self.task.dateEnd)
        except Exception as e:
            raise RuntimeError(f"Failed to parse dateStart/dateEnd: {e}") from e
        
        # Calculate initial load date: dateStart - (history_size * timeframe.timedelta())
        history_start = date_start - (history_size * timeframe.timedelta())
        
        # Get quotes data from QuotesClient
        client = QuotesClient()
        logger.debug(f"Getting quotes for {self.task.source}:{self.task.symbol}:{self.task.timeframe} from {history_start} to {date_end}")
        quotes_data = client.get_quotes(self.task.source, self.task.symbol, timeframe, history_start, date_end)
        logger.debug(f"Quotes received: {len(quotes_data['time'])} bars")
        
        # Validate that we have quotes data
        if len(quotes_data['time']) == 0:
            raise RuntimeError("No quotes data available for backtesting")
        
        # Call set_quotes() on each TA proxy
        for proxy_name, proxy in ta_proxies.items():
            if hasattr(proxy, 'set_quotes'):
                proxy.set_quotes(quotes_data)
        
        return quotes_data
    
    def fetch_next_bar(
        self, 
        quotes_data: Dict[str, Any], 
        ta_proxies: Dict[str, Any]
    ) -> Tuple[BarStatus, Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.datetime64, PRICE_TYPE]]]:
        """
        Get next bar data for strategy execution (backtesting implementation).
        
        Args:
            quotes_data: Quotes data dictionary (from initialize_quotes)
            ta_proxies: Dictionary of TA proxies (for backtesting, set_quotes() is not called)
        
        Returns:
            Tuple of (status, data_tuple):
            - status: BarStatus (RECEIVED, WAITING, FINISHED)
            - data_tuple: Tuple of (time_array, open_array, high_array, low_array, close_array, volume_array, current_time, current_price) if status is RECEIVED, else None
        """
        
        # Extract arrays from quotes_data
        all_time = quotes_data['time']
        all_close = quotes_data['close']
        
        # Check if we've reached the end of data
        if self.i_time >= len(all_close):
            return (BarStatus.FINISHED, None)
        
        # Get current time and price
        current_time = all_time[self.i_time]
        current_price = all_close[self.i_time]
        
        # Update current bar high and low for stop order processing
        self.bar_high = quotes_data['high'][self.i_time]
        self.bar_low = quotes_data['low'][self.i_time]
        
        # Return slices up to current index (inclusive) and current time/price
        data_tuple = (
            all_time[:self.i_time+1],
            quotes_data['open'][:self.i_time+1],
            quotes_data['high'][:self.i_time+1],
            quotes_data['low'][:self.i_time+1],
            all_close[:self.i_time+1],
            quotes_data['volume'][:self.i_time+1],
            current_time,
            current_price
        )

        self.i_time += 1
        
        return (BarStatus.RECEIVED, data_tuple)
    
