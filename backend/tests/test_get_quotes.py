"""
Tests for get_quotes API endpoint using production database.

These tests use production configuration from ~/.config/r2d2/.env
and should be run separately from regular tests.
"""
import pytest
from datetime import datetime, UTC
from app.main import app

# Import TestClient from fastapi (which wraps starlette.testclient)
from fastapi.testclient import TestClient


@pytest.fixture
def client(quotes_service_production):
    """
    Create test client for FastAPI app.
    QuotesClient is already initialized by quotes_service_production fixture.
    """
    # QuotesClient is already initialized by quotes_service_production fixture
    # No need to initialize it again here
    return TestClient(app)


def test_get_quotes_success(client, quotes_service_production):
    """
    Test successful get_quotes request.
    """
    # Test parameters
    source = "binance"
    symbol = "BTC/USDT"
    timeframe = "1d"
    date_start = "2024-01-01T00:00:00Z"
    date_end = "2024-01-31T23:59:59Z"
    
    # Make request
    response = client.get(
        "/api/v1/common/quotes",
        params={
            "source": source,
            "symbol": symbol,
            "timeframe": timeframe,
            "date_start": date_start,
            "date_end": date_end
        }
    )
    
    # Check response
    assert response.status_code == 200
    data = response.json()
    
    # Check that data is a list
    assert isinstance(data, list)
    assert len(data) > 0
    
    # Check structure of first item
    first_item = data[0]
    assert "time" in first_item
    assert "open" in first_item
    assert "high" in first_item
    assert "low" in first_item
    assert "close" in first_item
    assert "volume" in first_item
    
    # Check types
    assert isinstance(first_item["time"], str)
    assert isinstance(first_item["open"], float)
    assert isinstance(first_item["high"], float)
    assert isinstance(first_item["low"], float)
    assert isinstance(first_item["close"], float)
    assert isinstance(first_item["volume"], float)
    
    # Check that time is in ISO format
    assert "T" in first_item["time"]
    assert first_item["time"].endswith("Z") or "+" in first_item["time"]
    
    # Check that prices are positive
    assert first_item["open"] > 0
    assert first_item["high"] > 0
    assert first_item["low"] > 0
    assert first_item["close"] > 0
    assert first_item["volume"] >= 0
    
    # Check that high >= low
    assert first_item["high"] >= first_item["low"]
    # Check that high >= open and high >= close
    assert first_item["high"] >= first_item["open"]
    assert first_item["high"] >= first_item["close"]
    # Check that low <= open and low <= close
    assert first_item["low"] <= first_item["open"]
    assert first_item["low"] <= first_item["close"]


def test_get_quotes_invalid_timeframe(client, quotes_service_production):
    """
    Test get_quotes with invalid timeframe.
    """
    response = client.get(
        "/api/v1/common/quotes",
        params={
            "source": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "invalid_tf",
            "date_start": "2024-01-01T00:00:00Z",
            "date_end": "2024-01-31T23:59:59Z"
        }
    )
    
    assert response.status_code == 400
    assert "Invalid timeframe" in response.json()["detail"]


def test_get_quotes_invalid_date_format(client, quotes_service_production):
    """
    Test get_quotes with invalid date format.
    """
    response = client.get(
        "/api/v1/common/quotes",
        params={
            "source": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "date_start": "invalid-date",
            "date_end": "2024-01-31T23:59:59Z"
        }
    )
    
    assert response.status_code == 400
    assert "Invalid date format" in response.json()["detail"]


def test_get_quotes_invalid_date_range(client, quotes_service_production):
    """
    Test get_quotes with invalid date range (start >= end).
    """
    response = client.get(
        "/api/v1/common/quotes",
        params={
            "source": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "date_start": "2024-01-31T23:59:59Z",
            "date_end": "2024-01-01T00:00:00Z"
        }
    )
    
    assert response.status_code == 400
    assert "date_start must be before date_end" in response.json()["detail"]


def test_get_quotes_missing_parameter(client, quotes_service_production):
    """
    Test get_quotes with missing required parameter.
    """
    response = client.get(
        "/api/v1/common/quotes",
        params={
            "source": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "date_start": "2024-01-01T00:00:00Z"
            # Missing date_end
        }
    )
    
    assert response.status_code == 422  # FastAPI validation error


def test_get_quotes_empty_result(client, quotes_service_production):
    """
    Test get_quotes with date range that has no data.
    Note: This test may return 200 with empty list or 404 depending on data availability.
    """
    # Use a very old date range that likely has no data
    response = client.get(
        "/api/v1/common/quotes",
        params={
            "source": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "date_start": "2000-01-01T00:00:00Z",
            "date_end": "2000-01-02T00:00:00Z"
        }
    )
    
    # Should return 200 with empty list or 404 if no data
    assert response.status_code in [200, 404]
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)
        # Empty list is acceptable if no data exists for this range


def test_get_quotes_different_timeframes(client, quotes_service_production):
    """
    Test get_quotes with different timeframes.
    """
    timeframes = ["1h", "4h", "1d"]
    
    for timeframe in timeframes:
        response = client.get(
            "/api/v1/common/quotes",
            params={
                "source": "binance",
                "symbol": "BTC/USDT",
                "timeframe": timeframe,
                "date_start": "2024-01-01T00:00:00Z",
                "date_end": "2024-01-02T23:59:59Z"
            }
        )
        
        # Should succeed or return 404 if no data
        assert response.status_code in [200, 404]
        
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
            if len(data) > 0:
                # Verify structure
                assert all(
                    "time" in item and "open" in item and "high" in item
                    and "low" in item and "close" in item and "volume" in item
                    for item in data
                )
