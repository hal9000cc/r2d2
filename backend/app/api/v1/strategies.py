from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import ccxt
from app.core.active_strategy import (
    get as active_strategy_get_all,
    get_by_id as active_strategy_get_by_id,
    add as active_strategy_add,
    update as active_strategy_update,
    delete as active_strategy_delete,
    new_strategy as active_strategy_new
)
from app.services.quotes.timeframe import Timeframe

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


def _get_timeframes_list() -> List[str]:
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
    return _get_timeframes_list()


@router.get("/sources", response_model=List[str])
async def get_sources():
    """
    Get list of available sources (exchanges) from ccxt
    """
    # Get list of all available exchanges from ccxt
    return sorted(ccxt.exchanges)


# Cache for symbols by source
source_symbols: Dict[str, List[str]] = {}


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


@router.get("", response_model=List[Dict[str, Any]])
async def get_active_strategies():
    """
    Get list of active strategies
    """
    return active_strategy_get_all()


@router.get("/{strategy_id}", response_model=Dict[str, Any])
async def get_active_strategy(strategy_id: int):
    """
    Get single active strategy by ID
    If strategy_id is 0, returns empty strategy with new ID
    """
    # If strategy_id == 0, return empty strategy with new ID
    if strategy_id == 0:
        return active_strategy_new()
    
    strategy = active_strategy_get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    return strategy


@router.delete("/{strategy_id}", response_model=List[Dict[str, Any]])
async def delete_strategy(strategy_id: int):
    """
    Delete active strategy
    Returns updated list of strategies
    """
    try:
        active_strategy_delete(strategy_id)
        return active_strategy_get_all()
    except KeyError:
        raise HTTPException(status_code=404, detail="Strategy not found")


@router.post("/{strategy_id}/start", response_model=Dict[str, Any])
async def start_strategy(strategy_id: int):
    """
    Start strategy
    Returns updated strategy object
    """
    strategy = active_strategy_get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Update isRunning to True
    strategy["isRunning"] = True
    return active_strategy_update(strategy_id, strategy)


@router.post("/{strategy_id}/stop", response_model=Dict[str, Any])
async def stop_strategy(strategy_id: int):
    """
    Stop strategy
    Returns updated strategy object
    """
    strategy = active_strategy_get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Update isRunning to False
    strategy["isRunning"] = False
    return active_strategy_update(strategy_id, strategy)


@router.post("/{strategy_id}/toggle-trading", response_model=Dict[str, Any])
async def toggle_trading(strategy_id: int):
    """
    Toggle trading for strategy
    Returns updated strategy object
    """
    strategy = active_strategy_get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Toggle isTrading
    strategy["isTrading"] = not strategy.get("isTrading", False)
    return active_strategy_update(strategy_id, strategy)


@router.put("/{strategy_id}", response_model=Dict[str, Any])
async def update_strategy(strategy_id: int, strategy_data: Dict[str, Any]):
    """
    Update active strategy
    Returns updated strategy object
    """
    # Ensure active_strategy_id matches
    strategy_data["active_strategy_id"] = strategy_id
    
    try:
        return active_strategy_update(strategy_id, strategy_data)
    except KeyError:
        # Strategy doesn't exist, create new one
        return active_strategy_add(strategy_data)

