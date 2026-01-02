import pytest
import numpy as np
import time
from datetime import datetime, UTC, timedelta
from multiprocessing import get_context

from app.services.quotes.client import PriceSeries, QuotesBackTest, Client
from app.services.quotes.constants import PRICE_TYPE, TIME_TYPE, TIME_TYPE_UNIT
from app.services.quotes.exceptions import R2D2QuotesExceptionDataNotReceived
from app.core.config import redis_params
from app.services.quotes.timeframe import Timeframe


def test_quotes_usage_scenario(quotes_service):
    """
    Test Quotes usage scenario:
    quotes = Quotes('btc/usdt', '1d', 'binance')
    high = quotes.close
    close10 = high[-2: -12]
    
    high - is PriceSeries
    close10 - is numpy array with PRICE_TYPE
    """
    
    timeout = 10
    
    # QuotesBackTest should raise an exception with invalid parameters
    with pytest.raises(R2D2QuotesExceptionDataNotReceived) as e:
        quotes = QuotesBackTest('badsymbol/usdt', '1d', '2024-01-01', '2025-01-31', 'binance', 100, timeout=timeout)
    assert e.value.error == 'binance does not have market symbol badsymbol/usdt'

    quotes = QuotesBackTest('BTC/USDT', '1d', '2023-01-01', '2023-12-31', 'binance', 100, timeout=timeout)
    assert len(quotes.close) == 365

    quotes = QuotesBackTest('BTC/USDT', '1d', '2024-01-01', '2024-12-31', 'binance', 100, timeout=timeout)
    assert len(quotes.close) == 366
    
    # Test slices work correctly
    close_series = quotes.close
    assert isinstance(close_series, PriceSeries), "quotes.close should return PriceSeries"
    
    # Test slice [1:10]
    slice_data = close_series[1:10]
    assert isinstance(slice_data, np.ndarray), "Slice should return numpy array"
    assert len(slice_data) == 9, f"Slice [1:10] should return 9 elements, got {len(slice_data)}"
    assert slice_data.dtype == PRICE_TYPE, f"Slice should have PRICE_TYPE dtype, got {slice_data.dtype}"
    
    # Test slice [-10:]
    slice_data_end = close_series[-10:]
    assert isinstance(slice_data_end, np.ndarray), "Slice [-10:] should return numpy array"
    assert len(slice_data_end) == 10, f"Slice [-10:] should return 10 elements, got {len(slice_data_end)}"
    
    # Test that there are no zero values in prices
    assert np.all(quotes.open.values > 0), "Open prices should not contain zero values"
    assert np.all(quotes.high.values > 0), "High prices should not contain zero values"
    assert np.all(quotes.low.values > 0), "Low prices should not contain zero values"
    assert np.all(quotes.close.values > 0), "Close prices should not contain zero values"
    assert np.all(quotes.volume.values >= 0), "Volume should not contain negative values"


def check_data_completeness(quotes: QuotesBackTest, expected_start: datetime, expected_end: datetime, timeframe: Timeframe):
    """
    Check that quotes data is complete - no gaps from expected_start to expected_end.
    
    Args:
        quotes: QuotesBackTest object
        expected_start: Expected start datetime
        expected_end: Expected end datetime
        timeframe: Timeframe object
    """
    time_array = quotes.time.values
    
    # Convert expected times to numpy datetime64
    expected_start_dt64 = np.datetime64(expected_start.replace(tzinfo=None), TIME_TYPE_UNIT)
    expected_end_dt64 = np.datetime64(expected_end.replace(tzinfo=None), TIME_TYPE_UNIT)
    
    # Check that we have data
    assert len(time_array) > 0, f"Expected data from {expected_start} to {expected_end}, but got empty array"
    
    # Check start time
    first_time = time_array[0]
    assert first_time == expected_start_dt64, f"First time should be {expected_start_dt64}, got {first_time}"
    
    # Check end time - last bar should be the last possible bar for this timeframe that doesn't exceed expected_end
    last_time = time_array[-1]
    timeframe_delta = Timeframe.cast(timeframe).timedelta64()
    
    # Last bar should not exceed expected_end
    assert last_time <= expected_end_dt64, f"Last time {last_time} should not exceed expected_end {expected_end_dt64}"
    
    # Next bar (if it existed) should exceed expected_end, meaning we have the last possible bar
    next_possible_bar = last_time + timeframe_delta
    assert next_possible_bar > expected_end_dt64, \
        f"Last time {last_time} is not the last possible bar. Next bar {next_possible_bar} should exceed expected_end {expected_end_dt64}"
    
    # Check for gaps using vectorized operations
    if len(time_array) > 1:
        current_times = time_array[:-1]
        next_times = time_array[1:]
        expected_next_times = current_times + timeframe_delta
        
        # Check that all next times equal expected next times (no gaps)
        gaps = np.where(next_times != expected_next_times)[0]
        if len(gaps) > 0:
            gap_info = []
            for idx in gaps[:5]:  # Show first 5 gaps
                gap_info.append(f"gap at index {idx}: expected {expected_next_times[idx]}, got {next_times[idx]}")
            pytest.fail(f"Found {len(gaps)} gaps in data: {', '.join(gap_info)}")
    
    # Check that all arrays have the same length
    assert len(quotes.open.values) == len(time_array), "Open array length mismatch"
    assert len(quotes.high.values) == len(time_array), "High array length mismatch"
    assert len(quotes.low.values) == len(time_array), "Low array length mismatch"
    assert len(quotes.close.values) == len(time_array), "Close array length mismatch"
    assert len(quotes.volume.values) == len(time_array), "Volume array length mismatch"


