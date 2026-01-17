"""
Trading statistics class for tracking trading performance.
"""
from typing import Optional, TYPE_CHECKING
from pydantic import BaseModel

from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE

# Import enums that are used in runtime code
from app.services.tasks.broker import OrderSide, DealType

# Import types only for type checking (used in annotations)
if TYPE_CHECKING:
    from app.services.tasks.broker import Trade, Deal


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
    
    def add_trade(self, trade: 'Trade') -> None:
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
    
    def add_deal(self, deal: 'Deal') -> None:
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

