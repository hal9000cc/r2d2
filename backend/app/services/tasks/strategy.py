from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Union, List, Tuple
import numpy as np
import weakref
from app.services.quotes.client import QuotesBackTest
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE, TIME_TYPE
from app.services.tasks.tasks import Task


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class Deal:
    """
    Represents a trading deal with buy/sell mechanics.
    """
    def __init__(self, side: OrderSide, entry_time: np.datetime64, entry_price: PRICE_TYPE, initial_balance: PRICE_TYPE = 0.0):
        self.side = side  # Order side (BUY or SELL)
        self.entry_time = entry_time  # Time when position was opened
        self.exit_time: Optional[np.datetime64] = None  # Time when position was closed (None if still open)
        self.entry_price = entry_price  # Price at which position was opened
        self.exit_price: Optional[PRICE_TYPE] = None  # Price at which position was closed (None if still open)
        self.max_volume: VOLUME_TYPE = 0.0  # Maximum absolute value of symbol_balance
        self.profit: PRICE_TYPE = 0.0  # Total profit/loss from the deal (symbol_balance after closing)
        self.fees: PRICE_TYPE = 0.0  # Total fees paid for the deal
        
        # Internal state
        self.symbol_balance: VOLUME_TYPE = 0.0  # Current symbol balance (can go negative)
        self.balance: PRICE_TYPE = initial_balance  # Current cash balance
    
    def buy(self, volume: VOLUME_TYPE, price: PRICE_TYPE, fee: PRICE_TYPE):
        """
        Execute a buy operation.
        
        Args:
            volume: Volume to buy
            price: Price per unit
            fee: Fee rate (as fraction, e.g., 0.001 for 0.1%)
        """
        fees = volume * price * fee
        self.symbol_balance += volume
        self.balance -= fees + volume * price
        self.fees += fees
        
        # Update max_volume (maximum absolute value of symbol_balance)
        if self.max_volume < abs(self.symbol_balance):
            self.max_volume = abs(self.symbol_balance)
    
    def sell(self, volume: VOLUME_TYPE, price: PRICE_TYPE, fee: PRICE_TYPE):
        """
        Execute a sell operation.
        
        Args:
            volume: Volume to sell
            price: Price per unit
            fee: Fee rate (as fraction, e.g., 0.001 for 0.1%)
        """
        fees = volume * price * fee
        self.symbol_balance -= volume
        self.balance += volume * price - fees
        self.fees += fees
        
        # Update max_volume (maximum absolute value of symbol_balance)
        if self.max_volume < abs(self.symbol_balance):
            self.max_volume = abs(self.symbol_balance)
    
    def close(self, exit_time: np.datetime64, exit_price: PRICE_TYPE, fee: PRICE_TYPE):
        """
        Close the deal by closing the position first.
        
        Args:
            exit_time: Time when position was closed
            exit_price: Price at which position was closed
            fee: Fee rate (as fraction, e.g., 0.001 for 0.1%)
        """
        # Close the position: if in long (symbol_balance > 0), sell; if in short (symbol_balance < 0), buy
        if self.symbol_balance > 0:
            # We are in long position, need to sell
            self.sell(self.symbol_balance, exit_price, fee)
        elif self.symbol_balance < 0:
            # We are in short position, need to buy
            self.buy(abs(self.symbol_balance), exit_price, fee)
        
        self.exit_time = exit_time
        self.exit_price = exit_price
        # Profit is the balance after closing (with fees already accounted for)
        self.profit = self.balance


class Order:
    def __init__(self, strategy: 'Strategy'):
        self.strategy = strategy


class Strategy(ABC):
    def __init__(self, task: Task):
        
        self.task = task

        self.time: Optional[np.ndarray] = None  # dtype: TIME_TYPE
        self.open: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.high: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.low: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.close: Optional[np.ndarray] = None  # dtype: PRICE_TYPE
        self.volume: Optional[np.ndarray] = None  # dtype: VOLUME_TYPE
        
        # self._orders: List[weakref.ref] = []

    @abstractmethod
    def on_bar(self):
        """
        Called when a new bar is received.
        """
        pass

    @abstractmethod
    def order(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        stop_loss: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None,
        take_profit: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None
    ) -> Order:
        """
        Place an order.
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Order quantity (volume)
            price: Limit price. If None, order is placed as market order.
                  If specified, order is placed as limit order, but may be executed
                  at market price if market price is better than the limit price.
            stop_loss: Stop loss price or list of tuples (volume, price) for partial stop loss levels.
                      If a single price is provided, stop loss is set for the entire order quantity.
                      If a list of tuples is provided, each tuple defines a partial stop loss level
                      with specific volume and price.
            take_profit: Take profit price or list of tuples (volume, price) for partial take profit levels.
                        If a single price is provided, take profit is set for the entire order quantity.
                        If a list of tuples is provided, each tuple defines a partial take profit level
                        with specific volume and price.
        
        Returns:
            Order object representing the placed order
        """
        pass
    