def test_gaps_handling(quotes_service):
    """
    Test gap handling with multiple sequential requests.
    Hourly timeframe, multiple date ranges.
    """
    
    # Base date for testing
    base_date = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    timeframe = Timeframe.t1h
    
    # Day 1 scenarios
    day1 = base_date
    
    # Request 1: 0:00 to 0:00 (single hour)
    quotes1 = QuotesBackTest('BTC/USDT', '1h', day1, day1, 'binance', 100, timeout=1200)
    check_data_completeness(quotes1, day1, day1, timeframe)
    
    # Request 2: 2:00 to 4:00
    quotes2 = QuotesBackTest('BTC/USDT', '1h', day1 + timedelta(hours=2), day1 + timedelta(hours=4), 'binance', 100, timeout=1200)
    check_data_completeness(quotes2, day1 + timedelta(hours=2), day1 + timedelta(hours=4), timeframe)
    
    # Request 3: 8:00 to 10:00
    quotes3 = QuotesBackTest('BTC/USDT', '1h', day1 + timedelta(hours=8), day1 + timedelta(hours=10), 'binance', 100, timeout=1200)
    check_data_completeness(quotes3, day1 + timedelta(hours=8), day1 + timedelta(hours=10), timeframe)
    
    # Request 4: 0:00 to 22:00 (should fill all gaps)
    quotes4 = QuotesBackTest('BTC/USDT', '1h', day1, day1 + timedelta(hours=22), 'binance', 100, timeout=1200)
    check_data_completeness(quotes4, day1, day1 + timedelta(hours=22), timeframe)
    
    # Day 2 scenarios
    day2 = base_date + timedelta(days=1)
    
    # Request 5: 2:00 to 4:00
    quotes5 = QuotesBackTest('BTC/USDT', '1h', day2 + timedelta(hours=2), day2 + timedelta(hours=4), 'binance', 100, timeout=1200)
    check_data_completeness(quotes5, day2 + timedelta(hours=2), day2 + timedelta(hours=4), timeframe)
    
    # Request 6: 6:00 to 12:00
    quotes6 = QuotesBackTest('BTC/USDT', '1h', day2 + timedelta(hours=6), day2 + timedelta(hours=12), 'binance', 100, timeout=1200)
    check_data_completeness(quotes6, day2 + timedelta(hours=6), day2 + timedelta(hours=12), timeframe)
    
    # Request 7: 0:00 to 12:00 (should fill gaps)
    quotes7 = QuotesBackTest('BTC/USDT', '1h', day2, day2 + timedelta(hours=12), 'binance', 100, timeout=1200)
    check_data_completeness(quotes7, day2, day2 + timedelta(hours=12), timeframe)
    
    # Day 3 scenarios
    day3 = base_date + timedelta(days=2)
    
    # Request 8: 2:00 to 4:00
    quotes8 = QuotesBackTest('BTC/USDT', '1h', day3 + timedelta(hours=2), day3 + timedelta(hours=4), 'binance', 100, timeout=1200)
    check_data_completeness(quotes8, day3 + timedelta(hours=2), day3 + timedelta(hours=4), timeframe)
    
    # Request 9: 6:00 to 12:00
    quotes9 = QuotesBackTest('BTC/USDT', '1h', day3 + timedelta(hours=6), day3 + timedelta(hours=12), 'binance', 100, timeout=1200)
    check_data_completeness(quotes9, day3 + timedelta(hours=6), day3 + timedelta(hours=12), timeframe)
    
    # Request 10: 2:00 to 12:00 (should fill gaps)
    quotes10 = QuotesBackTest('BTC/USDT', '1h', day3 + timedelta(hours=2), day3 + timedelta(hours=12), 'binance', 100, timeout=1200)
    check_data_completeness(quotes10, day3 + timedelta(hours=2), day3 + timedelta(hours=12), timeframe)
    
    # Day 4 scenarios
    day4 = base_date + timedelta(days=3)
    
    # Request 11: 2:00 to 4:00
    quotes11 = QuotesBackTest('BTC/USDT', '1h', day4 + timedelta(hours=2), day4 + timedelta(hours=4), 'binance', 100, timeout=1200)
    check_data_completeness(quotes11, day4 + timedelta(hours=2), day4 + timedelta(hours=4), timeframe)
    
    # Request 12: 6:00 to 12:00
    quotes12 = QuotesBackTest('BTC/USDT', '1h', day4 + timedelta(hours=6), day4 + timedelta(hours=12), 'binance', 100, timeout=1200)
    check_data_completeness(quotes12, day4 + timedelta(hours=6), day4 + timedelta(hours=12), timeframe)
    
    # Request 13: 3:00 to 12:00 (should fill gaps)
    quotes13 = QuotesBackTest('BTC/USDT', '1h', day4 + timedelta(hours=3), day4 + timedelta(hours=12), 'binance', 100, timeout=1200)
    check_data_completeness(quotes13, day4 + timedelta(hours=3), day4 + timedelta(hours=12), timeframe)
    
    # Request 14: 0:00 to 15:00 (should fill all gaps)
    quotes14 = QuotesBackTest('BTC/USDT', '1h', day4, day4 + timedelta(hours=15), 'binance', 100, timeout=1200)
    check_data_completeness(quotes14, day4, day4 + timedelta(hours=15), timeframe)
    
    # Day 11 scenarios
    day11 = base_date + timedelta(days=10)
    
    # Request 15: 12:00 to 15:00
    quotes15 = QuotesBackTest('BTC/USDT', '1h', day11 + timedelta(hours=12), day11 + timedelta(hours=15), 'binance', 100, timeout=1200)
    check_data_completeness(quotes15, day11 + timedelta(hours=12), day11 + timedelta(hours=15), timeframe)
    
    # Request 16: 18:00 to 19:00
    quotes16 = QuotesBackTest('BTC/USDT', '1h', day11 + timedelta(hours=18), day11 + timedelta(hours=19), 'binance', 100, timeout=1200)
    check_data_completeness(quotes16, day11 + timedelta(hours=18), day11 + timedelta(hours=19), timeframe)
    
    # Request 17: 17:00 to 18:00
    quotes17 = QuotesBackTest('BTC/USDT', '1h', day11 + timedelta(hours=17), day11 + timedelta(hours=18), 'binance', 100, timeout=1200)
    check_data_completeness(quotes17, day11 + timedelta(hours=17), day11 + timedelta(hours=18), timeframe)
    
    # Request 18: 13:00 to 18:00
    quotes18 = QuotesBackTest('BTC/USDT', '1h', day11 + timedelta(hours=13), day11 + timedelta(hours=18), 'binance', 100, timeout=1200)
    check_data_completeness(quotes18, day11 + timedelta(hours=13), day11 + timedelta(hours=18), timeframe)
    
    # Request 19: 11:00 to 19:00 (should fill gaps)
    quotes19 = QuotesBackTest('BTC/USDT', '1h', day11 + timedelta(hours=11), day11 + timedelta(hours=19), 'binance', 100, timeout=1200)
    check_data_completeness(quotes19, day11 + timedelta(hours=11), day11 + timedelta(hours=19), timeframe)
    
    # Day 12 scenarios
    day12 = base_date + timedelta(days=11)
    
    # Request 20: 12:00 to 15:00
    quotes20 = QuotesBackTest('BTC/USDT', '1h', day12 + timedelta(hours=12), day12 + timedelta(hours=15), 'binance', 100, timeout=1200)
    check_data_completeness(quotes20, day12 + timedelta(hours=12), day12 + timedelta(hours=15), timeframe)
    
    # Request 21: 18:00 to 19:00
    quotes21 = QuotesBackTest('BTC/USDT', '1h', day12 + timedelta(hours=18), day12 + timedelta(hours=19), 'binance', 100, timeout=1200)
    check_data_completeness(quotes21, day12 + timedelta(hours=18), day12 + timedelta(hours=19), timeframe)
    
    # Request 22: 17:00 to 18:00
    quotes22 = QuotesBackTest('BTC/USDT', '1h', day12 + timedelta(hours=17), day12 + timedelta(hours=18), 'binance', 100, timeout=1200)
    check_data_completeness(quotes22, day12 + timedelta(hours=17), day12 + timedelta(hours=18), timeframe)
    
    # Request 23: 13:00 to 18:00
    quotes23 = QuotesBackTest('BTC/USDT', '1h', day12 + timedelta(hours=13), day12 + timedelta(hours=18), 'binance', 100, timeout=1200)
    check_data_completeness(quotes23, day12 + timedelta(hours=13), day12 + timedelta(hours=18), timeframe)
    
    # Request 24: 11:00 to 18:00 (should fill gaps)
    quotes24 = QuotesBackTest('BTC/USDT', '1h', day12 + timedelta(hours=11), day12 + timedelta(hours=18), 'binance', 100, timeout=1200)
    check_data_completeness(quotes24, day12 + timedelta(hours=11), day12 + timedelta(hours=18), timeframe)
    
    # Day 13 scenarios
    day13 = base_date + timedelta(days=12)
    
    # Request 25: 12:00 to 15:00
    quotes25 = QuotesBackTest('BTC/USDT', '1h', day13 + timedelta(hours=12), day13 + timedelta(hours=15), 'binance', 100, timeout=1200)
    check_data_completeness(quotes25, day13 + timedelta(hours=12), day13 + timedelta(hours=15), timeframe)
    
    # Request 26: 18:00 to 19:00
    quotes26 = QuotesBackTest('BTC/USDT', '1h', day13 + timedelta(hours=18), day13 + timedelta(hours=19), 'binance', 100, timeout=1200)
    check_data_completeness(quotes26, day13 + timedelta(hours=18), day13 + timedelta(hours=19), timeframe)
    
    # Request 27: 17:00 to 18:00
    quotes27 = QuotesBackTest('BTC/USDT', '1h', day13 + timedelta(hours=17), day13 + timedelta(hours=18), 'binance', 100, timeout=1200)
    check_data_completeness(quotes27, day13 + timedelta(hours=17), day13 + timedelta(hours=18), timeframe)
    
    # Request 28: 13:00 to 18:00
    quotes28 = QuotesBackTest('BTC/USDT', '1h', day13 + timedelta(hours=13), day13 + timedelta(hours=18), 'binance', 100, timeout=1200)
    check_data_completeness(quotes28, day13 + timedelta(hours=13), day13 + timedelta(hours=18), timeframe)
    
    # Day 14 scenarios
    day14 = base_date + timedelta(days=13)
    
    # Request 29: All day 14 (0:00 to 23:00)
    quotes29 = QuotesBackTest('BTC/USDT', '1h', day14, day14 + timedelta(hours=23), 'binance', 100, timeout=1200)
    check_data_completeness(quotes29, day14, day14 + timedelta(hours=23), timeframe)
    
    # Request 30: 0:00 to 8:00 - odd hours first (1, 3, 5, 7)
    quotes30_1 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=1), day14 + timedelta(hours=1), 'binance', 100, timeout=1200)
    check_data_completeness(quotes30_1, day14 + timedelta(hours=1), day14 + timedelta(hours=1), timeframe)
    quotes30_3 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=3), day14 + timedelta(hours=3), 'binance', 100, timeout=1200)
    check_data_completeness(quotes30_3, day14 + timedelta(hours=3), day14 + timedelta(hours=3), timeframe)
    quotes30_5 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=5), day14 + timedelta(hours=5), 'binance', 100, timeout=1200)
    check_data_completeness(quotes30_5, day14 + timedelta(hours=5), day14 + timedelta(hours=5), timeframe)
    quotes30_7 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=7), day14 + timedelta(hours=7), 'binance', 100, timeout=1200)
    check_data_completeness(quotes30_7, day14 + timedelta(hours=7), day14 + timedelta(hours=7), timeframe)
    
    # Request 31: 0:00 to 8:00 - even hours after (0, 2, 4, 6, 8)
    quotes31_0 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=0), day14 + timedelta(hours=0), 'binance', 100, timeout=1200)
    check_data_completeness(quotes31_0, day14 + timedelta(hours=0), day14 + timedelta(hours=0), timeframe)
    quotes31_2 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=2), day14 + timedelta(hours=2), 'binance', 100, timeout=1200)
    check_data_completeness(quotes31_2, day14 + timedelta(hours=2), day14 + timedelta(hours=2), timeframe)
    quotes31_4 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=4), day14 + timedelta(hours=4), 'binance', 100, timeout=1200)
    check_data_completeness(quotes31_4, day14 + timedelta(hours=4), day14 + timedelta(hours=4), timeframe)
    quotes31_6 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=6), day14 + timedelta(hours=6), 'binance', 100, timeout=1200)
    check_data_completeness(quotes31_6, day14 + timedelta(hours=6), day14 + timedelta(hours=6), timeframe)
    quotes31_8 = QuotesBackTest('BTC/USDT', '1h', day14 + timedelta(hours=8), day14 + timedelta(hours=8), 'binance', 100, timeout=1200)
    check_data_completeness(quotes31_8, day14 + timedelta(hours=8), day14 + timedelta(hours=8), timeframe)
    
    # Day 15 scenarios
    day15 = base_date + timedelta(days=14)
    
    # Request 32: All day 15 (0:00 to 23:00)
    quotes32 = QuotesBackTest('BTC/USDT', '1h', day15, day15 + timedelta(hours=23), 'binance', 100, timeout=1200)
    check_data_completeness(quotes32, day15, day15 + timedelta(hours=23), timeframe)
    
    # Request 33: 0:00 to 8:00 - even hours first (0, 2, 4, 6, 8)
    quotes33_0 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=0), day15 + timedelta(hours=0), 'binance', 100, timeout=1200)
    check_data_completeness(quotes33_0, day15 + timedelta(hours=0), day15 + timedelta(hours=0), timeframe)
    quotes33_2 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=2), day15 + timedelta(hours=2), 'binance', 100, timeout=1200)
    check_data_completeness(quotes33_2, day15 + timedelta(hours=2), day15 + timedelta(hours=2), timeframe)
    quotes33_4 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=4), day15 + timedelta(hours=4), 'binance', 100, timeout=1200)
    check_data_completeness(quotes33_4, day15 + timedelta(hours=4), day15 + timedelta(hours=4), timeframe)
    quotes33_6 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=6), day15 + timedelta(hours=6), 'binance', 100, timeout=1200)
    check_data_completeness(quotes33_6, day15 + timedelta(hours=6), day15 + timedelta(hours=6), timeframe)
    quotes33_8 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=8), day15 + timedelta(hours=8), 'binance', 100, timeout=1200)
    check_data_completeness(quotes33_8, day15 + timedelta(hours=8), day15 + timedelta(hours=8), timeframe)
    
    # Request 34: 0:00 to 8:00 - odd hours after (1, 3, 5, 7)
    quotes34_1 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=1), day15 + timedelta(hours=1), 'binance', 100, timeout=1200)
    check_data_completeness(quotes34_1, day15 + timedelta(hours=1), day15 + timedelta(hours=1), timeframe)
    quotes34_3 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=3), day15 + timedelta(hours=3), 'binance', 100, timeout=1200)
    check_data_completeness(quotes34_3, day15 + timedelta(hours=3), day15 + timedelta(hours=3), timeframe)
    quotes34_5 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=5), day15 + timedelta(hours=5), 'binance', 100, timeout=1200)
    check_data_completeness(quotes34_5, day15 + timedelta(hours=5), day15 + timedelta(hours=5), timeframe)
    quotes34_7 = QuotesBackTest('BTC/USDT', '1h', day15 + timedelta(hours=7), day15 + timedelta(hours=7), 'binance', 100, timeout=1200)
    check_data_completeness(quotes34_7, day15 + timedelta(hours=7), day15 + timedelta(hours=7), timeframe)
    
    # Cross-day requests
    # Request 35: From day 1 to day 14 (0:00 day1 to 23:00 day14)
    quotes35 = QuotesBackTest('BTC/USDT', '1h', day1, day14 + timedelta(hours=23), 'binance', 100, timeout=1200)
    check_data_completeness(quotes35, day1, day14 + timedelta(hours=23), timeframe)
    
    # Request 36: From day 2 to day 16 (0:00 day2 to 23:00 day16)
    day16 = base_date + timedelta(days=15)
    quotes36 = QuotesBackTest('BTC/USDT', '1h', day2, day16 + timedelta(hours=23), 'binance', 100, timeout=1200)
    check_data_completeness(quotes36, day2, day16 + timedelta(hours=23), timeframe)


