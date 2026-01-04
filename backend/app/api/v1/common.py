from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Union, Optional, Tuple
from pydantic import BaseModel, Field
import ccxt
import numpy as np
import time
from app.services.quotes.timeframe import Timeframe
from app.services.quotes.client import QuotesClient
from app.services.quotes.exceptions import R2D2QuotesExceptionDataNotReceived
from app.core.datetime_utils import parse_utc_datetime, datetime64_to_iso
from app.core.config import SYMBOLS_CACHE_TTL_SECONDS, get_api_key, get_api_secret
from app.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/common", tags=["common"])


class SymbolInfo(BaseModel):
    """Information about a trading symbol including fees and precision."""
    symbol: str = Field(..., description="Symbol name (e.g., 'BTC/USDT')")
    fee_maker_common: float = Field(..., description="Common maker fee rate for symbol (without user level, from exchange info, as fraction, e.g., 0.001 for 0.1%)")
    fee_taker_common: float = Field(..., description="Common taker fee rate for symbol (without user level, from exchange info, as fraction, e.g., 0.001 for 0.1%)")
    fee_maker: Optional[float] = Field(None, description="User-specific maker fee rate (requires authentication, as fraction, e.g., 0.001 for 0.1%)")
    fee_taker: Optional[float] = Field(None, description="User-specific taker fee rate (requires authentication, as fraction, e.g., 0.001 for 0.1%)")
    precision_amount: Optional[float] = Field(None, description="Minimum step size for amount/base currency (e.g., 0.1, 0.001)")
    precision_price: Optional[float] = Field(None, description="Minimum step size for price/quote currency (e.g., 0.1, 0.001)")


class SymbolInfoResponse(BaseModel):
    """Response containing symbol information and any errors."""
    symbol_info: SymbolInfo = Field(..., description="Symbol information")
    errors: List[str] = Field(default_factory=list, description="List of warning/error messages (if any)")


# Cache for symbols by source (stores tuple of (List[SymbolInfo], timestamp))
# timestamp is Unix time when cache was created
source_symbols: Dict[str, Tuple[List[SymbolInfo], float]] = {}