class StrategyBacktest(Strategy):
    def __init__(self, task: Task):
        super().__init__(task)
        self.__quotes = QuotesBackTest(task.symbol, task.timeframe, task.dateStart, task.dateEnd, task.source)
        self.fee = 0.001
        self.__reset()

    def __reset(self):

        self.limit_orders = []
        self.limit_orders_ix = np.array([], dtype=np.int32)
        self.limit_orders_price = np.array([], dtype=PRICE_TYPE)
        self.limit_orders_type = np.array([], dtype=np.int8) # 1 - buy, -1 - sell
        self.limit_orders_quantity = np.array([], dtype=VOLUME_TYPE)

        self.deals = []  # List of closed deals only

        self.price = None
        self.current_time = self.__quotes.time.values[0]

        self.global_deal = Deal(
            side=None,
            entry_time=self.current_time,
            entry_price=0.0,
            initial_balance=0.0
        )
        
        # Current deal (None initially, created on first buy/sell)
        self.current_deal: Optional[Deal] = None

    def __buy(self, volume: VOLUME_TYPE):
        """
        Execute a buy operation on both current and global deals.
        """
        # Create current deal if it doesn't exist
        if self.current_deal is None:
            self.current_deal = Deal(
                side=OrderSide.BUY,
                entry_time=self.current_time,
                entry_price=self.price,
                initial_balance=0.0
            )
        
        # Execute buy on both deals
        self.current_deal.buy(volume, self.price, self.fee)
        self.global_deal.buy(volume, self.price, self.fee)
        
        # Check if current deal is closed (symbol_balance == 0)
        if self.current_deal.symbol_balance == 0:
            self.current_deal.close(self.current_time, self.price, self.fee)
            self.deals.append(self.current_deal)
            self.current_deal = None

    def __sell(self, volume: VOLUME_TYPE):
        """
        Execute a sell operation on both current and global deals.
        """
        # Create current deal if it doesn't exist
        if self.current_deal is None:
            self.current_deal = Deal(
                side=OrderSide.SELL,
                entry_time=self.current_time,
                entry_price=self.price,
                initial_balance=0.0
            )
        
        # Execute sell on both deals
        self.current_deal.sell(volume, self.price, self.fee)
        self.global_deal.sell(volume, self.price, self.fee)
        
        # Check if current deal is closed (symbol_balance == 0)
        if self.current_deal.symbol_balance == 0:
            self.current_deal.close(self.current_time, self.price, self.fee)
            self.deals.append(self.current_deal)
            self.current_deal = None

    def order(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        stop_loss: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None,
        take_profit: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None
    ) -> None:
        """
        Place an order. Currently only market orders are supported.
        
        Args:
            side: Order side (BUY or SELL)
            quantity: Order quantity (volume)
            price: Limit price. If None, order is placed as market order.
                  If specified, raises NotImplementedError (not realized).
            stop_loss: Stop loss price. Raises NotImplementedError (not realized).
            take_profit: Take profit price. Raises NotImplementedError (not realized).
        
        Returns:
            Order object representing the placed order
        """
        # Check if limit order or stop loss/take profit are specified
        if price is not None or stop_loss is not None or take_profit is not None:
            raise NotImplementedError("not realized")
        
        # Market order: execute immediately
        if side == OrderSide.BUY:
            self.__buy(quantity)
        elif side == OrderSide.SELL:
            self.__sell(quantity)
        else:
            raise ValueError(f"Unknown order side: {side}")
        

    def run(self):
        """
        Run backtest strategy.
        Loads market data and iterates through bars, calling on_bar for each bar.
        """

        all_time = self.__quotes.time.values
        all_open = self.__quotes.open.values
        all_high = self.__quotes.high.values
        all_low = self.__quotes.low.values
        all_close = self.__quotes.close.values
        all_volume = self.__quotes.volume.values
        
        for i in range(len(all_close)):
            self.time = all_time[:i+1]
            self.open = all_open[:i+1]
            self.high = all_high[:i+1]
            self.low = all_low[:i+1]
            self.close = all_close[:i+1]
            self.volume = all_volume[:i+1]
            
            # Set current time and price for deal operations
            self.current_time = all_time[i]
            self.price = all_close[i]
            
            self.on_bar()

        if self.current_deal is not None:
            self.current_deal.close(self.current_time, self.price, self.fee)
            self.deals.append(self.current_deal)
            self.current_deal = None

        self.global_deal.close(self.current_time, self.price, self.fee)
    
    def on_bar(self):
        pass