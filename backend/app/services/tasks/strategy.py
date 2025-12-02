from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Union, List, Tuple
import numpy as np
from app.services.quotes.client import QuotesBackTest
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE, TIME_TYPE
from app.services.tasks.tasks import Task


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


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
        self.__reset()

    def __reset(self):
        pass

    def order(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: Optional[PRICE_TYPE] = None,
        stop_loss: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None,
        take_profit: Optional[Union[PRICE_TYPE, List[Tuple[VOLUME_TYPE, PRICE_TYPE]]]] = None
    ) -> Order:
        pass

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
            
            self.on_bar()

    def on_bar(self):
        pass