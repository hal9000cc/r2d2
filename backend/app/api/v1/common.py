from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Union
import ccxt
import numpy as np
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.client import QuotesClient
from app.services.quotes.exceptions import R2D2QuotesExceptionDataNotReceived
from app.core.datetime_utils import parse_utc_datetime, datetime64_to_iso

router = APIRouter(prefix="/api/v1/common", tags=["common"])

# Cache for symbols by source
source_symbols: Dict[str, List[str]] = {}


def get_timeframes_list() -> List[str]:
    """
    Get list of timeframes from Timeframe class.
    Selects all attributes that start with 't' and have numeric type.
    Returns names without 't' prefix (e.g., '1m' instead of 't1m'),
    sorted by value in ascending order.
    """
    timeframes = []
    for attr_name in dir(Timeframe):
        if attr_name.startswith('t') and not attr_name.startswith('__'):
            attr_value = getattr(Timeframe, attr_name)
            if isinstance(attr_value, (int, float)):
                # Store tuple (value, name) for sorting by value
                timeframes.append((attr_value, attr_name[1:]))
    # Sort by value (first element of tuple) and return only names
    return [name for _, name in sorted(timeframes, key=lambda x: x[0])]


@router.get("/timeframes", response_model=List[str])
async def get_timeframes():
    """
    Get list of available timeframes
    """
    return get_timeframes_list()


@router.get("/sources", response_model=List[str])
async def get_sources():
    """
    Get list of available sources (exchanges) from ccxt
    """
    # Get list of all available exchanges from ccxt
    return sorted(ccxt.exchanges)


@router.get("/sources/{source}/symbols", response_model=List[str])
async def get_source_symbols(source: str):
    """
    Get list of symbols for a specific source (exchange)
    Symbols are cached per source to avoid repeated API calls
    """
    # Check cache first
    if source in source_symbols:
        return source_symbols[source]
    
    try:
        # Create exchange instance
        exchange_class = getattr(ccxt, source)
        exchange = exchange_class({
            'enableRateLimit': True,
        })
        
        # Load markets to get symbols
        markets = exchange.load_markets()
        
        # Extract unique symbols
        symbols = sorted(list(set(markets.keys())))
        
        # Cache the result
        source_symbols[source] = symbols
        
        return symbols
    except AttributeError:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found in ccxt")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load symbols for source '{source}': {str(e)}")


@router.get("/quotes", response_model=List[Dict[str, Union[float, str]]])
async def get_quotes(
    source: str = Query(..., description="Data source (exchange name, e.g., 'binance')"),
    symbol: str = Query(..., description="Trading symbol (e.g., 'BTC/USDT')"),
    timeframe: str = Query(..., description="Timeframe (e.g., '1h', '1d', '5m')"),
    date_start: str = Query(..., description="Start date/time in ISO format (e.g., '2024-01-01T00:00:00Z')"),
    date_end: str = Query(..., description="End date/time in ISO format (e.g., '2024-01-31T23:59:59Z')")
):
    """
    Get quotes data for a symbol and timeframe.
    
    Returns array of quote objects, each containing:
    - time: ISO format datetime string
    - open: Opening price
    - high: Highest price
    - low: Lowest price
    - close: Closing price
    - volume: Trading volume
    
    Format is optimized for charting libraries.
    """
    try:
        # Parse timeframe
        try:
            tf = Timeframe.cast(timeframe)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid timeframe '{timeframe}': {str(e)}")
        
        # Parse dates
        try:
            start_dt = parse_utc_datetime(date_start)
            end_dt = parse_utc_datetime(date_end)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
        
        # Validate date range
        if start_dt >= end_dt:
            raise HTTPException(status_code=400, detail="date_start must be before date_end")
        
        # Get quotes data using Client (already initialized in startup)
        try:
            client = QuotesClient()
            quotes_data = client.get_quotes(
                source=source,
                symbol=symbol,
                timeframe=tf,
                history_start=start_dt,
                history_end=end_dt,
                timeout=30
            )
        except R2D2QuotesExceptionDataNotReceived as e:
            error_msg = e.error if e.error else f"Failed to get quotes data for {source}/{symbol}/{timeframe}"
            raise HTTPException(status_code=404, detail=error_msg)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting quotes: {str(e)}")
        
        # Convert numpy arrays to list of objects for charting
        time_array = quotes_data['time']
        open_array = quotes_data['open']
        high_array = quotes_data['high']
        low_array = quotes_data['low']
        close_array = quotes_data['close']
        volume_array = quotes_data['volume']
        
        # Get length (all arrays should have same length)
        length = len(time_array)
        
        # Convert to list of dictionaries
        result = []
        for i in range(length):
            # Convert numpy datetime64 to ISO string
            time_dt64 = time_array[i]
            if isinstance(time_dt64, np.datetime64):
                time_str = datetime64_to_iso(time_dt64).replace('+00:00', 'Z')
            else:
                time_str = str(time_dt64)
            
            result.append({
                "time": time_str,
                "open": float(open_array[i]),
                "high": float(high_array[i]),
                "low": float(low_array[i]),
                "close": float(close_array[i]),
                "volume": float(volume_array[i])
            })
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