def test_5m_small(quotes_service):
    timeframe = '5m'
    start_date = datetime(2025, 10, 10, 0, 0, 0, tzinfo=UTC)
    date_end = start_date + timedelta(hours=23, minutes=59)
    
    def run_test(call_num: int):
        """Run a single test call"""
        start_time = time.time()
        
        quotes = QuotesBackTest('BTC/USDT', '5m', start_date, date_end, 'binance', timeout=1200)
        
        # Check data completeness
        check_data_completeness(quotes, start_date, date_end, timeframe)
        
        # Calculate expected number of bars
        timeframe_delta = Timeframe.cast(timeframe).timedelta()
        total_seconds = (date_end - start_date).total_seconds()
        expected_bars = int(total_seconds / timeframe_delta.total_seconds()) + 1
        
        # Verify we got the expected number of bars
        assert len(quotes.time.values) == expected_bars, \
            f"Expected {expected_bars} bars for {timeframe} timeframe, got {len(quotes.time.values)}"
        
        # Verify no zero values in prices
        assert np.all(quotes.open.values > 0), "Open prices should not contain zero values"
        assert np.all(quotes.high.values > 0), "High prices should not contain zero values"
        assert np.all(quotes.low.values > 0), "Low prices should not contain zero values"
        assert np.all(quotes.close.values > 0), "Close prices should not contain zero values"
        
        elapsed_time = time.time() - start_time
        print(f"Call {call_num}: completed in {elapsed_time:.2f} seconds")
    
    # First call
    run_test(1)
    
    # Second call (same as first)
    run_test(2)


