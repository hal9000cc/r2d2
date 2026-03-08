"""
Snapshot model for live trading broker state persistence.

Stores only what cannot be recovered from external sources
(exchange API, quotes history, task configuration).
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel


class BrokerSnapshot(BaseModel):
    """
    Minimal broker state snapshot for live trading recovery.

    Saved to Redis before/after critical operations and restored
    on process restart. Only fields that cannot be reconstructed
    from the exchange API or quotes history are included.
    """

    # --- Core trading objects ---
    deals: List[Dict[str, Any]]          # Deal.model_dump() for each deal
    orders: List[Dict[str, Any]]         # Order.model_dump() for each order
    trades: List[Dict[str, Any]]         # Trade.model_dump() for each trade

    # --- Exchange order tracking ---
    # Maps exchange_order_id (str) → internal order_id (int)
    exchange_order_map: Dict[str, int]
    # Set of exchange trade IDs already processed (avoids duplicates on restart)
    processed_trade_ids: List[str]
    # Timestamp (ms) of the last processed trade for fetch_my_trades(since=...)
    last_trade_time: Optional[int] = None

    # --- Auto-deal context ---
    current_auto_deal_id: Optional[int] = None
    active_deals: List[int]              # Set[int] serialised as list

    # --- Broker time tracking ---
    # Used for order.modify_time and progress events after restore
    current_time: Optional[str] = None   # ISO format datetime
    date_start: Optional[str] = None     # ISO format datetime

    # --- TaskResults incremental save indices ---
    trades_start_index: int = 0
    last_orders_save_time: Optional[str] = None  # ISO format datetime

    # --- Trading statistics ---
    stats: Dict[str, Any]                # TradingStats.model_dump()

    # --- Error registry ---
    error_registry_errors: List[Dict[str, Any]]  # [ErrorEntry.model_dump()]
    error_registry_next_id: int = 1
    error_registry_flush_index: int = 0

    # --- Strategy state (optional, from Strategy.save_state()) ---
    # None  → strategy's on_start() was never called (should not happen on restore)
    # {}    → on_start() was called but save_state() was never overridden / returned {}
    # {...} → actual state dict returned by save_state()
    strategy_state: Optional[Dict[str, Any]] = None
