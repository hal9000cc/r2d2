"""
Generic broker classes for handling trading operations.
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional

import numpy as np
from pydantic import BaseModel, Field

from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.core.logger import get_logger

logger = get_logger(__name__)


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class Trade(BaseModel):
    """
    Represents a single trade (buy or sell operation).
    """

    trade_id: int
    deal_id: int
    order_id: int
    time: np.datetime64
    side: OrderSide
    price: PRICE_TYPE
    quantity: VOLUME_TYPE
    fee: PRICE_TYPE
    sum: PRICE_TYPE


class Deal(BaseModel):
    """
    Trading deal that groups multiple trades.

    - Accumulates trades belonging to a single logical deal.
    - Tracks average buy and sell prices across all trades.
    - Tracks current position quantity, total fees and profit.
    """

    deal_id: int
    trades: List[Trade] = Field(default_factory=list)

    # Average prices across all buy / sell trades in the deal
    avg_buy_price: Optional[PRICE_TYPE] = None
    avg_sell_price: Optional[PRICE_TYPE] = None

    # Current position quantity in symbol units; becomes 0 when fully closed
    quantity: VOLUME_TYPE = 0.0

    # Aggregated fees and realized profit for the deal
    fee: PRICE_TYPE = 0.0
    profit: Optional[PRICE_TYPE] = None

    # Internal accumulators for efficient incremental updates
    buy_quantity: VOLUME_TYPE = 0.0
    buy_cost: PRICE_TYPE = 0.0
    sell_quantity: VOLUME_TYPE = 0.0
    sell_proceeds: PRICE_TYPE = 0.0

    def add_trade(self, trade: Trade) -> None:
        """
        Add trade to the deal and update aggregates incrementally.

        - Sets trade.deal_id to this deal_id.
        - Updates quantity, avg_buy_price, avg_sell_price, fee and profit.
        """

        trade.deal_id = self.deal_id
        self.trades.append(trade)

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

        # Realized profit only when position is fully closed
        if self.is_closed:
            self.profit = self.sell_proceeds - self.buy_cost - self.fee
        else:
            self.profit = None

    @property
    def is_closed(self) -> bool:
        """
        Deal is closed when there was at least one trade and
        total bought quantity equals total sold quantity.
        """
        return (self.buy_quantity > 0 or self.sell_quantity > 0) and self.buy_quantity == self.sell_quantity

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


class Broker(ABC):
    """
    Generic broker base class.
    """

    def __init__(self):
        self.deals: Optional[List[Deal]] = None

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

    def reset(self) -> None:
        """
        Reset broker state. Initialize deals list.
        """
        self.deals = []

    # --- Deal registration helpers -------------------------------------------------

    def _get_or_create_deal_by_id(self, deal_id: int) -> Deal:
        """
        Get deal by index (deal_id is index in deals list).
        Raises IndexError if deal with such index does not exist.
        """
        if self.deals is None:
            self.deals = []

        if deal_id < 0 or deal_id >= len(self.deals):
            raise IndexError(f"Deal index {deal_id} is out of range (len={len(self.deals)})")

        return self.deals[deal_id]

    def _get_last_open_deal(self) -> Optional[Deal]:
        """
        Return last not-closed deal or None.
        """
        if self.deals is None or not self.deals:
            return None
        last = self.deals[-1]
        return None if last.is_closed else last

    def reg_buy(
        self,
        quantity: VOLUME_TYPE,
        fee: PRICE_TYPE,
        price: PRICE_TYPE,
        time: np.datetime64,
        deal_id: Optional[int] = None,
    ) -> None:
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
        """
        trade = self._create_trade(OrderSide.BUY, quantity, price=price, fee=fee, time=time)
        self._register_trade(trade, deal_id)

    def reg_sell(
        self,
        quantity: VOLUME_TYPE,
        fee: PRICE_TYPE,
        price: PRICE_TYPE,
        time: np.datetime64,
        deal_id: Optional[int] = None,
    ) -> None:
        """
        Register sell trade in deals structure.

        See reg_buy() for detailed behaviour description.

        Args:
            quantity: Quantity to sell
            fee: Fee for this trade
            price: Price for this trade
            deal_id: Optional deal index to register trade in
        """
        trade = self._create_trade(OrderSide.SELL, quantity, price=price, fee=fee, time=time)
        self._register_trade(trade, deal_id)

    def _create_trade(
        self,
        side: OrderSide,
        quantity: VOLUME_TYPE,
        price: PRICE_TYPE,
        fee: PRICE_TYPE,
        time: np.datetime64,
    ) -> Trade:
        """
        Create Trade object from quantity, price, fee and time.
        """
        trade_amount = quantity * price

        return Trade(
            trade_id=0,  # Will be set by deal if needed
            deal_id=0,  # Will be set by deal
            order_id=0,  # Not used in this context
            time=time,
            side=side,
            price=price,
            quantity=quantity,
            fee=fee,
            sum=trade_amount
        )

    def _register_trade(self, trade: Trade, deal_id: Optional[int]) -> None:
        """
        Core logic for registering trade in deals with flip handling.
        """
        # Explicit deal_id: just add to that deal, no flip-logic
        if deal_id is not None:
            deal = self._get_or_create_deal_by_id(deal_id)
            deal.add_trade(trade)
            return

        # If there are no deals at all – create first one and put whole trade there
        if not self.deals:
            new_deal_id = 0
            new_deal = Deal(deal_id=new_deal_id)
            self.deals.append(new_deal)
            new_deal.add_trade(trade)
            return

        last_deal = self._get_last_open_deal()

        # If last deal is closed – create a new one and put whole trade there
        if last_deal is None:
            new_deal_id = len(self.deals)
            new_deal = Deal(deal_id=new_deal_id)
            self.deals.append(new_deal)
            new_deal.add_trade(trade)
            return

        # There is an open deal; check if trade will flip position or not
        current_qty = last_deal.quantity
        trade_qty = trade.quantity

        if trade.side == OrderSide.BUY:
            new_qty = current_qty + trade_qty
        else:
            new_qty = current_qty - trade_qty

        # If no flip (including full close to 0) – just add trade
        if current_qty == 0 or new_qty == 0 or (current_qty > 0 and new_qty > 0) or (current_qty < 0 and new_qty < 0):
            last_deal.add_trade(trade)
            return

        # Flip: split trade into closing part and opening part of new deal
        # Determine volume needed to fully close current position
        close_volume = abs(current_qty)
        total_volume = trade_qty

        # Remaining volume opens new deal
        remainder_quantity = total_volume - close_volume

        # Trade for closing current deal
        close_ratio = close_volume / trade.quantity
        closing_trade = trade.model_copy(
            update={
                "quantity": close_volume,
                "fee": trade.fee * close_ratio,
                "sum": trade.price * close_volume,
            }
        )
        last_deal.add_trade(closing_trade)

        # Remaining volume opens new deal with same side
        new_deal_id = len(self.deals)
        new_deal = Deal(deal_id=new_deal_id)
        self.deals.append(new_deal)

        remainder_ratio = remainder_quantity / trade.quantity
        opening_trade = trade.model_copy(
            update={
                "quantity": remainder_quantity,
                "fee": trade.fee * remainder_ratio,
                "sum": trade.price * remainder_quantity,
            }
        )
        new_deal.add_trade(opening_trade)