def test_5m_big(quotes_service):
    timeframe = '5m'
    start_date = datetime(2025, 10, 10, 0, 0, 0, tzinfo=UTC)
    date_end = start_date + timedelta(hours=24*29+23, minutes=59)
    
    def run_test(call_num: int):
        """Run a single test call"""
        start_time = time.time()
        
        quotes = QuotesBackTest('BTC/USDT', '5m', start_date, date_end, 'binance', timeout=1200)
        
        # Check data completeness
        check_data_completeness(quotes, start_date, date_end, timeframe)
        
        # Calculate expected number of bars
        timeframe_delta = Timeframe.cast(timeframe).timedelta()
        total_seconds = (date_end - start_date).total_seconds()
        expected_bars = int(total_seconds / timeframe_delta.total_seconds()) + 1
        
        # Verify we got the expected number of bars
        assert len(quotes.time.values) == expected_bars, \
            f"Expected {expected_bars} bars for {timeframe} timeframe, got {len(quotes.time.values)}"
        
        # Verify no zero values in prices
        assert np.all(quotes.open.values > 0), "Open prices should not contain zero values"
        assert np.all(quotes.high.values > 0), "High prices should not contain zero values"
        assert np.all(quotes.low.values > 0), "Low prices should not contain zero values"
        assert np.all(quotes.close.values > 0), "Close prices should not contain zero values"
        
        elapsed_time = time.time() - start_time
        print(f"Call {call_num}: completed in {elapsed_time:.2f} seconds")
    
    # First call
    run_test(1)
    
    # Second call (same as first)
    run_test(2)


