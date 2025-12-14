from fastapi import APIRouter, HTTPException
from typing import List, Dict
import ccxt
from app.services.quotes.timeframe import Timeframe

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