def _is_source_cached(source: str) -> bool:
    """
    Check if symbols for a source are cached and not expired.
    
    Args:
        source: Exchange name
        
    Returns:
        True if source is cached and not expired, False otherwise
    """
    if source not in source_symbols:
        return False
    
    # Check if cache is expired
    _, cache_timestamp = source_symbols[source]
    current_time = time.time()
    cache_age = current_time - cache_timestamp
    
    if cache_age > SYMBOLS_CACHE_TTL_SECONDS:
        # Cache expired, remove it
        del source_symbols[source]
        return False
    
    return True


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
    # CCXT returns precision as step size (float) directly (e.g., 0.1, 0.001)
    # Use values as-is without any conversion
    precision_amount = None
    precision_price = None
    if isinstance(precision, dict):
        precision_amount_val = precision.get('amount')
        precision_price_val = precision.get('price')
        if precision_amount_val is not None:
            precision_amount = float(precision_amount_val)
        if precision_price_val is not None:
            precision_price = float(precision_price_val)
    
    # If fees are in percentage format, they're already decimals
    # If not percentage, we might need to handle differently, but for now assume they're decimals
    return SymbolInfo(
        symbol=symbol,
        fee_maker_common=float(maker_fee) if maker_fee is not None else 0.0,
        fee_taker_common=float(taker_fee) if taker_fee is not None else 0.0,
        fee_maker=None,  # Will be filled from fetch_trading_fee if available (user-specific, requires auth)
        fee_taker=None,  # Will be filled from fetch_trading_fee if available (user-specific, requires auth)
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
    
    # Cache the result with current timestamp
    cache_timestamp = time.time()
    source_symbols[source] = (symbol_infos, cache_timestamp)
    
    return symbol_infos


def _ensure_source_loaded(source: str) -> List[SymbolInfo]:
    """
    Ensure symbols for a source are loaded (from cache or by fetching).
    Checks cache expiration and reloads if needed.
    
    Args:
        source: Exchange name
        
    Returns:
        List of SymbolInfo objects for all symbols on the exchange
        
    Raises:
        AttributeError: If source is not found in ccxt
        Exception: If failed to load markets
    """
    if _is_source_cached(source):
        symbol_infos, _ = source_symbols[source]
        return symbol_infos
    
    return _load_source_symbols(source)


def _get_symbol_info(source: str, symbol: str) -> Optional[SymbolInfo]:
    """
    Get SymbolInfo for a specific symbol from a source.
    
    Args:
        source: Exchange name
        symbol: Symbol name (exact match as returned by ccxt)
        
    Returns:
        SymbolInfo object if found, None otherwise
        
    Raises:
        AttributeError: If source is not found in ccxt
        Exception: If failed to load markets
    """
    symbol_infos = _ensure_source_loaded(source)
    
    # Try exact match
    for symbol_info in symbol_infos:
        if symbol_info.symbol == symbol:
            # Return a copy to avoid modifying cached object
            return SymbolInfo.model_validate(symbol_info.model_dump())
    
    return None


def _update_symbol_info_in_cache(source: str, symbol: str, symbol_info: SymbolInfo) -> None:
    """
    Update SymbolInfo in cache for a specific symbol.
    
    Args:
        source: Exchange name
        symbol: Symbol name
        symbol_info: Updated SymbolInfo object
    """
    if source not in source_symbols:
        return
    
    symbol_infos, cache_timestamp = source_symbols[source]
    
    # Find and update the symbol in the list
    for i, cached_info in enumerate(symbol_infos):
        if cached_info.symbol == symbol:
            symbol_infos[i] = symbol_info
            # Update cache with new timestamp (keep original cache timestamp)
            source_symbols[source] = (symbol_infos, cache_timestamp)
            break


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


@router.get("/sources/{source}/symbols/info", response_model=SymbolInfoResponse)
async def get_symbol_info(source: str, symbol: str = Query(..., description="Trading symbol (e.g., 'BTC/USDT')")):
    """
    Get detailed information about a specific symbol from a source (exchange).
    
    Returns SymbolInfoResponse containing:
    - symbol_info: Symbol information with fees and precision
    - errors: List of warning/error messages (if any)
    """
    errors: List[str] = []
    
    try:
        symbol_info = _get_symbol_info(source, symbol)
        if symbol_info is None:
            raise HTTPException(
                status_code=404,
                detail=f"Symbol '{symbol}' not found for source '{source}'"
            )
        
        # Check if user-specific fees need to be fetched (requires authentication)
        if symbol_info.fee_maker is None or symbol_info.fee_taker is None:
            try:
                # Get API credentials from config
                api_key = get_api_key(source)
                api_secret = get_api_secret(source)
                
                # Create exchange instance with API credentials if available
                exchange_class = getattr(ccxt, source)
                exchange_config = {
                    'enableRateLimit': True,
                }
                if api_key:
                    exchange_config['apiKey'] = api_key
                if api_secret:
                    exchange_config['secret'] = api_secret
                
                exchange = exchange_class(exchange_config)
                
                # Fetch user-specific trading fees (requires authentication)
                trading_fee = exchange.fetch_trading_fee(symbol=symbol)
                
                # Extract fee_maker and fee_taker from trading_fee response
                # Structure: {'maker': 0.00036, 'taker': 0.001, ...}
                if 'maker' in trading_fee and trading_fee['maker'] is not None:
                    symbol_info.fee_maker = float(trading_fee['maker'])
                if 'taker' in trading_fee and trading_fee['taker'] is not None:
                    symbol_info.fee_taker = float(trading_fee['taker'])
                
                # Update cache with successfully fetched fees
                _update_symbol_info_in_cache(source, symbol, symbol_info)
                
            except Exception as fee_error:
                # Log warning and use common fees as fallback
                error_msg = f"Failed to fetch user-specific fees for {source}/{symbol}: {str(fee_error)}"
                logger.warning(error_msg)
                errors.append(error_msg)
                
                # Use common fees as fallback
                symbol_info.fee_maker = symbol_info.fee_maker_common
                symbol_info.fee_taker = symbol_info.fee_taker_common
                
                # Don't update cache on error - allow retry on next request

        
        return SymbolInfoResponse(symbol_info=symbol_info, errors=errors)
        
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