def _parallel_worker(symbol: str, timeframe_str: str, date_start: datetime, date_end: datetime, 
                     source: str, history_size: int, timeout: int, worker_id: int,
                     redis_params: dict):
    """
    Worker function for parallel requests.
    Loads quotes data in a separate process and checks data integrity.
    """
    # Initialize quotes client with Redis parameters in this process
    Client(redis_params=redis_params)
    
    # Create Timeframe object from string
    timeframe = Timeframe.cast(timeframe_str)
    
    quotes = QuotesBackTest(symbol, timeframe_str, date_start, date_end, source, history_size, timeout=timeout)
    
    # Check data completeness
    check_data_completeness(quotes, date_start, date_end, timeframe)
    
    # Calculate expected number of bars
    timeframe_delta = timeframe.timedelta()
    total_seconds = (date_end - date_start).total_seconds()
    expected_bars = int(total_seconds / timeframe_delta.total_seconds()) + 1
    
    # Verify we got the expected number of bars
    assert len(quotes.time.values) == expected_bars, \
        f"Expected {expected_bars} bars for {timeframe_str} timeframe, got {len(quotes.time.values)}"
    
    # Verify no zero values in prices
    assert np.all(quotes.open.values > 0), "Open prices should not contain zero values"
    assert np.all(quotes.high.values > 0), "High prices should not contain zero values"
    assert np.all(quotes.low.values > 0), "Low prices should not contain zero values"
    assert np.all(quotes.close.values > 0), "Close prices should not contain zero values"


