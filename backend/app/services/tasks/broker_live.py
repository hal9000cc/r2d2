"""
Live trading broker implementation.

Uses ccxt for exchange interaction and QuotesClient for real-time bar data.
Supports any exchange supported by ccxt.
"""
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple, Callable

import ccxt
import numpy as np
import pyita as ta

from app.services.tasks.broker import Broker, OrderType, OrderSide, BarStatus
from app.services.tasks.error_registry import ErrorCategory
from app.services.tasks.quotes_provider import RealTimeQuotesProvider, QuotesProvider
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.config import (
    BAR_WAIT_INTERVAL,
    ORDER_WAIT_INTERVAL,
    ORDER_PLACEMENT_TIMEOUT,
    get_api_key,
    get_api_secret,
)
from app.core.datetime_utils import parse_utc_datetime
from app.core.logger import get_logger
from app.services.tasks.tasks import Task

logger = get_logger(__name__)


class BrokerLive(Broker):
    """
    Live trading broker implementation.

    Connects to a real exchange via ccxt, subscribes to real-time bars
    via QuotesClient, and routes orders/trades through the exchange API.
    """

    def __init__(
        self,
        task: Task,
        result_id: str,
        callbacks_dict: Dict[str, Callable],
        results_save_period: float = TRADE_RESULTS_SAVE_PERIOD,
    ):
        super().__init__(
            task=task,
            result_id=result_id,
            callbacks_dict=callbacks_dict,
            results_save_period=results_save_period,
        )

        self.is_live = True

        self.order_placement_timeout = ORDER_PLACEMENT_TIMEOUT

        # Will be set in initialize_run()
        self.exchange: Optional[ccxt.Exchange] = None
        self._timeframe: Optional[Timeframe] = None
        self._quotes_client: Optional[QuotesClient] = None
        self._subscribed: bool = False

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def initialize_run(self) -> None:
        """
        Create ccxt exchange instance, load markets, extract precision.
        """
        source = self.task.source.lower()

        api_key = get_api_key(source)
        api_secret = get_api_secret(source)

        exchange_class = getattr(ccxt, source, None)
        if exchange_class is None:
            raise RuntimeError(f"Exchange '{source}' is not supported by ccxt")

        exchange_config: Dict[str, Any] = {"enableRateLimit": True}
        if api_key:
            exchange_config["apiKey"] = api_key
        if api_secret:
            exchange_config["secret"] = api_secret

        self.exchange = exchange_class(exchange_config)
        self.exchange.load_markets()

        market = self.exchange.market(self.symbol)
        if market is None:
            raise RuntimeError(
                f"Symbol '{self.symbol}' not found on {source}"
            )

        # Extract precision from market info
        precision = market.get("precision", {})
        amount_precision = precision.get("amount")
        price_precision = precision.get("price")

        if amount_precision is not None:
            self.precision_amount = float(amount_precision)
        if price_precision is not None:
            self.precision_price = float(price_precision)

        logger.info(
            "BrokerLive initialized: %s %s  precision_amount=%s  precision_price=%s",
            source, self.symbol, self.precision_amount, self.precision_price,
        )

        try:
            self._timeframe = Timeframe.cast(self.task.timeframe)
        except Exception as e:
            raise RuntimeError(f"Failed to parse timeframe '{self.task.timeframe}': {e}") from e

        self.date_start = np.datetime64(datetime.now(timezone.utc).replace(microsecond=0), "ms")

        self.bar_wait_interval = BAR_WAIT_INTERVAL
        self.order_wait_interval = ORDER_WAIT_INTERVAL

    def initialize_quotes(
        self, history_size: int, ta_proxies: Dict[str, Any]
    ) -> QuotesProvider:
        """
        Load historical bars, subscribe to real-time stream, create provider.
        """
        history_size = self.task.history_size
        timeframe = self._timeframe

        history_start = datetime.now(timezone.utc) - (history_size * timeframe.timedelta())

        self._quotes_client = QuotesClient()

        logger.info(
            "Loading history for %s:%s:%s from %s (%d bars)",
            self.source, self.symbol, timeframe, history_start, history_size,
        )
        quotes_dict = self._quotes_client.get_quotes(
            self.source, self.symbol, timeframe, history_start
        )

        if len(quotes_dict["time"]) == 0:
            raise RuntimeError("No historical quotes available for live trading")

        logger.info("History loaded: %d bars", len(quotes_dict["time"]))

        primary_quotes = ta.Quotes(
            **{k: quotes_dict[k] for k in ("time", "open", "high", "low", "close", "volume")}
        )

        provider = RealTimeQuotesProvider(
            source=self.source,
            symbol=self.symbol,
            timeframe=timeframe,
            history_start=history_start,
            primary_quotes=primary_quotes,
        )

        # Subscribe to real-time bar stream
        self._quotes_client.subscribe(self.source, self.symbol, timeframe)
        self._subscribed = True
        logger.info("Subscribed to real-time bars: %s:%s:%s", self.source, self.symbol, timeframe)

        for proxy in ta_proxies.values():
            if hasattr(proxy, "set_quotes"):
                proxy.set_quotes(provider)

        return provider

    def fetch_next_bar(
        self,
        quotes_provider: QuotesProvider,
        ta_proxies: Dict[str, Any],
    ) -> Tuple[BarStatus, Optional[Tuple[ta.Quotes, np.datetime64, PRICE_TYPE]]]:
        """
        Wait for the next completed bar from the real-time stream.

        Also checks task.isRunning to allow graceful stop.
        """
        # Check if task was stopped
        if self._is_stopped():
            return (BarStatus.FINISHED, None)

        try:
            bar_data = self._quotes_client.wait_next_bar(
                self.source,
                self.symbol,
                self._timeframe,
                timeout=self.bar_wait_interval,
            )
        except RuntimeError as e:
            self.logging(f"Bar subscription error: {e}", level="error", category=ErrorCategory.DATA)
            return (BarStatus.FINISHED, None)
        except Exception as e:
            self.logging(f"Error waiting for bar: {e}", level="error", category=ErrorCategory.DATA)
            return (BarStatus.WAITING, None)

        if bar_data is None:
            return (BarStatus.WAITING, None)

        # Append bar to provider
        quotes_provider.append_bar(bar_data)

        # Update ta_proxies with new provider state
        for proxy in ta_proxies.values():
            if hasattr(proxy, "set_quotes"):
                proxy.set_quotes(quotes_provider)

        primary = quotes_provider.primary
        self.i_time = len(primary.close) - 1

        current_time = primary.time[self.i_time]
        current_price = PRICE_TYPE(primary.close[self.i_time])

        sliced_quotes = primary[: self.i_time + 1]
        sliced_quotes.writeable = False

        return (BarStatus.RECEIVED, (sliced_quotes, current_time, current_price))

    def progress(self) -> float:
        """Live trading has no finite progress."""
        return 0.0

    # ------------------------------------------------------------------
    # Exchange interaction
    # ------------------------------------------------------------------

    def exchange_create_order(
        self,
        symbol: str,
        order_type: OrderType,
        side: OrderSide,
        amount: float,
        price: Optional[float] = None,
    ) -> Dict:
        """
        Place an order on the exchange via ccxt.

        Order type mapping:
        - MARKET  → market order
        - LIMIT   → limit order
        - STOP    → stop-market order (trigger at `price`, execute at market)
        """
        try:
            ccxt_side = side.value  # "buy" or "sell"

            if order_type == OrderType.MARKET:
                result = self.exchange.create_order(
                    symbol, "market", ccxt_side, amount
                )
            elif order_type == OrderType.LIMIT:
                result = self.exchange.create_order(
                    symbol, "limit", ccxt_side, amount, price
                )
            elif order_type == OrderType.STOP:
                # Stop-market: trigger at `price`, execute at market
                result = self.exchange.create_order(
                    symbol,
                    "market",
                    ccxt_side,
                    amount,
                    None,
                    params={"stopPrice": price},
                )
            else:
                self.logging(
                    f"Unsupported order type: {order_type}",
                    level="error",
                    category=ErrorCategory.EXCHANGE,
                )
                return {}

            return {
                "id": str(result.get("id", "")),
                "symbol": symbol,
                "type": order_type.value,
                "side": ccxt_side,
                "amount": amount,
                "price": price,
                "status": result.get("status", "open"),
                "info": result.get("info", {}),
            }

        except Exception as e:
            self.logging(
                f"exchange_create_order failed: {order_type.value} {side.value} "
                f"{amount} @ {price}: {e}",
                level="error",
                category=ErrorCategory.EXCHANGE,
            )
            return {}

    def exchange_cancel_order(self, exchange_order_id: str, symbol: str) -> Dict:
        """Cancel an order on the exchange via ccxt."""
        try:
            result = self.exchange.cancel_order(exchange_order_id, symbol)
            return {
                "id": exchange_order_id,
                "symbol": symbol,
                "status": "canceled",
                "info": result.get("info", {}) if isinstance(result, dict) else {},
            }
        except Exception as e:
            self.logging(
                f"exchange_cancel_order failed for {exchange_order_id}: {e}",
                level="error",
                category=ErrorCategory.EXCHANGE,
            )
            return {"id": exchange_order_id, "status": "error"}

    def exchange_fetch_my_trades(
        self, symbol: str, since: Optional[int] = None, markets_only: bool = False
    ) -> List[Dict]:
        """
        Fetch executed trades from the exchange via ccxt.

        Normalises the ``fee`` field from ccxt's ``{cost, currency}`` dict
        to a plain float as expected by the base Broker.
        """
        try:
            raw_trades = self.exchange.fetch_my_trades(symbol, since=since)
        except Exception as e:
            self.logging(
                f"exchange_fetch_my_trades failed: {e}",
                level="error",
                category=ErrorCategory.EXCHANGE,
            )
            return []

        normalised: List[Dict] = []
        for t in raw_trades:
            fee_raw = t.get("fee")
            if isinstance(fee_raw, dict):
                fee_value = float(fee_raw.get("cost", 0.0))
            elif fee_raw is not None:
                fee_value = float(fee_raw)
            else:
                fee_value = 0.0

            normalised.append(
                {
                    "id": str(t["id"]),
                    "order": str(t["order"]),
                    "timestamp": t["timestamp"],
                    "price": float(t["price"]),
                    "amount": float(t["amount"]),
                    "fee": fee_value,
                }
            )

        return normalised

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_stopped(self) -> bool:
        """Check if the task was stopped via Redis (isRunning = False)."""
        if self.task._list is None:
            return False
        try:
            current_task = self.task.load()
            if current_task is None:
                return True
            return not current_task.isRunning
        except Exception:
            return False

    def cleanup(self) -> None:
        """Unsubscribe from bars and close exchange connection."""
        if self._subscribed and self._quotes_client is not None:
            try:
                self._quotes_client.unsubscribe(
                    self.source, self.symbol, self._timeframe
                )
                logger.info("Unsubscribed from bars: %s:%s:%s", self.source, self.symbol, self._timeframe)
            except Exception as e:
                logger.warning("Error unsubscribing from bars: %s", e)
            self._subscribed = False

        if self.exchange is not None:
            try:
                self.exchange.close()
            except Exception as e:
                logger.warning("Error closing exchange: %s", e)
            self.exchange = None

    def run(self, save_results: bool = True):
        """Override run() to ensure cleanup is called."""
        try:
            super().run(save_results=save_results)
        finally:
            self.cleanup()
