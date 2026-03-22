import time
from typing import Any, cast
from unittest.mock import patch

import pytest

from app.services.quotes.client import QuotesClient
from app.services.quotes.constants import (
    SUB_MSG_COMPLETED_BAR,
    SUB_MSG_MARKET_SNAPSHOT,
    SUB_MSG_SHUTDOWN,
)
from app.services.quotes.exceptions import R2D2QuotesException
from app.services.quotes.server import _create_subscription_manager
from app.services.quotes.timeframe import Timeframe


def _build_client_with_subscription(channel: str) -> QuotesClient:
    client = QuotesClient.__new__(QuotesClient)
    client._pubsub = cast(Any, object())
    client._subscribed_channels = {channel: True}
    client._latest_market_snapshots = {}
    client._pending_messages = []
    return client


def test_wait_next_completed_bar_respects_global_timeout_during_snapshots():
    channel = "quotes:bars:bybit:BTC/USDT:USDT:1m"
    client = _build_client_with_subscription(channel)
    snapshot = {"time": [1]}

    def fake_poll(timeout: float = 1.0):
        time.sleep(min(timeout, 0.01))
        return {
            "channel": channel,
            "type": SUB_MSG_MARKET_SNAPSHOT,
            "bar_data": snapshot,
        }

    with patch.object(client, "_poll_subscription_message", side_effect=fake_poll):
        started = time.monotonic()
        result = client.wait_next_completed_bar(
            "bybit",
            "BTC/USDT:USDT",
            Timeframe.t1m,
            timeout=0.05,
        )
        elapsed = time.monotonic() - started

    assert result is None
    assert elapsed < 0.5
    assert client._latest_market_snapshots[channel] == snapshot


def test_wait_next_completed_bar_returns_completed_bar_after_snapshots():
    channel = "quotes:bars:bybit:BTC/USDT:USDT:1m"
    client = _build_client_with_subscription(channel)
    snapshot = {"time": [1]}
    completed_bar = {"time": [2]}
    messages = [
        {"channel": channel, "type": SUB_MSG_MARKET_SNAPSHOT, "bar_data": snapshot},
        {"channel": channel, "type": SUB_MSG_COMPLETED_BAR, "bar_data": completed_bar},
    ]

    def fake_poll(timeout: float = 1.0):
        return messages.pop(0) if messages else None

    with patch.object(client, "_poll_subscription_message", side_effect=fake_poll):
        result = client.wait_next_completed_bar(
            "bybit",
            "BTC/USDT:USDT",
            Timeframe.t1m,
            timeout=0.2,
        )

    assert result == completed_bar
    assert client._latest_market_snapshots[channel] == snapshot


def test_wait_next_completed_bar_raises_on_shutdown_message():
    channel = "quotes:bars:bybit:BTC/USDT:USDT:1m"
    client = _build_client_with_subscription(channel)

    with patch.object(
        client,
        "_poll_subscription_message",
        return_value={"channel": channel, "type": SUB_MSG_SHUTDOWN},
    ):
        with pytest.raises(RuntimeError, match="QuotesServer shut down"):
            client.wait_next_completed_bar(
                "bybit",
                "BTC/USDT:USDT",
                Timeframe.t1m,
                timeout=0.2,
            )


def test_wait_next_completed_bar_raises_on_error_message():
    channel = "quotes:bars:bybit:BTC/USDT:USDT:1m"
    client = _build_client_with_subscription(channel)

    with patch.object(
        client,
        "_poll_subscription_message",
        return_value={"channel": channel, "type": "error", "error": "boom"},
    ):
        with pytest.raises(R2D2QuotesException, match="boom"):
            client.wait_next_completed_bar(
                "bybit",
                "BTC/USDT:USDT",
                Timeframe.t1m,
                timeout=0.2,
            )


def test_create_subscription_manager_raises_clear_error_when_class_missing():
    class DummyServer:
        pass

    with patch("app.services.quotes.server.SubscriptionManager", new=None):
        with pytest.raises(RuntimeError, match="SubscriptionManager is not available"):
            _create_subscription_manager(DummyServer())


def test_create_subscription_manager_returns_manager_instance_when_class_available():
    class DummyManager:
        def __init__(self, server):
            self.server = server

    class DummyServer:
        pass

    server = DummyServer()

    with patch("app.services.quotes.server.SubscriptionManager", new=DummyManager):
        manager = _create_subscription_manager(server)

    assert isinstance(manager, DummyManager)
    assert manager.server is server


def test_subscribe_retries_transient_subscription_manager_error_then_succeeds():
    client = QuotesClient.__new__(QuotesClient)
    client._pubsub = None
    client._subscribed_channels = {}
    client._latest_market_snapshots = {}
    client._pending_messages = []
    client.redis_client = cast(Any, type("RedisMock", (), {})())

    pubsub_mock = cast(Any, type("PubSubMock", (), {"subscribe": lambda self, channel: None})())

    calls = [
        R2D2QuotesException(
            "subscribe failed: cannot import name 'SubscriptionManager' from 'app.services.quotes.server'"
        ),
        None,
    ]

    def fake_send_action_request(*args, **kwargs):
        result = calls.pop(0)
        if isinstance(result, Exception):
            raise result

    with patch.object(client, "_send_action_request", side_effect=fake_send_action_request), \
         patch.object(client.redis_client, "pubsub", return_value=pubsub_mock, create=True), \
         patch("app.services.quotes.client._time.sleep") as sleep_mock:
        client.subscribe("bybit", "BTC/USDT:USDT", Timeframe.t1m)

    assert client._pubsub is pubsub_mock
    assert client._subscribed_channels["quotes:bars:bybit:BTC/USDT:USDT:1m"] is True
    sleep_mock.assert_called_once()


def test_subscribe_does_not_retry_non_retryable_error():
    client = QuotesClient.__new__(QuotesClient)
    client._pubsub = None
    client._subscribed_channels = {}
    client._latest_market_snapshots = {}
    client._pending_messages = []
    client.redis_client = cast(Any, type("RedisMock", (), {})())

    error = R2D2QuotesException("subscribe failed: boom")

    with patch.object(client, "_send_action_request", side_effect=error) as send_mock, \
         patch("app.services.quotes.client._time.sleep") as sleep_mock:
        with pytest.raises(R2D2QuotesException, match="boom"):
            client.subscribe("bybit", "BTC/USDT:USDT", Timeframe.t1m)

    assert send_mock.call_count == 1
    sleep_mock.assert_not_called()