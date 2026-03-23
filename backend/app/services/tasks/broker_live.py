"""
Live trading broker implementation.

Uses ccxt for exchange interaction and QuotesClient for real-time bar data.
Supports any exchange supported by ccxt.
"""
import json
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple, Callable

import ccxt
import numpy as np
import pyita as ta

from app.services.tasks.broker import (
    Broker, OrderType, OrderSide, BarStatus,
    Deal, Order, Trade,
)
from app.services.tasks.broker_snapshot import BrokerSnapshot
from app.services.tasks.enums import (
    OrderType as OT, OrderSide as OS, OrderStatus, OrderGroup, DealType,
)
from app.services.tasks.error_registry import ErrorCategory, ErrorEntry, ErrorLevel, ErrorRegistry
from app.services.tasks.trading_stats import TradingStats
from app.services.tasks.quotes_provider import RealTimeQuotesProvider, QuotesProvider
from app.services.quotes.constants import PRICE_TYPE, VOLUME_TYPE
from app.services.quotes.client import QuotesClient
from app.services.quotes.timeframe import Timeframe
from app.core.constants import TRADE_RESULTS_SAVE_PERIOD
from app.core.config import (
    BAR_WAIT_INTERVAL,
    ORDER_WAIT_INTERVAL,
    ORDER_PLACEMENT_TIMEOUT,
    EXCHANGE_RETRY_ATTEMPTS,
    EXCHANGE_RETRY_DELAY,
    build_ccxt_exchange_config,
)
from app.core.datetime_utils import parse_utc_datetime, datetime64_to_iso
from app.core.logger import get_logger
from app.services.tasks.tasks import Task

logger = get_logger(__name__)

def _summarize_exchange_result(result: Any) -> str:
    """Build a short human-readable summary for exchange responses."""
    if isinstance(result, dict):
        parts = []
        for key in ("id", "clientOrderId", "symbol", "type", "side", "status", "price", "amount", "timestamp"):
            value = result.get(key)
            if value not in (None, "", {}, []):
                parts.append(f"{key}={value}")
        if not parts:
            parts.append(f"keys={sorted(result.keys())}")
        return ", ".join(parts)
    if isinstance(result, list):
        return f"items={len(result)}"
    return str(result)


def _build_exchange_debug_context(exchange: Any) -> Dict[str, Any]:
    """Build a safe diagnostic snapshot of an exchange instance."""
    context: Dict[str, Any] = {
        "exchange_id": getattr(exchange, "id", None),
        "hostname": getattr(exchange, "hostname", None),
        "rate_limit": getattr(exchange, "rateLimit", None),
        "timeout": getattr(exchange, "timeout", None),
    }

    options = getattr(exchange, "options", None)
    if isinstance(options, dict):
        context["options_keys"] = sorted(options.keys())
        for key in ("defaultType", "defaultSubType", "recvWindow", "recv_window"):
            if key in options:
                context[f"option_{key}"] = options.get(key)

    urls = getattr(exchange, "urls", None)
    if isinstance(urls, dict):
        api_urls = urls.get("api")
        if isinstance(api_urls, dict):
            context["api_url_keys"] = sorted(api_urls.keys())
        elif api_urls:
            context["api_url_type"] = type(api_urls).__name__

    return context


def _build_exchange_runtime_context(exchange: Any) -> Dict[str, Any]:
    """Build runtime diagnostics for a concrete exchange request."""
    context = _build_exchange_debug_context(exchange)

    for attr_name, key in (
        ("lastRestRequestTimestamp", "last_rest_request_timestamp"),
        ("last_response_headers", "last_response_headers_present"),
    ):
        value = getattr(exchange, attr_name, None)
        if value not in (None, "", {}, []):
            if key == "last_response_headers_present":
                context[key] = True
            else:
                context[key] = value

    options = getattr(exchange, "options", None)
    if isinstance(options, dict):
        time_difference = options.get("timeDifference")
        if time_difference not in (None, "", {}, []):
            context["time_difference"] = time_difference
    else:
        time_difference = getattr(exchange, "timeDifference", None)
        if time_difference not in (None, "", {}, []):
            context["time_difference"] = time_difference

    milliseconds_method = getattr(exchange, "milliseconds", None)
    if callable(milliseconds_method):
        try:
            context["exchange_milliseconds"] = milliseconds_method()
        except Exception as exc:
            context["exchange_milliseconds_error"] = type(exc).__name__

    context["local_wall_time_ms"] = int(time.time() * 1000)
    return context


