from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Union, Optional
import ccxt
import numpy as np
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.client import QuotesClient
from app.services.quotes.exceptions import R2D2QuotesExceptionDataNotReceived
from app.core.datetime_utils import parse_utc_datetime, datetime64_to_iso

router = APIRouter(prefix="/api/v1/common", tags=["common"])

# Cache for symbols by source
source_symbols: Dict[str, List[str]] = {}


def get_timeframes_dict() -> Dict[str, int]:
    """
    Get dictionary of timeframes from Timeframe class.
    Selects all attributes that start with 't' and have numeric type.
    Returns dict with names without 't' prefix as keys and values in milliseconds.
    Example: { "1s": 1000, "1m": 60000, "1h": 3600000, ... }
    """
    timeframes = {}
    for attr_name in dir(Timeframe):
        if attr_name.startswith('t') and not attr_name.startswith('__'):
            attr_value = getattr(Timeframe, attr_name)
            if isinstance(attr_value, (int, float)):
                # Store name without 't' prefix and value in milliseconds
                timeframes[attr_name[1:]] = int(attr_value)
    return timeframes


@router.get("/timeframes", response_model=Dict[str, int])
async def get_timeframes():
    """
    Get dictionary of available timeframes with their values in milliseconds
    """
    return get_timeframes_dict()


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
    date_end: str = Query(..., description="End date/time in ISO format (e.g., '2024-01-31T23:59:59Z')"),
    fields: Optional[str] = Query(None, description="Comma-separated list of fields to return (e.g., 'time,open,high,low,close'). If not specified, all fields are returned.")
):
    """
    Get quotes data for a symbol and timeframe.
    
    Returns array of quote objects, each containing:
    - time: Unix timestamp in seconds (for lightweight-charts compatibility)
    - open: Opening price
    - high: Highest price
    - low: Lowest price
    - close: Closing price
    - volume: Trading volume
    
    Format is optimized for lightweight-charts library.
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
        
        # Parse requested fields
        requested_fields = None
        if fields:
            # Split by comma and strip whitespace
            requested_fields = [f.strip().lower() for f in fields.split(',') if f.strip()]
            # Validate fields
            valid_fields = {'time', 'open', 'high', 'low', 'close', 'volume'}
            invalid_fields = [f for f in requested_fields if f not in valid_fields]
            if invalid_fields:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid fields: {', '.join(invalid_fields)}. Valid fields are: {', '.join(sorted(valid_fields))}"
                )
        
        # Convert to list of dictionaries
        # Format optimized for lightweight-charts: time as Unix timestamp in seconds
        result = []
        for i in range(length):
            # Convert numpy datetime64 to Unix timestamp in seconds
            time_dt64 = time_array[i]
            if isinstance(time_dt64, np.datetime64):
                # Convert to seconds timestamp (Unix epoch)
                time_timestamp = int(time_dt64.astype('datetime64[s]').astype(int))
            else:
                # Fallback: try to parse as datetime and convert
                time_timestamp = int(np.datetime64(time_dt64).astype('datetime64[s]').astype(int))
            
            # Build result dictionary with only requested fields
            quote_dict = {}
            
            # Always include time if requested (or if no fields specified)
            if not requested_fields or 'time' in requested_fields:
                quote_dict["time"] = time_timestamp
            
            if not requested_fields or 'open' in requested_fields:
                quote_dict["open"] = float(open_array[i])
            
            if not requested_fields or 'high' in requested_fields:
                quote_dict["high"] = float(high_array[i])
            
            if not requested_fields or 'low' in requested_fields:
                quote_dict["low"] = float(low_array[i])
            
            if not requested_fields or 'close' in requested_fields:
                quote_dict["close"] = float(close_array[i])
            
            if not requested_fields or 'volume' in requested_fields:
                quote_dict["volume"] = float(volume_array[i])
            
            result.append(quote_dict)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