def test_parallel_requests(quotes_service):
    """
    Test parallel requests from multiple processes.
    Runs three batches: first two batches on 10.10.2025 (3 processes each: 2 for BTC/USDT, 1 for ETH/USDT),
    third batch on 11.10.2025 with the same configuration.
    """
    # Get Redis parameters from config (same as in quotes_service fixture)
    params = redis_params()
    
    # Use spawn context to avoid fork() issues in multi-threaded environment
    ctx = get_context('spawn')
    
    def create_processes(test_date: datetime, date_end: datetime):
        """Create a batch of 3 processes: 2 for BTC/USDT, 1 for ETH/USDT"""
        processes = []
        
        # First two processes for BTC/USDT (same symbol, will be processed sequentially due to lock)
        for i in range(2):
            p = ctx.Process(
                target=_parallel_worker,
                args=('BTC/USDT', '5m', test_date, date_end, 'binance', 100, 120, i + 1, params)
            )
            processes.append(p)
        
        # Third process for ETH/USDT (different symbol, will run in parallel)
        p = ctx.Process(
            target=_parallel_worker,
            args=('ETH/USDT', '5m', test_date, date_end, 'binance', 100, 120, 3, params)
        )
        processes.append(p)
        
        return processes
    
    def run_batch(batch_num: int, test_date: datetime, date_end: datetime):
        """Run a batch of processes and wait for completion"""
        processes = create_processes(test_date, date_end)
        
        # Start timing before starting processes
        batch_start_time = time.time()
        
        # Start all processes
        for p in processes:
            p.start()
        
        # Wait for all to complete
        for i, p in enumerate(processes, 1):
            p.join(timeout=300)  # 3 minutes timeout per process
            assert not p.is_alive(), f"Batch {batch_num}: Process did not complete within timeout"
            assert p.exitcode == 0, f"Batch {batch_num}: Process exited with code {p.exitcode}"
        
        # Calculate total time for this batch
        batch_elapsed = time.time() - batch_start_time
        print(f"Batch {batch_num}: All {len(processes)} parallel workers completed. Total time: {batch_elapsed:.2f} seconds")
    
    # First batch: 10.10.2025
    test_date_1 = datetime(2025, 10, 10, 0, 0, 0, tzinfo=UTC)
    date_end_1 = test_date_1 + timedelta(hours=23, minutes=59)
    run_batch(1, test_date_1, date_end_1)
    
    # Second batch: 10.10.2025 (same date)
    run_batch(2, test_date_1, date_end_1)
    
    # Third batch: 11.10.2025 (different date)
    test_date_2 = datetime(2025, 10, 11, 0, 0, 0, tzinfo=UTC)
    date_end_2 = test_date_2 + timedelta(hours=23, minutes=59)
    run_batch(3, test_date_2, date_end_2)