def _is_retryable_exchange_error(exc: Exception) -> bool:
    """Return True for transient exchange initialization errors."""
    retryable_types = (
        ccxt.NetworkError,
        ccxt.RequestTimeout,
        ccxt.ExchangeNotAvailable,
        ccxt.DDoSProtection,
        ccxt.RateLimitExceeded,
    )
    if isinstance(exc, retryable_types):
        return True

    message = str(exc).lower()
    retryable_fragments = (
        "remotedisconnected",
        "remote end closed connection without response",
        "connection aborted",
        "connection reset",
        "temporarily unavailable",
        "timed out",
        "timeout",
        'retcode":10002',
        "server timestamp or recv_window",
    )
    return any(fragment in message for fragment in retryable_fragments)


def _execute_exchange_operation_with_retry(
    *,
    exchange: Any,
    operation_name: str,
    func: Callable[[], Any],
    exchange_name: str,
    max_attempts: int = EXCHANGE_RETRY_ATTEMPTS,
    retry_delay: float = EXCHANGE_RETRY_DELAY,
) -> Any:
    """Execute an exchange operation with latency diagnostics and retry."""
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        started_at = time.monotonic()
        logger.info(
            "Exchange request: method=%s exchange=%s attempt=%s/%s context=%s",
            operation_name,
            exchange_name,
            attempt,
            max_attempts,
            json.dumps(_build_exchange_debug_context(exchange), ensure_ascii=False, sort_keys=True),
        )
        try:
            result = func()
        except Exception as exc:
            elapsed = time.monotonic() - started_at
            last_error = exc
            retryable = _is_retryable_exchange_error(exc)
            logger.warning(
                "Exchange failure: method=%s exchange=%s attempt=%s/%s elapsed=%.3fs retryable=%s error_type=%s error=%s",
                operation_name,
                exchange_name,
                attempt,
                max_attempts,
                elapsed,
                retryable,
                type(exc).__name__,
                exc,
            )
            if attempt >= max_attempts or not retryable:
                raise
            time.sleep(retry_delay)
            continue

        elapsed = time.monotonic() - started_at
        logger.info(
            "Exchange result: method=%s exchange=%s attempt=%s/%s elapsed=%.3fs %s",
            operation_name,
            exchange_name,
            attempt,
            max_attempts,
            elapsed,
            _summarize_exchange_result(result),
        )
        return result

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Exchange operation failed unexpectedly: {operation_name}")


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

        # Set to True after restore_from_snapshot() so the first update_state()
        # forces re-save of all restored trades/orders to Redis.
        self._first_update_after_restore: bool = False

    @property
    def current_time(self) -> np.datetime64:
        assert self.market_time is not None, "Current market time is not available"
        return self.market_time

    @property
    def current_price(self) -> PRICE_TYPE:
        assert self.market_price is not None, "Current market price is not available"
        return self.market_price

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def initialize_run(self) -> None:
        """
        Create ccxt exchange instance, load markets, extract precision.
        """
        source = self.task.source.lower()

        exchange_class = getattr(ccxt, source, None)
        if exchange_class is None:
            raise RuntimeError(f"Exchange '{source}' is not supported by ccxt")

        create_started_at = time.monotonic()
        logger.info("Exchange client create request: exchange=%s auth=%s", source, True)
        self.exchange = exchange_class(build_ccxt_exchange_config(source, with_auth=True))
        logger.info(
            "Exchange client create result: exchange=%s client=%s elapsed=%.3fs context=%s",
            source,
            exchange_class.__name__,
            time.monotonic() - create_started_at,
            json.dumps(_build_exchange_debug_context(self.exchange), ensure_ascii=False, sort_keys=True),
        )
        assert self.exchange is not None

        _execute_exchange_operation_with_retry(
            exchange=self.exchange,
            operation_name="load_markets",
            func=self.exchange.load_markets,
            exchange_name=source,
        )

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

        self.date_start = np.datetime64(datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None), "ms")

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
        if timeframe is None:
            raise RuntimeError("BrokerLive timeframe is not initialized")

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
            if self._quotes_client is None:
                raise RuntimeError("Quotes client is not initialized")
            if self._timeframe is None:
                raise RuntimeError("BrokerLive timeframe is not initialized")

            snapshot_data = self._quotes_client.get_latest_market_snapshot(
                self.source,
                self.symbol,
                self._timeframe,
            )
            if snapshot_data is not None:
                self.market_time = snapshot_data["time"][0]
                self.market_price = PRICE_TYPE(snapshot_data["close"][0])

            bar_data = self._quotes_client.wait_next_completed_bar(
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
        if not isinstance(quotes_provider, RealTimeQuotesProvider):
            raise RuntimeError("BrokerLive requires RealTimeQuotesProvider in live mode")
        quotes_provider.append_bar(bar_data)

        # Update ta_proxies with new provider state
        for proxy in ta_proxies.values():
            if hasattr(proxy, "set_quotes"):
                proxy.set_quotes(quotes_provider)

        primary = quotes_provider.primary
        self.i_time = len(primary.close) - 1

        completed_bar_time = primary.time[self.i_time]
        completed_bar_close_price = PRICE_TYPE(primary.close[self.i_time])

        self.bar_time = completed_bar_time
        self.bar_close_price = completed_bar_close_price
        self.market_time = completed_bar_time
        self.market_price = completed_bar_close_price

        sliced_quotes = primary[: self.i_time + 1]
        sliced_quotes.writeable = False

        return (BarStatus.RECEIVED, (sliced_quotes, completed_bar_time, completed_bar_close_price))

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
            assert self.exchange is not None
            ccxt_side = side.value  # "buy" or "sell"
            logger.info(
                "Exchange request: method=create_order exchange=%s symbol=%s order_type=%s side=%s amount=%s price=%s",
                self.source,
                symbol,
                order_type.value,
                ccxt_side,
                amount,
                price,
            )

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

            logger.info(
                "Exchange result: method=create_order exchange=%s %s",
                self.source,
                _summarize_exchange_result(result),
            )

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
            assert self.exchange is not None
            logger.info(
                "Exchange request: method=cancel_order exchange=%s symbol=%s order_id=%s",
                self.source,
                symbol,
                exchange_order_id,
            )
            result = self.exchange.cancel_order(exchange_order_id, symbol)
            logger.info(
                "Exchange result: method=cancel_order exchange=%s %s",
                self.source,
                _summarize_exchange_result(result),
            )
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
        raw_trades: Optional[List[Dict]] = None
        last_error: Optional[Exception] = None
        assert self.exchange is not None

        for attempt in range(1, EXCHANGE_RETRY_ATTEMPTS + 1):
            started_at = time.monotonic()
            request_context = json.dumps(
                _build_exchange_runtime_context(self.exchange),
                ensure_ascii=False,
                sort_keys=True,
            )
            try:
                logger.info(
                    "Exchange request: method=fetch_my_trades exchange=%s symbol=%s since=%s markets_only=%s attempt=%s/%s context=%s",
                    self.source,
                    symbol,
                    since,
                    markets_only,
                    attempt,
                    EXCHANGE_RETRY_ATTEMPTS,
                    request_context,
                )
                raw_trades = self.exchange.fetch_my_trades(symbol, since=since)
                elapsed = time.monotonic() - started_at
                logger.info(
                    "Exchange result: method=fetch_my_trades exchange=%s items=%s elapsed=%.3fs attempt=%s/%s context=%s",
                    self.source,
                    len(raw_trades),
                    elapsed,
                    attempt,
                    EXCHANGE_RETRY_ATTEMPTS,
                    json.dumps(
                        _build_exchange_runtime_context(self.exchange),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
                break
            except Exception as e:
                elapsed = time.monotonic() - started_at
                last_error = e
                retryable = _is_retryable_exchange_error(e)

                if retryable and attempt < EXCHANGE_RETRY_ATTEMPTS:
                    logger.warning(
                        "Exchange retry: method=fetch_my_trades exchange=%s symbol=%s since=%s markets_only=%s attempt=%s/%s elapsed=%.3fs retry_delay=%.3fs error_type=%s error=%s context=%s",
                        self.source,
                        symbol,
                        since,
                        markets_only,
                        attempt,
                        EXCHANGE_RETRY_ATTEMPTS,
                        elapsed,
                        EXCHANGE_RETRY_DELAY,
                        type(e).__name__,
                        e,
                        json.dumps(
                            _build_exchange_runtime_context(self.exchange),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                    time.sleep(EXCHANGE_RETRY_DELAY)
                    continue

                self.logging(
                    "exchange_fetch_my_trades failed: "
                    f"{e}; elapsed={elapsed:.3f}s; attempt={attempt}/{EXCHANGE_RETRY_ATTEMPTS}; "
                    f"context={json.dumps(_build_exchange_runtime_context(self.exchange), ensure_ascii=False, sort_keys=True)}",
                    level="error",
                    category=ErrorCategory.EXCHANGE,
                )
                return []

        if raw_trades is None:
            self.logging(
                "exchange_fetch_my_trades failed without result: "
                f"last_error={last_error}; context={json.dumps(_build_exchange_runtime_context(self.exchange), ensure_ascii=False, sort_keys=True)}",
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

    # ------------------------------------------------------------------
    # Snapshot: serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dt64(iso: Optional[str]) -> Optional[np.datetime64]:
        """Convert ISO string → np.datetime64[ms], or None."""
        if not iso:
            return None
        return np.datetime64(parse_utc_datetime(iso), "ms")

    @staticmethod
    def _serialize_trade(t: Trade) -> Dict[str, Any]:
        return {
            "trade_id": t.trade_id,
            "exchange_trade_id": t.exchange_trade_id,
            "deal_id": t.deal_id,
            "order_id": t.order_id,
            "time": datetime64_to_iso(t.time),
            "side": t.side.value,
            "price": float(t.price),
            "quantity": float(t.quantity),
            "fee": float(t.fee),
            "sum": float(t.sum),
        }

    @staticmethod
    def _deserialize_trade(d: Dict[str, Any]) -> Trade:
        return Trade(
            trade_id=d["trade_id"],
            exchange_trade_id=d["exchange_trade_id"],
            deal_id=d["deal_id"],
            order_id=d["order_id"],
            time=np.datetime64(parse_utc_datetime(d["time"]), "ms"),
            side=OrderSide(d["side"]),
            price=d["price"],
            quantity=d["quantity"],
            fee=d["fee"],
            sum=d["sum"],
        )

    @staticmethod
    def _serialize_order(o: Order) -> Dict[str, Any]:
        return {
            "order_id": o.order_id,
            "deal_id": o.deal_id,
            "order_type": o.order_type.value,
            "create_time": datetime64_to_iso(o.create_time),
            "side": o.side.value,
            "price": float(o.price) if o.price is not None else None,
            "trigger_price": float(o.trigger_price) if o.trigger_price is not None else None,
            "modify_time": datetime64_to_iso(o.modify_time),
            "volume": float(o.volume),
            "filled_volume": float(o.filled_volume),
            "status": o.status.value,
            "order_group": o.order_group.value,
            "fraction": o.fraction,
            "fraction_remain": o.fraction_remain,
            "exchange_order_id": str(o.exchange_order_id) if o.exchange_order_id is not None else None,
            "actual": o.actual,
        }

    @staticmethod
    def _deserialize_order(d: Dict[str, Any]) -> Order:
        ts = lambda s: np.datetime64(parse_utc_datetime(s), "ms")
        return Order(
            order_id=d["order_id"],
            deal_id=d["deal_id"],
            order_type=OT(d["order_type"]),
            create_time=ts(d["create_time"]),
            side=OS(d["side"]),
            price=d.get("price"),
            trigger_price=d.get("trigger_price"),
            modify_time=ts(d["modify_time"]),
            volume=d["volume"],
            filled_volume=d["filled_volume"],
            status=OrderStatus(d["status"]),
            order_group=OrderGroup(d["order_group"]),
            fraction=d.get("fraction"),
            fraction_remain=d.get("fraction_remain"),
            exchange_order_id=d.get("exchange_order_id"),
            actual=d.get("actual", False),
        )

    @staticmethod
    def _serialize_deal(deal: Deal) -> Dict[str, Any]:
        """Serialize a Deal to a JSON-safe dict (without nested orders/trades)."""
        return {
            "deal_id": deal.deal_id,
            "type": deal.type.value if deal.type is not None else None,
            "avg_buy_price": float(deal.avg_buy_price) if deal.avg_buy_price is not None else None,
            "avg_sell_price": float(deal.avg_sell_price) if deal.avg_sell_price is not None else None,
            "quantity": float(deal.quantity),
            "fee": float(deal.fee),
            "profit": float(deal.profit) if deal.profit is not None else None,
            "is_closed": deal.is_closed,
            "date_open": datetime64_to_iso(deal.date_open) if deal.date_open is not None else None,
            "date_close": datetime64_to_iso(deal.date_close) if deal.date_close is not None else None,
            "pending_close": deal.pending_close,
            "close_type": deal.close_type.value if deal.close_type is not None else None,
            "auto": deal.auto,
            "emergency_close": deal.emergency_close,
            "buy_quantity": float(deal.buy_quantity),
            "buy_cost": float(deal.buy_cost),
            "sell_quantity": float(deal.sell_quantity),
            "sell_proceeds": float(deal.sell_proceeds),
            # Keep order/trade IDs for reference reconstruction
            "order_ids": [o.order_id for o in deal.orders],
            "trade_ids": [t.trade_id for t in deal.trades],
        }

    # ------------------------------------------------------------------
    # Snapshot: save / load / restore
    # ------------------------------------------------------------------

    def _get_snapshot_key(self) -> str:
        """Redis key for broker snapshot (shared across result_id restarts)."""
        return f"{self.task.get_result_key()}:snapshot"

    def save_snapshot(self, results: Optional[Any] = None) -> None:
        """
        Persist current broker state to Redis as a JSON snapshot.

        Called periodically from update_state() and (optionally) at shutdown.

        Args:
            results: Optional TaskResults instance; if provided, its incremental
                     indices (trades_start_index, last_orders_save_time) are stored
                     so they can be restored after restart.
        """
        # Collect strategy state via 'save_state' callback (added in create_strategy_callbacks)
        strategy_state: Optional[Dict[str, Any]] = None
        save_state_fn = self.callbacks.get("save_state")
        if save_state_fn is not None:
            try:
                strategy_state = save_state_fn()
            except Exception as e:
                self.logging(f"save_state() raised an exception: {e}", level="error")
                strategy_state = {}

        # Exchange order map: exchange_order_id (str) → order_id (int)
        exchange_order_map: Dict[str, int] = {
            eid: order.order_id
            for eid, order in self._exchange_order_map.items()
        }

        # Serialize TaskResults indices when available
        trades_start_index = 0
        last_orders_save_time_iso: Optional[str] = None
        if results is not None:
            trades_start_index = results._trades_start_index
            if results._last_orders_save_time is not None:
                last_orders_save_time_iso = datetime64_to_iso(results._last_orders_save_time)

        # Serialize stats
        stats_dict: Dict[str, Any] = {}
        if self.stats is not None:
            try:
                stats_dict = self.stats.model_dump()
            except Exception:
                pass

        # Serialize error registry
        error_entries = [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "broker_time": e.broker_time,
                "level": e.level.value,
                "category": e.category.value,
                "message": e.message,
                "deal_id": e.deal_id,
                "order_id": e.order_id,
            }
            for e in self.error_registry._errors
        ]

        snapshot = BrokerSnapshot(
            deals=[self._serialize_deal(d) for d in self.deals],
            orders=[self._serialize_order(o) for o in self.orders],
            trades=[self._serialize_trade(t) for t in self.trades],
            exchange_order_map=exchange_order_map,
            processed_trade_ids=list(self._processed_trade_ids),
            last_trade_time=self._last_trade_time,
            current_auto_deal_id=self._current_auto_deal_id,
            active_deals=list(self.active_deals),
            market_time=datetime64_to_iso(self.market_time) if self.market_time is not None else None,
            bar_time=datetime64_to_iso(self.bar_time) if self.bar_time is not None else None,
            market_price=float(self.market_price) if self.market_price is not None else None,
            bar_close_price=float(self.bar_close_price) if self.bar_close_price is not None else None,
            date_start=datetime64_to_iso(self.date_start) if self.date_start is not None else None,
            trades_start_index=trades_start_index,
            last_orders_save_time=last_orders_save_time_iso,
            stats=stats_dict,
            error_registry_errors=error_entries,
            error_registry_next_id=self.error_registry._next_id,
            error_registry_flush_index=self.error_registry._flush_index,
            strategy_state=strategy_state,
        )

        try:
            client = self.task.get_redis_client()
            client.set(self._get_snapshot_key(), snapshot.model_dump_json())
            logger.debug("Broker snapshot saved (%d deals, %d orders, %d trades)",
                         len(self.deals), len(self.orders), len(self.trades))
        except Exception as e:
            self.logging(f"Failed to save broker snapshot: {e}", level="error",
                         category=ErrorCategory.INFRASTRUCTURE)

    def load_snapshot(self) -> Optional[BrokerSnapshot]:
        """
        Load broker snapshot from Redis.

        Returns:
            BrokerSnapshot if found and valid, None otherwise.
        """
        if self.task._list is None:
            return None
        try:
            client = self.task.get_redis_client()
            raw = client.get(self._get_snapshot_key())
            if raw is None:
                return None
            snapshot = BrokerSnapshot.model_validate_json(raw)
            logger.info(
                "Broker snapshot loaded: %d deals, %d orders, %d trades",
                len(snapshot.deals), len(snapshot.orders), len(snapshot.trades),
            )
            return snapshot
        except Exception as e:
            logger.warning("Failed to load broker snapshot (will start fresh): %s", e)
            return None

    def restore_from_snapshot(self, snapshot: BrokerSnapshot) -> None:
        """
        Restore broker state from a previously saved snapshot.

        Recreates deals, orders, trades and auxiliary tracking structures.
        Called in run() before super().run() so that TaskResults initialization
        sees the correct trade count.
        """
        # 1. Restore trades (flat list)
        self.trades = [self._deserialize_trade(d) for d in snapshot.trades]

        # 2. Restore orders (flat list)
        self.orders = [self._deserialize_order(d) for d in snapshot.orders]

        # Build order_id → Order lookup for deal reconstruction
        order_by_id: Dict[int, Order] = {o.order_id: o for o in self.orders}
        trade_by_id: Dict[int, Trade] = {t.trade_id: t for t in self.trades}

        # 3. Restore deals (scalar fields + reconnect orders/trades)
        restored_deals: List[Deal] = []
        for d in snapshot.deals:
            deal = Deal(
                deal_id=d["deal_id"],
                type=DealType(d["type"]) if d.get("type") else None,
                avg_buy_price=d.get("avg_buy_price"),
                avg_sell_price=d.get("avg_sell_price"),
                quantity=d["quantity"],
                fee=d["fee"],
                profit=d.get("profit"),
                is_closed=d["is_closed"],
                date_open=self._dt64(d.get("date_open")),
                date_close=self._dt64(d.get("date_close")),
                pending_close=d.get("pending_close", False),
                close_type=OrderGroup(d["close_type"]) if d.get("close_type") is not None else None,
                auto=d.get("auto", False),
                emergency_close=d.get("emergency_close", False),
                buy_quantity=d.get("buy_quantity", 0.0),
                buy_cost=d.get("buy_cost", 0.0),
                sell_quantity=d.get("sell_quantity", 0.0),
                sell_proceeds=d.get("sell_proceeds", 0.0),
            )
            # Reconnect orders
            for oid in d.get("order_ids", []):
                order = order_by_id.get(oid)
                if order is not None:
                    deal.orders.append(order)
            # Reconnect trades
            for tid in d.get("trade_ids", []):
                trade = trade_by_id.get(tid)
                if trade is not None:
                    deal.trades.append(trade)
            restored_deals.append(deal)
        self.deals = restored_deals

        # 4. Restore exchange tracking structures
        self._exchange_order_map = {}
        for eid, oid in snapshot.exchange_order_map.items():
            order = order_by_id.get(oid)
            if order is not None:
                self._exchange_order_map[eid] = order

        self._processed_trade_ids = set(snapshot.processed_trade_ids)
        self._last_trade_time = snapshot.last_trade_time

        # 5. Restore auto-deal context
        self._current_auto_deal_id = snapshot.current_auto_deal_id
        self.active_deals = set(snapshot.active_deals)

        # 6. Restore time tracking
        self.market_time = self._dt64(snapshot.market_time)
        self.bar_time = self._dt64(snapshot.bar_time)
        self.market_price = snapshot.market_price
        self.bar_close_price = snapshot.bar_close_price
        if snapshot.date_start:
            # Keep the original session start for progress events
            self.date_start = self._dt64(snapshot.date_start)

        # 7. Restore stats
        if snapshot.stats:
            try:
                self.stats = TradingStats.model_validate(snapshot.stats)
            except Exception as e:
                logger.warning("Failed to restore TradingStats from snapshot: %s", e)

        # 8. Restore error registry
        if snapshot.error_registry_errors:
            entries = []
            for e in snapshot.error_registry_errors:
                try:
                    entry = ErrorEntry(
                        id=e["id"],
                        timestamp=e["timestamp"],
                        broker_time=e.get("broker_time"),
                        level=ErrorLevel(e["level"]),
                        category=ErrorCategory(e["category"]),
                        message=e["message"],
                        deal_id=e.get("deal_id"),
                        order_id=e.get("order_id"),
                    )
                    entries.append(entry)
                except Exception as exc:
                    logger.warning("Failed to restore error entry: %s", exc)
            self.error_registry._errors = entries
        self.error_registry._next_id = snapshot.error_registry_next_id
        self.error_registry._flush_index = snapshot.error_registry_flush_index

        logger.info(
            "Broker state restored from snapshot: %d deals, %d orders, %d trades",
            len(self.deals), len(self.orders), len(self.trades),
        )

    # ------------------------------------------------------------------
    # Override update_state to periodically save snapshot
    # ------------------------------------------------------------------

    def update_state(self, results: Optional[Any], is_finish: bool = False) -> None:
        """
        Override to reset TaskResults indices on first call after restore,
        then save a snapshot after each successful state update.
        """
        # On first call after snapshot restore, force re-save of all restored data
        if self._first_update_after_restore and results is not None:
            results._trades_start_index = 0
            results._last_orders_save_time = None
            self._first_update_after_restore = False

        # Parent may raise RuntimeError if task was stopped
        super().update_state(results, is_finish)

        # Periodically persist broker state
        self.save_snapshot(results)

    def cleanup(self) -> None:
        """Unsubscribe from bars and close exchange connection."""
        if self._subscribed and self._quotes_client is not None:
            try:
                assert self._timeframe is not None
                self._quotes_client.unsubscribe(
                    self.source, self.symbol, self._timeframe
                )
                logger.info("Unsubscribed from bars: %s:%s:%s", self.source, self.symbol, self._timeframe)
            except Exception as e:
                logger.warning("Error unsubscribing from bars: %s", e)
            self._subscribed = False

        if self.exchange is not None:
            try:
                close_method = getattr(self.exchange, "close", None)
                if callable(close_method):
                    logger.info("Exchange request: method=close exchange=%s", self.source)
                    close_method()
                    logger.info("Exchange result: method=close exchange=%s status=success", self.source)
                else:
                    logger.debug(
                        "Exchange %s does not expose close(); skipping sync client cleanup",
                        self.source,
                    )
            except Exception as e:
                logger.warning("Error closing exchange: %s", e)
            self.exchange = None

    def run(self, save_results: bool = True):
        """
        Override run() to:
        1. Load snapshot from Redis and restore broker state (if exists).
        2. Pass the strategy state to on_start() via _strategy_state.
        3. Ensure cleanup is called on exit.
        """
        # Load snapshot BEFORE super().run() creates TaskResults
        # (TaskResults.__init__ deletes all Redis result keys, including the snapshot,
        #  so the data must be in memory before that happens).
        snapshot = self.load_snapshot()
        if snapshot is not None:
            self.restore_from_snapshot(snapshot)
            # Strategy state will be passed to on_start() in super().run()
            self._strategy_state = snapshot.strategy_state
            # Force re-save of all restored trades/orders to Redis on first update_state()
            self._first_update_after_restore = True

        try:
            super().run(save_results=save_results)
        finally:
            self.cleanup()
