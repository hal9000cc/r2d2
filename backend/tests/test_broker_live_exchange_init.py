from unittest.mock import patch

import ccxt
import pytest

from app.services.tasks.broker_live import (
    _build_exchange_debug_context,
    _build_exchange_runtime_context,
    _execute_exchange_operation_with_retry,
    _is_retryable_exchange_error,
)


class DummyExchange:
    id = "dummy"
    hostname = "example.test"
    rateLimit = 100
    timeout = 5000
    options = {
        "defaultType": "spot",
        "recvWindow": 10000,
        "timeDifference": 321,
    }
    urls = {
        "api": {
            "public": "https://example.test/public",
            "private": "https://example.test/private",
        }
    }
    lastRestRequestTimestamp = 1234567890

    def milliseconds(self):
        return 9876543210


def test_build_exchange_debug_context_returns_safe_fields_only():
    context = _build_exchange_debug_context(DummyExchange())

    assert context["exchange_id"] == "dummy"
    assert context["hostname"] == "example.test"
    assert context["rate_limit"] == 100
    assert context["timeout"] == 5000
    assert context["option_defaultType"] == "spot"
    assert context["option_recvWindow"] == 10000
    assert context["api_url_keys"] == ["private", "public"]
    assert "apiKey" not in context
    assert "secret" not in context


def test_build_exchange_runtime_context_includes_timing_fields():
    context = _build_exchange_runtime_context(DummyExchange())

    assert context["exchange_id"] == "dummy"
    assert context["last_rest_request_timestamp"] == 1234567890
    assert context["time_difference"] == 321
    assert context["exchange_milliseconds"] == 9876543210
    assert isinstance(context["local_wall_time_ms"], int)


def test_is_retryable_exchange_error_detects_transient_ccxt_errors():
    assert _is_retryable_exchange_error(ccxt.NetworkError("boom")) is True
    assert _is_retryable_exchange_error(Exception("Remote end closed connection without response")) is True
    assert _is_retryable_exchange_error(Exception('bybit {"retCode":10002,"retMsg":"invalid request, please check your server timestamp or recv_window param"}')) is True
    assert _is_retryable_exchange_error(Exception("invalid nonce")) is False


def test_execute_exchange_operation_with_retry_retries_then_succeeds():
    exchange = DummyExchange()
    calls = {"count": 0}

    def flaky_operation():
        calls["count"] += 1
        if calls["count"] == 1:
            raise ccxt.NetworkError("temporary failure")
        return {"ok": True}

    with patch("app.services.tasks.broker_live.time.sleep") as sleep_mock:
        result = _execute_exchange_operation_with_retry(
            exchange=exchange,
            operation_name="load_markets",
            func=flaky_operation,
            exchange_name="bybit",
            max_attempts=2,
            retry_delay=0.1,
        )

    assert result == {"ok": True}
    assert calls["count"] == 2
    sleep_mock.assert_called_once_with(0.1)


def test_execute_exchange_operation_with_retry_does_not_retry_non_retryable_error():
    exchange = DummyExchange()

    with patch("app.services.tasks.broker_live.time.sleep") as sleep_mock:
        with pytest.raises(ValueError, match="fatal"):
            _execute_exchange_operation_with_retry(
                exchange=exchange,
                operation_name="load_markets",
                func=lambda: (_ for _ in ()).throw(ValueError("fatal")),
                exchange_name="bybit",
                max_attempts=3,
                retry_delay=0.1,
            )

    sleep_mock.assert_not_called()