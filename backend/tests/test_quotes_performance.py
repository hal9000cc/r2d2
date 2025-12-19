"""
Performance tests for quotes service using production database.

These tests use production configuration from ~/.config/r2d2/.env
and should be run separately from regular tests.
"""
import time
from datetime import datetime, UTC

import pytest

from app.services.quotes.client import QuotesBackTest


def test_quotes_performance_btc_usdt_5m(quotes_service_production):
    """
    Performance test: Get BTC/USDT:USDT quotes for period 01.01.2025 - 18.01.2025, timeframe 5m.
    Makes two consecutive requests and outputs execution time and number of bars.
    
    This test uses production configuration from ~/.config/r2d2/.env
    and requires production database to be accessible.
    """
    symbol = "BTC/USDT:USDT"
    timeframe = "5m"
    source = "binance"
    
    # Date range: 01.01.2025 - 18.01.2025
    date_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    date_end = datetime(2025, 12, 18, 23, 59, 59, tzinfo=UTC)
    
    # First request
    print(f"\n{'='*60}")
    print(f"Performance Test: {symbol}, {timeframe}")
    print(f"Period: {date_start.date()} - {date_end.date()}")
    print(f"{'='*60}")
    
    start_time_1 = time.time()
    quotes_1 = QuotesBackTest(
        symbol=symbol,
        timeframe=timeframe,
        history_start=date_start,
        history_end=date_end,
        source=source,
        timeout=1200
    )
    elapsed_time_1 = time.time() - start_time_1
    bars_count_1 = len(quotes_1.time.values)
    
    print(f"Запрос 1: {elapsed_time_1:.3f} с, количество баров: {bars_count_1}")
    
    # Second request (same parameters)
    start_time_2 = time.time()
    quotes_2 = QuotesBackTest(
        symbol=symbol,
        timeframe=timeframe,
        history_start=date_start,
        history_end=date_end,
        source=source,
        timeout=1200
    )
    elapsed_time_2 = time.time() - start_time_2
    bars_count_2 = len(quotes_2.time.values)
    
    print(f"Запрос 2: {elapsed_time_2:.3f} с, количество баров: {bars_count_2}")
    print(f"{'='*60}\n")
    
    # Verify both requests returned the same data
    assert bars_count_1 == bars_count_2, "Both requests should return the same number of bars"
    assert len(quotes_1.time.values) > 0, "First request should return data"
    assert len(quotes_2.time.values) > 0, "Second request should return data"
    
    # Verify data integrity
    assert len(quotes_1.open.values) == bars_count_1
    assert len(quotes_1.high.values) == bars_count_1
    assert len(quotes_1.low.values) == bars_count_1
    assert len(quotes_1.close.values) == bars_count_1
    assert len(quotes_1.volume.values) == bars_count_1
