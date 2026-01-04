from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Union, Optional
from pydantic import BaseModel, Field
import ccxt
import numpy as np
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.client import QuotesClient
from app.services.quotes.exceptions import R2D2QuotesExceptionDataNotReceived
from app.core.datetime_utils import parse_utc_datetime, datetime64_to_iso

router = APIRouter(prefix="/api/v1/common", tags=["common"])


class SymbolInfo(BaseModel):
    """Information about a trading symbol including fees and precision."""
    symbol: str = Field(..., description="Symbol name (e.g., 'BTC/USDT')")
    fee_maker: float = Field(..., description="Maker fee rate (as fraction, e.g., 0.001 for 0.1%)")
    fee_taker: float = Field(..., description="Taker fee rate (as fraction, e.g., 0.001 for 0.1%)")
    precision_amount: Optional[int] = Field(None, description="Number of decimal places for amount/base currency")
    precision_price: Optional[int] = Field(None, description="Number of decimal places for price/quote currency")


# Cache for symbols by source (stores SymbolInfo objects)
source_symbols: Dict[str, List[SymbolInfo]] = {}


def _is_source_cached(source: str) -> bool:
    """
    Check if symbols for a source are already cached.
    
    Args:
        source: Exchange name
        
    Returns:
        True if source is cached, False otherwise
    """
    return source in source_symbols


def _create_symbol_info_from_market(symbol: str, market: dict) -> SymbolInfo:
    """
    Create SymbolInfo object from ccxt market data.
    
    Args:
        symbol: Symbol name
        market: Market data from ccxt
        
    Returns:
        SymbolInfo object with symbol information
    """
    # Get maker and taker fees, default to 0.0 if not available
    maker_fee = market.get('maker', 0.0)
    taker_fee = market.get('taker', 0.0)
    
    # Get precision information
    precision = market.get('precision', {})
    # precision can be a dict with 'amount' and 'price' keys, or None
    precision_amount = None
    precision_price = None
    if isinstance(precision, dict):
        precision_amount = precision.get('amount')
        precision_price = precision.get('price')
        # Convert to int if they are numbers
        if precision_amount is not None:
            precision_amount = int(precision_amount) if isinstance(precision_amount, (int, float)) else None
        if precision_price is not None:
            precision_price = int(precision_price) if isinstance(precision_price, (int, float)) else None
    
    # If fees are in percentage format, they're already decimals
    # If not percentage, we might need to handle differently, but for now assume they're decimals
    return SymbolInfo(
        symbol=symbol,
        fee_maker=float(maker_fee) if maker_fee is not None else 0.0,
        fee_taker=float(taker_fee) if taker_fee is not None else 0.0,
        precision_amount=precision_amount,
        precision_price=precision_price
    )


def _load_source_symbols(source: str) -> List[SymbolInfo]:
    """
    Load symbols for a source from ccxt and cache them.
    
    Args:
        source: Exchange name
        
    Returns:
        List of SymbolInfo objects for all symbols on the exchange
        
    Raises:
        AttributeError: If source is not found in ccxt
        Exception: If failed to load markets
    """
    # Create exchange instance
    exchange_class = getattr(ccxt, source)
    exchange = exchange_class({
        'enableRateLimit': True,
    })
    
    # Load markets to get symbols and fee information
    markets = exchange.load_markets()
    
    # Build list of SymbolInfo objects with fee information
    symbol_infos = []
    for symbol in sorted(set(markets.keys())):
        market = markets[symbol]
        symbol_info = _create_symbol_info_from_market(symbol, market)
        symbol_infos.append(symbol_info)
    
    # Cache the result
    source_symbols[source] = symbol_infos
    
    return symbol_infos


def _ensure_source_loaded(source: str) -> List[SymbolInfo]:
    """
    Ensure symbols for a source are loaded (from cache or by fetching).
    
    Args:
        source: Exchange name
        
    Returns:
        List of SymbolInfo objects for all symbols on the exchange
        
    Raises:
        AttributeError: If source is not found in ccxt
        Exception: If failed to load markets
    """
    if _is_source_cached(source):
        return source_symbols[source]
    
    return _load_source_symbols(source)


def _get_symbol_info(source: str, symbol: str) -> Optional[SymbolInfo]:
    """
    Get SymbolInfo for a specific symbol from a source.
    
    Args:
        source: Exchange name
        symbol: Symbol name
        
    Returns:
        SymbolInfo object if found, None otherwise
        
    Raises:
        AttributeError: If source is not found in ccxt
        Exception: If failed to load markets
    """
    symbol_infos = _ensure_source_loaded(source)
    
    # Find the symbol in cached data
    for symbol_info in symbol_infos:
        if symbol_info.symbol == symbol:
            return symbol_info
    
    return None


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
    try:
        symbol_infos = _ensure_source_loaded(source)
        # Return only symbol names for backward compatibility
        return [symbol_info.symbol for symbol_info in symbol_infos]
    except AttributeError:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found in ccxt")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load symbols for source '{source}': {str(e)}")


@router.get("/sources/{source}/symbols/{symbol}", response_model=SymbolInfo)
async def get_symbol_info(source: str, symbol: str):
    """
    Get detailed information about a specific symbol from a source (exchange).
    
    Returns SymbolInfo containing:
    - symbol: Symbol name
    - fee_maker: Maker fee rate
    - fee_taker: Taker fee rate
    - precision_amount: Number of decimal places for amount
    - precision_price: Number of decimal places for price
    """
    try:
        symbol_info = _get_symbol_info(source, symbol)
        if symbol_info is None:
            raise HTTPException(
                status_code=404,
                detail=f"Symbol '{symbol}' not found for source '{source}'"
            )
        return symbol_info
    except HTTPException:
        raise
    except AttributeError:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found in ccxt")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load symbol info for '{source}/{symbol}': {str(e)}"
        )


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
