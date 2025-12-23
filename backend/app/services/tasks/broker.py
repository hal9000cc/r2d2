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


class Broker(ABC):
    """
    Generic broker base class.
    """
    
    class Trade(BaseModel):
        """
        Represents a single trade (buy or sell operation).
        """

        trade_id: int = Field(gt=0)
        deal_id: int = Field(gt=0)
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

        deal_id: int = Field(gt=0)
        trades: List['Broker.Trade'] = Field(default_factory=list)

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

        def add_trade(self, trade: 'Broker.Trade') -> None:
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

    def __init__(self, result_id: str):
        """
        Initialize broker.
        
        Args:
            result_id: Unique ID for this backtesting run
        """
        self.deals: Optional[List['Broker.Deal']] = None
        self.trades: List['Broker.Trade'] = []
        self.result_id = result_id

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
        Reset broker state. Initialize deals list and trades list.
        """
        self.deals = []
        self.trades = []

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
        
        # Check 3: All trade_id in ascending order by time
        trades_by_time = sorted(all_trades, key=lambda t: t.time)
        if trade_ids != [t.trade_id for t in trades_by_time]:
            errors.append("trade_id are not in ascending order by time")
        
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
            
            # Compare with stored values using generator expressions
            errors.extend([
                f"Deal {deal.deal_id}: {field} mismatch (stored={stored}, recalc={recalc})"
                for field, stored, recalc in [
                    ('buy_quantity', deal.buy_quantity, recalc_buy_quantity),
                    ('buy_cost', deal.buy_cost, recalc_buy_cost),
                    ('sell_quantity', deal.sell_quantity, recalc_sell_quantity),
                    ('sell_proceeds', deal.sell_proceeds, recalc_sell_proceeds),
                    ('fee', deal.fee, recalc_fee),
                ]
                if stored != recalc
            ])
            
            # Compare prices with tolerance for floating point
            if recalc_avg_buy_price is not None and deal.avg_buy_price is not None:
                if abs(recalc_avg_buy_price - deal.avg_buy_price) > 1e-10:
                    errors.append(f"Deal {deal.deal_id}: avg_buy_price mismatch (stored={deal.avg_buy_price}, recalc={recalc_avg_buy_price})")
            elif recalc_avg_buy_price != deal.avg_buy_price:
                errors.append(f"Deal {deal.deal_id}: avg_buy_price mismatch (stored={deal.avg_buy_price}, recalc={recalc_avg_buy_price})")
            
            if recalc_avg_sell_price is not None and deal.avg_sell_price is not None:
                if abs(recalc_avg_sell_price - deal.avg_sell_price) > 1e-10:
                    errors.append(f"Deal {deal.deal_id}: avg_sell_price mismatch (stored={deal.avg_sell_price}, recalc={recalc_avg_sell_price})")
            elif recalc_avg_sell_price != deal.avg_sell_price:
                errors.append(f"Deal {deal.deal_id}: avg_sell_price mismatch (stored={deal.avg_sell_price}, recalc={recalc_avg_sell_price})")
            
            # Compare profit for closed deals
            if deal.is_closed and recalc_profit is not None and deal.profit is not None:
                if abs(recalc_profit - deal.profit) > 1e-10:
                    errors.append(f"Deal {deal.deal_id}: profit mismatch (stored={deal.profit}, recalc={recalc_profit})")
            elif deal.is_closed and recalc_profit != deal.profit:
                errors.append(f"Deal {deal.deal_id}: profit mismatch (stored={deal.profit}, recalc={recalc_profit})")
        
        return errors


    def _get_or_create_deal_by_id(self, deal_id: int) -> 'Broker.Deal':
        """
        Get deal by deal_id (deal_id = index + 1).
        Raises IndexError if deal with such deal_id does not exist.
        """
        if self.deals is None:
            self.deals = []

        # Convert deal_id to index (deal_id = index + 1, so index = deal_id - 1)
        index = deal_id - 1
        if index < 0 or index >= len(self.deals):
            raise IndexError(f"Deal with deal_id {deal_id} does not exist (len={len(self.deals)})")

        return self.deals[index]

    def _get_last_open_deal(self) -> Optional['Broker.Deal']:
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
    ) -> 'Broker.Trade':
        """
        Create Trade object from quantity, price, fee and time.
        Assigns trade_id based on trades list size and adds trade to the list.
        """
        trade_id = len(self.trades) + 1
        trade_amount = quantity * price

        trade = Broker.Trade(
            trade_id=trade_id,
            deal_id=0,  # Will be set by deal
            order_id=0,  # Not used in this context
            time=time,
            side=side,
            price=price,
            quantity=quantity,
            fee=fee,
            sum=trade_amount
        )
        
        self.trades.append(trade)
        return trade

    def _register_trade(self, trade: 'Broker.Trade', deal_id: Optional[int]) -> None:
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
            new_deal_id = len(self.deals) + 1
            new_deal = Broker.Deal(deal_id=new_deal_id)
            self.deals.append(new_deal)
            new_deal.add_trade(trade)
            return

        last_deal = self._get_last_open_deal()

        # If last deal is closed – create a new one and put whole trade there
        if last_deal is None:
            new_deal_id = len(self.deals) + 1
            new_deal = Broker.Deal(deal_id=new_deal_id)
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
        new_deal_id = len(self.deals) + 1
        new_deal = Broker.Deal(deal_id=new_deal_id)
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
